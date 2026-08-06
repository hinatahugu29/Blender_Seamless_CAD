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
| `core_bridge.py` の OS 分岐 | **済**（実行ファイル名 / Popen フラグ / +x 復元） |
| `package_addon.py` の実行権限保持 | **済**（`SEAMLESS_TARGET_OS` で対象 OS を指定） |
| `src_rust/build.rs` の OS 分岐 | **済**（`OCCT_ROOT` 対応・rpath 設定込み） |
| `build_cad_addon.sh` | **済**（未実行・未検証） |
| GitHub Actions ワークフロー | **済**（未実行・未検証） |
| OCCT（macOS 版） | 未取得。CI が conda-forge から取る |
| `cad_server`（macOS 版バイナリ） | **未ビルド** |
| `license.txt` への OCCT ライセンス追加 | **未対応** |

コードの下準備は完了しているが、**実際のビルドはまだ一度も通していない**。
最初の CI 実行で `build.rs` の追加調整が発生する見込み（conda-forge の
ヘッダ配置やライブラリ名が公式 Windows 版と異なる可能性があるため）。

## 残っている作業

1. **OCCT ランタイムの同梱を実地で検証する**
   - `build_cad_addon.sh` が OCCT の `.dylib` を `bin/` に並べ、
     `@loader_path` 基準で解決させる。`install_name_tool` で install_name を `@rpath` 基準に書き換える処理は
     `build_cad_addon.sh` に入れてあるが、未検証。
   - CI のログで `otool -L` の出力を必ず確認すること。
     ビルドマシンの絶対パスが残っていると、ユーザー環境で起動しない。

2. **`CAD_8_1_5_1/license.txt` への OCCT ライセンス追加**
   - 現在 GPL-2.0-or-later のみ。OCCT は LGPL-2.1 なので全文の追加が必要。

3. **実機での動作確認**
   - ZIP が Blender に入るか / 有効化できるか / スケッチと押し出しが通るか。

### 対応済み（参考）

- `src_rust/build.rs` — MSVC フラグと VS2022 の include パスを `cfg!` 分岐に。
  OCCT の場所は `OCCT_ROOT` から取る。
- `CAD_8_1_5_1/core_bridge.py` — 実行ファイル名を `_SERVER_EXE_NAME` に集約。
  `CREATE_NO_WINDOW` は Windows 限定（他 OS では属性自体が無く AttributeError になる）。
  起動時に `+x` を補う保険も追加。
- `package_addon.py` — ZIP エントリに 0o755 / 0o644 を明示。

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


## CI（GitHub Actions）

`.github/workflows/build-cross-platform.yml` が macOS(`macos-14`) と
Linux(`ubuntu-22.04`) の両方をビルドし、ZIP を artifact として出す。

- 手動実行: Actions タブ > "Build cad_server for macOS and Linux" > Run workflow
- 自動実行: このフォルダ配下かワークフロー自体を push したとき
- OCCT は conda-forge から `occt=8.0.0` を micromamba で取得し、
  `OCCT_ROOT` として `build_cad_addon.sh` に渡している。

**Artifact は二重 ZIP になる**（GitHub の仕様）。一度解凍して、中の
`CAD_8.1.5.3_install.zip` を取り出してから配布すること。

## 参考

- `E:\blender_addon\外部テスト\cross_platform_build_notes.md` — SDF.R の移植ノート
- `E:\blender_addon\外部テスト\GITHUB_ACTIONS_SETUP.md`
- `E:\blender_addon\外部テスト\build_sdf_addon.sh` — ビルドスクリプトの雛形
