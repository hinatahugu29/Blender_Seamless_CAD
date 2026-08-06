# Blender_CAD 8.1.5.1 — Linux 移植作業フォルダ

Windows 版 `Blender_CAD_V_8_1_5_1` から、**Windows 専用バイナリを除いて**複製した
Linux 用の作業フォルダ。SDF.R の `Rust-GPU-SDF-V16.1.0_LINUX` と同じ流儀。

## このフォルダに「無い」もの（意図的に外した）

- `*.dll` / `cad_server.exe` / `seamless_core.pyd` — Windows 専用。
  持ち込むと「ファイルはあるのに動かない」で必ず混乱するので、最初から入れない。
- `src_rust/target/` と `*.obj` — MSVC の中間生成物。
- `*.step` のテストデータ、各種 `.zip` / `.log`。

`CAD_8_1_5_1/bin/` は**空のまま置いてある**。ここに Linux 版 `cad_server` が入る。

## 現状ステータス

| 項目 | 状態 |
|---|---|
| Python 側コード | Windows 版と同一。**未改修** |
| `src_rust/build.rs` | Windows 版と同一。**MSVC 決め打ちのまま。要改修** |
| `cad_server`（Linux 版バイナリ） | **未ビルド** |
| OCCT（Linux 版） | **未取得** |
| ビルドスクリプト | **未作成** |

つまり、**現時点でこのフォルダは動かない**。これは正常な状態。

## 必要な改修（着手前に必ず読む）

1. **`src_rust/build.rs`** — 現在 MSVC 前提でベタ書き。
   - `/std:c++17` `/utf-8` → Linux では `-std=c++17`
   - `occt_root` の `win64/vc14/lib` → Linux のライブラリパス
   - VS2022 の include パス群（15〜24 行目）は Linux では不要。`cfg!(target_os)` で分岐する。

2. **`CAD_8_1_5_1/core_bridge.py`** — 2 箇所。
   - `cad_server.exe` の決め打ち（578 行目付近）→ Linux では拡張子なし `cad_server`
   - `creationflags=subprocess.CREATE_NO_WINDOW`（599 行目付近）
     → **Windows 以外では AttributeError で即死する**。分岐必須。

3. **`package_addon.py`**
   - `REQUIRED_PATHS` の `cad_server.exe` → プラットフォーム別に。
   - **実行権限（+x）の保持**。素の `zipfile` は権限ビットを落とすため、
     このまま zip を作ると Linux で `Permission denied` になる。
     `ZipInfo.external_attr` に `0o755 << 16` を明示する必要がある。
     ※ SDF.R は `.so`（実行権限不要）だったのでこの罠を踏んでいない。**こちらは踏む。**

4. **OCCT ランタイムの同梱と `$ORIGIN`**
   - OCCT の `.so` を同梱し、rpath を `$ORIGIN` 基準にする
     （`cargo:rustc-link-arg=-Wl,-rpath,$ORIGIN/...`）。
     ビルドマシンの絶対パスが残っているとユーザー環境で起動しない。

5. **`CAD_8_1_5_1/license.txt`**
   - 現在 GPL-2.0-or-later のみ。OCCT は LGPL-2.1 なので、その全文の追加が必要。

## OCCT の入手方法（調査済み・2026-08-06 時点）

**公式サイト `dev.opencascade.org/release` のプリビルドは Windows 専用。**
Linux 向けはソースのみ。よって以下から選ぶ。

| 入手元 | バージョン | 判定 |
|---|---|---|
| **conda-forge `occt`** | **8.0.1 / 8.0.0**（linux-64 あり） | ◎ **採用候補** |
| Ubuntu 22.04 apt | 7.5.1 | ✗ **使用不可**（下記） |
| Ubuntu 24.04 apt | 7.6.3 | ✗ **使用不可**（下記） |
| ソースからビルド | 任意 | ○ 確実だが CI で 30〜40 分 |

**apt が使えない理由**：`build.rs` がリンクしている `TKDESTEP` は OCCT 7.8 で
導入された名前（それ以前は `TKSTEP`）。Ubuntu の apt が持つ 7.5 / 7.6 には存在せず、
リンクが通らない。glibc 対策で古い Ubuntu を選ぶ必要がある一方、apt の OCCT は
古すぎて使えない、という板挟みになる。

**conda-forge がこの板挟みを解く**。conda-forge の linux-64 ビルドは古い glibc
（2.17 相当）を前提にしているため、`ubuntu-22.04` ランナーとの相性がよく、
かつ 8.0.0 で Windows 版と版を揃えられる。

## Linux 固有の注意（SDF.R の実績から）

- **glibc**。最新ランナー（`ubuntu-latest` / `24.04`）でビルドすると
  `GLIBC_2.xx not found` で古い環境で起動しなくなる。**`ubuntu-22.04` を明示指定**すること。
  （廃止済みの `ubuntu-20.04` を指定すると割り当て待ちでフリーズする。）
- GitHub Actions の Artifacts は**二重 ZIP**になる。解凍して中身の ZIP を配布すること。
- ZIP は必ず `CAD_8_1_5_1` フォルダごと圧縮する（中身を直接圧縮しない）。

## 参考

- `E:\blender_addon\外部テスト\cross_platform_build_notes.md` — SDF.R の移植ノート
- `E:\blender_addon\外部テスト\GITHUB_ACTIONS_SETUP.md`
- `E:\blender_addon\外部テスト\build_sdf_addon.sh` — ビルドスクリプトの雛形
