<!-- DOC-STATUS -->
> **状態: 歴史的資料** — V8.1.4 時点の棚卸し。**現行は `INVENTORY_V8_1_5_1.md`。**
> 本書の数値には既知の誤りがある（「全22種」「約45コマンド」など）。数を引用しないこと。
>
> 全体の分類は `CLAUDE.md` §6 にある。**このバナーを消さないこと。**

---

# Blender CAD アドオン 棚卸し (V8.1.4時点)

対象: `Blender_CAD_V_8_1_4/CAD_8_1_4`(bl_info version 8.1.4, target Blender 4.2.0)
作成日: 2026-07-14

---

## 1. 技術スタック概要

### コア構成
- **Python(Blenderアドオン側)** + **Rust製BSPエンジン**(`seamless_core.pyd`/`.dll`、高速プレビュー用) + **OpenCASCADE(OCCT)を包んだ外部CADサーバー**(`bin/cad_server.exe`、TCPソケット経由、正確なB-repブーリアン用)という三層構成。
- `core_bridge.py`がPython↔Rust/C++の橋渡しを担当し、127.0.0.1のローカルソケットで`cad_server.exe`と通信。
- 描画は二系統: `graphics/wgpu_manager.py`(WGPUベースのオーバーレイ)と`gpu_manager.py`(Blender標準の`gpu`モジュール)。`drawing.py`がどちらを使うか選択する。

### 外部依存・同梱バイナリ
- **OpenCASCADE(OCCT) 7.x**: `TK*.dll`一式(ジオメトリ/トポロジーカーネル、STEP/IGES/STL/glTF/VRMLの入出力、可視化、インスペクタツールまでフル装備)
- **VTK 9.4**: `vtk*-9.4.dll`一式(OCCTのインスペクタ/可視化ツール経由の間接依存とみられる)
- **Qt5 / Qt3D**: `Qt5*.dll`(デバッグ版含む) — OCCTのインスペクタ用途で、アドオン自体のUIはBlender純正UIのみ
- **FFmpeg**: `avcodec/avformat/avutil`等 — VTK/Qt経由の間接依存とみられる
- **MSVCランタイム、Intel TBB、jemalloc**などの標準的な実行時ライブラリ
- **NumPy 2.4.6 / SciPy 1.17.1**(`libs/`配下にwheelとして同梱、Blender付属Pythonにpipインストール不要な自己完結構成)
- リポジトリ直下に`test_roundtrip_box.step`等のSTEP往復テスト成果物が残存(実行時には不要)

### モジュールマップ(主要ファイル)
| ファイル/ディレクトリ | 役割 |
|---|---|
| `__init__.py` | アドオン登録エントリポイント |
| `properties.py`(767行) | 全プロパティ定義(プリミティブ・スケッチ・シーン設定) |
| `core_bridge.py`(2011行) | Rust/OCCTブリッジ、プレビュー更新の中枢 |
| `drawing.py`(1257行) | ビューポートのワイヤーフレーム/オーバーレイ描画 |
| `graphics/wgpu_manager.py` | WGPUベースの描画エンジン |
| `gpu_manager.py` | Blender標準`gpu`モジュールによる描画 |
| `utils.py`(1348行) | プロキシ同期、UUID/スタック管理、親子関係などの共通処理 |
| `modal_selection.py`(806行) | 辺/面のモーダル選択(フィレット・面取り・オフセット対象の選択に使用) |
| `svg_parser.py` | SVGインポート用パーサー |
| `core/state_manager.py` | フィーチャースタックの状態管理・ロールバック |
| `core/semantic_targets.py` | プリミティブ/辺/面へのセマンティック参照(スタック編集後も追従) |
| `operators/` | 各種オペレータ(後述) |
| `sketch/` | 2Dスケッチのモーダルツール・ソルバー |
| `ui/` | サイドバーパネル |

---

## 2. 対応プリミティブ形状(全21種)

**基本形状**: Box / Cylinder / Sphere / Cone / Torus / Polygon / Gear(インボリュートギア、歯数・モジュール・圧力角指定) / Helix(螺旋、巻き数・パイプ半径) / Slot(スタジアム形状)

**スケッチ由来の2D→3D形状**: Polyline(フィレット付き折れ線) / Arc(円弧/真円) / Curve(自由曲線/BSpline) / Surface(閉曲線から面生成)

**プロファイル操作**: Revolve(回転体) / FaceRevolve(特定面の回転) / Sweep(パス沿いスイープ、フレームモードAUTO/HELIX_AXIS対応) / Loft(複数断面のロフト) / FaceLoft(2面間ロフト+フュージョン) / VariableBox(動的ロフト、上下で別形状指定可)

**インポート**: STEP_PART(STEP読込) / SVG_PART(SVG読込)

**パターン/複製**: Mirror(X/Y/Z軸/点対称) / Instance(ボディリンク、独立トランスフォーム付き複製) / ArrayLinear / ArrayCircular

**構造化**: GroupStart/GroupEnd(ブーリアングループのネスト)

**モディファイア型(既存形状の辺/面に作用)**: Fillet / Chamfer / FaceOffset(押し出し/引き込み) / FaceInset / Draft(抜き勾配) / Shell(シェル化) / Cleanup(同一平面/同軸面・共線/共円辺の統合、"Slow"フラグ付き)

---

## 3. ブーリアン演算

- 基本演算: `BASE`(起点形状) / `ADD`(結合) / `SUB`(切り取り) / `INT`(共通部分) — スタック上で前段の結果に対して逐次適用
- モディファイア系(Fillet/Chamfer/FaceOffset/FaceInset/Draft/Shell/Cleanup)は`modal_selection.py`で選択した辺/面IDに対して作用
- パターン系(Mirror/ArrayLinear/ArrayCircular/Instance)は`target_uuid`で対象プリミティブを参照する方式(直接ジオメトリ編集ではない)
- Part(独立したブーリアンスタック)は`seamless.add_part`/`seamless.remove_part`で複数管理可能
- Bake(`seamless.bake_mesh`): OCCTの正確なB-rep結果を静的なBlenderメッシュに変換、専用の高品質テッセレーション設定(`bake_quality`/`bake_angular_quality`)を使用可能

---

## 4. 2Dスケッチ機能

**描画ツール(ペンモード)**: Select / Point / Line / Arc / Circle / Rectangle(角基準) / CenterRect(中心基準) / Semicircle — 各々`sketch/states/state_*.py`のモーダルステートマシンで実装

**編集・選択操作**: 全選択 / チェーン選択 / 削除 / コピー&ペースト / 構築線トグル

**ジオメトリ操作**: X/Yミラー / オフセット / トリム / 延長

**コーナー処理**: フィレット / 面取り(半径・距離をそれぞれ指定可)

**拘束ソルバー(GCS)**: 固定 / 水平・垂直 / 平行・直交 / 接線 / 距離 / 中点 / 一致(結合)、拘束削除

**その他**: 「面にスケッチ」(既存ソリッドの面を参照平面として選択) / グリッドスナップ・表示トグル / アンドゥ/リドゥ履歴

スケッチはRevolve/Sweep/Loft/Surface/Curveなどのプロファイルソースとして機能する。

---

## 5. 特殊機能

- **ビジュアルスナップ移動**(`seamless.visual_snap`): 面中心/辺中点/頂点にスナップしながら2段階(移動元→移動先)でプリミティブを再配置。軸/平面拘束オプションあり。
- **オフセットピック**(`seamless.interactive_offset_pick`): スナップ点を拾って法線方向のオフセット距離を対話的に決定。
- **セマンティックターゲット**: プリミティブ/辺/面をIDではなく安定参照で保持し、スタック編集後もフィレット/パターンが追従。
- **ロールバック**: フィーチャーツリーの任意の時点まで「巻き戻して」編集できる(CADの典型的なロールバックバー相当)。
- **STEP/SVGインポート・エクスポート**、**Separate by Base**(スタックの一部を新規Partとして分離)
- **パターンターゲットピック**(リスト選択/ビューポート内モーダル選択)
- **グループ選択**(複数プリミティブをまとめてグループ化)
- **独立トランスフォーム**: 親を動かしても子のワールド位置を引きずらないオプション
- **パフォーマンスロギング**: `cad_profile.log`へプレビューパイプラインのタイミングを出力

---

## 6. 描画/プレビューパイプライン

- 2種類の更新関数: `update_cad_preview`(通常) / `update_cad_preview_fast` / `update_cad_preview_forced` / `update_cad_preview_high_quality`(ベイク前専用)
- テッセレーション品質はプレビュー用(`mesh_quality`/`mesh_angular_quality`)とベイク用(`bake_quality`/`bake_angular_quality`)で分離
- **`fast_modifier_preview`**(既定ON): フィレット/面取り/シェル半径のドラッグ中はシェーディング面を省略しワイヤーフレームのみ表示、離した時点でフルシェーディング復帰
- **`live_boolean_preview`**(既定OFF): ブーリアンツールのドラッグ中、Rust側BSPエンジンで毎フレーム軽量ブーリアンを実行しライブ表示。最も重いパスのため既定OFF — 通常はプロキシ移動のみ行い、正確なOCCT再計算はドラッグ終了時まで遅延
- `is_dragging`/`is_placing`フラグでBlender標準の移動モーダルと本アドオン独自のモーダルを区別し、重い描画更新を適切にスキップ/再開

---

## 7. UIパネル構成

**メインパネル(`ui_main_panel.py`、3Dビューポートのサイドバー)**
- Active CAD Workspace — Part/コレクション選択、CADサーバー起動制御
- Viewport Display — 表示透明度、WGPUオーバーレイ切替
- Quality & Export — メッシュ品質、ベイク品質、Bake/STEPエクスポート操作
- Selection Mode — 辺/面選択モード切替
- Placement & Snap — スナップ、ライブ/高速プレビュー切替、オフセットピック等
- Create — 各プリミティブ追加ボタン(Box/Cylinder/…/STEP・SVGインポート等)
- Modify & Pattern — Fillet/Chamfer/Shell/Draft/Offset/Insetおよびパターン操作ボタン
- Feature Tree — プリミティブスタックのリストUI(追加/削除/複製/並べ替え/ロールバック)
- Active Property Editor — 選択中プリミティブのプロパティを動的表示

**スケッチパネル(`ui_sketch_panel.py`)**: ペンモードツール、拘束、コーナー処理、スケッチアクション、グリッド/スナップ切替

**アドオン設定(`ui_preferences.py`)**: サーバーパス等のグローバル設定

---

## 8. 全オペレータ一覧(約45コマンド)

`seamless.*`名前空間で20個の独立オペレータクラス+`seamless.sketch_action`が約25種のアクション文字列を振り分ける構成。

**Part管理**: start_cad / add_part / remove_part / get_version

**プリミティブ**: add_primitive / add_dynamic_loft_hole / add_curve_point / add_curve_point_at / remove_curve_point_at

**移動/配置**: interactive_placement / interactive_transform / visual_snap / interactive_offset_pick

**管理**: remove_primitive / set_active_primitive / duplicate_primitive / pick_active_as_target / pick_target_modal / set_rollback_index / group_selection

**インポート/エクスポート**: import_step / import_svg / export_step / separate_by_base

**ベイク**: bake_mesh

**スケッチ**: start_sketch / sketch_draw_tool / select_reference_plane(面にスケッチ) / sketch_action(UNDO, APPLY, CANCEL, 選択系, ミラー/オフセット/トリム/延長, フィレット/面取り, 各種拘束など約25種)

---

## 補足: 現状認識(2026-07-14時点の会話から)

- ブーリアンスキップ(セトル方式+任意のライブBSPプレビュー)の土台は前日(2026-07-13)の不具合修正で安定化したばかりで、対症療法的な修正も含まれるため「実戦未経験」な部分がある。
- 半径系プロパティのUIステップ幅(矢印クリック時の増分)を0.03→0.01に統一済み。未検証。
- β版的運用の開始を検討中。
