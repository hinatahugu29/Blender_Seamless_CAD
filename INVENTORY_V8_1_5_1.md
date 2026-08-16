# Seamless CAD アドオン 棚卸し

対象: `Blender_CAD_V_8_1_5_1/CAD_8_1_5_1` (bl_info version 8.1.5.7, target Blender 4.2.0 以上)
作成日: 2026-07-15 / 全面検証: 2026-08-02 / **数値再実測: 2026-08-14 (8.1.5.7)**

> 数(プリミティブ型・オペレータ・パネル等)は enum とソースを機械的に数え直した実測値。
> 同梱物は `CAD_8_1_5_1/` の実ファイルを集計した値。前版の数値には誤りがあった
> (「全22種」「約45コマンド」など)ので、記載の数字は本版を信用すること。

---

## 1. 技術スタック概要

### コア構成
- **Python (Blenderアドオン側)** + **Rust製BSPエンジン** (`seamless_core.pyd`/`.dll`、高速プレビュー用) + **OpenCASCADE (OCCT) を包んだ外部CADサーバー** (`bin/cad_server.exe`、TCPソケット経由、正確なB-repブーリアン用) という三層構成。
- `core_bridge.py` が Python ↔ Rust/C++ の橋渡しを担当し、127.0.0.1 のローカルソケットで `cad_server.exe` と通信。
- 描画は二系統: `graphics/wgpu_manager.py` (WGPUベースのオーバーレイ) と `gpu_manager.py` (Blender標準の `gpu` モジュール)。`drawing.py` がどちらを使うか選択する。

### 外部依存・同梱バイナリ (2026-08-02 実測)

同梱 DLL は **118個 / 約98MB**。配布 ZIP は **40.9MB / 227ファイル**。
(8.1.5.5 で不要な同梱物を落としたぶん、8.1.5.1 時点の 129個/45.9MB から減っている)

| 種別 | 個数 | サイズ | 必要性 |
|---|---|---|---|
| **OCCT (`TK*.dll`)** | 84 | 62.3 MB | 必須。幾何カーネル本体 |
| **FFmpeg (`av*`/`sw*`)** | 6 | 22.0 MB | **必須**。見た目は無関係だが `cad_server.exe` のロード時依存で、外すとカーネルが一切応答しない(実測) |
| FreeImage | 2 | 6.8 MB | OCCT の画像 I/O |
| Intel TBB | 6 | 2.0 MB | OCCT の並列処理 |
| `seamless_core.dll` | 1 | 2.0 MB | 自作 Rust エンジン |
| MSVC ランタイム | 9 | 1.4 MB | 同梱済みなので利用者の別途インストールは不要 |
| その他 (freetype/jemalloc 等) | 21 | 4.5 MB | OCCT の依存 |

- **OpenCASCADE は 8.0.1** (vc14/win64)。8.0.0 から 2026-08-11 に更新。前々版の「7.x」は誤り。
- **`libs/` の同梱 Python は `svgwrite` と `svgpathtools` のみ**(各 1MB 未満)。
  NumPy / SciPy は同梱していない — Blender が自前の NumPy を必ず持っており、
  `vendor_libs.py` は `libs/` を sys.path の**末尾**に足すだけなので同梱版は使われない設計。
- **Qt5 / VTK / Tcl-Tk / SQLite は同梱していない。** OCCT 配布物に含まれるインスペクタ・
  可視化ツール用の依存で、このアドオンは使わない。2026-08-01/02 に段階的に除去
  (Qt5 66個/111MB、NumPy 45MB、VTK+Qtプラグイン等 222個/143MB)。
  **いずれも「退避して回帰テストが通ること」を確認してから削除**しており、推測では消していない。
  除去物は `_removed_from_addon/` に保管(git 管理外)。

### Rust 側の依存 (`src_rust/Cargo.toml`)

`cpp` (C++ 埋め込み) / `ezpz` (KittyCAD 製 2D 拘束ソルバ、GCS の実体) / `rayon` (並列化) /
`wgpu` + `bytemuck` + `pollster` (GPU オーバーレイ) / `memmap2` / `serde`

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

## 2. フィーチャー型 (enum 実測 全34種)

> `properties.py` の `SeamlessPrimitive.type` enum を数えた値。「形状」だけでなくモディファイア・パターン・構造化も同じ enum に入っているので、**Feature Tree に並びうる要素の全種類**という意味の34種。

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

## 4. 2Dスケッチ機能

> 描画ツールは `sketch/states/` に **11種** (select / point / line / arc / circle /
> rectangle / semicircle / slot / fillet / trim_extend / base)。拘束は enum 実測で **14種** (8.1.5.6 で半径・角度・同長・同心・対称を追加)。
> 拘束ソルバ(GCS)の実体は Rust 依存の `ezpz` (KittyCAD 製)。
> **2026-08-02 に HORIZONTAL / VERTICAL / DISTANCE / PARALLEL / PERPENDICULAR /
> MIDPOINT / FIXED の解が正しいことを実測で確認済み**(回帰テストに固定)。

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

## 7. UIパネル構成 (実測 全12パネル)

すべて 3D ビューポートのサイドバー `Seamless` タブ配下。

| パネル | 内容 |
|---|---|
| `WorkspacePanel` | Part(独立スタック)の選択・追加・削除、CAD 開始 |
| `DisplayPanel` | 不透明度 / WGPU Overlay / **Hide Occluded Edges** (2026-07-30 追加。Overlay OFF かつ不透明のときだけ有効で、それ以外はグレーアウト) |
| `QualityBakePanel` | テッセレーション品質(プレビュー用/ベイク用で別)、高速モディファイアドラッグ、ライブブーリアン、Bake、STEP/SVG 入出力 |
| **`MeasurePanel`** | **[2026-08-17 追記]** 質量特性の計測。Part 全体(体積・表面積・寸法・重心)と辺/面の個別(長さ・面積・半径)。**測るのはボタンを押したときだけ**で `draw()` からカーネルを呼ばない。lineage が現在の形状に一致しないときは値を出さず再選択を促す |
| `SelectionPanel` | 辺/面の選択モード切替 |
| `PlacementSnapPanel` | サーフェススナップ / 対話配置 / ビジュアルスナップ移動 |
| `CreatePanel` | プリミティブ追加、スケッチ開始 |
| `ModifyPatternPanel` | モディファイア・トポロジー整理・ミラー/配列 |
| `FeatureTreePanel` | 履歴一覧、ロールバック、グループ選択 |
| `PropertyEditorPanel` | 選択中フィーチャーのパラメータ編集 |
| `SketchPanel` | スケッチモード中のツール・拘束・アクション |

**表示されるパラメータは「実際に形状へ効くもの」だけに揃えてある。**
`audit_ui_params.py` が UI の描画内容と実際の効果を突き合わせ、不一致があれば終了コード 1 を返す。
2026-08-01 の監査で見つかった死んだ欄(CYLINDER/SPHERE の Radius、SLOT/CONE/ARC/VARIABLE_BOX の
余剰 size 成分、CLEANUP のチェックボックス2つ)は除去済み。現在は不一致ゼロ。

---

## 8. 全オペレータ一覧 (実測 37クラス)

`seamless.*` 名前空間に **37個**の独立オペレータクラス。加えて `seamless.sketch_action` が
**32種**のアクション文字列を振り分けるので、利用者から見える操作数はさらに多い。

| 分類 | オペレータ |
|---|---|
| Part 管理 | `start_cad` / `add_part` / `remove_part` / `get_version` |
| プリミティブ | `add_primitive` / `add_dynamic_loft_hole` / `variable_box_hole` / `add_curve_point` / `add_curve_point_at` / `remove_curve_point_at` |
| 選択 | `selection_modal` (辺/面のモーダル選択の本体) |
| 移動・配置 | `interactive_placement` / `interactive_transform` / `visual_snap` / `interactive_offset_pick` |
| 管理 | `remove_primitive` / `set_active_primitive` / `duplicate_primitive` / `pick_active_as_target` / `pick_target_modal` / `set_rollback_index` / `group_selection` / `force_recompute` / `toggle_fillet_edge_default` |
| 入出力 | `import_step` / `import_svg` / `export_step` / `separate_by_base` |
| ベイク | `bake_mesh` |
| スケッチ | `start_sketch` / `sketch_draw_tool` / `sketch_action` / `select_reference_plane` / `edit_sketch` / `edit_dimension_value` |

> 前版は「20クラス / 約45コマンド」としていたが、いずれも実測と合わず、
> `selection_modal` `variable_box_hole` `force_recompute` `edit_sketch`
> `toggle_fillet_edge_default` `edit_dimension_value` の6件が一覧から漏れていた。

---

## 9. 対応ファイル形式 (実測)

| 形式 | 読込 | 書出 |
|---|---|---|
| **STEP** (`.stp` / `.step`) | ✅ `import_step` | ✅ `export_step` (**名前・アセンブリ構造つき**) |
| **STL** (`.stl`) | — | ✅ `export_stl` **[2026-08-17 追加]** |
| **SVG** | ✅ `import_svg` (2D プロファイル/ロゴ) | — |
| Blender メッシュ | — | ✅ `bake_mesh` (以降は Blender 標準の書出が使える) |

**STEP は 2026-08-17 から XCAF 経由**(`STEPCAFControl_Writer`)。それ以前は
`STEPControl_Writer` に直接渡していたため、受け取った側では**名前の無い塊が
ひとつ**見えるだけだった。現在は Part 名が製品名として入り、
`All Parts as Assembly` を入れると全 Part が1ファイルのアセンブリになる:

```
Assembly
  ├─ Part_1
  └─ Part_2      (NEXT_ASSEMBLY_USAGE_OCCURRENCE で関係づけ)
```

**色は載っていない。** アドオン側に色という概念がまだ無く
(`properties.py` に色プロパティは1つも無い)、書き出す元データが存在しない。
詳細は `IMPLEMENTATION_ROADMAP.md` の「追加項目 — Part の色」。

**STL はカーネルから直接書き出す**(Bake → Blender メッシュ → Blender の STL
エクスポータ、という往復を通さない)。利点は手数ではなく**精度**で、
テセレーションをベイク品質の設定で直接指定できる。バイナリ既定、ASCII も選べる。
STEP と同じ `Scale (1 unit = N mm)` を持つ。

> 実装で一度踏んだ罠: `current_shape` にはプレビューが作った三角形分割が載って
> いて、`BRepMesh_IncrementalMesh` は要求精度を満たす面を切り直さない。
> 書き出し用のコピーに `BRepTools::Clean` をかけてから切り直さないと、
> **指定した品質が黙って無視される**。サボタージュテストで発覚した
> (メッシュ生成を丸ごと削ってもテストが緑のままだった)。

**IGES は非対応。** コード内に該当する処理は一切存在しない
(2026-08-01 に Python / Rust / C++ 全体を検索して確認。販売ページの原稿に
「STEP & IGES 対応」と書かれていたため実装を確認し、誤りと判明して修正した)。

---

## 10. 品質保証の仕組み (2026-07-30 以降に整備)

| 仕組み | 内容 |
|---|---|
| `regression_test.py` | ヘッドレス回帰テスト **43件** (2026-08-17 実測)。Blender 4.2 / 5.1 で確認。登録、プリミティブ追加、双方向同期、削除同期、確定フェーズの契約、FILLET/CHAMFER が実際に形状を変えること、スケッチ拘束ソルバ、スケッチ確定、ベイク、STEP 書出、保存→再読込、Undo 1回=1ステップ |
| `audit_ui_params.py` | UI に出ているパラメータと実際に効くパラメータの突き合わせ。全11型で不一致ゼロ |
| `package_addon.py` の PREFLIGHT | 必須ファイルの存在、全 `.py` の構文、同梱ライブラリの**実 import**、文字化け、バージョン整合、`license.txt` の同梱 |

**自動化できないもの**: ドラッグ追従・確定後の描画・WGPU Overlay OFF 時の挙動。
ネイティブの変形モーダルと GPU 描画が要るため原理的に再現できず、実機確認が必要。
詳細は `Blender_CAD_V_8_1_5_1/DEPSGRAPH_STATE_MACHINE.md` §5。

---

## 11. 動作環境

- **Windows 10 / 11 (64bit) のみ。** macOS / Linux ビルドは無い(カーネルが Windows 向けビルド)
- **Blender 4.2 LTS 〜 5.1** で回帰テスト通過を確認 (4.2.7 / 4.3.2 / 4.4.0 / 5.1.1)
- ライセンス: **GPL-2.0-or-later** (Blender 本体と同じ)
- 状態: Beta
