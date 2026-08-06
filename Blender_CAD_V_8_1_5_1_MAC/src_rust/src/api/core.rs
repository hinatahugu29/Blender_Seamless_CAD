use cpp::cpp;

pub fn create_cad_stack() -> isize {
    let ptr = unsafe {
        cpp!([] -> *mut std::ffi::c_void as "void*" {
            return occ_core::create_cad_stack();
        }) as isize
    };
    crate::register_stack_ptr(ptr);
    ptr
}

pub fn delete_cad_stack(stack_ptr: isize) {
    // 既に削除済み(未登録)のポインタに対する二重解放を防ぐ。
    if !crate::is_valid_stack_ptr(stack_ptr) {
        return;
    }
    // 先にレジストリから外し、以後のFFI呼び出しが失効ポインタへ触れないようにする。
    crate::unregister_stack_ptr(stack_ptr);
    let ptr = stack_ptr as *mut std::ffi::c_void;
    unsafe {
        cpp!([ptr as "void*"] {
            occ_core::delete_cad_stack(ptr);
        });
    }
}

pub fn set_cad_debug_logging(enabled: bool) {
    unsafe {
        cpp!([enabled as "bool"] {
            occ_core::set_debug_logging(enabled);
        });
    }
}

pub fn import_step(filepath: &str, scale: f64) -> Result<Vec<String>, String> {
    let filepath_c = std::ffi::CString::new(filepath).map_err(|_| "Invalid filepath")?;
    let filepath_ptr = filepath_c.as_ptr();
    
    let mut new_uuids = Vec::new();
    let uuids_ptr = &mut new_uuids as *mut Vec<String> as *mut std::ffi::c_void;
    let rps: extern "C" fn(*mut Vec<String>, *const std::ffi::c_char) = crate::rust_push_string;
    
    unsafe {
        let success = cpp!([filepath_ptr as "const char*", scale as "double", uuids_ptr as "void*", rps as "PushStringFn"] -> bool as "bool" {
            std::vector<std::string> ids = occ::import_step(filepath_ptr, scale);
            if (ids.empty()) return false;
            for (const auto& id : ids) {
                rps(uuids_ptr, id.c_str());
            }
            return true;
        });
        
        if success {
            Ok(new_uuids)
        } else {
            Err("Failed to import STEP file".to_string())
        }
    }
}

pub fn import_svg(filepath: &str, scale: f64, flat_data: Vec<f64>) -> Result<Vec<String>, String> {
    let filepath_c = std::ffi::CString::new(filepath).map_err(|_| "Invalid filepath")?;
    let filepath_ptr = filepath_c.as_ptr();
    
    let mut new_uuids = Vec::new();
    let uuids_ptr = &mut new_uuids as *mut Vec<String> as *mut std::ffi::c_void;
    let rps: extern "C" fn(*mut Vec<String>, *const std::ffi::c_char) = crate::rust_push_string;
    
    let data_ptr = flat_data.as_ptr();
    let data_len = flat_data.len() as i32;

    unsafe {
        let success = cpp!([filepath_ptr as "const char*", scale as "double", data_ptr as "const double*", data_len as "int", uuids_ptr as "void*", rps as "PushStringFn"] -> bool as "bool" {
            std::vector<std::string> ids = occ::import_svg(filepath_ptr, scale, data_ptr, data_len);
            if (ids.empty()) return false;
            for (const auto& id : ids) {
                rps(uuids_ptr, id.c_str());
            }
            return true;
        });
        
        if success {
            Ok(new_uuids)
        } else {
            Err("Failed to import SVG file".to_string())
        }
    }
}

pub fn export_step(uuids: Vec<String>, filepath: &str) -> Result<(), String> {
    let filepath_c = std::ffi::CString::new(filepath).map_err(|_| "Invalid filepath")?;
    let filepath_ptr = filepath_c.as_ptr();
    
    let uuids_c: Vec<std::ffi::CString> = uuids.into_iter().map(|s| std::ffi::CString::new(s).unwrap()).collect();
    let uuids_ptr: Vec<*const i8> = uuids_c.iter().map(|c| c.as_ptr()).collect();
    let u_ptr = uuids_ptr.as_ptr();
    let n_uuids = uuids_ptr.len() as i32;
    
    unsafe {
        let success = cpp!([filepath_ptr as "const char*", u_ptr as "const char**", n_uuids as "int"] -> bool as "bool" {
            std::vector<std::string> ids;
            for (int i = 0; i < n_uuids; ++i) {
                ids.push_back(u_ptr[i]);
            }
            return occ::export_step(ids, filepath_ptr);
        });
        
        if success {
            Ok(())
        } else {
            Err("Failed to export STEP file".to_string())
        }
    }
}

pub fn export_stack_to_step(stack_ptr: isize, filepath: &str) -> Result<(), String> {
    if !crate::is_valid_stack_ptr(stack_ptr) {
        return Err(format!("export_stack_to_step: unknown or already-deleted stack_ptr {}", stack_ptr));
    }
    let filepath_c = std::ffi::CString::new(filepath).map_err(|_| "Invalid filepath")?;
    let filepath_ptr = filepath_c.as_ptr();
    
    unsafe {
        let success = cpp!([stack_ptr as "void*", filepath_ptr as "const char*"] -> bool as "bool" {
            return occ::export_stack_to_step(stack_ptr, filepath_ptr);
        });
        
        if success {
            Ok(())
        } else {
            Err("Failed to export stack to STEP".to_string())
        }
    }
}
