# V_7_0_6 リファクタリング計画案（OpenCASCADE拡張の土台作り）

## Goal Description

現在1,850行を超える超巨大モノリスとなっている `occ_core.cpp` を役割ごとに分割・整理し、Sweep、Loft、Knife（Split Face）などの高度で複雑なCAD機能を安全に追加できる「スケーラブルなC++アーキテクチャ」を構築する。
同時に、C++内部の不要な文字列パース処理を共通化し、エラーハンドリングを強化してBlender側へ異常を伝えられるようにする。

---

## Proposed Changes (Architecture & Files)

### 1. `occ_core.cpp` のモジュール分割
単一のファイルに全機能が詰め込まれている現状から、以下の複数のファイルに分割（モジュール化）します。

#### [NEW] `occ_primitives.cpp / .h`
- **役割**: 基本的な立体（ソリッド）の生成
- **移行する関数**: `make_box`, `make_cylinder`, `make_sphere`, `make_cone`, `make_torus`, `make_wedge`

#### [NEW] `occ_modifiers.cpp / .h`
- **役割**: 既存の立体に対する変形・加工
- **移行する関数**: `apply_fillet`, `apply_chamfer`, `apply_shell`, `apply_draft`, `apply_face_inset`, `apply_face_offset`

#### [NEW] `occ_booleans.cpp / .h`
- **役割**: 立体同士の論理演算
- **移行する関数**: `apply_boolean` (Fuse, Cut, Intersect)

#### [NEW] `occ_sketch.cpp / .h`
- **役割**: スケッチ由来の2Dワイヤー構築と、面への投影・分割処理
- **移行する関数**: `build_wire_from_segments`, `make_extrude`
- **拡張予定**: 将来的な `SplitFace`（ナイフ）機能のロジック基盤

#### [NEW] `occ_mesh.cpp / .h`
- **役割**: WGPU描画用のメッシュ（三角形・エッジ）抽出とデータ変換
- **移行する関数**: `generate_mesh`, `get_face_mesh`, `get_edge_points` 等のメッシュエクスポート群

#### [MODIFY] `occ_core.cpp` (Main Entry)
- **役割**: RustからのFFIエントリーポイント（`update_geometry`）の維持。
- ループ処理と `switch-case` (strcmpによる分岐) のみに専念し、実際の処理は上記モジュールの関数を呼び出すだけのクリーンな状態にする。

---

### 2. Rust側ビルドシステムの更新
#### [MODIFY] `build.rs`
- 新しく作成した複数の `.cpp` ファイルをコンパイル対象として `cc::Build::new()` に追加する。

---

### 3. C++内部のユーティリティ共通化
#### [NEW] `occ_utils.cpp / .h`
- **文字列分割の共通化**: 現在各関数に散らばっている `"Face:3|Face:4"` のようなパイプ区切り文字列のパース処理（`substr`等）を、安全なユーティリティ関数（例: `std::vector<std::string> split_string(const std::string&, char)`）として切り出し、バグを防ぐ。
- **堅牢な顔検索**: `find_face_robust` などの共通関数をここに配置。

---

### 4. エラー伝達基盤の構築（今後のための布石）
- **現状**: `try-catch` で `Standard_Failure` をキャッチしても、単に `log_debug` に吐き出して握りつぶしている。
- **改善**: C++側で起きたエラー文（例: "Cannot apply fillet: Radius too large"）を蓄積し、Rust経由でPythonに返し、Blender画面上に警告として表示できる構造への第一歩を仕込む。

---

## User Review Required

> [!WARNING]
> **C++ファイルの大規模な移動が発生します**
> このリファクタリングにより、C++側のファイル構造が大きく変わります。PythonやRustからの機能的な見た目（挙動）は一切変わりませんが、作業中はアドオンが一時的にビルドできなくなる可能性があります。

> [!IMPORTANT]
> **追加したい機能の優先順位について**
> この土台が完成した後、次に実装を優先したい機能はどれでしょうか？
> 1. Sweep（スイープ）
> 2. Loft（ロフト）
> 3. Knife（面のスケッチ分割）
> 
> リファクタリング完了後、指定された機能の実装へスムーズに移行します。

## Verification Plan

### Automated Tests
- `cargo build --release` が新しいファイル構造で正常に通過することを確認する。

### Manual Verification
- リファクタリング前と全く同じプロジェクトファイル（以前のテストで使ったフィレットやインセットのデータ）をBlenderで開き、再計算（Update）をかけても形状やメッシュ描画が完全に一致（劣化なし）することを確認する。
