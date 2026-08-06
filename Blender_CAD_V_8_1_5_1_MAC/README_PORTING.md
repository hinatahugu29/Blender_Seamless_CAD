# Blender_CAD 8.1.5.1 — macOS 移植作業フォルダ

Windows 版 `Blender_CAD_V_8_1_5_1` から、**Windows 専用バイナリを除いて**複製した
macOS 用の作業フォルダ。SDF.R の `Rust-GPU-SDF-V16.1.0_MAC` と同じ流儀。

## このフォルダに「無い」もの（意図的に外した）

- `*.dll` / `cad_server.exe` / `seamless_core.pyd` — Windows 専用。
  持ち込むと「ファイルはあるのに動かない」で必ず混乱するので、最初から入れない。
- `src_rust/target/` と `*.obj` — MSVC の中間生成物。
- `*.step` のテストデータ、各種 `.zip` / `.log`。

`CAD_8_1_5_1/bin/` は**空のまま置いてある**。ここに macOS 版 `cad_server` が入る。

## 現状ステータス

| 項目 | 状態 |
|---|---|
| Python 側コード | Windows 版と同一。**未改修** |
| `src_rust/build.rs` | Windows 版と同一。**MSVC 決め打ちのまま。要改修** |
| `cad_server`（macOS 版バイナリ） | **未ビルド** |
| OCCT（macOS 版） | **未取得** |
| ビルドスクリプト | **未作成** |

つまり、**現時点でこのフォルダは動かない**。これは正常な状態。

## 必要な改修（着手前に必ず読む）

1. **`src_rust/build.rs`** — 現在 MSVC 前提でベタ書き。
   - `/std:c++17` `/utf-8` → macOS では `-std=c++17`
   - `occt_root` の `win64/vc14/lib` → macOS のライブラリパス
   - VS2022 の include パス群（15〜24 行目）は macOS では不要。`cfg!(target_os)` で分岐する。

2. **`CAD_8_1_5_1/core_bridge.py`** — 2 箇所。
   - `cad_server.exe` の決め打ち（578 行目付近）→ macOS では拡張子なし `cad_server`
   - `creationflags=subprocess.CREATE_NO_WINDOW`（599 行目付近）
     → **Windows 以外では AttributeError で即死する**。分岐必須。

3. **`package_addon.py`**
   - `REQUIRED_PATHS` の `cad_server.exe` → プラットフォーム別に。
   - **実行権限（+x）の保持**。素の `zipfile` は権限ビットを落とすため、
     このまま zip を作ると macOS で `Permission denied` になる。
     `ZipInfo.external_attr` に `0o755 << 16` を明示する必要がある。
     ※ SDF.R は `.so`（実行権限不要）だったのでこの罠を踏んでいない。**こちらは踏む。**

4. **OCCT ランタイムの同梱と `@loader_path`**
   - OCCT の `.dylib` を同梱し、`install_name_tool` で参照を `@loader_path` 基準に
     書き換える。ビルドマシンの絶対パスが残っているとユーザー環境で起動しない。

5. **`CAD_8_1_5_1/license.txt`**
   - 現在 GPL-2.0-or-later のみ。OCCT は LGPL-2.1 なので、その全文の追加が必要。

## OCCT の入手方法（調査済み・2026-08-06 時点）

**公式サイト `dev.opencascade.org/release` のプリビルドは Windows 専用。**
macOS 向けはソースのみ。よって以下から選ぶ。

| 入手元 | バージョン | 判定 |
|---|---|---|
| **conda-forge `occt`** | **8.0.1 / 8.0.0**（osx-arm64, osx-64 あり） | ◎ **採用候補**。Windows 版 8.0.0 と揃えられる |
| Homebrew `opencascade` | 7.9.3 | △ 版が揃わない |
| ソースからビルド | 任意 | ○ 確実だが CI で 30〜40 分 |

conda-forge が 8.0.0 を持っているのが決定打。**3 OS すべてを 8.0.0 で揃えられる**ため、
「Mac だけフィレットの挙動が違う」類の再現困難なバグを回避できる。

## macOS 固有の注意（SDF.R の実績から）

- **Gatekeeper**：未署名バイナリはブロックされる。当面は**テスター配布**として、
  「システム設定 > プライバシーとセキュリティ > このまま開く」を案内する運用。
  ドキュメントに正直に明記すること。将来的に Apple Developer 登録を行う方針。
  ※ SDF.R は `.so` のブロックだったが、こちらは**実行ファイル**なので
  ブロックの出方が異なる可能性がある。要検証。
- CI ランナーは `macos-14`（Apple Silicon）。
- GitHub Actions の Artifacts は**二重 ZIP**になる。解凍して中身の ZIP を配布すること。
- ZIP は必ず `CAD_8_1_5_1` フォルダごと圧縮する（中身を直接圧縮しない）。

## 参考

- `E:\blender_addon\外部テスト\cross_platform_build_notes.md` — SDF.R の移植ノート
- `E:\blender_addon\外部テスト\GITHUB_ACTIONS_SETUP.md`
- `E:\blender_addon\外部テスト\build_sdf_addon.sh` — ビルドスクリプトの雛形
