# Knife Mode (Split Face) 実装計画案

CADエンジンの厳密性を保ちつつ、Blenderのナイフツールのような「面を自由に割る」操作を実現するための実装計画です。

## Goal Description

既存の面に対してユーザーが直感的にスケッチを描き、その線に沿って面を複数の独立した面に分割（Split）する機能を追加する。分割された面は、独立してPush/Pull（押し出し）や面取り、マテリアル割り当てが可能になる。

## Proposed Workflow & UI

### 1. UIへのボタン追加
- `CAD_7_0_5/ui/panels.py` または対象となるモディファイアパネルに「🔪 ナイフ（Split Face）」ボタンを追加。
- 実行条件: ユーザーが面（Face）を1つ選択していること。

### 2. ナイフモード（スケッチ）への移行
- ボタンを押すと、対象面を基準平面（ワークプレーン）とした**専用のスケッチモード**が起動する。
- 内部的には `SketchContext` に `is_knife_mode=True` のようなフラグを持たせ、通常の「新規立体生成スケッチ」とは挙動を分ける。
- 視点が自動的に面の真正面に移動する。

### 3. スケッチの描画
- ユーザーは既存のスケッチツール（Line, Arc, Splineなど）を使って、自由に切り取り線を描画する。
- **特徴**: 閉じた図形（円や四角形）である必要はなく、開いた一本の線（始点と終点が面の外に出ている線）でも可能。

### 4. スケッチの確定（Finalize）とデータ構築
- ユーザーがEnterキーを押してスケッチを確定する。
- Python側（`sketch_finalize.py`等）で、描画されたスケッチデータから**新しいモディファイア情報（PrimitiveJSON）**を構築する。
  - `type`: `SPLIT_FACE` (または `KNIFE`)
  - `target_lineage`: 選択されていた面のID（例: `Face:3`）
  - `segments`: ユーザーが描いた線のデータ（Line, Arc等のリスト）

## Proposed Changes (Rust/C++ Core)

### [NEW] `occ_core.cpp` - Split Faceロジックの追加

`update_geometry` 関数内のモディファイア適用フェーズに、新しく `SPLIT_FACE` 用の処理ブロックを追加する。

#### 1. スケッチ線（ワイヤー）の復元
- Pythonから渡された `segments` データを読み取り、`BRepBuilderAPI_MakeWire` を使ってOpenCASCADEのワイヤー（複数の線が繋がった形状）を構築する。

#### 2. 対象面への投影（Projection）
- ワイヤーを対象の面上に厳密に投影する。
- 対象面が曲面（円柱の側面など）である場合を考慮し、`BRepProj_Projection` クラスを使用して、描いた線が曲面に完全に沿うように計算する。

#### 3. 面の分割（Split Shape）
- 投影して得られた面上の曲線（3Dエッジ）を使い、`BRepFeat_SplitShape` クラスを初期化する。
- `splitter.Add(projected_edge, target_face)` で切り取り線を登録し、`splitter.Build()` でトポロジーの分割を実行する。

#### 4. 全体形状の更新
- 分割処理が成功したら、現在のソリッド（`out_shape`）を分割後のソリッドに置き換える。

## Verification Plan

### Automated Tests
- C++の単体テスト（`test_inset.cpp`等に類似するテスト）で、平面および円柱面に対して直線を投影し、面が2つ以上に増える（`TopExp_Explorer`でのFACEカウントが増加する）ことを検証する。

### Manual Verification
- Blender上でCubeの1つの面を選択し「ナイフ」を実行。斜めに線を引いて確定後、三角形の面が2つできていることを確認する。
- Cylinderの側面に波線（Spline）を描き、曲面が正しく波状に分割されるか確認する。
- 分割された片方の面だけを選択し、Push/Pull（押し出し）が正常に行えるか確認する。
