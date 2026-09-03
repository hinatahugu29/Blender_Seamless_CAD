use cpp::cpp;

/// OCCT のシグナルハンドラを **呼んだスレッドに** 設置する。
///
/// コード中の `OCC_CATCH_SIGNALS` は、これを一度も呼んでいないと**完全な
/// no-op** で、OCCT 内部のアクセス違反やゼロ除算はそのままプロセスを殺す。
/// 8.1.5.8 まで `OSD::SetSignal` はソースのどこにも無く、`apply_face_inset`
/// のような「呼び出し元が try/catch で囲んである」処理でさえ、フォルトが
/// 起きればサーバーごと落ちていた (2026-09-03, Linux での Face Inset)。
///
/// 設置するとフォルトは `Standard_Failure` に化け、既にある catch が拾う。
/// 演算は失敗するが**プロセスは生き残る**。履歴は毎回フル送信で組み直す
/// 設計なので、次のリクエストからは何事も無かったように続けられる。
///
/// **スレッドごとに呼ぶこと。** OCCT のハンドラ状態はスレッドローカルで、
/// main で1回呼んでもワーカースレッドには効かない。実際の計算はすべて
/// `run_stack_worker` の中で走るので、そちらが本命。
///
/// 引数の `Standard_False` は「浮動小数点例外は捕まえない」。OCCT の通常の
/// 幾何計算は inf/NaN を正常な中間値として使うので、有効にすると健全な
/// 演算まで落ちる。
pub fn install_occ_signal_handler() {
    unsafe {
        cpp!([] {
            OSD::SetSignal(Standard_False);
        })
    }
}

pub fn get_version() -> String {

    let res = unsafe { cpp!([] -> *const std::ffi::c_char as "const char*" { static std::string v = occ_core::get_version(); return v.c_str(); }) };

    let c_str = unsafe { std::ffi::CStr::from_ptr(res) };

    c_str.to_string_lossy().into_owned()

}

pub fn is_blender_background() -> bool {

    false

}

pub fn test_ezpz_solver() -> Result<String, String> {

    use ezpz::{solve, Config, Constraint, ConstraintRequest, IdGenerator};

    use ezpz::datatypes::inputs::DatumPoint;



    // 1. IDジェネレータの作成

    let mut ids = IdGenerator::default();



    // 2. 2D上の二つの点 P と Q を定義

    let p = DatumPoint::new(&mut ids);

    let q = DatumPoint::new(&mut ids);



    // 3. 拘束リスト（Request）を組み立てる

    let requests = [

        // 点PのX座標を「0.0」に固定

        ConstraintRequest::highest_priority(Constraint::Fixed(p.id_x(), 0.0)),

        // 点PのY座標を「0.0」に固定（これで点Pは原点 (0, 0) に完全固定）

        ConstraintRequest::highest_priority(Constraint::Fixed(p.id_y(), 0.0)),

        // 点P と 点Q の距離を「50.0」にするという寸法拘束を追加

        ConstraintRequest::highest_priority(Constraint::Distance(p, q, 50.0)),

    ];



    // 4. 初期値の推測値（初期座標）を定義

    // 点Pは(0, 0)、点Qは最初は (10.0, 10.0) に置いておく

    let initial_guesses = vec![

        (p.id_x(), 0.0),

        (p.id_y(), 0.0),

        (q.id_x(), 10.0),

        (q.id_y(), 10.0),

    ];



    // 5. ソルバーを実行！

    match solve(&requests, initial_guesses, Config::default()) {

        Ok(outcome) => {

            // 計算完了後の final_values から点Qの新しい座標を取り出す

            // final_values は initial_guesses と同じ順序で値が入っている

            // 順序：p_x (idx 0), p_y (idx 1), q_x (idx 2), q_y (idx 3)

            let q_x = outcome.final_values()[2];

            let q_y = outcome.final_values()[3];

            Ok(format!(

                "EZPZ計算成功！点Qの新しい座標: ({:.2}, {:.2}) [距離が完全に50.0になりました！]",

                q_x, q_y

            ))

        }

        Err(e) => {

            Err(String::from(format!(

                "EZPZの収束計算に失敗しました。エラー: {:?}",

                e.error

            )))

        }

    }

}

