# Seamless CAD — 作業前に読むこと

Blender の中でノンデストラクティブな CAD モデリングを行うアドオン。
形状計算は Blender のメッシュではなく **OpenCASCADE (OCCT)** が別プロセスで行う。

このファイルは**セッション開始時に自動で読み込まれる**。
人間向けの説明は [`README.md`](README.md)、使い方は
[ユーザーマニュアル](https://hinatahugu29.github.io/Blender_Seamless_CAD/)。

---

## 1. 編集して良い場所は1つだけ

```
Blender_CAD_V_8_1_5_1/          ← 正本。ここだけを編集する
  CAD_8_1_5_1/                  アドオン本体（これが ZIP になる）
  src_rust/                     幾何カーネル（Rust + C++/OCCT）
  package_addon.py              配布 ZIP のビルド（PREFLIGHT 付き）
  deploy.py                     ビルドしたバイナリをアドオンへコピー
  regression_test.py            ヘッドレス回帰テスト
```

> **紛らわしい点**：ディレクトリ名は `_8_1_5_1` だが、中身の `bl_info` は
> **8.1.5.8**。ディレクトリ名は版が上がっても変えていない。

リポジトリ直下には `Blender_CAD_V_8_1_0` 〜 `V_8_1_5` など**過去版が20以上**
残っている。`PAST_20260609/` `temp_extract/` `_removed_from_addon/` も同様。
**これらは読むだけ。編集しない。**

`MAC_LINUX/` だけは別で、**macOS / Linux 版 ZIP の保管庫として現役**。
CI（`build-kernel.yml`）の成果物をここへ置く。命名規則と現在の中身は
`MAC_LINUX/README.md`。`.gitignore` 対象なので clone しても入っていない。

grep を仕掛けるときはリポジトリ全体ではなく `Blender_CAD_V_8_1_5_1/` を
対象にすること。全体だと過去版の同名ファイルが大量にヒットして、
どれが現行か分からなくなる（実際に起きた）。

---

## 2. ビルドと配布の鉄則

| | |
|---|---|
| Python の起動 | **`py`**。`python` ではない |
| 配布 ZIP | **必ず `package_addon.py`** で作る。手作業のコピー禁止 |
| バイナリの配置 | `cargo build --release` の後に **`py deploy.py`** |
| インストール | ユーザーが Blender の `Install...` で行う |
| **やってはいけないこと** | **Roaming の addons ディレクトリへ直接コピーしない** |

```bash
cd Blender_CAD_V_8_1_5_1/src_rust && cargo build --release && cd .. && py deploy.py
```

**`cargo build` だけでは回帰テストが読むバイナリは変わらない。**
`deploy.py` を通していないと、直したはずの失敗が残り、別のバグを疑うことになる。

手作業コピー禁止の理由：過去に `libs/svgpathtools` と `libs/svgwrite` が
ディレクトリコピーで脱落し、**SVG インポートが10バージョン以上にわたり
無言で壊れていた**。PREFLIGHT はその事故への対策。

---

## 3. 検証

```bash
"C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe" --background --factory-startup --python Blender_CAD_V_8_1_5_1/regression_test.py
```

**Blender は Steam 版**（5.1.2）。`C:\Program Files\Blender Foundation\` の下には
`Blender 4.2` 〜 `4.4` のデータフォルダだけが残っていて **実行ファイルは無い**。
`.blend` の関連付けも消えた 3.6 を指したまま。ここを探して「Blender が入っていない」と
判断しかけたことがある（2026-08-18）。

終了コード 0 = 全パス。**ただしこれで確認できないものがある**：
ドラッグ追従・確定後の描画・WGPU Overlay OFF 時の挙動。
ネイティブの変形モーダルと GPU 描画が要るため原理的に自動化できない。
これらを触ったら `Blender_CAD_V_8_1_5_1/DEPSGRAPH_STATE_MACHINE.md` §5 の
**手動チェックリスト C・D・H** を実機で通すこと。

---

## 4. 既知の罠

**過去に実際に踏んだもの。** 症状が「原因不明」に見えるので先に書いておく。

| 罠 | 症状 | 対処 |
|---|---|---|
| **古い `cad_server` が残る** | 新しいアクションが `None` を返す。エラーはどこにも出ない | ポート 8080 のプロセスを落としてから起動し直す |
| **プレビュー読み戻しの非同期差** | ヘッドレスでは通るのに実機で失敗する | `update_cad_preview_forced` は **GUI では非同期・バックグラウンドでは同期**。直後に形状を読み戻すテストは嘘をつく |
| **`deploy.py` 忘れ** | 直したはずの失敗が残る | §2 参照 |
| **対称な値だけのテスト** | 符号・向きの誤りが素通りする | 90度・正方形・原点対称だけで確かめない。非対称な値を必ず1つ混ぜる |
| **CLEANUP (UnifySameDomain)** | フィレット等の参照先が消える | 面の同一性を破壊する。**opt-in のまま**にすること。自動で有効化しない |

---

## 5. アーキテクチャの要点

```
Blender (Python アドオン)  ──TCP──>  cad_server.exe  ──Rust──>  OpenCASCADE (C++)
```

- プロキシを動かすたびに**履歴全体**を送り、サーバ側が形状を組み直す。
  この「毎回フル送信」のおかげで `.blend` を開き直しても Feature Tree から復元できる
- ドラッグ中は重い OCC ブーリアンを避け、**純 Rust の BSP CSG** に切り替わる
- Python 側はネイティブコードを **import しない**（V7.0.0 でアウトプロセス化済み）

### カーネル機能を1つ足すときに通る6箇所

```
occ_*.cpp  →  occ_*.hpp  →  api/*.rs（ロックはここ）  →  main.rs（アクション分岐）
           →  core_bridge.py  →  operators/ + ui/
```

応答形式は **成功 = `1u8` + ペイロード / 失敗 = `0u8` + 長さ + エラー文字列**。
`measure_stack` と `export_stack_to_step` が確立した形に揃える。新しい形を作らない。

---

## 6. ドキュメントの権威

**root に .md が25本ある。半分以上は歴史的資料。**
下の分類を見ずに読み始めると、完成済みの機能を「未実装」と判断する。

### 現行（信用してよい）

| ファイル | 内容 |
|---|---|
| `README.md` | リポジトリの入口。ビルド手順・構成・ライセンス |
| `INVENTORY_V8_1_5_1.md` | **今何があるか**の実測棚卸し |
| `FEATURE_GAPS.md` | 自分のコードを読んで見つけた穴 |
| `COMPETITIVE_GAP_ANALYSIS.md` | 他社CAD（Fusion / Plasticity）との比較と到達可能性 |
| `IMPLEMENTATION_ROADMAP.md` | **着手順。実装するならここから読む** |
| `CROSS_PLATFORM_BUILD.md` | macOS / Linux 対応の実測結果 |
| `Blender_CAD_V_8_1_5_1/DEPSGRAPH_STATE_MACHINE.md` | ドラッグ〜確定の状態機械。手動チェックリスト |
| `docs/` | ユーザー向けマニュアルの原稿（英語が正本） |

### 参考（現行だが用途が限定的）

`EZPZ_CAPABILITIES.md`（拘束ソルバの仕様）／`LOC_STATS_V8_1_5.md`（行数統計）／
`PROJECT_COMPLEXITY_GUIDE.md`（対外説明資料）

出品ページの現物は root の `SUPERHIVE_PRODUCT_DESCRIPTION_20260811.html`（商品説明）／
`SUPERHIVE_FAQ.html`／`SUPERHIVE_CUSTOMER_NOTE.html`（購入後の案内）。手で Superhive へ貼る。

### 歴史的資料（**計画の根拠に使わない**）

`PROJECT_STATUS.md`（2026-06-04 で更新停止）／`PERFORMANCE_ROADMAP.md`／
`ROADMAP_V1_4_0.md`／`2D_CAD_ROADMAP.md`／`INVENTORY_V8_1_4.md`／
`V_1_2_0_PLAN.md`／`V_1_2_1_PLAN.md`／`V_1_3_0_PLAN.md`／`V_1_3_2_PLAN.md`／
`roadmap_v_2_0_4.md`／`bottleneck_analysis_report.md`／
`implementation_plan_sweep_loft.md`／`implementation_plan_v7_0_6_refactor.md`／
`LISTING_PREP.md`（8.1.0 期の出品準備メモ。出品は済んでいる。
**`.gitignore` 対象で手元にしか無い** — clone しても見つからないのは正常）

**`implementation_plan_ナイフモード.md` だけは歴史的資料ではなく「未実装の提案」。**
`IMPLEMENTATION_ROADMAP.md` フェーズ2.3（Split）と同じ主題。

各ファイルの冒頭に状態バナーが入っている。**バナーを消さないこと。**

> **版番号が3世代混在している。** `V1.2.0`〜`V1.4.0` → `V2.0.4` → `V8.1.x`。
> 古い計画書の「V1.5.0」等は現行の版番号とは**無関係**。

---

## 7. 作業の進め方（この人の好み）

- **小さく revert 可能なコミット**にする。コード判断は任されている
- 確認を取るのは **DEPSGRAPH_STATE_MACHINE.md §5 のチェックリスト C・D・H**
  のような実機確認が要る場面
- 推測で書かない。**確かめていないことは「未検証」と明記する**
  （`CROSS_PLATFORM_BUILD.md` がその書き方の見本）
- ドキュメントの数値は実測値。「たぶん」で書き換えない
