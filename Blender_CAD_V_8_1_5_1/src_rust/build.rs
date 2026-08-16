extern crate cpp_build;

// C++ ソースはプラットフォーム非依存 (occ_*.cpp に #ifdef _WIN32 は1つも無い)。
// 分岐するのは「OCCT がどこにあるか」と「コンパイラのフラグ方言」だけ。
const CPP_SOURCES: [&str; 9] = [
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

/// OCCT の展開先。CI では OS ごとに置き場所が違うので環境変数を最優先する。
/// 未設定なら、従来どおりリポジトリ同梱の Windows 版を相対パスで見る
/// (USB メモリ等に載せて移動しても動くように、絶対パスにはしない)。
///
/// 8.0.0 のドロップ (`occt-combined-release-no-pch/`) はディスク上に残してある。
/// 8.0.1 で回帰が出たときに、このパスを戻すだけで前の版に戻れるようにするため。
fn occt_root() -> String {
    if let Ok(root) = std::env::var("OCCT_ROOT") {
        println!("cargo:rerun-if-env-changed=OCCT_ROOT");
        return root.trim_end_matches(['/', '\\']).to_string();
    }
    "../../occt-combined-release-no-pch_801/opencascade-8.0.1-vc14-64-combined/opencascade-8.0.1-vc14-64"
        .to_string()
}

/// OCCT のインストール階層は配布形態でまちまち。Windows 向けドロップは
/// `inc` / `win64/vc14/lib`、cmake の Unix レイアウトは
/// `include/opencascade` / `lib`、Homebrew はまた別。決め打ちすると
/// 「ヘッダが無い」という遠い場所のコンパイルエラーになるので、ここで探す。
fn find_subdir(root: &str, candidates: &[&str], what: &str) -> String {
    for rel in candidates {
        let path = format!("{}/{}", root, rel);
        if std::path::Path::new(&path).is_dir() {
            return path;
        }
    }
    panic!(
        "OCCT {} not found under {:?}. Tried: {:?}. \
         Set OCCT_ROOT to the OpenCASCADE install prefix.",
        what, root, candidates
    );
}

fn main() {
    println!("cargo:rerun-if-env-changed=OCCT_ROOT");

    let target_os = std::env::var("CARGO_CFG_TARGET_OS").unwrap_or_default();
    let is_windows = target_os == "windows";

    let occt_root = occt_root();
    let occt_inc = find_subdir(&occt_root, &["inc", "include/opencascade", "include"], "headers");
    // Windows 同梱ドロップだけが win64/vc14 という階層を持つ。
    let occt_lib = find_subdir(&occt_root, &["win64/vc14/lib", "lib", "lib64"], "libraries");

    // MSVC 標準ヘッダパス。cl.exe を素の環境から呼ぶ都合で明示している。
    // Unix では clang/gcc が自前で標準ヘッダを見つけるので、渡すものは無い。
    let system_includes: Vec<&str> = if is_windows {
        vec![
            "C:/Program Files/Microsoft Visual Studio/2022/Community/VC/Tools/MSVC/14.44.35207/include",
            "C:/Program Files (x86)/Windows Kits/10/include/10.0.26100.0/ucrt",
            "C:/Program Files (x86)/Windows Kits/10/include/10.0.26100.0/um",
            "C:/Program Files (x86)/Windows Kits/10/include/10.0.26100.0/shared",
        ]
    } else {
        vec![]
    };

    // MSVC と GCC/Clang でフラグの綴りが違う。/utf-8 に相当するものは
    // Unix 側では不要 (ソースも実行環境も UTF-8 が前提)。
    let cpp_flags: Vec<&str> = if is_windows {
        vec!["/std:c++17", "/utf-8"]
    } else {
        vec!["-std=c++17"]
    };

    // C++ ブリッジのビルド設定
    let mut config = cpp_build::Config::new();
    config.include(&occt_inc).include("src");
    for flag in &cpp_flags {
        config.flag(flag);
    }
    for inc in &system_includes {
        config.include(inc);
    }
    config.build("src/lib.rs");

    // Compile C++ modules
    let mut cc_build = cc::Build::new();
    cc_build.cpp(true).include(&occt_inc);
    for flag in &cpp_flags {
        cc_build.flag(flag);
    }
    for inc in &system_includes {
        cc_build.include(inc);
    }
    for src in CPP_SOURCES {
        cc_build.file(src);
    }
    cc_build.compile("occ_core");


    // ライブラリのリンクパス
    println!("cargo:rustc-link-search=native={}", occt_lib);

    // 同梱した OCCT の .so/.dylib を実行時に見つけられるようにする。Windows は
    // exe と同じフォルダの DLL を自動で拾うので何も要らないが、Unix は
    // RPATH を自分で埋めないと、配布先で「起動した瞬間に何も応答しない」形で
    // 失敗する (Windows で av*.dll を外したときと同じ症状)。
    if !is_windows {
        let origin = if target_os == "macos" { "@loader_path" } else { "$ORIGIN" };
        println!("cargo:rustc-link-arg=-Wl,-rpath,{}", origin);
        println!("cargo:rustc-link-arg=-Wl,-rpath,{}/lib", origin);
    }

    // 必要な OCCT ライブラリのリンク
    let libs = [
        "TKernel", "TKMath", "TKG2d", "TKG3d", "TKGeomBase", "TKBRep",
        "TKGeomAlgo", "TKTopAlgo", "TKPrim", "TKBO", "TKMesh", 
        "TKShHealing", "TKFillet", "TKOffset", "TKFeat",
        // TKDESTL は StlAPI_Writer (occ_step.cpp の export_stack_to_stl) 用。
        // TKXCAF / TKLCAF は XCAF 文書 (名前付き STEP = export_parts_to_step) 用。
        // **いずれも DLL は以前から配布物に同梱されていたが、リンクはしていなかった。**
        // 未配線の OCCT 機能を足すときは、ここに追記しないと未解決シンボルで落ちる。
        "TKDESTEP", "TKDESTL", "TKDEIGES", "TKXCAF", "TKLCAF", "TKXSBase"
    ];

    for lib in libs {
        println!("cargo:rustc-link-lib=dylib={}", lib);
    }

    println!("cargo:rerun-if-changed=src/lib.rs");

    // cpp! マクロを含む Rust ソースは**全部**監視する。
    //
    // ここに載っていないファイルの cpp! を書き足すと、build.rs が再実行されず
    // rust-cpp のメタデータが古いまま残り、
    //   error: This cpp! macro is not found in the library's rust-cpp metadata
    // という、書いたコードとは何の関係も無いエラーになる。原因が
    // 「監視対象の漏れ」だと気付くまで時間を溶かす類の失敗。
    for entry in std::fs::read_dir("src/api").into_iter().flatten().flatten() {
        if entry.path().extension().and_then(|e| e.to_str()) == Some("rs") {
            println!("cargo:rerun-if-changed={}", entry.path().display());
        }
    }
    
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
