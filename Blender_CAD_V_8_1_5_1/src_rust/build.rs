extern crate cpp_build;

fn main() {
    // 相対パスによるOpenCASCADEの指定 (USBメモリ等の移動に対応)
    let occt_root = "../../occt-combined-release-no-pch/opencascade-8.0.0-vc14-64-combined/opencascade-8.0.0-vc14-64";
    let occt_inc = format!("{}/inc", occt_root);
    let occt_lib = format!("{}/win64/vc14/lib", occt_root);

    // C++ ブリッジのビルド設定
    let mut config = cpp_build::Config::new();
    config
        .include(&occt_inc)
        .include("src")
        .flag("/std:c++17")
        .flag("/utf-8");
    
    // MSVC 標準ヘッダパスを現在の環境 (Community) に合わせて修正
    let msvc_inc = "C:/Program Files/Microsoft Visual Studio/2022/Community/VC/Tools/MSVC/14.44.35207/include";
    let ucrt_inc = "C:/Program Files (x86)/Windows Kits/10/include/10.0.26100.0/ucrt";
    let um_inc = "C:/Program Files (x86)/Windows Kits/10/include/10.0.26100.0/um";
    let shared_inc = "C:/Program Files (x86)/Windows Kits/10/include/10.0.26100.0/shared";
    config.include(msvc_inc);
    config.include(ucrt_inc);
    config.include(um_inc);
    config.include(shared_inc);
    
    config.build("src/lib.rs");

    // Compile C++ modules
    cc::Build::new()
        .cpp(true)
        .flag("/std:c++17")
        .flag("/utf-8")
        .include(&occt_inc)
        .include(msvc_inc)
        .include(ucrt_inc)
        .include(um_inc)
        .include(shared_inc)
        .file("src/occ_core.cpp")
        .file("src/occ_utils.cpp")
        .file("src/occ_primitives.cpp")
        .file("src/occ_modifiers.cpp")
        .file("src/occ_booleans.cpp")
        .file("src/occ_sketch.cpp")
        .file("src/occ_mesh.cpp")
        .file("src/occ_arrays.cpp")
        .file("src/occ_step.cpp")
        .compile("occ_core");


    // ライブラリのリンクパス
    println!("cargo:rustc-link-search=native={}", occt_lib);

    // 必要な OCCT ライブラリのリンク
    let libs = [
        "TKernel", "TKMath", "TKG2d", "TKG3d", "TKGeomBase", "TKBRep",
        "TKGeomAlgo", "TKTopAlgo", "TKPrim", "TKBO", "TKMesh", 
        "TKShHealing", "TKFillet", "TKOffset", "TKFeat",
        "TKDESTEP", "TKXSBase"
    ];

    for lib in libs {
        println!("cargo:rustc-link-lib=dylib={}", lib);
    }

    println!("cargo:rerun-if-changed=src/lib.rs");
    
    println!("cargo:rerun-if-changed=src/occ_core.cpp");
    println!("cargo:rerun-if-changed=src/occ_core.hpp");
    println!("cargo:rerun-if-changed=src/occ_utils.cpp");
    println!("cargo:rerun-if-changed=src/occ_utils.hpp");
    println!("cargo:rerun-if-changed=src/occ_primitives.cpp");
    println!("cargo:rerun-if-changed=src/occ_primitives.hpp");
    println!("cargo:rerun-if-changed=src/occ_modifiers.cpp");
    println!("cargo:rerun-if-changed=src/occ_modifiers.hpp");
    println!("cargo:rerun-if-changed=src/occ_booleans.cpp");
    println!("cargo:rerun-if-changed=src/occ_booleans.hpp");
    println!("cargo:rerun-if-changed=src/occ_sketch.cpp");
    println!("cargo:rerun-if-changed=src/occ_sketch.hpp");
    println!("cargo:rerun-if-changed=src/occ_mesh.cpp");
    println!("cargo:rerun-if-changed=src/occ_mesh.hpp");
    println!("cargo:rerun-if-changed=src/occ_arrays.cpp");
    println!("cargo:rerun-if-changed=src/occ_arrays.hpp");
    println!("cargo:rerun-if-changed=src/occ_step.cpp");
    println!("cargo:rerun-if-changed=src/occ_step.hpp");
}
