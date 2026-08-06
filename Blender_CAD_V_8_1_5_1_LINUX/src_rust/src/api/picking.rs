use cpp::cpp;
use crate::*;

// main.rs の JSON経路(action: "pick_edge"等)は origin/direction の配列長を
// 検証しないため、要素数が3未満のペイロードが来ると添字アクセスでパニックしうる。
// (バイナリ高速ピッキングプロトコルは固定長3要素を組み立てるため影響を受けない)
fn validate_ray(origin: &[f32], direction: &[f32]) -> Result<(), String> {
    if origin.len() < 3 || direction.len() < 3 {
        return Err(format!(
            "pick: origin/direction must have 3 elements each (got origin={}, direction={})",
            origin.len(), direction.len()
        ));
    }
    Ok(())
}

pub fn pick_edge(stack_ptr: isize, origin: Vec<f32>, direction: Vec<f32>, tolerance: f32) -> Result<Option<(String, f32, f32, f32)>, String> {

    if !crate::is_valid_stack_ptr(stack_ptr) {
        return Err(format!("pick: unknown or already-deleted stack_ptr {}", stack_ptr));
    }
    validate_ray(&origin, &direction)?;

    let o = [origin[0] as f64, origin[1] as f64, origin[2] as f64];

    let d = [direction[0] as f64, direction[1] as f64, direction[2] as f64];

    let mut lid_buf = vec![0u8; 256]; let mut p_buf = [0f64; 3];

    let lid_ptr = lid_buf.as_mut_ptr() as *mut std::ffi::c_char;

    let p_ptr = p_buf.as_mut_ptr(); let o_ptr = o.as_ptr(); let d_ptr = d.as_ptr();

    let occ_mutex = get_stack_lock(stack_ptr);

    let _occ_lock = occ_mutex.lock().unwrap();

    let found = unsafe { cpp!([stack_ptr as "void*", o_ptr as "const double*", d_ptr as "const double*", tolerance as "float", lid_ptr as "char*", p_ptr as "double*"] -> bool as "bool" {

        return occ_core::pick_edge(stack_ptr, o_ptr, d_ptr, (double)tolerance, lid_ptr, p_ptr);

    }) };

    if found {

        let c_str = unsafe { std::ffi::CStr::from_ptr(lid_ptr) };

        let lid = c_str.to_string_lossy().into_owned();

        Ok(Some((lid, p_buf[0] as f32, p_buf[1] as f32, p_buf[2] as f32)))

    } else { Ok(None) }

}

pub fn pick_face(stack_ptr: isize, origin: Vec<f32>, direction: Vec<f32>, tolerance: f32) -> Result<Option<(String, f32, f32, f32, f32, f32, f32)>, String> {

    if !crate::is_valid_stack_ptr(stack_ptr) {
        return Err(format!("pick: unknown or already-deleted stack_ptr {}", stack_ptr));
    }
    validate_ray(&origin, &direction)?;

    let o = [origin[0] as f64, origin[1] as f64, origin[2] as f64];

    let d = [direction[0] as f64, direction[1] as f64, direction[2] as f64];

    let mut lid_buf = vec![0u8; 256]; let mut p_buf = [0f64; 6]; // 3(pos) + 3(norm)

    let lid_ptr = lid_buf.as_mut_ptr() as *mut std::ffi::c_char;

    let p_ptr = p_buf.as_mut_ptr(); let o_ptr = o.as_ptr(); let d_ptr = d.as_ptr();

    let occ_mutex = get_stack_lock(stack_ptr);

    let _occ_lock = occ_mutex.lock().unwrap();

    let found = unsafe { cpp!([stack_ptr as "void*", o_ptr as "const double*", d_ptr as "const double*", tolerance as "float", lid_ptr as "char*", p_ptr as "double*"] -> bool as "bool" {

        return occ_core::pick_face(stack_ptr, o_ptr, d_ptr, (double)tolerance, lid_ptr, p_ptr);

    }) };

    if found {

        let c_str = unsafe { std::ffi::CStr::from_ptr(lid_ptr) };

        let lid = c_str.to_string_lossy().into_owned();

        Ok(Some((

            lid, 

            p_buf[0] as f32, p_buf[1] as f32, p_buf[2] as f32, // Position

            p_buf[3] as f32, p_buf[4] as f32, p_buf[5] as f32  // Normal

        )))

    } else { Ok(None) }

}

pub fn pick_edge_from_stack(stack_ptr: isize, stack_idx: i32, origin: Vec<f32>, direction: Vec<f32>, tolerance: f32) -> Result<Option<(String, f32, f32, f32)>, String> {

    if !crate::is_valid_stack_ptr(stack_ptr) {
        return Err(format!("pick: unknown or already-deleted stack_ptr {}", stack_ptr));
    }
    validate_ray(&origin, &direction)?;

    let o = [origin[0] as f64, origin[1] as f64, origin[2] as f64];

    let d = [direction[0] as f64, direction[1] as f64, direction[2] as f64];

    let mut lid_buf = vec![0u8; 256]; let mut p_buf = [0f64; 3];

    let lid_ptr = lid_buf.as_mut_ptr() as *mut std::ffi::c_char;

    let p_ptr = p_buf.as_mut_ptr(); let o_ptr = o.as_ptr(); let d_ptr = d.as_ptr();

    let occ_mutex = get_stack_lock(stack_ptr);

    let _occ_lock = occ_mutex.lock().unwrap();

    let found = unsafe { cpp!([stack_ptr as "void*", stack_idx as "int", o_ptr as "const double*", d_ptr as "const double*", tolerance as "float", lid_ptr as "char*", p_ptr as "double*"] -> bool as "bool" {

        return occ_core::pick_edge_from_stack(stack_ptr, stack_idx, o_ptr, d_ptr, (double)tolerance, lid_ptr, p_ptr);

    }) };

    if found {

        let c_str = unsafe { std::ffi::CStr::from_ptr(lid_ptr) };

        let lid = c_str.to_string_lossy().into_owned();

        Ok(Some((lid, p_buf[0] as f32, p_buf[1] as f32, p_buf[2] as f32)))

    } else { Ok(None) }

}

pub fn pick_face_from_stack(stack_ptr: isize, stack_idx: i32, origin: Vec<f32>, direction: Vec<f32>, tolerance: f32) -> Result<Option<(String, f32, f32, f32, f32, f32, f32)>, String> {

    if !crate::is_valid_stack_ptr(stack_ptr) {
        return Err(format!("pick: unknown or already-deleted stack_ptr {}", stack_ptr));
    }
    validate_ray(&origin, &direction)?;

    let o = [origin[0] as f64, origin[1] as f64, origin[2] as f64];

    let d = [direction[0] as f64, direction[1] as f64, direction[2] as f64];

    let mut lid_buf = vec![0u8; 256]; let mut p_buf = [0f64; 6];

    let lid_ptr = lid_buf.as_mut_ptr() as *mut std::ffi::c_char;

    let p_ptr = p_buf.as_mut_ptr(); let o_ptr = o.as_ptr(); let d_ptr = d.as_ptr();

    let occ_mutex = get_stack_lock(stack_ptr);

    let _occ_lock = occ_mutex.lock().unwrap();

    let found = unsafe { cpp!([stack_ptr as "void*", stack_idx as "int", o_ptr as "const double*", d_ptr as "const double*", tolerance as "float", lid_ptr as "char*", p_ptr as "double*"] -> bool as "bool" {

        return occ_core::pick_face_from_stack(stack_ptr, stack_idx, o_ptr, d_ptr, (double)tolerance, lid_ptr, p_ptr);

    }) };

    if found {

        let c_str = unsafe { std::ffi::CStr::from_ptr(lid_ptr) };

        let lid = c_str.to_string_lossy().into_owned();

        Ok(Some((lid, p_buf[0] as f32, p_buf[1] as f32, p_buf[2] as f32, p_buf[3] as f32, p_buf[4] as f32, p_buf[5] as f32)))

    } else { Ok(None) }

}

pub fn pick_vertex_from_stack(stack_ptr: isize, stack_idx: i32, origin: Vec<f32>, direction: Vec<f32>, tolerance: f32) -> Result<Option<(String, f32, f32, f32, f32, f32, f32)>, String> {

    if !crate::is_valid_stack_ptr(stack_ptr) {
        return Err(format!("pick: unknown or already-deleted stack_ptr {}", stack_ptr));
    }
    validate_ray(&origin, &direction)?;

    let o = [origin[0] as f64, origin[1] as f64, origin[2] as f64];

    let d = [direction[0] as f64, direction[1] as f64, direction[2] as f64];

    let mut lid_buf = vec![0u8; 256]; let mut p_buf = [0f64; 6];

    let lid_ptr = lid_buf.as_mut_ptr() as *mut std::ffi::c_char;

    let p_ptr = p_buf.as_mut_ptr(); let o_ptr = o.as_ptr(); let d_ptr = d.as_ptr();

    let occ_mutex = get_stack_lock(stack_ptr);

    let _occ_lock = occ_mutex.lock().unwrap();

    let found = unsafe { cpp!([stack_ptr as "void*", stack_idx as "int", o_ptr as "const double*", d_ptr as "const double*", tolerance as "float", lid_ptr as "char*", p_ptr as "double*"] -> bool as "bool" {

        return occ_core::pick_vertex_from_stack(stack_ptr, stack_idx, o_ptr, d_ptr, (double)tolerance, lid_ptr, p_ptr);

    }) };

    if found {

        let c_str = unsafe { std::ffi::CStr::from_ptr(lid_ptr) };

        let lid = c_str.to_string_lossy().into_owned();

        Ok(Some((lid, p_buf[0] as f32, p_buf[1] as f32, p_buf[2] as f32, p_buf[3] as f32, p_buf[4] as f32, p_buf[5] as f32)))

    } else { Ok(None) }

}

pub fn pick_midpoint_from_stack(stack_ptr: isize, stack_idx: i32, origin: Vec<f32>, direction: Vec<f32>, tolerance: f32) -> Result<Option<(String, f32, f32, f32, f32, f32, f32)>, String> {

    if !crate::is_valid_stack_ptr(stack_ptr) {
        return Err(format!("pick: unknown or already-deleted stack_ptr {}", stack_ptr));
    }
    validate_ray(&origin, &direction)?;

    let o = [origin[0] as f64, origin[1] as f64, origin[2] as f64];

    let d = [direction[0] as f64, direction[1] as f64, direction[2] as f64];

    let mut lid_buf = vec![0u8; 256]; let mut p_buf = [0f64; 6];

    let lid_ptr = lid_buf.as_mut_ptr() as *mut std::ffi::c_char;

    let p_ptr = p_buf.as_mut_ptr(); let o_ptr = o.as_ptr(); let d_ptr = d.as_ptr();

    let occ_mutex = get_stack_lock(stack_ptr);

    let _occ_lock = occ_mutex.lock().unwrap();

    let found = unsafe { cpp!([stack_ptr as "void*", stack_idx as "int", o_ptr as "const double*", d_ptr as "const double*", tolerance as "float", lid_ptr as "char*", p_ptr as "double*"] -> bool as "bool" {

        return occ_core::pick_midpoint_from_stack(stack_ptr, stack_idx, o_ptr, d_ptr, (double)tolerance, lid_ptr, p_ptr);

    }) };

    if found {

        let c_str = unsafe { std::ffi::CStr::from_ptr(lid_ptr) };

        let lid = c_str.to_string_lossy().into_owned();

        Ok(Some((lid, p_buf[0] as f32, p_buf[1] as f32, p_buf[2] as f32, p_buf[3] as f32, p_buf[4] as f32, p_buf[5] as f32)))

    } else { Ok(None) }

}

