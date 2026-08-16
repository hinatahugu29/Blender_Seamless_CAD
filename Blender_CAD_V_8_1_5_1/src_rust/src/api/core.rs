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

/// スタックの質量特性と外形寸法。
///
/// 返るのは 11 個の f64:
/// `[体積, 表面積, 重心x, 重心y, 重心z, xmin, ymin, zmin, xmax, ymax, zmax]`
///
/// 体積 0 は「測れなかった」ではなく「ソリッドではない(閉じていない)」の意味。
/// 呼び出し側でそう扱うこと。
pub fn measure_stack(stack_ptr: isize) -> Result<Vec<f64>, String> {
    if !crate::is_valid_stack_ptr(stack_ptr) {
        return Err(format!("measure_stack: unknown or already-deleted stack_ptr {}", stack_ptr));
    }

    // 形状の更新中に読むと、作りかけの TopoDS_Shape を触ることになる。
    // ピッキングが同じ理由でスタック単位のロックを取っているのに倣う。
    let lock = crate::get_stack_lock(stack_ptr);
    let _guard = lock.lock().map_err(|_| "measure_stack: stack lock poisoned".to_string())?;

    let mut out = vec![0.0f64; 11];
    let out_ptr = out.as_mut_ptr();
    let ok = unsafe {
        cpp!([stack_ptr as "void*", out_ptr as "double*"] -> bool as "bool" {
            return occ_core::measure_stack(stack_ptr, out_ptr);
        })
    };

    if ok {
        Ok(out)
    } else {
        Err("measure_stack: the stack has no shape to measure".to_string())
    }
}

/// 選択されている辺/面ひとつの寸法。
///
/// 返るのは10個の f64:
/// `[種別, 長さor面積, 半径, 形状コード, 中心xyz, 法線xyz]`
///
/// 中心と法線は**カーネルの厳密な幾何から**取る。面なら面積重心と平面法線で、
/// どちらも倍精度。テセレーション結果(float32)を平均する経路とは精度が3桁違い、
/// スポイトで面を揃えたときに 1e-6 級のずれが残らない。
/// 法線が (0,0,0) のときは「平面ではないので厳密な法線は無い」の意味。
/// 種別 0 は「lineage を解決できなかった」で、エラーではない。トポロジが
/// 変わって照合が外れるのは正常に起こりうるので、UI 側で「取得できません」と
/// 出すこと。**近い別の辺を返して数字を埋めるより、出さないほうがよい。**
pub fn measure_entity(stack_ptr: isize, lineage: &str, is_face: bool) -> Result<Vec<f64>, String> {
    if !crate::is_valid_stack_ptr(stack_ptr) {
        return Err(format!("measure_entity: unknown or already-deleted stack_ptr {}", stack_ptr));
    }
    let lineage_c = std::ffi::CString::new(lineage).map_err(|_| "Invalid lineage")?;
    let lineage_ptr = lineage_c.as_ptr();

    // measure_stack と同じ理由でスタックのロックを取る。更新中の
    // current_shape を読むと作りかけの形状を触ることになる。
    let lock = crate::get_stack_lock(stack_ptr);
    let _guard = lock.lock().map_err(|_| "measure_entity: stack lock poisoned".to_string())?;

    let mut out = vec![0.0f64; 10];
    let out_ptr = out.as_mut_ptr();
    let ok = unsafe {
        cpp!([stack_ptr as "void*", lineage_ptr as "const char*", is_face as "bool", out_ptr as "double*"] -> bool as "bool" {
            return occ_core::measure_entity(stack_ptr, lineage_ptr, is_face, out_ptr);
        })
    };

    if ok { Ok(out) } else { Err("measure_entity: the stack has no shape to measure".to_string()) }
}

/// STEP 書き出し。`scale` は「1 Blender 単位を何 mm として出すか」。
///
/// 既定の 1.0 は従来どおり 1 単位 = 1 mm。メートルで作っているモデルなら
/// 1000.0 を渡す。インポート側の scale と同じ意味・同じ扱いにしてある。
pub fn export_stack_to_step(stack_ptr: isize, filepath: &str, scale: f64) -> Result<(), String> {
    if !crate::is_valid_stack_ptr(stack_ptr) {
        return Err(format!("export_stack_to_step: unknown or already-deleted stack_ptr {}", stack_ptr));
    }
    let filepath_c = std::ffi::CString::new(filepath).map_err(|_| "Invalid filepath")?;
    let filepath_ptr = filepath_c.as_ptr();
    
    unsafe {
        let success = cpp!([stack_ptr as "void*", filepath_ptr as "const char*", scale as "double"] -> bool as "bool" {
            return occ::export_stack_to_step(stack_ptr, filepath_ptr, scale);
        });

        if success {
            Ok(())
        } else {
            Err("Failed to export stack to STEP".to_string())
        }
    }
}

/// 名前付き STEP 書き出し。複数 Part を渡すとアセンブリ構造になる。
///
/// `export_stack_to_step` との違いは **XCAF を通すこと** だけ。あちらは
/// `STEPControl_Writer` に直接渡すので、形状しか出ない (名前も構造も無い)。
/// 旧関数は互換のために残してあり、回帰テストも両方を見ている。
///
/// `parts` は (stack_ptr, 名前) の並び。`assembly_name` は 2つ以上のときだけ
/// 使われる。`scale` の意味は `export_stack_to_step` と同じ。
pub fn export_parts_to_step(parts: Vec<(isize, String)>, filepath: &str, scale: f64,
                            assembly_name: &str) -> Result<(), String> {
    if parts.is_empty() {
        return Err("export_parts_to_step: no parts were given".to_string());
    }
    for (ptr, name) in &parts {
        if !crate::is_valid_stack_ptr(*ptr) {
            return Err(format!("export_parts_to_step: unknown or already-deleted stack_ptr {} (part {:?})",
                               ptr, name));
        }
    }

    // **ポインタの昇順でロックを取る。** 複数スタックを同時に押さえるので、
    // 呼ぶ側の並び順のまま取ると、別スレッドが逆順で取ったときに刺さる。
    // 順序を1つに決めておけば、その組み合わせは起こらない。
    let mut ordered: Vec<isize> = parts.iter().map(|(p, _)| *p).collect();
    ordered.sort_unstable();
    ordered.dedup();
    let locks: Vec<_> = ordered.iter().map(|p| crate::get_stack_lock(*p)).collect();
    let mut _guards = Vec::with_capacity(locks.len());
    for lock in &locks {
        _guards.push(lock.lock().map_err(|_| "export_parts_to_step: stack lock poisoned".to_string())?);
    }

    let filepath_c = std::ffi::CString::new(filepath).map_err(|_| "Invalid filepath")?;
    let filepath_ptr = filepath_c.as_ptr();
    let asm_c = std::ffi::CString::new(assembly_name).map_err(|_| "Invalid assembly name")?;
    let asm_ptr = asm_c.as_ptr();

    let ptrs: Vec<isize> = parts.iter().map(|(p, _)| *p).collect();
    let names_c: Vec<std::ffi::CString> = parts.iter()
        .map(|(_, n)| std::ffi::CString::new(n.as_str()).unwrap_or_default())
        .collect();
    let names_ptr: Vec<*const i8> = names_c.iter().map(|c| c.as_ptr()).collect();

    let p_ptr = ptrs.as_ptr();
    let n_ptr = names_ptr.as_ptr();
    let n_parts = ptrs.len() as i32;

    unsafe {
        let success = cpp!([p_ptr as "const intptr_t*", n_ptr as "const char**", n_parts as "int",
                            filepath_ptr as "const char*", scale as "double",
                            asm_ptr as "const char*"] -> bool as "bool" {
            std::vector<void*> stacks;
            std::vector<std::string> names;
            for (int i = 0; i < n_parts; ++i) {
                stacks.push_back(reinterpret_cast<void*>(p_ptr[i]));
                names.push_back(n_ptr[i] ? n_ptr[i] : "");
            }
            return occ::export_parts_to_step(stacks, names, filepath_ptr, scale, asm_ptr);
        });

        if success {
            Ok(())
        } else {
            Err("export_parts_to_step: nothing was written (every part may be empty)".to_string())
        }
    }
}

/// IGES 書き出し。`scale` の意味は `export_stack_to_step` と同じ。
///
/// **幾何のみ。** 名前もアセンブリ構造も入らない (IGES 側の事情。詳細は
/// `occ_step.hpp` の宣言に書いてある)。名前が要るなら STEP を使うこと。
///
/// `brep_mode` は true でソリッドとして、false で面の集まりとして書く。
pub fn export_stack_to_iges(stack_ptr: isize, filepath: &str, scale: f64,
                            brep_mode: bool) -> Result<(), String> {
    if !crate::is_valid_stack_ptr(stack_ptr) {
        return Err(format!("export_stack_to_iges: unknown or already-deleted stack_ptr {}", stack_ptr));
    }
    let filepath_c = std::ffi::CString::new(filepath).map_err(|_| "Invalid filepath")?;
    let filepath_ptr = filepath_c.as_ptr();

    let lock = crate::get_stack_lock(stack_ptr);
    let _guard = lock.lock().map_err(|_| "export_stack_to_iges: stack lock poisoned".to_string())?;

    unsafe {
        let success = cpp!([stack_ptr as "void*", filepath_ptr as "const char*",
                            scale as "double", brep_mode as "bool"] -> bool as "bool" {
            return occ::export_stack_to_iges(stack_ptr, filepath_ptr, scale, brep_mode);
        });

        if success {
            Ok(())
        } else {
            Err("export_stack_to_iges: nothing was written (no shape, or the writer rejected it)".to_string())
        }
    }
}

/// STL 書き出し。`scale` の意味は `export_stack_to_step` と同じ。
///
/// `angular_deflection` は**ラジアン**で渡すこと。アドオン側のプロパティは
/// 度で持っているので、変換は呼び出し側の責任 (`operators/bake.py` と同じ約束)。
///
/// Bake してから Blender の STL エクスポータを通す経路と違い、テセレーションを
/// ベイク品質の設定で直接指定できる。`ascii_mode` の既定はバイナリ。
///
/// 三角形が1枚も出なかった場合は**書かずに** Err を返す。「開けるが空」の
/// STL が一番たちの悪い失敗方なので、成功として返さない。
pub fn export_stack_to_stl(stack_ptr: isize, filepath: &str, scale: f64,
                           linear_deflection: f64, angular_deflection: f64,
                           ascii_mode: bool) -> Result<(), String> {
    if !crate::is_valid_stack_ptr(stack_ptr) {
        return Err(format!("export_stack_to_stl: unknown or already-deleted stack_ptr {}", stack_ptr));
    }
    let filepath_c = std::ffi::CString::new(filepath).map_err(|_| "Invalid filepath")?;
    let filepath_ptr = filepath_c.as_ptr();

    // measure_stack と同じ理由でスタックのロックを取る。書き出しは
    // current_shape を読むだけだが、更新中に読むと作りかけの形状を
    // メッシュに落とすことになる。
    let lock = crate::get_stack_lock(stack_ptr);
    let _guard = lock.lock().map_err(|_| "export_stack_to_stl: stack lock poisoned".to_string())?;

    unsafe {
        let success = cpp!([stack_ptr as "void*", filepath_ptr as "const char*", scale as "double",
                            linear_deflection as "double", angular_deflection as "double",
                            ascii_mode as "bool"] -> bool as "bool" {
            return occ::export_stack_to_stl(stack_ptr, filepath_ptr, scale,
                                            linear_deflection, angular_deflection, ascii_mode);
        });

        if success {
            Ok(())
        } else {
            Err("export_stack_to_stl: nothing was written (no shape, meshing failed, or no triangles)".to_string())
        }
    }
}
