use cpp::cpp;
use crate::*;

pub fn generate_mesh(stack_ptr: isize, deflection: f64, angular_deflection: f64) -> Result<(Vec<f32>, Vec<i32>, Vec<String>, Vec<i32>), String> {

    if !crate::is_valid_stack_ptr(stack_ptr) {
        return Err(format!("generate_mesh: unknown or already-deleted stack_ptr {}", stack_ptr));
    }

    let total_hash = if let Ok(hashes) = get_stack_total_hashes().lock() {

        *hashes.get(&stack_ptr).unwrap_or(&0)

    } else {

        0

    };

    

    // 🌟【超重要】total_hash が 0（プリミティブが空）の時は、C++ 側のメッシュ生成（BRepMesh）を完全に回避して安全に早期リターンする！

    if total_hash == 0 {
        eprintln!(
            "[CACHE_ANALYSIS][mesh] early-empty stack_ptr={} total_hash=0 deflection={} angular_deflection={}",
            stack_ptr, deflection, angular_deflection
        );

        return Ok((Vec::new(), Vec::new(), Vec::new(), Vec::new()));

    }

    

    let computing = is_computing(stack_ptr);



    if let Ok(caches) = get_mesh_caches().lock() {

        if let Some(cache) = caches.get(&stack_ptr) {
            if cache.total_hash == total_hash {
                eprintln!(
                    "[CACHE_ANALYSIS][mesh] hit stack_ptr={} reason=hash-match total_hash={} deflection={} angular_deflection={} cached_deflection={} cached_angular_deflection={}",
                    stack_ptr, total_hash, deflection, angular_deflection, cache.deflection, cache.angular_deflection
                );
                return Ok((cache.verts.clone(), cache.tris.clone(), cache.face_ids.clone(), cache.tri_counts.clone()));
            }
            if computing {
                eprintln!(
                    "[CACHE_ANALYSIS][mesh] hit stack_ptr={} reason=compute-in-flight requested_hash={} cached_hash={} deflection={} angular_deflection={}",
                    stack_ptr, total_hash, cache.total_hash, deflection, angular_deflection
                );
                return Ok((cache.verts.clone(), cache.tris.clone(), cache.face_ids.clone(), cache.tri_counts.clone()));
            }
            eprintln!(
                "[CACHE_ANALYSIS][mesh] miss stack_ptr={} reason=hash-mismatch requested_hash={} cached_hash={} deflection={} angular_deflection={} cached_deflection={} cached_angular_deflection={}",
                stack_ptr, total_hash, cache.total_hash, deflection, angular_deflection, cache.deflection, cache.angular_deflection
            );
        } else {
            eprintln!(
                "[CACHE_ANALYSIS][mesh] miss stack_ptr={} reason=no-cache total_hash={} deflection={} angular_deflection={}",
                stack_ptr, total_hash, deflection, angular_deflection
            );
        }
    }

    let occ_mutex = get_stack_lock(stack_ptr);

    let _occ_lock = occ_mutex.lock().unwrap();

    unsafe {

        let mut verts: Vec<f32> = Vec::new(); let mut tris: Vec<i32> = Vec::new(); let mut face_ids: Vec<String> = Vec::new(); let mut tri_counts: Vec<i32> = Vec::new();

        let v_ptr = &mut verts as *mut Vec<f32> as *mut std::ffi::c_void;

        let t_ptr = &mut tris as *mut Vec<i32> as *mut std::ffi::c_void;

        let f_ptr = &mut face_ids as *mut Vec<String> as *mut std::ffi::c_void;

        let tc_ptr = &mut tri_counts as *mut Vec<i32> as *mut std::ffi::c_void;

        let rpp: extern "C" fn(*mut Vec<f32>, f32, f32, f32) = rust_push_point;

        let rpc: extern "C" fn(*mut Vec<i32>, i32) = rust_push_count;

        let rps: extern "C" fn(*mut Vec<String>, *const std::ffi::c_char) = rust_push_string;

        cpp!([stack_ptr as "void*", deflection as "double", angular_deflection as "double", v_ptr as "void*", t_ptr as "void*", f_ptr as "void*", tc_ptr as "void*", rpp as "PushPointFn", rpc as "PushCountFn", rps as "PushStringFn"] {
            occ_core::generate_full_mesh(stack_ptr, deflection, angular_deflection, false, v_ptr, t_ptr, f_ptr, tc_ptr, rpp, rpc, rps);
        });

        

        if let Ok(mut caches) = get_mesh_caches().lock() {
            caches.insert(stack_ptr, MeshDataCache {
                total_hash: total_hash,
                deflection: deflection,
                angular_deflection: angular_deflection,
                verts: verts.clone(),
                tris: tris.clone(),
                face_ids: face_ids.clone(),
                tri_counts: tri_counts.clone(),
            });
        }
        eprintln!(
            "[CACHE_ANALYSIS][mesh] store stack_ptr={} total_hash={} verts={} tris={} face_ids={} tri_counts={}",
            stack_ptr, total_hash, verts.len(), tris.len(), face_ids.len(), tri_counts.len()
        );

        Ok((verts, tris, face_ids, tri_counts))

    }

}

pub fn make_variable_box_mesh(tw: f64, th: f64, bw: f64, bh: f64, h: f64, deflection: f64) -> Result<(Vec<f32>, Vec<i32>), String> {

    unsafe {

        let mut verts: Vec<f32> = Vec::new(); let mut tris: Vec<i32> = Vec::new();

        let v_ptr = &mut verts as *mut Vec<f32> as *mut std::ffi::c_void;

        let t_ptr = &mut tris as *mut Vec<i32> as *mut std::ffi::c_void;

        let rpp: extern "C" fn(*mut Vec<f32>, f32, f32, f32) = rust_push_point;

        let rpc: extern "C" fn(*mut Vec<i32>, i32) = rust_push_count;

        let occ_mutex = get_stack_lock(0);

        let _occ_lock = occ_mutex.lock().unwrap();

        cpp!([tw as "double", th as "double", bw as "double", bh as "double", h as "double", deflection as "double", v_ptr as "void*", t_ptr as "void*", rpp as "PushPointFn", rpc as "PushCountFn"] {

            occ_core::make_variable_box_mesh(tw, th, bw, bh, h, deflection, v_ptr, t_ptr, nullptr, rpp, rpc);

        });

        Ok((verts, tris))

    }

}

/// Interactive CSG preview: tessellate the base (result before the tool) and the
/// tool (world-space at drag start) into two welded meshes, for the pure-Rust
/// BSP boolean preview. Read-only w.r.t. the OCC stack.
pub fn tessellate_preview_meshes(
    stack_ptr: isize,
    tool_index: i32,
    tool_uuid: &str,
    deflection: f64,
    angular_deflection: f64,
) -> Option<(Vec<f32>, Vec<i32>, Vec<f32>, Vec<i32>)> {
    if !crate::is_valid_stack_ptr(stack_ptr) {
        return None;
    }
    let occ_mutex = get_stack_lock(stack_ptr);
    let _occ_lock = occ_mutex.lock().unwrap();
    unsafe {
        let mut base_v: Vec<f32> = Vec::new();
        let mut base_t: Vec<i32> = Vec::new();
        let mut tool_v: Vec<f32> = Vec::new();
        let mut tool_t: Vec<i32> = Vec::new();
        let bv = &mut base_v as *mut Vec<f32> as *mut std::ffi::c_void;
        let bt = &mut base_t as *mut Vec<i32> as *mut std::ffi::c_void;
        let tv = &mut tool_v as *mut Vec<f32> as *mut std::ffi::c_void;
        let tt = &mut tool_t as *mut Vec<i32> as *mut std::ffi::c_void;
        let rpp: extern "C" fn(*mut Vec<f32>, f32, f32, f32) = rust_push_point;
        let rpc: extern "C" fn(*mut Vec<i32>, i32) = rust_push_count;

        let uuid_c = std::ffi::CString::new(tool_uuid).unwrap_or_default();
        let uuid_ptr = uuid_c.as_ptr();

        let ok = cpp!([
            stack_ptr as "void*", tool_index as "int", uuid_ptr as "const char*",
            deflection as "double", angular_deflection as "double",
            bv as "void*", bt as "void*", tv as "void*", tt as "void*",
            rpp as "PushPointFn", rpc as "PushCountFn"
        ] -> bool as "bool" {
            return occ_core::tessellate_preview_meshes(stack_ptr, tool_index, uuid_ptr, deflection, angular_deflection, bv, bt, tv, tt, rpp, rpc);
        });

        let _keep_alive = (uuid_c,);
        if ok { Some((base_v, base_t, tool_v, tool_t)) } else { None }
    }
}


