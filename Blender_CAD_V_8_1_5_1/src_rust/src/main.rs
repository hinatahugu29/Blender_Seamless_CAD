
use std::net::{TcpListener, TcpStream};
use std::io::{Read, Write};
use std::sync::{Arc, Mutex, mpsc};
use std::collections::HashMap;
use once_cell::sync::Lazy;

// --- Interactive CSG preview state (per stack) ---
// During a drag of a boolean tool (SUB/ADD/INT), Python sends the base mesh
// (everything except the tool) and the tool mesh once at drag start; each frame
// it sends only the tool's transform. Rust runs the pure-Rust BSP boolean of the
// matching op and returns feature edges. This keeps interactive preview entirely
// off the OCC path.
struct PreviewMesh {
    base_v: Vec<f32>,
    base_t: Vec<i32>,
    tool_v: Vec<f32>,
    tool_t: Vec<i32>,
    op: String,
}
static PREVIEW_STATE: Lazy<Mutex<HashMap<isize, PreviewMesh>>> =
    Lazy::new(|| Mutex::new(HashMap::new()));

// --- Shared-memory result transfer (revived) ---
// Python creates a 64MB file-backed mmap (seamless_cad_shm.bin) and passes its
// path as argv[1]. We map the same file and write mesh results into it instead of
// pushing the whole mesh over the loopback socket each frame. To stay safe under
// parallel per-stack workers AND the async client (which reads the buffer on a
// different thread than it consumes it), we round-robin across N disjoint slots:
// a slot can only be clobbered after N more responses, which cannot happen inside
// the microsecond window the client needs to copy the data out.
use std::sync::atomic::{AtomicUsize, Ordering};
const SHM_SLOTS: usize = 4;
const SHM_SLOT_SIZE: usize = 16 * 1024 * 1024;
struct ShmBuf { ptr: *mut u8, _map: memmap2::MmapMut }
unsafe impl Send for ShmBuf {}
unsafe impl Sync for ShmBuf {}
static SHM: once_cell::sync::OnceCell<ShmBuf> = once_cell::sync::OnceCell::new();
static SHM_SLOT: AtomicUsize = AtomicUsize::new(0);

fn init_shm(path: &str) {
    use std::fs::OpenOptions;
    if let Ok(file) = OpenOptions::new().read(true).write(true).open(path) {
        if let Ok(mut map) = unsafe { memmap2::MmapMut::map_mut(&file) } {
            if map.len() >= SHM_SLOTS * SHM_SLOT_SIZE {
                let ptr = map.as_mut_ptr();
                let _ = SHM.set(ShmBuf { ptr, _map: map });
                println!("Seamless CAD Server: shared memory mapped ({} bytes) for result transfer", SHM_SLOTS * SHM_SLOT_SIZE);
            }
        }
    }
}

struct UpdateTask {
    stack_ptr: isize,
    f_lineage_list: Vec<String>,
    f_radius: f64,
    f_deflection: f64,
    f_angular_deflection: f64,
    fast_mode: bool,
    include_mesh: bool,
    binary_payload: Vec<u8>,
    stream: TcpStream,
}

// Per-stack worker map: stack_ptr → Sender<UpdateTask>
// Different stacks can run OCC updates in parallel.
// Same stack's tasks are thinned (only latest is executed).
type StackWorkers = Arc<Mutex<HashMap<isize, mpsc::Sender<UpdateTask>>>>;

fn get_or_spawn_stack_worker(stack_ptr: isize, workers: &StackWorkers) -> mpsc::Sender<UpdateTask> {
    let mut map = workers.lock().unwrap();
    map.entry(stack_ptr).or_insert_with(|| {
        let (tx, rx) = mpsc::channel::<UpdateTask>();
        std::thread::spawn(move || run_stack_worker(rx));
        tx
    }).clone()
}

fn send_update_result(stream: &mut TcpStream, r: seamless_core::AsyncResult) {
    if stream.write_all(&[1u8]).is_err() { return; }
    let ep_len = r.edge_points.len() * 4;
    let ec_len = r.edge_counts.len() * 4;
    let v_len  = r.mesh_verts.len() * 4;
    let t_len  = r.mesh_tris.len() * 4;
    let mtc_len= r.mesh_tri_counts.len() * 4;
    let lengths = [ep_len as u32, ec_len as u32, v_len as u32, t_len as u32, mtc_len as u32];
    for l in &lengths {
        if stream.write_all(&l.to_le_bytes()).is_err() { return; }
    }

    let ep_bytes: &[u8] = unsafe { std::slice::from_raw_parts(r.edge_points.as_ptr() as *const u8, ep_len) };
    let ec_bytes: &[u8] = unsafe { std::slice::from_raw_parts(r.edge_counts.as_ptr() as *const u8, ec_len) };
    let v_bytes:  &[u8] = unsafe { std::slice::from_raw_parts(r.mesh_verts.as_ptr() as *const u8, v_len) };
    let t_bytes:  &[u8] = unsafe { std::slice::from_raw_parts(r.mesh_tris.as_ptr() as *const u8, t_len) };
    let mtc_bytes:&[u8] = unsafe { std::slice::from_raw_parts(r.mesh_tri_counts.as_ptr() as *const u8, mtc_len) };

    // Try to place the payload in a shared-memory slot; fall back to socket if it
    // doesn't fit or shm isn't mapped.
    let total = ep_len + ec_len + v_len + t_len + mtc_len;
    let mut use_mmap = false;
    let mut offsets = [0usize; 5];
    if let Some(shm) = SHM.get() {
        if total <= SHM_SLOT_SIZE {
            let base = (SHM_SLOT.fetch_add(1, Ordering::Relaxed) % SHM_SLOTS) * SHM_SLOT_SIZE;
            let mut off = base;
            for (i, (src, len)) in [(ep_bytes, ep_len), (ec_bytes, ec_len), (v_bytes, v_len), (t_bytes, t_len), (mtc_bytes, mtc_len)].iter().enumerate() {
                offsets[i] = off;
                if *len > 0 {
                    unsafe { std::ptr::copy_nonoverlapping(src.as_ptr(), shm.ptr.add(off), *len); }
                }
                off += *len;
            }
            use_mmap = true;
        }
    }

    let mmap_meta = if use_mmap {
        format!(", \"use_mmap\":true, \"mmap_offsets\":[{},{},{},{},{}]",
            offsets[0], offsets[1], offsets[2], offsets[3], offsets[4])
    } else { String::new() };

    let meta_json = format!(
        "{{\"edge_lineages\":{}, \"mesh_face_ids\":{}, \
          \"perf_bool\":{}, \"perf_edge\":{}, \"perf_mesh\":{}, \
          \"perf_prim\":{}, \"perf_bool_main\":{}, \"perf_bool_modifier\":{}, \
          \"perf_extrema\":{}, \"perf_unify\":{}, \"perf_resume_restore\":{}, \
          \"perf_modifier_target_assign\":{}, \"perf_modifier_apply\":{}, \
          \"perf_modifier_recluster\":{}, \"perf_fillet_setup\":{}, \
          \"perf_fillet_target_resolve\":{}, \"perf_fillet_add\":{}, \
          \"perf_fillet_build\":{}, \"perf_fillet_history\":{}, \
          \"perf_fillet_added_edges\":{}, \"perf_fillet_contours\":{}{}}}",
        serde_json::to_string(&r.edge_lineages).unwrap(),
        serde_json::to_string(&r.mesh_face_ids).unwrap(),
        r.perf_bool, r.perf_edge, r.perf_mesh,
        r.perf_prim, r.perf_bool_main, r.perf_bool_modifier,
        r.perf_extrema, r.perf_unify, r.perf_resume_restore,
        r.perf_modifier_target_assign, r.perf_modifier_apply,
        r.perf_modifier_recluster, r.perf_fillet_setup,
        r.perf_fillet_target_resolve, r.perf_fillet_add,
        r.perf_fillet_build, r.perf_fillet_history,
        r.perf_fillet_added_edges, r.perf_fillet_contours,
        mmap_meta,
    );
    let meta_bytes = meta_json.into_bytes();
    if stream.write_all(&(meta_bytes.len() as u32).to_le_bytes()).is_err() { return; }
    if stream.write_all(&meta_bytes).is_err() { return; }

    // Only push the arrays over the socket when we didn't use shared memory.
    if !use_mmap {
        let _ = stream.write_all(ep_bytes);
        let _ = stream.write_all(ec_bytes);
        let _ = stream.write_all(v_bytes);
        let _ = stream.write_all(t_bytes);
        let _ = stream.write_all(mtc_bytes);
    }
}

// Each stack gets its own worker thread. Tasks are thinned: only the latest
// queued task is executed, older ones are cancelled with status byte 2.
fn run_stack_worker(rx: mpsc::Receiver<UpdateTask>) {
    loop {
        let mut latest_task = match rx.recv() {
            Ok(t) => t,
            Err(_) => break,
        };

        // Drain the queue, keep only the newest task (thinning)
        while let Ok(task) = rx.try_recv() {
            let mut old_stream = latest_task.stream;
            let _ = old_stream.write_all(&[2u8]); // 2 = Cancelled
            latest_task = task;
        }

        let stack_ptr            = latest_task.stack_ptr;
        let binary_payload       = latest_task.binary_payload;
        let f_lineage_list       = latest_task.f_lineage_list;
        let f_radius             = latest_task.f_radius;
        let f_deflection         = latest_task.f_deflection;
        let f_angular_deflection = latest_task.f_angular_deflection;
        let fast_mode            = latest_task.fast_mode;
        let include_mesh         = latest_task.include_mesh;
        let mut stream           = latest_task.stream;

        // 外部入力(NULバイトを含む文字列等)に起因するRust側のパニックで
        // このワーカースレッド自体が死んでしまうと、get_or_spawn_stack_worker が
        // 死んだSenderを再利用し続けるため、当該stack_ptrへの以後の update が
        // 永久に無応答になる("ゾンビワーカー")。catch_unwind でタスク単位に
        // 閉じ込め、クライアントにはエラー応答を返した上でループを継続する。
        let res = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            seamless_core::perform_update_internal(
                stack_ptr,
                &binary_payload,
                f_lineage_list,
                f_radius,
                f_deflection,
                f_angular_deflection,
                fast_mode,
                include_mesh,
            )
        }));

        match res {
            Ok(Ok(r)) => send_update_result(&mut stream, r),
            Ok(Err(e)) => {
                if stream.write_all(&[0u8]).is_ok() {
                    let eb = e.as_bytes();
                    let _ = stream.write_all(&(eb.len() as u32).to_le_bytes());
                    let _ = stream.write_all(eb);
                }
            }
            Err(panic_payload) => {
                let msg = panic_payload.downcast_ref::<&str>().map(|s| s.to_string())
                    .or_else(|| panic_payload.downcast_ref::<String>().cloned())
                    .unwrap_or_else(|| "unknown panic".to_string());
                eprintln!("Seamless CAD Server: update panicked for stack {}: {}", stack_ptr, msg);
                if stream.write_all(&[0u8]).is_ok() {
                    let eb = format!("internal error (panic): {}", msg).into_bytes();
                    let _ = stream.write_all(&(eb.len() as u32).to_le_bytes());
                    let _ = stream.write_all(&eb);
                }
            }
        }
    }
}

fn handle_client(mut stream: TcpStream, workers: StackWorkers) {
    let mut len_buf = [0u8; 4];
    if stream.read_exact(&mut len_buf).is_err() { return; }
    let msg_len = u32::from_le_bytes(len_buf) as usize;

    let mut msg_buf = vec![0u8; msg_len];
    if stream.read_exact(&mut msg_buf).is_err() { return; }

    let mut json_str_slice = &msg_buf[..];
    let mut binary_payload = &[][..];

    if msg_len >= 4 && msg_buf[0] != b'{' {
        let json_len = u32::from_le_bytes([msg_buf[0], msg_buf[1], msg_buf[2], msg_buf[3]]) as usize;
        if json_len + 4 <= msg_len {
            json_str_slice  = &msg_buf[4..4+json_len];
            binary_payload  = &msg_buf[4+json_len..];
        }
    }

    // Fast binary picking protocol (compact binary frame)
    if msg_len == 37 || msg_len == 41 {
        let action = msg_buf[0];
        if action >= 1 && action <= 6 {
            let mut ptr_bytes = [0u8; 8];
            ptr_bytes.copy_from_slice(&msg_buf[1..9]);
            let stack_ptr = i64::from_le_bytes(ptr_bytes) as isize;

            let mut idx_offset = 9;
            let mut stack_idx  = 0i32;
            if msg_len == 41 {
                let mut idx_bytes = [0u8; 4];
                idx_bytes.copy_from_slice(&msg_buf[9..13]);
                stack_idx  = i32::from_le_bytes(idx_bytes);
                idx_offset = 13;
            }

            let mut o = [0.0f32; 3];
            let mut d = [0.0f32; 3];
            for i in 0..3 {
                let mut b = [0u8; 4];
                b.copy_from_slice(&msg_buf[idx_offset + i*4 .. idx_offset + i*4 + 4]);
                o[i] = f32::from_le_bytes(b);
                b.copy_from_slice(&msg_buf[idx_offset + 12 + i*4 .. idx_offset + 12 + i*4 + 4]);
                d[i] = f32::from_le_bytes(b);
            }
            let mut tol_bytes = [0u8; 4];
            tol_bytes.copy_from_slice(&msg_buf[idx_offset + 24 .. idx_offset + 28]);
            let tolerance = f32::from_le_bytes(tol_bytes);

            let origin    = o.to_vec();
            let direction = d.to_vec();

            let mut handled = false;
            let mut write_res_bin = |lid: &str, floats: &[f32]| {
                handled = true;
                stream.write_all(&[1u8]).unwrap();
                let lid_bytes = lid.as_bytes();
                let total_len = 4 + lid_bytes.len() + 4 + floats.len() * 4;
                stream.write_all(&(total_len as u32).to_le_bytes()).unwrap();
                stream.write_all(&(lid_bytes.len() as u32).to_le_bytes()).unwrap();
                stream.write_all(lid_bytes).unwrap();
                stream.write_all(&(floats.len() as u32).to_le_bytes()).unwrap();
                let f_bytes: &[u8] = unsafe { std::slice::from_raw_parts(floats.as_ptr() as *const u8, floats.len() * 4) };
                stream.write_all(f_bytes).unwrap();
            };

            match action {
                1 => if let Ok(Some(r)) = seamless_core::pick_edge(stack_ptr, origin.clone(), direction.clone(), tolerance)             { write_res_bin(&r.0, &[r.1, r.2, r.3]); },
                2 => if let Ok(Some(r)) = seamless_core::pick_face(stack_ptr, origin.clone(), direction.clone(), tolerance)             { write_res_bin(&r.0, &[r.1, r.2, r.3, r.4, r.5, r.6]); },
                3 => if let Ok(Some(r)) = seamless_core::pick_vertex_from_stack(stack_ptr, stack_idx, origin.clone(), direction.clone(), tolerance)   { write_res_bin(&r.0, &[r.1, r.2, r.3, r.4, r.5, r.6]); },
                4 => if let Ok(Some(r)) = seamless_core::pick_midpoint_from_stack(stack_ptr, stack_idx, origin.clone(), direction.clone(), tolerance) { write_res_bin(&r.0, &[r.1, r.2, r.3, r.4, r.5, r.6]); },
                5 => if let Ok(Some(r)) = seamless_core::pick_face_from_stack(stack_ptr, stack_idx, origin.clone(), direction.clone(), tolerance)     { write_res_bin(&r.0, &[r.1, r.2, r.3, r.4, r.5, r.6]); },
                6 => if let Ok(Some(r)) = seamless_core::pick_edge_from_stack(stack_ptr, stack_idx, origin.clone(), direction.clone(), tolerance)     { write_res_bin(&r.0, &[r.1, r.2, r.3]); },
                _ => {},
            }
            if !handled { stream.write_all(&[0u8]).unwrap(); }
            return;
        }
    }

    let msg_str = String::from_utf8_lossy(json_str_slice);

    if let Ok(req) = serde_json::from_str::<serde_json::Value>(&msg_str) {
        let action = req["action"].as_str().unwrap_or("");

        if action == "update" {
            let stack_ptr             = req["stack_ptr"].as_i64().unwrap_or(0) as isize;
            let f_radius              = req["f_radius"].as_f64().unwrap_or(0.0);
            let f_deflection          = req["f_deflection"].as_f64().unwrap_or(0.1);
            let f_angular_deflection  = req["f_angular_deflection"].as_f64().unwrap_or(0.5);
            let fast_mode             = req["fast_mode"].as_bool().unwrap_or(false);
            let include_mesh          = req["include_mesh"].as_bool().unwrap_or(true);
            let f_lineage_list: Vec<String> = req["f_lineage_list"].as_array().unwrap_or(&vec![])
                .iter().map(|v| v.as_str().unwrap_or("").to_string()).collect();

            let task = UpdateTask {
                stack_ptr, f_lineage_list, f_radius, f_deflection, f_angular_deflection,
                fast_mode, include_mesh,
                binary_payload: binary_payload.to_vec(),
                stream,
            };
            // Route to the per-stack worker (spawns one if first time for this stack)
            let tx = get_or_spawn_stack_worker(stack_ptr, &workers);
            let _ = tx.send(task);
            return;

        } else if action == "create_stack" {
            let ptr = seamless_core::create_cad_stack();
            stream.write_all(&[1u8]).unwrap();
            stream.write_all(&(ptr as i64).to_le_bytes()).unwrap();

        } else if action == "delete_stack" {
            let stack_ptr = req["stack_ptr"].as_i64().unwrap_or(0) as isize;
            // 1) Sender を先に外す → worker は新タスクを受け取れなくなり、次の recv() でスレッド終了へ
            {
                let mut map = workers.lock().unwrap();
                map.remove(&stack_ptr);
            }
            // 2) スタックロックを取得してから C++ メモリ解放
            //    perform_update_internal が実行中なら完了まで待機 (use-after-free 防止)
            {
                let occ_mutex = seamless_core::get_stack_lock(stack_ptr);
                let _guard = occ_mutex.lock().unwrap();
                seamless_core::delete_cad_stack(stack_ptr);
            }
            // 3) このスタック分のwgpuジオメトリだけを取り除く（他の生存中パーツは影響を受けない）
            seamless_core::remove_render_scene_stack(stack_ptr);
            // 4) このスタックの CSG プレビュー状態（キャッシュ済みメッシュ）も破棄
            PREVIEW_STATE.lock().unwrap().remove(&stack_ptr);
            stream.write_all(&[1u8]).unwrap();

        } else if action == "pick_edge" {
            let stack_ptr = req["stack_ptr"].as_i64().unwrap_or(0) as isize;
            let origin:    Vec<f32> = req["origin"].as_array().unwrap_or(&vec![]).iter().map(|v| v.as_f64().unwrap_or(0.0) as f32).collect();
            let direction: Vec<f32> = req["direction"].as_array().unwrap_or(&vec![]).iter().map(|v| v.as_f64().unwrap_or(0.0) as f32).collect();
            let tolerance = req["tolerance"].as_f64().unwrap_or(0.6) as f32;
            if let Ok(Some(res)) = seamless_core::pick_edge(stack_ptr, origin, direction, tolerance) {
                stream.write_all(&[1u8]).unwrap();
                let json_bytes = serde_json::to_string(&res).unwrap().into_bytes();
                stream.write_all(&(json_bytes.len() as u32).to_le_bytes()).unwrap();
                stream.write_all(&json_bytes).unwrap();
            } else { stream.write_all(&[0u8]).unwrap(); }

        } else if action == "pick_face" {
            let stack_ptr = req["stack_ptr"].as_i64().unwrap_or(0) as isize;
            let origin:    Vec<f32> = req["origin"].as_array().unwrap_or(&vec![]).iter().map(|v| v.as_f64().unwrap_or(0.0) as f32).collect();
            let direction: Vec<f32> = req["direction"].as_array().unwrap_or(&vec![]).iter().map(|v| v.as_f64().unwrap_or(0.0) as f32).collect();
            let tolerance = req["tolerance"].as_f64().unwrap_or(0.6) as f32;
            if let Ok(Some(res)) = seamless_core::pick_face(stack_ptr, origin, direction, tolerance) {
                stream.write_all(&[1u8]).unwrap();
                let json_bytes = serde_json::to_string(&res).unwrap().into_bytes();
                stream.write_all(&(json_bytes.len() as u32).to_le_bytes()).unwrap();
                stream.write_all(&json_bytes).unwrap();
            } else { stream.write_all(&[0u8]).unwrap(); }

        } else if action == "generate_mesh" {
            let stack_ptr        = req["stack_ptr"].as_i64().unwrap_or(0) as isize;
            let deflection       = req["deflection"].as_f64().unwrap_or(0.1);
            let angular_defl     = req["angular_deflection"].as_f64().unwrap_or(0.5);
            if let Ok((verts, tris, face_ids, tri_counts)) = seamless_core::generate_mesh(stack_ptr, deflection, angular_defl) {
                stream.write_all(&[1u8]).unwrap();
                let lengths = [(verts.len()*4) as u32, (tris.len()*4) as u32, (tri_counts.len()*4) as u32];
                for l in &lengths { stream.write_all(&l.to_le_bytes()).unwrap(); }
                let meta = format!("{{\"face_ids\":{}}}", serde_json::to_string(&face_ids).unwrap_or("[]".into()));
                let mb = meta.into_bytes();
                stream.write_all(&(mb.len() as u32).to_le_bytes()).unwrap();
                stream.write_all(&mb).unwrap();
                let vb: &[u8] = unsafe { std::slice::from_raw_parts(verts.as_ptr()      as *const u8, verts.len()*4) };
                let tb: &[u8] = unsafe { std::slice::from_raw_parts(tris.as_ptr()       as *const u8, tris.len()*4) };
                let tc: &[u8] = unsafe { std::slice::from_raw_parts(tri_counts.as_ptr() as *const u8, tri_counts.len()*4) };
                stream.write_all(vb).unwrap(); stream.write_all(tb).unwrap(); stream.write_all(tc).unwrap();
            } else { stream.write_all(&[0u8]).unwrap(); }

        } else if action == "pick_vertex_from_stack" {
            let stack_ptr = req["stack_ptr"].as_i64().unwrap_or(0) as isize;
            let stack_idx = req["stack_idx"].as_i64().unwrap_or(0) as i32;
            let origin:    Vec<f32> = req["origin"].as_array().unwrap_or(&vec![]).iter().map(|v| v.as_f64().unwrap_or(0.0) as f32).collect();
            let direction: Vec<f32> = req["direction"].as_array().unwrap_or(&vec![]).iter().map(|v| v.as_f64().unwrap_or(0.0) as f32).collect();
            let tolerance = req["tolerance"].as_f64().unwrap_or(0.6) as f32;
            if let Ok(Some(res)) = seamless_core::pick_vertex_from_stack(stack_ptr, stack_idx, origin, direction, tolerance) {
                stream.write_all(&[1u8]).unwrap();
                let json_bytes = serde_json::to_string(&res).unwrap().into_bytes();
                stream.write_all(&(json_bytes.len() as u32).to_le_bytes()).unwrap();
                stream.write_all(&json_bytes).unwrap();
            } else { stream.write_all(&[0u8]).unwrap(); }

        } else if action == "pick_midpoint_from_stack" {
            let stack_ptr = req["stack_ptr"].as_i64().unwrap_or(0) as isize;
            let stack_idx = req["stack_idx"].as_i64().unwrap_or(0) as i32;
            let origin:    Vec<f32> = req["origin"].as_array().unwrap_or(&vec![]).iter().map(|v| v.as_f64().unwrap_or(0.0) as f32).collect();
            let direction: Vec<f32> = req["direction"].as_array().unwrap_or(&vec![]).iter().map(|v| v.as_f64().unwrap_or(0.0) as f32).collect();
            let tolerance = req["tolerance"].as_f64().unwrap_or(0.6) as f32;
            if let Ok(Some(res)) = seamless_core::pick_midpoint_from_stack(stack_ptr, stack_idx, origin, direction, tolerance) {
                stream.write_all(&[1u8]).unwrap();
                let json_bytes = serde_json::to_string(&res).unwrap().into_bytes();
                stream.write_all(&(json_bytes.len() as u32).to_le_bytes()).unwrap();
                stream.write_all(&json_bytes).unwrap();
            } else { stream.write_all(&[0u8]).unwrap(); }

        } else if action == "pick_face_from_stack" {
            let stack_ptr = req["stack_ptr"].as_i64().unwrap_or(0) as isize;
            let stack_idx = req["stack_idx"].as_i64().unwrap_or(0) as i32;
            let origin:    Vec<f32> = req["origin"].as_array().unwrap_or(&vec![]).iter().map(|v| v.as_f64().unwrap_or(0.0) as f32).collect();
            let direction: Vec<f32> = req["direction"].as_array().unwrap_or(&vec![]).iter().map(|v| v.as_f64().unwrap_or(0.0) as f32).collect();
            let tolerance = req["tolerance"].as_f64().unwrap_or(0.6) as f32;
            if let Ok(Some(res)) = seamless_core::pick_face_from_stack(stack_ptr, stack_idx, origin, direction, tolerance) {
                stream.write_all(&[1u8]).unwrap();
                let json_bytes = serde_json::to_string(&res).unwrap().into_bytes();
                stream.write_all(&(json_bytes.len() as u32).to_le_bytes()).unwrap();
                stream.write_all(&json_bytes).unwrap();
            } else { stream.write_all(&[0u8]).unwrap(); }

        } else if action == "pick_edge_from_stack" {
            let stack_ptr = req["stack_ptr"].as_i64().unwrap_or(0) as isize;
            let stack_idx = req["stack_idx"].as_i64().unwrap_or(0) as i32;
            let origin:    Vec<f32> = req["origin"].as_array().unwrap_or(&vec![]).iter().map(|v| v.as_f64().unwrap_or(0.0) as f32).collect();
            let direction: Vec<f32> = req["direction"].as_array().unwrap_or(&vec![]).iter().map(|v| v.as_f64().unwrap_or(0.0) as f32).collect();
            let tolerance = req["tolerance"].as_f64().unwrap_or(0.6) as f32;
            if let Ok(Some(res)) = seamless_core::pick_edge_from_stack(stack_ptr, stack_idx, origin, direction, tolerance) {
                stream.write_all(&[1u8]).unwrap();
                let json_bytes = serde_json::to_string(&res).unwrap().into_bytes();
                stream.write_all(&(json_bytes.len() as u32).to_le_bytes()).unwrap();
                stream.write_all(&json_bytes).unwrap();
            } else { stream.write_all(&[0u8]).unwrap(); }

        } else if action == "solve_sketch" {
            let mut points_vec = Vec::new();
            if let Some(pts_arr) = req["points"].as_array() {
                for pt_val in pts_arr {
                    if let Some(arr) = pt_val.as_array() {
                        if arr.len() == 3 {
                            points_vec.push((
                                arr[0].as_u64().unwrap_or(0) as u32,
                                arr[1].as_f64().unwrap_or(0.0),
                                arr[2].as_f64().unwrap_or(0.0),
                            ));
                        }
                    }
                }
            }
            let mut consts_vec = Vec::new();
            if let Some(consts_arr) = req["constraints"].as_array() {
                for c_val in consts_arr {
                    if let Some(arr) = c_val.as_array() {
                        if arr.len() == 3 {
                            consts_vec.push((
                                arr[0].as_str().unwrap_or("").to_string(),
                                arr[1].as_array().unwrap_or(&vec![]).iter().map(|v| v.as_u64().unwrap_or(0) as u32).collect::<Vec<_>>(),
                                arr[2].as_f64().unwrap_or(0.0),
                            ));
                        }
                    }
                }
            }
            match seamless_core::solve_sketch(points_vec, consts_vec) {
                Ok(res) => {
                    stream.write_all(&[1u8]).unwrap();
                    let json_bytes = serde_json::to_string(&res).unwrap().into_bytes();
                    stream.write_all(&(json_bytes.len() as u32).to_le_bytes()).unwrap();
                    stream.write_all(&json_bytes).unwrap();
                },
                Err(e) => {
                    stream.write_all(&[0u8]).unwrap();
                    let eb = e.as_bytes();
                    stream.write_all(&(eb.len() as u32).to_le_bytes()).unwrap();
                    stream.write_all(eb).unwrap();
                }
            }

        } else if action == "import_step" {
            let filepath = req["filepath"].as_str().unwrap_or("");
            let scale    = req["scale"].as_f64().unwrap_or(1.0);
            match seamless_core::import_step(filepath, scale) {
                Ok(uuids) => {
                    stream.write_all(&[1u8]).unwrap();
                    let json_bytes = serde_json::to_string(&uuids).unwrap().into_bytes();
                    stream.write_all(&(json_bytes.len() as u32).to_le_bytes()).unwrap();
                    stream.write_all(&json_bytes).unwrap();
                },
                Err(e) => {
                    stream.write_all(&[0u8]).unwrap();
                    let eb = e.as_bytes();
                    stream.write_all(&(eb.len() as u32).to_le_bytes()).unwrap();
                    stream.write_all(eb).unwrap();
                }
            }

        } else if action == "import_svg" {
            let filepath  = req["filepath"].as_str().unwrap_or("");
            let scale     = req["scale"].as_f64().unwrap_or(1.0);
            let flat_data: Vec<f64> = req["flat_data"].as_array().unwrap_or(&vec![]).iter().map(|v| v.as_f64().unwrap_or(0.0)).collect();
            match seamless_core::import_svg(filepath, scale, flat_data) {
                Ok(uuids) => {
                    stream.write_all(&[1u8]).unwrap();
                    let json_bytes = serde_json::to_string(&uuids).unwrap().into_bytes();
                    stream.write_all(&(json_bytes.len() as u32).to_le_bytes()).unwrap();
                    stream.write_all(&json_bytes).unwrap();
                },
                Err(e) => {
                    stream.write_all(&[0u8]).unwrap();
                    let eb = e.as_bytes();
                    stream.write_all(&(eb.len() as u32).to_le_bytes()).unwrap();
                    stream.write_all(eb).unwrap();
                }
            }

        } else if action == "export_step" {
            let filepath = req["filepath"].as_str().unwrap_or("");
            let uuids: Vec<String> = req["uuids"].as_array().unwrap_or(&vec![]).iter().map(|v| v.as_str().unwrap_or("").to_string()).collect();
            match seamless_core::export_step(uuids, filepath) {
                Ok(_) => { stream.write_all(&[1u8]).unwrap(); },
                Err(e) => {
                    stream.write_all(&[0u8]).unwrap();
                    let eb = e.as_bytes();
                    stream.write_all(&(eb.len() as u32).to_le_bytes()).unwrap();
                    stream.write_all(eb).unwrap();
                }
            }

        } else if action == "measure_stack" {
            // 応答: 成功なら 1u8 + f64 を 11 個 (リトルエンディアン)。
            // 失敗なら 0u8 + エラー長 + エラー文字列。export_stack_to_step と同じ形。
            let stack_ptr = req["stack_ptr"].as_i64().unwrap_or(0) as isize;
            match seamless_core::measure_stack(stack_ptr) {
                Ok(vals) => {
                    stream.write_all(&[1u8]).unwrap();
                    for v in &vals {
                        stream.write_all(&v.to_le_bytes()).unwrap();
                    }
                },
                Err(e) => {
                    stream.write_all(&[0u8]).unwrap();
                    let eb = e.as_bytes();
                    stream.write_all(&(eb.len() as u32).to_le_bytes()).unwrap();
                    stream.write_all(eb).unwrap();
                }
            }

        } else if action == "measure_entity" {
            // 応答は measure_stack と同じ形。成功なら 1u8 + f64 4個
            let stack_ptr = req["stack_ptr"].as_i64().unwrap_or(0) as isize;
            let lineage   = req["lineage"].as_str().unwrap_or("");
            let is_face   = req["is_face"].as_bool().unwrap_or(false);
            match seamless_core::measure_entity(stack_ptr, lineage, is_face) {
                Ok(vals) => {
                    stream.write_all(&[1u8]).unwrap();
                    for v in &vals { stream.write_all(&v.to_le_bytes()).unwrap(); }
                },
                Err(e) => {
                    stream.write_all(&[0u8]).unwrap();
                    let eb = e.as_bytes();
                    stream.write_all(&(eb.len() as u32).to_le_bytes()).unwrap();
                    stream.write_all(eb).unwrap();
                }
            }

        } else if action == "export_stack_to_step" {
            let filepath  = req["filepath"].as_str().unwrap_or("");
            let stack_ptr = req["stack_ptr"].as_i64().unwrap_or(0) as isize;
            // 未指定なら 1.0 = 従来どおり 1 Blender 単位 1 mm
            let scale     = req["scale"].as_f64().unwrap_or(1.0);
            match seamless_core::export_stack_to_step(stack_ptr, filepath, scale) {
                Ok(_) => { stream.write_all(&[1u8]).unwrap(); },
                Err(e) => {
                    stream.write_all(&[0u8]).unwrap();
                    let eb = e.as_bytes();
                    stream.write_all(&(eb.len() as u32).to_le_bytes()).unwrap();
                    stream.write_all(eb).unwrap();
                }
            }

        } else if action == "export_stack_to_stl" {
            // 応答は export_stack_to_step と同じ形 (成功 1u8 / 失敗 0u8 + 長さ + 文字列)。
            let filepath  = req["filepath"].as_str().unwrap_or("");
            let stack_ptr = req["stack_ptr"].as_i64().unwrap_or(0) as isize;
            let scale     = req["scale"].as_f64().unwrap_or(1.0);
            // たわみ量の既定は「指定が来なかったとき」の保険。実際の値は
            // アドオン側の品質設定から必ず送られてくる。角度は**ラジアン**。
            let lin       = req["linear_deflection"].as_f64().unwrap_or(0.1);
            let ang       = req["angular_deflection"].as_f64().unwrap_or(0.5);
            let ascii     = req["ascii"].as_bool().unwrap_or(false);
            match seamless_core::export_stack_to_stl(stack_ptr, filepath, scale, lin, ang, ascii) {
                Ok(_) => { stream.write_all(&[1u8]).unwrap(); },
                Err(e) => {
                    stream.write_all(&[0u8]).unwrap();
                    let eb = e.as_bytes();
                    stream.write_all(&(eb.len() as u32).to_le_bytes()).unwrap();
                    stream.write_all(eb).unwrap();
                }
            }

        } else if action == "render_viewport" {
            let width  = req["width"].as_u64().unwrap_or(256) as u32;
            let height = req["height"].as_u64().unwrap_or(256) as u32;
            let view_proj: Vec<f32> = req["view_proj"].as_array().unwrap_or(&vec![])
                .iter().map(|v| v.as_f64().unwrap_or(0.0) as f32).collect();
            match seamless_core::render_viewport(width, height, view_proj) {
                Ok(pixels) => {
                    stream.write_all(&[1u8]).unwrap();
                    stream.write_all(&(pixels.len() as u32).to_le_bytes()).unwrap();
                    stream.write_all(&pixels).unwrap();
                },
                Err(e) => {
                    stream.write_all(&[0u8]).unwrap();
                    let eb = e.as_bytes();
                    stream.write_all(&(eb.len() as u32).to_le_bytes()).unwrap();
                    stream.write_all(eb).unwrap();
                }
            }

        } else if action == "render_viewport_sdf" {
            let width  = req["width"].as_u64().unwrap_or(256) as u32;
            let height = req["height"].as_u64().unwrap_or(256) as u32;
            let view_proj: Vec<f32> = req["view_proj"].as_array().unwrap_or(&vec![])
                .iter().map(|v| v.as_f64().unwrap_or(0.0) as f32).collect();
            let inv_view_proj: Vec<f32> = req["inv_view_proj"].as_array().unwrap_or(&vec![])
                .iter().map(|v| v.as_f64().unwrap_or(0.0) as f32).collect();
            let camera_pos: Vec<f32> = req["camera_pos"].as_array().unwrap_or(&vec![])
                .iter().map(|v| v.as_f64().unwrap_or(0.0) as f32).collect();
            let fillet_radius = req["fillet_radius"].as_f64().unwrap_or(0.0) as f32;
            let box_size: Vec<f32> = req["box_size"].as_array().unwrap_or(&vec![])
                .iter().map(|v| v.as_f64().unwrap_or(1.0) as f32).collect();

            match seamless_core::render_viewport_sdf(width, height, view_proj, inv_view_proj, camera_pos, fillet_radius, box_size) {
                Ok(pixels) => {
                    stream.write_all(&[1u8]).unwrap();
                    stream.write_all(&(pixels.len() as u32).to_le_bytes()).unwrap();
                    stream.write_all(&pixels).unwrap();
                },
                Err(e) => {
                    stream.write_all(&[0u8]).unwrap();
                    let eb = e.as_bytes();
                    stream.write_all(&(eb.len() as u32).to_le_bytes()).unwrap();
                    stream.write_all(eb).unwrap();
                }
            }

        } else if action == "csg_preview_begin" {
            // Tessellate base (result before the tool) + tool (world-space at drag
            // start) directly from the OCC stack, once at drag start.
            let stack_ptr  = req["stack_ptr"].as_i64().unwrap_or(0) as isize;
            let tool_index = req["tool_index"].as_i64().unwrap_or(-1) as i32;
            let tool_uuid  = req["tool_uuid"].as_str().unwrap_or("").to_string();
            let deflection = req["deflection"].as_f64().unwrap_or(0.2);
            let angular    = req["angular_deflection"].as_f64().unwrap_or(0.7);
            let op         = req["op"].as_str().unwrap_or("SUB").to_uppercase();

            match seamless_core::tessellate_preview_meshes(stack_ptr, tool_index, &tool_uuid, deflection, angular) {
                Some((base_v, base_t, tool_v, tool_t)) if !base_t.is_empty() && !tool_t.is_empty() => {
                    PREVIEW_STATE.lock().unwrap().insert(stack_ptr, PreviewMesh { base_v, base_t, tool_v, tool_t, op });
                    stream.write_all(&[1u8]).unwrap();
                }
                _ => { stream.write_all(&[0u8]).unwrap(); }
            }

        } else if action == "csg_preview_update" {
            // Transform the tool by the current drag matrix, run the BSP boolean,
            // extract feature edges, and return them as a compact binary frame.
            let stack_ptr = req["stack_ptr"].as_i64().unwrap_or(0) as isize;
            let m: Vec<f32> = req["transform"].as_array().unwrap_or(&vec![])
                .iter().map(|v| v.as_f64().unwrap_or(0.0) as f32).collect();
            let angle = req["feature_angle"].as_f64().unwrap_or(20.0);
            // V8.1.5: ゴーストプレビュー - 呼び出し側が明示的に要求した場合のみ、
            // 削除/追加される体積のverts+trisも計算して末尾に返す(旧クライアントは
            // このキーを送らないため応答フォーマットは完全に従来通りのまま)。
            let include_ghost = req["include_ghost"].as_bool().unwrap_or(false);

            let result = if m.len() == 16 {
                let guard = PREVIEW_STATE.lock().unwrap();
                guard.get(&stack_ptr).map(|pm| {
                    let mut mat = [0.0f32; 16];
                    mat.copy_from_slice(&m);
                    let tool_v = seamless_core::csg::transform_verts(&pm.tool_v, &mat);
                    let (rv, rt) = match pm.op.as_str() {
                        "ADD" | "UNION" | "FUSE" => seamless_core::csg::union(&pm.base_v, &pm.base_t, &tool_v, &pm.tool_t),
                        "INT" | "INTERSECT" | "COMMON" => seamless_core::csg::intersect(&pm.base_v, &pm.base_t, &tool_v, &pm.tool_t),
                        _ => seamless_core::csg::subtract(&pm.base_v, &pm.base_t, &tool_v, &pm.tool_t),
                    };
                    let (ep, ec) = seamless_core::csg::feature_edges(&rv, &rt, angle);
                    // ゴースト体積: SUBは「削除される部分」= base∩tool、ADDは「追加される部分」
                    // = tool - base。INTはこのバージョンでは対象外(空を返す)。
                    let ghost = if include_ghost {
                        match pm.op.as_str() {
                            "ADD" | "UNION" | "FUSE" => Some(seamless_core::csg::subtract(&tool_v, &pm.tool_t, &pm.base_v, &pm.base_t)),
                            "INT" | "INTERSECT" | "COMMON" => None,
                            _ => Some(seamless_core::csg::intersect(&pm.base_v, &pm.base_t, &tool_v, &pm.tool_t)),
                        }
                    } else { None };
                    (ep, ec, ghost, include_ghost)
                })
            } else { None };

            match result {
                Some((points, counts, ghost, include_ghost)) => {
                    stream.write_all(&[1u8]).unwrap();
                    stream.write_all(&((points.len() * 4) as u32).to_le_bytes()).unwrap();
                    stream.write_all(&((counts.len() * 4) as u32).to_le_bytes()).unwrap();
                    let pb: &[u8] = unsafe { std::slice::from_raw_parts(points.as_ptr() as *const u8, points.len() * 4) };
                    let cb: &[u8] = unsafe { std::slice::from_raw_parts(counts.as_ptr() as *const u8, counts.len() * 4) };
                    let _ = stream.write_all(pb);
                    let _ = stream.write_all(cb);
                    if include_ghost {
                        let (gv, gt) = ghost.unwrap_or((Vec::new(), Vec::new()));
                        stream.write_all(&((gv.len() * 4) as u32).to_le_bytes()).unwrap();
                        stream.write_all(&((gt.len() * 4) as u32).to_le_bytes()).unwrap();
                        let gvb: &[u8] = unsafe { std::slice::from_raw_parts(gv.as_ptr() as *const u8, gv.len() * 4) };
                        let gtb: &[u8] = unsafe { std::slice::from_raw_parts(gt.as_ptr() as *const u8, gt.len() * 4) };
                        let _ = stream.write_all(gvb);
                        let _ = stream.write_all(gtb);
                    }
                }
                None => { stream.write_all(&[0u8]).unwrap(); }
            }

        } else if action == "csg_preview_end" {
            let stack_ptr = req["stack_ptr"].as_i64().unwrap_or(0) as isize;
            PREVIEW_STATE.lock().unwrap().remove(&stack_ptr);
            stream.write_all(&[1u8]).unwrap();
        }
    }
}

// Parent-death watchdog: exit when the launching Blender process disappears.
// atexit in Python kills us on a clean quit, but a Blender CRASH leaves this
// server orphaned holding port 8080. The next Blender session then reuses the
// orphan (start_server just connects to 8080) and draws its stale stacks. By
// self-terminating when the parent PID dies (crash or not), the port frees up
// and the next session always gets a fresh, empty server.
#[cfg(windows)]
fn watch_parent_and_exit(parent_pid: u32) {
    use std::os::raw::c_void;
    type Handle = *mut c_void;
    const SYNCHRONIZE: u32 = 0x0010_0000;
    const WAIT_TIMEOUT: u32 = 0x0000_0102;
    extern "system" {
        fn OpenProcess(access: u32, inherit: i32, pid: u32) -> Handle;
        fn WaitForSingleObject(h: Handle, ms: u32) -> u32;
        fn CloseHandle(h: Handle) -> i32;
    }
    std::thread::spawn(move || unsafe {
        let h = OpenProcess(SYNCHRONIZE, 0, parent_pid);
        if h.is_null() {
            // Parent already gone (or unopenable) -> don't linger as an orphan.
            std::process::exit(0);
        }
        loop {
            if WaitForSingleObject(h, 1000) != WAIT_TIMEOUT {
                CloseHandle(h);
                std::process::exit(0);
            }
        }
    });
}

// Unix equivalent of the watchdog above. There is no waitable process handle, so
// poll once a second instead.
//
// Two independent checks, because neither alone is enough:
//   - getppid() != parent_pid: we are a *direct* child of Blender, so when Blender
//     exits we are reparented to init/launchd and getppid() becomes 1. This fires
//     even while Blender is still an unreaped zombie, which kill(pid, 0) would not.
//   - kill(parent_pid, 0) != 0: covers the case where we were somehow not spawned
//     as a direct child, and catches the pid disappearing outright.
#[cfg(unix)]
fn watch_parent_and_exit(parent_pid: u32) {
    extern "C" {
        fn kill(pid: i32, sig: i32) -> i32;
        fn getppid() -> i32;
    }
    let parent = parent_pid as i32;
    std::thread::spawn(move || loop {
        let orphaned = unsafe { getppid() != parent || kill(parent, 0) != 0 };
        if orphaned {
            std::process::exit(0);
        }
        std::thread::sleep(std::time::Duration::from_secs(1));
    });
}

fn main() {
    // 起動バナーに OCCT の版を出す。8.0.0 と 8.0.1 は API が同じでビルドも
    // 通るので、不具合報告が来たときユーザーがどちらのカーネルを掴んでいるか
    // 判定する手段がこれ以外に無い。seamless_core::api::utils::get_version() は
    // OCC_VERSION_COMPLETE をそのまま返すので、手で更新する版数ではない。
    println!(
        "Starting Seamless CAD Server v1.7.0 (parallel stacks + CSG preview: SUB/ADD/INT) [{}] on port 8080...",
        seamless_core::api::utils::get_version()
    );

    // argv[1] (if present) is the path to Python's 64MB shared-memory file.
    // argv[2] (if present) is the launching Blender PID for the parent watchdog.
    let args: Vec<String> = std::env::args().collect();
    if args.len() > 1 {
        init_shm(&args[1]);
    }
    if args.len() > 2 {
        if let Ok(ppid) = args[2].parse::<u32>() {
            #[cfg(any(windows, unix))]
            watch_parent_and_exit(ppid);
            #[cfg(not(any(windows, unix)))]
            let _ = ppid;
        }
    }

    // Per-stack worker map: each CAD stack gets its own dedicated worker thread.
    // Updates for different stacks run in parallel; same-stack updates are thinned.
    let workers: StackWorkers = Arc::new(Mutex::new(HashMap::new()));

    let listener = TcpListener::bind("127.0.0.1:8080").expect("Failed to bind port 8080");
    for stream in listener.incoming() {
        match stream {
            Ok(stream) => {
                let w = Arc::clone(&workers);
                std::thread::spawn(move || { handle_client(stream, w); });
            }
            Err(e) => eprintln!("Connection error: {}", e),
        }
    }
}
