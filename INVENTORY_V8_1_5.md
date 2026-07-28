# Blender CAD アドオン 棚卸し (V8.1.5時点)

対象: `Blender_CAD_V_8_1_5/CAD_8_1_5` (bl_info version 8.1.5, target Blender 4.2.0)
作成日: 2026-07-15

---

## 1. 技術スタック概要

### コア構成
- **Python (Blenderアドオン側)** + **Rust製BSPエンジン** (`seamless_core.pyd`/`.dll`、高速プレビュー用) + **OpenCASCADE (OCCT) を包んだ外部CADサーバー** (`bin/cad_server.exe`、TCPソケット経由、正確なB-repブーリアン用) という三層構成。
- `core_bridge.py` が Python ↔ Rust/C++ の橋渡しを担当し、127.0.0.1 のローカルソケットで `cad_server.exe` と通信。
- 描画は二系統: `graphics/wgpu_manager.py` (WGPUベースのオーバーレイ) と `gpu_manager.py` (Blender標準の `gpu` モジュール)。`drawing.py` がどちらを使うか選択する。

### 外部依存・同梱バイナリ
- **OpenCASCADE (OCCT) 7.x**: `TK*.dll` 一式 (ジオメトリ/トポロジーカーネル、STEP/IGES/STL/glTF/VRMLの入出力、可視化、インスペクタツールまでフル装備)
- **VTK 9.4**: `vtk*-9.4.dll` 一式 (OCCTのインスペクタ/可視化ツール経由の間接依存とみられる)
- **Qt5 / Qt3D**: `Qt5*.dll` (デバッグ版含む) — OCCT of インスペクタ用途で、アドオン自体のUIはBlender純正UIのみ
- **FFmpeg**: `avcodec/avformat/avutil` 等 — VTK/Qt経由の間接依存とみられる
- **MSVCランタイム、Intel TBB、jemalloc** などの標準的な実行時ライブラリ
- **NumPy 2.4.6 / SciPy 1.17.1** (`libs/` 配下にwheelとして同梱、Blender付属Pythonにpipインストール不要な自己完結構成)

### モジュールマップ (主要ファイル)
| ファイル/ディレクトリ | 役割 |
|---|---|
| `__init__.py` | アドオン登録エントリポイント |
| `properties.py` | 全プロパティ定義 (プリミティブ・スケッチ・シーン設定。`Align X / Align Y` への表記統一等) |
| `core_bridge.py` | Rust/OCCTブリッジ、プレビュー更新の中枢 |
| `drawing.py` | ビューポートのワイヤーフレーム/オーバーレイ描画 |
| `graphics/wgpu_manager.py` | WGPUベースの描画エンジン |
| `gpu_manager.py` | Blender標準 `gpu` モジュールによる描画 |
| `utils.py` | プロキシ同期、UUID/スタック管理、親子関係などの共通処理 |
| `modal_selection.py` | 辺/面のモーダル選択 (フィレット・面取り・オフセット対象の選択に使用) |
| `svg_parser.py` | SVGインポート用パーサー |
| `core/state_manager.py` | フィーチャースタックの状態管理・ロールバック |
| `core/semantic_targets.py` | プリミティブ/辺/面へのセマンティック参照 (スタック編集後も追従) |
| `operators/` | 各種オペレータ |
| `sketch/` | 2Dスケッチのモーダルツール・ソルバー |
| `sketch/states/state_slot.py` | [NEW] スロット（長円）描画時の3点制御および自動拘束生成処理 |
| `sketch/states/state_trim_extend.py` | [NEW] トリム/延長モード時の交点算出および自動Trim/Extend切り替え処理 |

---

## 2. 対応プリミティブ形状 (全22種)

**基本形状**: Box / Cylinder / Sphere / Cone / Torus / Polygon / Gear (インボリュートギア、歯数・モジュール・圧力角指定) / Helix (螺旋、巻き数・パイプ半径) / Slot (スタジアム形状)

**スケッチ由来の2D→3D形状**: Polyline (フィレット付き折れ線) / Arc (円弧/真円) / Curve (自由曲線/BSpline) / Surface (閉曲線から面生成)

**プロファイル操作**: Revolve (回転体) / FaceRevolve (特定面の回転) / Sweep (パス沿いスイープ、フレームモードAUTO/HELIX_AXIS対応) / Loft (複数断面 of ロフト) / FaceLoft (2面間ロフト+フュージョン) / VariableBox (動的ロフト、上下で別形状指定可)

**インポート**: STEP_PART (STEP読込) / SVG_PART (SVG読込)

**パターン/複製**: Mirror (X/Y/Z軸/点対称) / Instance (ボディリンク、独立トランスフォーム付き複製) / ArrayLinear / ArrayCircular

**構造化**: GroupStart/GroupEnd (ブーリアングループのネスト)

**モディファイア型 (既存形状の辺/面に作用)**: Fillet / Chamfer / FaceOffset (押し出し/引き込み) / FaceInset / Draft (抜き勾配) / Shell (シェル化) / Cleanup (同一平面/同軸面・共線/共円辺の統合)

---

## 3. ブーリアン演算

- 基本演算: `BASE` (起点形状) / `ADD` (結合) / `SUB` (切り取り) / `INT` (共通部分) — スタック上で前段の結果に対して逐次適用
- モディファイア系 (Fillet/Chamfer/FaceOffset/FaceInset/Draft/Shell/Cleanup) は `modal_selection.py` で選択した辺/面IDに対して作用
- パターン系 (Mirror/ArrayLinear/ArrayCircular/Instance) は `target_uuid` で対象プリミティブを参照する方式 (直接ジオメトリ編集ではない)
- Part (独立したブーリアンスタック) は `seamless.add_part` / `seamless.remove_part` で複数管理可能
- Bake (`seamless.bake_mesh`): OCCTの正確なB-rep結果を静的なBlenderメッシュに変換

---

## 4. 2Dスケッチ機能 (V8.1.5で大幅に強化)

**描画ツール (ペンモード)**: 
- `Select` / `Point` / `Line` / `Arc` / `Circle` / `Rectangle` (角基準) / `CenterRect` (中心基準) / `Semicircle`
- **`Slot` (スロット / 長円) [NEW]**: 中心1・中心2・半径/幅を3点クリックで指定。描画中は外郭と中心線のプレビューがリアルタイムに表示され、Shiftキーによる直交スナップ（軸ロック）にも完全対応。平行線・半円弧、および接線拘束や円弧拘束が自動生成されます。

**編集・選択操作**: 全選択 / チェーン選択 / 削除 / コピー&ペースト / 構築線トグル
- **複数頂点・辺の同時ドラッグ移動 [NEW]**: 複数選択中の頂点群や、辺（直線）そのものをクリックしてドラッグした際、適用されている幾何拘束を満たした状態で全体の形状を維持しながらスムーズに平行移動（変位 delta 加算解決）が可能。

**ジオメトリ操作**: X/Yミラー / オフセット
- **トリム (Trim) / 延長 (Extend) [NEW]**: 同一のペンモード内で、マウスホバー位置に応じて「交差箇所をカットする赤プレビュー（トリム）」と「他の線まで引き伸ばす緑プレビュー（延長）」がインテリジェントに自動切り替え実行されます。

**スナップ・インジケータ**:
- **中点スナップ [NEW]**: 直線の中点に吸着し、緑色の三角形（△）マーカーを表示。
- **インファレンス（一時ガイドライン） [NEW]**: 他の既存頂点とX座標・Y座標が揃った際に自動スナップし、位置関係を示す白い点線（補助ガイドライン）を描画。

**拘束ソルバー (GCS)**:
- 固定 / **Align X (水平) [表記変更]** / **Align Y (垂直) [表記変更]** / 平行・直交 / 接線 / 距離 / 中点 / 一致 (結合)、拘束削除
- **自動水平・垂直拘束 (Auto-Constraint) [NEW]**: `Line` モードで描画された直線の角度が軸（水平・垂直）に極めて近い（約5度以内）場合に、自動で `Align X` または `Align Y` 拘束を付与して解決。
- **完全拘束（Fully Constrained）の色分け表示 [NEW]**: 完全に位置や寸法が決まり動かなくなった要素（点・線・円・円弧）を **「ダークブルー（ほぼ黒）」** で描画し、未拘束の要素（水色/緑色）と視覚的に区別。
  - **遅延実行（デバウンス）による最適化**: 連続編集やフィレット一括適用時の負荷を防ぐため、DoFテストは操作が静止した 0.15 秒後に非同期タイマーで実行され、描画用補間点（`is_segment`）はスキップする軽量化設計。

---

## 4.5. 寸法線編集 & スケッチ再編集 (棚卸し漏れにつき追記, 2026-07-15)

- **寸法線オーバーレイ＆インプレース編集 [部分実装]**: スケッチモード中、`DISTANCE`拘束を持つ2点の中点に `📏 数値` のテキストラベルをビューポート描画 (`sketch/sketch_draw.py:668-705`, `blf.draw`)。ラベルをクリックするとヒット判定 (`sketch/modal_sketch.py:200-209`) 経由で `seamless.edit_dimension_value` (`sketch/actions/dimension_edit.py:25-69`) が起動し、`invoke_props_dialog` の数値入力ポップアップで値を書き換え→GCS再ソルブ→プレビュー更新まで機能する。**未実装なのは見た目のみ**: 引き出し線・矢印などのCAD製図的な寸法線描画は無く、数値テキストラベルのみ。
- **Edit Sketch (非破壊スケッチ再編集) [実質完成]**: スケッチ由来プリミティブ選択時にNパネルへ「Edit Sketch」ボタンが出現 (`ui/ui_main_panel.py:369`)。`SEAMLESS_OT_EditSketch` (`operators/management.py:816-862`) が `sketch_snapshots`(`properties.py:117,464,524`、確定時に `sketch/sketch_finalize.py:580-581` で点・線・拘束をフル保存)から元のスケッチデータを復元し、スケッチモードを再起動。再確定時は同一プリミティブUUIDを使い回すため、下流のRevolve/Extrude等フィーチャーも自動追従して再計算される。`set_rollback_index`(プリミティブを隠すだけの別機構)とは独立した専用実装。

## 5. 特殊機能

- **ビジュアルスナップ移動** (`seamless.visual_snap`): 面中心/辺中点/頂点にスナップしながら2段階 (移動元→移動先) でプリミティブを再配置。
- **オフセットピック** (`seamless.interactive_offset_pick`): スナップ点を拾って法線方向のオフセット距離を対話的に決定。
- **セマンティックターゲット**: プリミティブ/辺/面をIDではなく安定参照で保持し、スタック編集後もフィレット/パターンが追従。
- **ロールバック**: フィーチャーツリーの任意の時点まで「巻き戻して」編集できる。
- **STEP/SVGインポート・エクスポート**、**Separate by Base**
- **パターンターゲットピック**、**グループ選択**、**独立トランスフォーム**
- **パフォーマンスロギング**: `cad_profile.log` へプレビューパイプラインのタイミングを出力

---

## 6. 描画/プレビューパイプライン

- テッセレーション品質はプレビュー用とベイク用で分離。
- **`fast_modifier_preview`** (既定ON): フィレット/面取り/シェル半径のドラッグ中はシェーディング面を省略しワイヤーフレームのみ表示。
- **`live_boolean_preview`** (既定OFF): ブーリアンツールのドラッグ中、Rust側BSPエンジンで毎フレーム軽量ブーリアンを実行しライブ表示。
- `is_dragging`/`is_placing` フラグで描画更新を最適制御。

---

## 7. UIパネル構成

**メインパネル (`ui_main_panel.py`、3Dビューポートのサイドバー)**
- Active CAD Workspace / Viewport Display / Quality & Export / Selection Mode / Placement & Snap
- Create (プリミティブ追加、STEP・SVGインポート等)
- Modify & Pattern / Feature Tree / Active Property Editor

**スケッチパネル (`ui_sketch_panel.py`)**: 
- ペンモードツール (スロットボタンの追加、`Align X / Align Y` への表記統一など)
- 拘束 / コーナー処理 / スケッチアクション / グリッド・スナップ切替

**アドオン設定 (`ui_preferences.py`)**: サーバーパス等のグローバル設定

---

## 8. 全オペレータ一覧 (約45コマンド)

`seamless.*` 名前空間で20個の独立オペレータクラス + `seamless.sketch_action` が約25種のアクション文字列を振り分ける構成。

**Part管理**: start_cad / add_part / remove_part / get_version

**プリミティブ**: add_primitive / add_dynamic_loft_hole / add_curve_point / add_curve_point_at / remove_curve_point_at

**移動/配置**: interactive_placement / interactive_transform / visual_snap / interactive_offset_pick

**管理**: remove_primitive / set_active_primitive / duplicate_primitive / pick_active_as_target / pick_target_modal / set_rollback_index / group_selection

**インポート/エクスポート**: import_step / import_svg / export_step / separate_by_base

**ベイク**: bake_mesh

**スケッチ**: start_sketch / sketch_draw_tool / select_reference_plane (面にスケッチ) / sketch_action (ミラー/オフセット/トリム/延長/自動直交拘束などのアクション制御)
