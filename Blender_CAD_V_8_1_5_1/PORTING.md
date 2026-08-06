# macOS / Linux 移植メモ

**ソースは1本です。**`Blender_CAD_V_8_1_5_1/` が唯一の正で、macOS 版・Linux 版も
このツリーからビルドします。プラットフォーム別の複製フォルダは作らないでください。

以前は `Blender_CAD_V_8_1_5_1_MAC` と `_LINUX` という複製を置いていましたが、
実測したところ Python アドオン（111ファイル）も Rust ソースも**3本すべて完全に
一致**しており、固有の内容はこのファイルと `build_cad_addon.sh` の2つだけでした。
約1800行を複製して2ファイルを運んでいる状態で、しかも Git は3本を無関係な
ファイルとして扱うため、片方だけ直しても誰も警告しません。
`libs/svgpathtools` と `libs/svgwrite` がディレクトリコピーで脱落し、SVG インポートが
10バージョン以上にわたり無言で壊れていた事故と同じ構造なので、1本に畳みました。

## なぜ1本で済むのか

**OS 分岐はすでにコードの中にあります。**

| 場所 | 分岐 |
|---|---|
| `CAD_8_1_5_1/core_bridge.py:37` | `_SERVER_EXE_NAME = "cad_server.exe" if sys.platform == "win32" else "cad_server"` |
| `CAD_8_1_5_1/core_bridge.py:47` | `Popen` のフラグ（`CREATE_NO_WINDOW` は Windows 限定。他 OS では属性自体が存在せず AttributeError になる） |
| `CAD_8_1_5_1/core_bridge.py:611` | 非 Windows では起動前に実行権限を補う |
| `src_rust/build.rs` | MSVC フラグと include パスを `cfg!` で分岐。OCCT の場所は `OCCT_ROOT` から取る |
| `package_addon.py` | `SEAMLESS_TARGET_OS=windows\|darwin\|linux` で対象を指定。ZIP エントリに 0o755 / 0o644 を明示 |

ツリーを分けなくても、環境変数と `uname` でビルド対象を切り替えられます。

## ビルド

### macOS / Linux

```bash
micromamba create -y -p ./occt-env -c conda-forge 'occt=8.0.0'
export OCCT_ROOT="$PWD/occt-env"
./build_cad_addon.sh
```

`build_cad_addon.sh` が `uname` で darwin / linux を判定し、カーネルのビルド →
`CAD_8_1_5_1/bin/` への配置 → OCCT ランタイムの同梱 → `package_addon.py` による
梱包まで通します。

### Windows

従来どおりです。

```
cd src_rust && cargo build --release
cd .. && py deploy.py
py package_addon.py
```

> **Windows 機で macOS / Linux 版を梱包しないでください。**`bin/` に Windows の
> `.exe` と `.dll` が残っているため、それらを巻き込んだ ZIP ができます。CI の
> チェックアウトはバイナリが `.gitignore` で除外されていて `bin/` が空なので、
> この問題は起きません。**macOS / Linux 版は CI でビルドしてください。**

## CI

`.github/workflows/build-cross-platform.yml` が `macos-14` と `ubuntu-22.04` の
両方で `build_cad_addon.sh` を走らせ、ZIP を artifact として出します。

- 手動実行: Actions タブ > "Build cad_server for macOS and Linux" > Run workflow
- OCCT は conda-forge から `occt=8.0.0` を micromamba で取得し、`OCCT_ROOT` として渡す

**artifact は二重 ZIP になります**（GitHub の仕様）。一度解凍して、中の
`CAD_<version>_install.zip` を取り出してから配布してください。二重のまま配ると
購入者側で構造エラーになります。

## OCCT の入手（調査済み・2026-08-06 時点）

**公式 `dev.opencascade.org/release` のプリビルドは Windows 専用です。**

| 入手元 | バージョン | 判定 |
|---|---|---|
| **conda-forge `occt`** | **8.0.0**（osx-arm64 / osx-64 / linux-64） | ◎ **採用** |
| Homebrew `opencascade` | 7.9.3 | △ 版が揃わない |
| Ubuntu 22.04 apt | 7.5.1 | ✗ 使用不可 |
| Ubuntu 24.04 apt | 7.6.3 | ✗ 使用不可 |

**apt が使えない理由:** `build.rs` がリンクする `TKDESTEP` は OCCT 7.8 で導入された
名前です（それ以前は `TKSTEP`）。apt の 7.5 / 7.6 には存在せずリンクが通りません。
glibc 対策で古い Ubuntu を選ぶ必要がある一方、apt の OCCT は古すぎて使えない、
という板挟みになります。

**conda-forge がこれを解きます。**linux-64 ビルドが古い glibc（2.17 相当）を前提に
しているため `ubuntu-22.04` と相性がよく、かつ 8.0.0 で Windows 版と版を揃えられます。
**3 OS すべてを 8.0.0 で統一できる**ので、「Mac だけフィレットの挙動が違う」類の
再現困難なバグを避けられます。

## プラットフォーム固有の注意

### macOS

- **Gatekeeper。**未署名バイナリはブロックされます。当面は**テスター配布**として、
  「システム設定 > プライバシーとセキュリティ > このまま開く」を案内する運用です。
  ドキュメントに正直に明記すること。将来的に Apple Developer 登録を行う方針。
  ※ SDF.R は `.so` のブロックでしたが、こちらは**実行ファイル**なのでブロックの
  出方が異なる可能性があります。要検証
- conda-forge の dylib は install_name に絶対パスを持ちます。`build_cad_addon.sh` が
  `install_name_tool` で `@rpath` 基準に書き換えますが、**未検証**。CI のログで
  `otool -L` を必ず確認し、ビルドマシンの絶対パスが残っていないか見ること
- CI ランナーは `macos-14`（Apple Silicon）。Intel Mac 向けが要るなら `macos-13` を追加

### Linux

- **glibc。**`ubuntu-latest` / `24.04` でビルドすると `GLIBC_2.xx not found` で古い環境
  で起動しなくなります。**`ubuntu-22.04` を明示指定**すること。廃止済みの
  `ubuntu-20.04` を指定すると割り当て待ちでフリーズします
- rpath は `build.rs` が `$ORIGIN` 基準に設定済みですが**未検証**。CI のログで `ldd` に
  `not found` が無いか確認すること
- **libstdc++ を同梱すること**（実測で必要と判明）。詳細は下記

#### libstdc++ の同梱が必要な理由（2026-08-06 の CI 失敗より）

最初の Linux ビルドはこれで落ちました。

```
libTKCDF.so.8.0: version `CXXABI_1.3.15' not found
    (required by .../bin/libTKCDF.so.8.0)
```

**conda-forge の OCCT 8.0.0 は GCC 14 世代でビルドされており、`CXXABI_1.3.15` を
要求します。**`ubuntu-22.04` のシステム libstdc++ は GCC 12 世代で `1.3.13` までしか
持ちません。

これは glibc の板挟みの一段深いところにある同種の問題です。**ランナーを上げても
解決しません**——`ubuntu-24.04` は GCC 13（`1.3.14`）で依然届かず、しかも glibc の要求
バージョンが上がって古いユーザー環境で動かなくなり、逆効果です。

**解は libstdc++ 側を conda から同梱すること**です。`build_cad_addon.sh` が
`libstdc++.so.6` と `libgcc_s.so.1` を `bin/` へコピーします。

- glibc と違い **libstdc++ は後方互換**なので、新しいものを持ち込む分には安全です
- `cad_server` は Blender に `dlopen` される `.so` ではなく**独立したプロセス**なので、
  Blender 本体や他のライブラリのランタイムを侵しません
- rpath が `$ORIGIN` なので、隣に置けば解決されます

**OCCT のバージョンを上げるときは、この要求も上がる可能性があります。**`ldd` の出力を
必ず確認してください。

## 残っている作業

1. **OCCT ランタイム同梱の実地検証**（上記の `otool -L` / `ldd` 確認）
2. **`CAD_8_1_5_1/license.txt` への OCCT ライセンス追加** — 現在 GPL-2.0-or-later のみ
3. **実機での動作確認** — ZIP が Blender に入るか、有効化できるか、スケッチと押し出しが通るか

コードの下準備は完了していますが、**ビルドはまだ一度も通っていません。**

## 参考

- `E:\blender_addon\外部テスト\cross_platform_build_notes.md` — SDF.R の移植ノート
- `E:\blender_addon\外部テスト\GITHUB_ACTIONS_SETUP.md`
