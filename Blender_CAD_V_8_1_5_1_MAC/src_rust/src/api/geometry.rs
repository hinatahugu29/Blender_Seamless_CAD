use cpp::cpp;
use crate::*;

pub fn update_cad_geometry(
    stack_ptr: isize,
    binary_payload: &[u8],
    f_lineage_list: Vec<String>,
    f_radius: f64,
    f_deflection: f64,

    f_angular_deflection: f64,

    fast_mode: bool,
    include_mesh: bool,

) -> Result<(Vec<f32>, Vec<i32>, Vec<String>), String> {

    set_is_computing(stack_ptr, false);

    if let Ok(mut res_guard) = ASYNC_RESULT.lock() {

        *res_guard = None; // 待機中の非同期結果を破棄

    }

    

    match perform_update_internal(stack_ptr, binary_payload, f_lineage_list, f_radius, f_deflection, f_angular_deflection, fast_mode, include_mesh) {
        Ok(res) => {

            Ok((res.edge_points, res.edge_counts, res.edge_lineages))

        },

        Err(e) => {

            eprintln!("Seamless CAD ERROR: Rust update_cad_geometry (SYNC) failed: {}", e);

            Err(String::from(e))

        },

    }

}

pub fn perform_update_internal(
    stack_ptr: isize,
    binary_payload: &[u8],
    f_lineage_list: Vec<String>,

    f_radius: f64,

    f_deflection: f64,

    f_angular_deflection: f64,

    fast_mode: bool,
    include_mesh: bool
) -> Result<AsyncResult, String> {
    if !crate::is_valid_stack_ptr(stack_ptr) {
        return Err(format!("update: unknown or already-deleted stack_ptr {}", stack_ptr));
    }
    let mut primitives: Vec<PrimitiveInput> = Vec::new();
    if binary_payload.len() >= 4 {
        let mut cursor = 0;
        let read_u32 = |c: &mut usize| -> u32 {
            if *c + 4 <= binary_payload.len() { let mut b = [0u8; 4]; b.copy_from_slice(&binary_payload[*c..*c+4]); *c += 4; u32::from_le_bytes(b) } else { 0 }
        };
        let read_u16 = |c: &mut usize| -> u16 {
            if *c + 2 <= binary_payload.len() { let mut b = [0u8; 2]; b.copy_from_slice(&binary_payload[*c..*c+2]); *c += 2; u16::from_le_bytes(b) } else { 0 }
        };
        let read_u8 = |c: &mut usize| -> u8 {
            if *c + 1 <= binary_payload.len() { let v = binary_payload[*c]; *c += 1; v } else { 0 }
        };
        let read_f64 = |c: &mut usize| -> f64 {
            if *c + 8 <= binary_payload.len() { let mut b = [0u8; 8]; b.copy_from_slice(&binary_payload[*c..*c+8]); *c += 8; f64::from_le_bytes(b) } else { 0.0 }
        };
        let read_i32 = |c: &mut usize| -> i32 {
            if *c + 4 <= binary_payload.len() { let mut b = [0u8; 4]; b.copy_from_slice(&binary_payload[*c..*c+4]); *c += 4; i32::from_le_bytes(b) } else { 0 }
        };
        let read_str = |c: &mut usize| -> String {
            let len = read_u16(c) as usize;
            if *c + len <= binary_payload.len() { let s = String::from_utf8_lossy(&binary_payload[*c..*c+len]).to_string(); *c += len; s } else { String::new() }
        };
        let num_prims = read_u32(&mut cursor);
        for _ in 0..num_prims {
            // Strings: ['type', 'operation', 'uuid', 'reference_lineage', 'target_uuid', 'pattern_axis', 'top_shape', 'bot_shape']
            let p_type = read_str(&mut cursor);
            let operation = read_str(&mut cursor);
            let uuid = read_str(&mut cursor);
            let reference_lineage = read_str(&mut cursor);
            let target_uuid = read_str(&mut cursor);
            let pattern_axis = read_str(&mut cursor);
            let top_shape = read_str(&mut cursor);
            let bot_shape = read_str(&mut cursor);
            let sweep_path_uuid = read_str(&mut cursor);
            let sweep_profile_uuid = read_str(&mut cursor);
            let sweep_frame_mode = read_str(&mut cursor);

            // Floats: loc, rot, sz (9d)
            let loc = [read_f64(&mut cursor), read_f64(&mut cursor), read_f64(&mut cursor)];
            let rot = [read_f64(&mut cursor), read_f64(&mut cursor), read_f64(&mut cursor)];
            let size = [read_f64(&mut cursor), read_f64(&mut cursor), read_f64(&mut cursor)];
            let rot_quat = Some([read_f64(&mut cursor), read_f64(&mut cursor), read_f64(&mut cursor), read_f64(&mut cursor)]);

            // Bools and scalars: fill_closed, use_pipe
            let fill_closed = read_u8(&mut cursor) != 0;
            let use_pipe = read_u8(&mut cursor) != 0;

            // <dddddddi ddi dd: radius, pipe_radius, angle_start, angle_end, extrude_height, radius2, minor_radius, sides, module, pressure_angle, count, distance, sweep_roll_degrees
            let radius = read_f64(&mut cursor);
            let pipe_radius = read_f64(&mut cursor);
            let angle_start = read_f64(&mut cursor);
            let angle_end = read_f64(&mut cursor);
            let extrude_height = read_f64(&mut cursor);
            let radius2 = read_f64(&mut cursor);
            let minor_radius = read_f64(&mut cursor);
            let sides = read_i32(&mut cursor);
            let module = read_f64(&mut cursor);
            let pressure_angle = read_f64(&mut cursor);
            let count = read_i32(&mut cursor);
            let distance = read_f64(&mut cursor);
            let sweep_roll_degrees = read_f64(&mut cursor);

            // target_lineages
            let num_tls = read_u16(&mut cursor) as usize;
            let mut target_lineages_v = Vec::new();
            for _ in 0..num_tls {
                target_lineages_v.push(read_str(&mut cursor));
            }

            // loft_uuids
            let num_loft = read_u16(&mut cursor) as usize;
            let mut loft_uuids = Vec::new();
            for _ in 0..num_loft {
                loft_uuids.push(read_str(&mut cursor));
            }

            // points
            let num_pts = read_u32(&mut cursor) as usize;
            let mut points_v = Vec::new();
            for _ in 0..num_pts {
                points_v.push([read_f64(&mut cursor), read_f64(&mut cursor), read_f64(&mut cursor), read_f64(&mut cursor)]);
            }

            // segments
            let num_segs = read_u32(&mut cursor) as usize;
            let mut segments_v = Vec::new();
            for _ in 0..num_segs {
                let s_type = read_str(&mut cursor);
                let read_opt_pt = |c: &mut usize| -> Option<[f64; 3]> {
                    if read_u8(c) == 1 { Some([read_f64(c), read_f64(c), read_f64(c)]) } else { None }
                };
                let st = read_opt_pt(&mut cursor);
                let en = read_opt_pt(&mut cursor);
                let mid = read_opt_pt(&mut cursor);
                let cen = read_opt_pt(&mut cursor);
                
                let rad = if read_u8(&mut cursor) == 1 { Some(read_f64(&mut cursor)) } else { None };
                
                let norm = read_opt_pt(&mut cursor);
                
                segments_v.push(SegmentData {
                    s_type,
                    start: st,
                    end: en,
                    mid: mid,
                    center: cen,
                    radius: rad,
                    normal: norm
                });
            }

            // V8.1.5: 可変フィレット - 末尾追加ブロック(token, radius)ペア。
            // 既存フィールドより後ろに置くことで、旧core_bridge.py(このブロックを
            // 送らないビルド)との構造体レイアウト互換を保つ。
            let num_edge_radii = read_u32(&mut cursor) as usize;
            let mut edge_radii_v = Vec::with_capacity(num_edge_radii);
            for _ in 0..num_edge_radii {
                let token = read_str(&mut cursor);
                let r = read_f64(&mut cursor);
                edge_radii_v.push((token, r));
            }

            primitives.push(PrimitiveInput {
                p_type, operation, uuid, location: loc, rotation: rot, rotation_quat: rot_quat, size,
                radius, fill_closed, use_pipe, pipe_radius, angle_start, angle_end,
                target_lineages: target_lineages_v, reference_lineage, extrude_height,
                radius2, minor_radius, sides, module, pressure_angle,
                target_uuid, count, distance, pattern_axis, top_shape, bot_shape,
                sweep_path_uuid, sweep_profile_uuid, sweep_frame_mode, sweep_roll_degrees, loft_uuids,
                points: Some(points_v), segments: Some(segments_v),
                unify_edges: Some(true), unify_faces: Some(true),
                edge_radii: Some(edge_radii_v)
            });
        }
    }


    

    // 🌟【超重要】プリミティブリストが空の時は、C++ OpenCASCADE FFI へのメモリアロケーションを完全に回避し、TBBアロケータ競合クラッシュを防ぐ！

    if primitives.is_empty() {

        return Ok(AsyncResult {

            total_hash: 0,

            deflection: f_deflection,

            angular_deflection: f_angular_deflection,

            edge_points: Vec::new(),

            edge_counts: Vec::new(),

            edge_lineages: Vec::new(),

            mesh_verts: Vec::new(),

            mesh_tris: Vec::new(),

            mesh_face_ids: Vec::new(),

            mesh_tri_counts: Vec::new(),

            perf_bool: 0.0,
            perf_edge: 0.0,
            perf_mesh: 0.0,
            perf_prim: 0.0,
            perf_bool_main: 0.0,
            perf_bool_modifier: 0.0,
            perf_extrema: 0.0,
            perf_resume_restore: 0.0,
            perf_modifier_target_assign: 0.0,
            perf_modifier_apply: 0.0,
            perf_modifier_recluster: 0.0,
            perf_fillet_setup: 0.0,
            perf_fillet_target_resolve: 0.0,
            perf_fillet_add: 0.0,
            perf_fillet_build: 0.0,
            perf_fillet_history: 0.0,
            perf_fillet_added_edges: 0.0,
            perf_fillet_contours: 0.0,
            perf_unify: 0.0,
        });

    }

    

    let mut total_hash: u64 = 0;

    use rayon::prelude::*;
    use std::collections::hash_map::DefaultHasher;
    use std::hash::{Hash, Hasher};

    // First pass: parallel base hash computation (independent per primitive)
    let base_full_hashes: std::collections::HashMap<String, u64> = primitives
        .par_iter()
        .map(|p| (p.uuid.clone(), p.calculate_full_hash()))
        .collect();

    // Second pass: parallel dependency-mixed hash computation (par_iter preserves order)
    let hash_pairs: Vec<(u64, u64)> = primitives
        .par_iter()
        .map(|p| {
            let mut h_full = p.calculate_full_hash();
            let mut h_geo = p.calculate_geo_hash();
            let mut dep_hasher = DefaultHasher::new();
            let mut has_deps = false;

            for dep_uuid in std::iter::once(p.reference_lineage.as_str())
                .chain(std::iter::once(p.sweep_path_uuid.as_str()))
                .chain(std::iter::once(p.sweep_profile_uuid.as_str()))
                .chain(p.loft_uuids.iter().map(|s| s.as_str()))
                .chain(p.target_lineages.iter().flat_map(|t| t.split('|')))
            {
                if let Some(&dep_hash) = base_full_hashes.get(dep_uuid) {
                    dep_hash.hash(&mut dep_hasher);
                    has_deps = true;
                }
            }

            if has_deps {
                let combined = dep_hasher.finish();
                let mut geo_mix = DefaultHasher::new();
                h_geo.hash(&mut geo_mix);
                combined.hash(&mut geo_mix);
                h_geo = geo_mix.finish();

                let mut full_mix = DefaultHasher::new();
                h_full.hash(&mut full_mix);
                combined.hash(&mut full_mix);
                h_full = full_mix.finish();
            }

            (h_full, h_geo)
        })
        .collect();

    let (primitive_full_hashes, primitive_geo_hashes): (Vec<u64>, Vec<u64>) =
        hash_pairs.into_iter().unzip();

    for &h in &primitive_full_hashes {
        total_hash = total_hash.wrapping_mul(31).wrapping_add(h);
    }

    {

        use std::collections::hash_map::DefaultHasher;

        use std::hash::{Hash, Hasher};

        let mut s = DefaultHasher::new();

        f_lineage_list.hash(&mut s);

        f_radius.to_bits().hash(&mut s);

        f_deflection.to_bits().hash(&mut s);

        f_angular_deflection.to_bits().hash(&mut s);

        total_hash = total_hash.wrapping_mul(31).wrapping_add(s.finish());

    }



    unsafe {

        let mut edge_points = Vec::new();

        let mut edge_counts = Vec::new();

        let mut edge_lineages = Vec::new();

        

        let points_ptr = &mut edge_points as *mut Vec<f32> as *mut std::ffi::c_void;

        let counts_ptr = &mut edge_counts as *mut Vec<i32> as *mut std::ffi::c_void;

        let lineages_out_ptr = &mut edge_lineages as *mut Vec<String> as *mut std::ffi::c_void;

        

        let lineages_c: Vec<std::ffi::CString> = f_lineage_list.iter().map(|s| std::ffi::CString::new(s.as_str()).unwrap()).collect();

        let lineages_ptr: Vec<*const std::ffi::c_char> = lineages_c.iter().map(|s| s.as_ptr()).collect();

        let lineages_ptr_raw = lineages_ptr.as_ptr();

        let n_lineages = f_lineage_list.len() as i32;



        let rpp: extern "C" fn(*mut Vec<f32>, f32, f32, f32) = rust_push_point;

        let rpc: extern "C" fn(*mut Vec<i32>, i32) = rust_push_count;

        let rps: extern "C" fn(*mut Vec<String>, *const std::ffi::c_char) = rust_push_string;



        let mut types = Vec::new(); let mut ops = Vec::new(); let mut uuids = Vec::new();

        let mut locs = Vec::new(); let mut rots = Vec::new(); let mut rots_quat = Vec::new(); let mut sizes = Vec::new();


        let mut radii = Vec::new(); let mut pipe_radii = Vec::new();

        let mut a_starts = Vec::new(); let mut a_ends = Vec::new();

        let mut e_heights = Vec::new(); let mut r2s = Vec::new(); let mut m_radii = Vec::new();

        let mut sides_v = Vec::new(); let mut modules_v = Vec::new(); let mut p_angles = Vec::new();

        let mut t_uuids = Vec::new(); let mut p_counts = Vec::new(); let mut distances_v = Vec::new();

        let mut p_axes = Vec::new(); let mut t_shapes = Vec::new(); let mut b_shapes = Vec::new();
        let mut sweep_frame_modes = Vec::new(); let mut sweep_rolls = Vec::new();

        let mut all_pts = Vec::<f64>::new(); let mut pt_counts = Vec::<i32>::new();

        let mut all_segments = Vec::<f64>::new(); let mut segment_counts = Vec::<i32>::new();



        for p in &primitives {

            types.push(std::ffi::CString::new(p.p_type.as_str()).unwrap());

            ops.push(std::ffi::CString::new(p.operation.as_str()).unwrap());

            uuids.push(std::ffi::CString::new(p.uuid.as_str()).unwrap());

            locs.extend_from_slice(&p.location); rots.extend_from_slice(&p.rotation); sizes.extend_from_slice(&p.size);
            let q = p.rotation_quat.unwrap_or([0.0, 0.0, 0.0, 1.0]); // x, y, z, w
            rots_quat.extend_from_slice(&q);

            a_starts.push(p.angle_start); a_ends.push(p.angle_end); radii.push(p.radius); pipe_radii.push(p.pipe_radius);

            e_heights.push(p.extrude_height); r2s.push(p.radius2); m_radii.push(p.minor_radius);

            sides_v.push(p.sides); modules_v.push(p.module); p_angles.push(p.pressure_angle);

            t_uuids.push(std::ffi::CString::new(p.target_uuid.as_str()).unwrap());

            p_counts.push(p.count); distances_v.push(p.distance);

            p_axes.push(std::ffi::CString::new(p.pattern_axis.as_str()).unwrap());

            t_shapes.push(std::ffi::CString::new(p.top_shape.as_str()).unwrap());

            b_shapes.push(std::ffi::CString::new(p.bot_shape.as_str()).unwrap());

            sweep_frame_modes.push(std::ffi::CString::new(p.sweep_frame_mode.as_str()).unwrap());
            sweep_rolls.push(p.sweep_roll_degrees);

                        if let Some(ref pts) = p.points { pt_counts.push(pts.len() as i32); for pt in pts { all_pts.extend_from_slice(pt); } }

            else { pt_counts.push(0); }

            if let Some(ref segs) = p.segments {

                segment_counts.push(segs.len() as i32);

                for seg in segs {

                    let type_val = match seg.s_type.as_str() {

                        "LINE" => 0.0,

                        "ARC" => 1.0,

                        "CIRCLE" => 2.0,

                        "DELIMITER" => 3.0,

                        _ => -1.0,

                    };

                    all_segments.push(type_val);

                    let push_opt_pnt = |opt: &Option<[f64; 3]>, out: &mut Vec<f64>| {

                        if let Some(pt) = opt { out.extend_from_slice(pt); } else { out.extend_from_slice(&[1e10, 1e10, 1e10]); }

                    };

                    push_opt_pnt(&seg.start, &mut all_segments);

                    push_opt_pnt(&seg.end, &mut all_segments);

                    push_opt_pnt(&seg.mid, &mut all_segments);

                    push_opt_pnt(&seg.center, &mut all_segments);

                    all_segments.push(seg.radius.unwrap_or(1e10));

                    push_opt_pnt(&seg.normal, &mut all_segments);

                }

            } else {

                segment_counts.push(0);

            }

        }

        

        let n_prims = primitives.len() as i32;

        let t_ptr_raw = types.iter().map(|s| s.as_ptr()).collect::<Vec<_>>();

        let o_ptr_raw = ops.iter().map(|s| s.as_ptr()).collect::<Vec<_>>();

        let u_ptr_raw = uuids.iter().map(|s| s.as_ptr()).collect::<Vec<_>>();

        let t_u_ptr_raw = t_uuids.iter().map(|s| s.as_ptr()).collect::<Vec<_>>();

        let p_a_ptr_raw = p_axes.iter().map(|s| s.as_ptr()).collect::<Vec<_>>();

        let ts_ptr_raw = t_shapes.iter().map(|s| s.as_ptr()).collect::<Vec<_>>();

        let bs_ptr_raw = b_shapes.iter().map(|s| s.as_ptr()).collect::<Vec<_>>();
        let sfm_ptr_raw = sweep_frame_modes.iter().map(|s| s.as_ptr()).collect::<Vec<_>>();



        let types_raw = t_ptr_raw.as_ptr();

        let ops_raw = o_ptr_raw.as_ptr();

        let uuids_raw = u_ptr_raw.as_ptr();

        let l_ptr = locs.as_ptr();

        let r_ptr = rots.as_ptr();
        let rq_ptr = rots_quat.as_ptr();

        let s_ptr = sizes.as_ptr();

        let rad_ptr = radii.as_ptr();

        let pr_ptr = pipe_radii.as_ptr();

        let as_ptr = a_starts.as_ptr();

        let ae_ptr = a_ends.as_ptr();

        let eh_ptr = e_heights.as_ptr();

        let r2_ptr = r2s.as_ptr();

        let mr_ptr = m_radii.as_ptr();

        let si_ptr = sides_v.as_ptr();

        let mo_ptr = modules_v.as_ptr();

        let pa_ptr = p_angles.as_ptr();

        let tu_ptr = t_u_ptr_raw.as_ptr();

        let pc_ptr = p_counts.as_ptr();

        let di_ptr = distances_v.as_ptr();

        let pax_ptr = p_a_ptr_raw.as_ptr();

        let ts_ptr = ts_ptr_raw.as_ptr();

        let bs_ptr = bs_ptr_raw.as_ptr();
        let sfm_ptr = sfm_ptr_raw.as_ptr();
        let sroll_ptr = sweep_rolls.as_ptr();

        let ap_ptr = all_pts.as_ptr();

        let ptc_ptr = pt_counts.as_ptr();

        let asegs_ptr = all_segments.as_ptr();

        let segc_ptr = segment_counts.as_ptr();

        let hashes_ptr = primitive_full_hashes.as_ptr();

        let geo_hashes_ptr = primitive_geo_hashes.as_ptr();



        let fill_closed: Vec<i32> = primitives.iter().map(|p| if p.fill_closed { 1 } else { 0 }).collect();

        let use_pipe: Vec<i32> = primitives.iter().map(|p| if p.use_pipe { 1 } else { 0 }).collect();

        let fc_ptr = fill_closed.as_ptr();

        let up_ptr = use_pipe.as_ptr();



        let t_lineages_joined: Vec<String> = primitives.iter().map(|p| p.target_lineages.join("|")).collect();

        let t_lineages_c: Vec<std::ffi::CString> = t_lineages_joined.iter().map(|s| std::ffi::CString::new(s.as_str()).unwrap()).collect();

        let t_lineages_r: Vec<*const i8> = t_lineages_c.iter().map(|c| c.as_ptr()).collect();

        let tl_ptr = t_lineages_r.as_ptr();



        let r_lineages_c: Vec<std::ffi::CString> = primitives.iter().map(|p| std::ffi::CString::new(p.reference_lineage.as_str()).unwrap()).collect();

        let r_lineages_r: Vec<*const i8> = r_lineages_c.iter().map(|c| c.as_ptr()).collect();

        let rl_ptr = r_lineages_r.as_ptr();

        // V8.1.5: 可変フィレット - primitive毎に "token=radius|token=radius" 形式へ結合。
        // トークン自体に '=' や '|' を含まない前提(既存の Edge:/SemLoop: トークン規約に準拠)。
        let edge_radii_joined: Vec<String> = primitives.iter().map(|p| {
            p.edge_radii.as_ref().map(|v| {
                v.iter().map(|(tok, r)| format!("{}={}", tok, r)).collect::<Vec<_>>().join("|")
            }).unwrap_or_default()
        }).collect();

        let edge_radii_c: Vec<std::ffi::CString> = edge_radii_joined.iter().map(|s| std::ffi::CString::new(s.as_str()).unwrap()).collect();

        let edge_radii_r: Vec<*const i8> = edge_radii_c.iter().map(|c| c.as_ptr()).collect();

        let er_ptr = edge_radii_r.as_ptr();



        // FFI debug prints removed to clean up output



        let occ_mutex = get_stack_lock(stack_ptr);

        let _occ_lock = occ_mutex.lock().unwrap();

        let t0_bool = std::time::Instant::now();

        let mut perf_out = [0.0f64; 17];
        let perf_out_ptr = perf_out.as_mut_ptr() as *mut std::ffi::c_void;

        let success = cpp!([
            stack_ptr as "void*",
            n_prims as "int", types_raw as "const char**", ops_raw as "const char**", uuids_raw as "const char**",
            l_ptr as "const double*", r_ptr as "const double*", rq_ptr as "const double*", s_ptr as "const double*", 
            rad_ptr as "const double*", pr_ptr as "const double*",
            as_ptr as "const double*", ae_ptr as "const double*",
            tl_ptr as "const char**", rl_ptr as "const char**", fc_ptr as "const int*", up_ptr as "const int*",
            eh_ptr as "const double*", r2_ptr as "const double*", mr_ptr as "const double*", 
            si_ptr as "const int*", mo_ptr as "const double*", pa_ptr as "const double*",
            tu_ptr as "const char**", pc_ptr as "const int*", di_ptr as "const double*", pax_ptr as "const char**",
            ts_ptr as "const char**", bs_ptr as "const char**", sfm_ptr as "const char**", sroll_ptr as "const double*",
            ap_ptr as "const double*", ptc_ptr as "const int*",
            asegs_ptr as "const double*", segc_ptr as "const int*",
            hashes_ptr as "const uint64_t*", geo_hashes_ptr as "const uint64_t*",
            er_ptr as "const char**",
            f_radius as "double", f_deflection as "double", lineages_ptr_raw as "const char**", n_lineages as "int",
            points_ptr as "void*", counts_ptr as "void*", lineages_out_ptr as "void*",
            rpp as "PushPointFn", rpc as "PushCountFn", rps as "PushStringFn",
            fast_mode as "bool", perf_out_ptr as "double*"
        ] -> bool as "bool" {
            return occ_core::update_geometry(
                stack_ptr,
                n_prims, types_raw, ops_raw, uuids_raw, l_ptr, r_ptr, rq_ptr, s_ptr,
                rad_ptr, pr_ptr, as_ptr, ae_ptr,
                tl_ptr, rl_ptr, fc_ptr, up_ptr,
                eh_ptr, r2_ptr, mr_ptr, si_ptr, mo_ptr, pa_ptr,
                tu_ptr, pc_ptr, di_ptr, pax_ptr,
                ts_ptr, bs_ptr, sfm_ptr, sroll_ptr, ap_ptr, ptc_ptr, asegs_ptr, segc_ptr, hashes_ptr, geo_hashes_ptr,
                er_ptr, f_radius, f_deflection, lineages_ptr_raw, n_lineages,
                points_ptr, counts_ptr, lineages_out_ptr, rpp, rpc, rps, fast_mode, perf_out_ptr
            );
        });

        // ライフサイクル保護ガード！！！ (Rustによるメモリの早期解放(drop)を完全に防止する)
        let _keep_alive = (
            types, ops, uuids, t_ptr_raw, o_ptr_raw, u_ptr_raw,
            t_uuids, p_axes, t_shapes, b_shapes, sweep_frame_modes, sweep_rolls, t_u_ptr_raw, p_a_ptr_raw, ts_ptr_raw, bs_ptr_raw, sfm_ptr_raw,
            locs, rots, sizes, radii, pipe_radii, a_starts, a_ends, e_heights, r2s, m_radii,
            sides_v, modules_v, p_angles, p_counts, distances_v, all_pts, pt_counts, all_segments, segment_counts,
            primitive_full_hashes, primitive_geo_hashes, fill_closed, use_pipe,
            t_lineages_joined, t_lineages_c, t_lineages_r, r_lineages_c, r_lineages_r,
            lineages_c, lineages_ptr,
            edge_radii_joined, edge_radii_c, edge_radii_r
        );

        if !success { return Err("CAD Update Failed".to_string()); }



        let points_ptr = &mut edge_points as *mut Vec<f32> as *mut std::ffi::c_void;
        let counts_ptr = &mut edge_counts as *mut Vec<i32> as *mut std::ffi::c_void;
        let lineages_out_ptr = &mut edge_lineages as *mut Vec<String> as *mut std::ffi::c_void;

        let rpp: extern "C" fn(*mut Vec<f32>, f32, f32, f32) = rust_push_point;
        let rpc: extern "C" fn(*mut Vec<i32>, i32) = rust_push_count;
        let rps: extern "C" fn(*mut Vec<String>, *const std::ffi::c_char) = rust_push_string;

        let perf_bool = t0_bool.elapsed().as_secs_f64() * 1000.0;
        let t0_edge = std::time::Instant::now();
        let edge_deflection = if fast_mode { f_deflection * 14.0 } else { f_deflection };
        let edge_angular_deflection = if fast_mode { f_angular_deflection * 7.0 } else { f_angular_deflection };
        
        cpp!([stack_ptr as "void*", edge_deflection as "double", edge_angular_deflection as "double", fast_mode as "bool", points_ptr as "void*", counts_ptr as "void*", lineages_out_ptr as "void*", rpp as "PushPointFn", rpc as "PushCountFn", rps as "PushStringFn"] {
            occ_core::generate_full_edges(stack_ptr, edge_deflection, edge_angular_deflection, fast_mode, points_ptr, counts_ptr, lineages_out_ptr, rpp, rpc, rps);
        });

        // fast_mode は粗いテッセレーション → すぐ高品質で上書きされるので GPU アップロード不要
        if !fast_mode {
            crate::renderer::update_scene_edges(stack_ptr, &edge_points, &edge_counts);
        }

        let mut mesh_verts = Vec::new();
        let mut mesh_tris = Vec::new();
        let mut mesh_face_ids = Vec::new();
        let mut mesh_tri_counts = Vec::new();

        let v_ptr = &mut mesh_verts as *mut Vec<f32> as *mut std::ffi::c_void;
        let t_ptr = &mut mesh_tris as *mut Vec<i32> as *mut std::ffi::c_void;
        let f_ptr = &mut mesh_face_ids as *mut Vec<String> as *mut std::ffi::c_void;
        let tc_ptr = &mut mesh_tri_counts as *mut Vec<i32> as *mut std::ffi::c_void;

        let perf_edge = t0_edge.elapsed().as_secs_f64() * 1000.0;
        let perf_mesh = if include_mesh {
            let t0_mesh = std::time::Instant::now();

            let mesh_deflection = if fast_mode { f_deflection * 24.0 } else { f_deflection };
            let mesh_angular_deflection = if fast_mode { f_angular_deflection * 10.0 } else { f_angular_deflection };

            cpp!([stack_ptr as "void*", mesh_deflection as "double", mesh_angular_deflection as "double", fast_mode as "bool", v_ptr as "void*", t_ptr as "void*", f_ptr as "void*", tc_ptr as "void*", rpp as "PushPointFn", rpc as "PushCountFn", rps as "PushStringFn"] {
                occ_core::generate_full_mesh(stack_ptr, mesh_deflection, mesh_angular_deflection, fast_mode, v_ptr, t_ptr, f_ptr, tc_ptr, rpp, rpc, rps);
            });

            t0_mesh.elapsed().as_secs_f64() * 1000.0
        } else {
            eprintln!(
                "[CACHE_ANALYSIS][mesh] skipped stack_ptr={} fast_mode={} reason=include_mesh_false",
                stack_ptr,
                fast_mode
            );
            0.0
        };

        if let Ok(mut hashes) = get_stack_total_hashes().lock() {
            hashes.insert(stack_ptr, total_hash);
        }



        Ok(AsyncResult {

            total_hash,

            deflection: f_deflection,

            angular_deflection: f_angular_deflection,

            edge_points,

            edge_counts,

            edge_lineages,

            mesh_verts,

            mesh_tris,

            mesh_face_ids,

            mesh_tri_counts,

            perf_bool,
            perf_edge,
            perf_mesh,
            perf_prim: perf_out[0],
            perf_bool_main: perf_out[1],
            perf_unify: perf_out[2],
            perf_bool_modifier: perf_out[3],
            perf_extrema: perf_out[4],
            perf_resume_restore: perf_out[5],
            perf_modifier_target_assign: perf_out[6],
            perf_modifier_apply: perf_out[7],
            perf_modifier_recluster: perf_out[8],
            perf_fillet_setup: perf_out[9],
            perf_fillet_target_resolve: perf_out[10],
            perf_fillet_add: perf_out[11],
            perf_fillet_build: perf_out[12],
            perf_fillet_history: perf_out[13],
            perf_fillet_added_edges: perf_out[14],
            perf_fillet_contours: perf_out[15],
        })

    }

}

pub fn update_cad_geometry_async(
    stack_ptr: isize,
    binary_payload: Vec<u8>,
    f_lineage_list: Vec<String>,

    f_radius: f64,

    f_deflection: f64,

    f_angular_deflection: f64,

    fast_mode: bool,
    include_mesh: bool

) -> Result<bool, String> {

    if is_computing(stack_ptr) {

        return Ok(false); // Already busy

    }



    set_is_computing(stack_ptr, true);



    std::thread::spawn(move || {

        // Here we perform the heavy computation

        // Note: We need a dedicated helper that wraps the synchronous logic but returns AsyncResult

        match perform_update_internal(stack_ptr, &binary_payload, f_lineage_list, f_radius, f_deflection, f_angular_deflection, fast_mode, include_mesh) {

            Ok(res) => {

                if let Ok(mut res_guard) = ASYNC_RESULT.lock() {

                    *res_guard = Some(res);

                }

            }

            Err(e) => {

                eprintln!("Async Update Error: {:?}", e);

            }

        }

        set_is_computing(stack_ptr, false);

    });



    Ok(true)

}

pub fn poll_update_result() -> Option<(Vec<f32>, Vec<i32>, Vec<String>, Vec<f32>, Vec<i32>, Vec<String>, Vec<i32>)> {

    if let Ok(mut res_guard) = ASYNC_RESULT.lock() {

        if let Some(res) = res_guard.take() {

            return Some((

                res.edge_points, res.edge_counts, res.edge_lineages,

                res.mesh_verts, res.mesh_tris, res.mesh_face_ids, res.mesh_tri_counts

            ));

        }

    }

    None

}
