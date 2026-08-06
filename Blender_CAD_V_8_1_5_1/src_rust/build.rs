extern crate cpp_build;

use std::env;
use std::path::PathBuf;

/// OCCT の在り処を決める。
///
/// Windows は公式サイト(dev.opencascade.org)のプリビルド ZIP を展開した
/// ディレクトリを相対パスで指す(USB メモリ等での移動に対応するため)。
///
/// Mac/Linux には公式プリビルドが存在せず、ソースのみが配布されている。
/// そのため conda-forge の occt 8.0.0 を使う前提とし、その prefix を
/// 環境変数 OCCT_ROOT で受け取る。CI ではここを注入する。
/// (Ubuntu の apt が持つ OCCT は 7.5/7.6 と古く、下でリンクしている
///  TKDESTEP が存在しない -- 7.8 で TKSTEP から改名されたため -- ので使えない。)
struct OcctPaths {
    include: String,
    lib: String,
}

fn occt_paths() -> OcctPaths {
    if let Ok(root) = env::var("OCCT_ROOT") {
        // conda-forge / 自前ビルドの標準レイアウト: <prefix>/include/opencascade, <prefix>/lib
        let inc = PathBuf::from(&root).join("include").join("opencascade");
        let include = if inc.exists() {
            inc.to_string_lossy().into_owned()
        } else {
            // 公式 Windows パッケージのレイアウト
            format!("{}/inc", root)
        };
        let lib = if cfg!(target_os = "windows") {
            let vc = PathBuf::from(&root).join("win64/vc14/lib");
            if vc.exists() {
                vc.to_string_lossy().into_owned()
            } else {
                format!("{}/lib", root)
            }
        } else {
            format!("{}/lib", root)
        };
        return OcctPaths { include, lib };
    }

    if cfg!(target_os = "windows") {
        let root = "../../occt-combined-release-no-pch/opencascade-8.0.0-vc14-64-combined/opencascade-8.0.0-vc14-64";
        return OcctPaths {
            include: format!("{}/inc", root),
            lib: format!("{}/win64/vc14/lib", root),
        };
    }

    panic!(
        "OCCT_ROOT is not set. On macOS/Linux there is no official prebuilt OCCT, \
         so point OCCT_ROOT at a conda-forge occt 8.0.0 prefix \
         (e.g. OCCT_ROOT=$CONDA_PREFIX) or at your own build."
    );
}

/// C++ の言語標準フラグ。MSVC だけ書式が違う。
fn cxx_flags() -> Vec<&'static str> {
    if cfg!(target_env = "msvc") {
        // /utf-8: ソースに日本語コメントがあるため、BOM 無し UTF-8 と明示する。
        vec!["/std:c++17", "/utf-8"]
    } else {
        vec!["-std=c++17"]
    }
}

/// MSVC の標準ヘッダは cpp_build が自力で見つけられないことがあるため明示する。
/// Windows 以外では不要(cc クレートが sysroot から解決する)。
fn msvc_system_includes() -> Vec<&'static str> {
    if !cfg!(target_env = "msvc") {
        return Vec::new();
    }
    vec![
        "C:/Program Files/Microsoft Visual Studio/2022/Community/VC/Tools/MSVC/14.44.35207/include",
        "C:/Program Files (x86)/Windows Kits/10/include/10.0.26100.0/ucrt",
        "C:/Program Files (x86)/Windows Kits/10/include/10.0.26100.0/um",
        "C:/Program Files (x86)/Windows Kits/10/include/10.0.26100.0/shared",
    ]
}

const CPP_SOURCES: &[&str] = &[
    "src/occ_core.cpp",
    "src/occ_utils.cpp",
    "src/occ_primitives.cpp",
    "src/occ_modifiers.cpp",
    "src/occ_booleans.cpp",
    "src/occ_sketch.cpp",
    "src/occ_mesh.cpp",
    "src/occ_arrays.cpp",
    "src/occ_step.cpp",
];

const OCCT_LIBS: &[&str] = &[
    "TKernel", "TKMath", "TKG2d", "TKG3d", "TKGeomBase", "TKBRep",
    "TKGeomAlgo", "TKTopAlgo", "TKPrim", "TKBO", "TKMesh",
    "TKShHealing", "TKFillet", "TKOffset", "TKFeat",
    // TKDESTEP / TKXSBase は OCCT 7.8 以降の名前。7.7 以前では TKSTEP。
    "TKDESTEP", "TKXSBase",
];

fn main() {
    let occt = occt_paths();
    let flags = cxx_flags();
    let sys_includes = msvc_system_includes();

    // C++ ブリッジ(cpp! マクロ)のビルド設定
    let mut config = cpp_build::Config::new();
    config.include(&occt.include).include("src");
    for flag in &flags {
        config.flag(flag);
    }
    for inc in &sys_includes {
        config.include(inc);
    }
    config.build("src/lib.rs");

    // C++ モジュール本体
    let mut cc_build = cc::Build::new();
    cc_build.cpp(true).include(&occt.include);
    for flag in &flags {
        cc_build.flag(flag);
    }
    for inc in &sys_includes {
        cc_build.include(inc);
    }
    for src in CPP_SOURCES {
        cc_build.file(src);
    }
    cc_build.compile("occ_core");

    println!("cargo:rustc-link-search=native={}", occt.lib);
    for lib in OCCT_LIBS {
        println!("cargo:rustc-link-lib=dylib={}", lib);
    }

    // 同梱した OCCT を実行ファイルの隣から探させる。
    // 絶対パスが焼き込まれたままだと、ビルドマシン以外では起動しない。
    // Windows は DLL を exe と同じディレクトリに置けば解決されるので不要。
    if cfg!(target_os = "macos") {
        println!("cargo:rustc-link-arg=-Wl,-rpath,@loader_path");
        println!("cargo:rustc-link-arg=-Wl,-rpath,@loader_path/../lib");
    } else if cfg!(target_os = "linux") {
        println!("cargo:rustc-link-arg=-Wl,-rpath,$ORIGIN");
        println!("cargo:rustc-link-arg=-Wl,-rpath,$ORIGIN/../lib");
    }

    println!("cargo:rerun-if-env-changed=OCCT_ROOT");
    println!("cargo:rerun-if-changed=src/lib.rs");
    for src in CPP_SOURCES {
        println!("cargo:rerun-if-changed={}", src);
        println!("cargo:rerun-if-changed={}", src.replace(".cpp", ".hpp"));
    }
}
