# Project Seamless CAD

Blender の中でノンデストラクティブな CAD モデリングを行うアドオンです。
形状の計算は Blender のメッシュではなく **OpenCASCADE (OCCT)** が行い、
Blender 側にはその結果が GPU で描画されます。

プリミティブやブーリアン演算、フィレット・面取りは履歴（Feature Tree）として
保持され、後からいつでも数値を編集し直せます。ビューポート上のプロキシを
G / R / S で動かせば、形状がリアルタイムに追従します。

> **Beta**。Windows 専用です。詳しくは「制約」を参照してください。

---

## 動作環境

| | |
|---|---|
| OS | **Windows のみ**（`cad_server.exe` を同梱するため） |
| Blender | 4.2 以降（`bl_info`）。開発・動作確認は **5.1** |
| GPU | 内蔵 GPU（Intel Iris Xe 等）でも動作 |

## インストール

配布用 ZIP を Blender に読み込ませます。

1. `Blender_CAD_V_8_1_5_1/package_addon.py` を実行して ZIP を作る
   ```
   py Blender_CAD_V_8_1_5_1/package_addon.py
   ```
2. Blender の `Edit > Preferences > Add-ons > Install...` で、できた
   `CAD_<version>_install_<日付>.zip` を選ぶ
3. 有効化すると、3D ビューのサイドバー（N キー）に `Seamless` タブが出る

`package_addon.py` は ZIP を作る前に出荷前チェック（PREFLIGHT）を通します。
必須ファイルの有無、同梱ライブラリが実際に import できるか、全 `.py` の構文、
文字化けの混入、バージョンの整合を機械的に検査します。過去に
`libs/svgpathtools` と `libs/svgwrite` がディレクトリコピーで脱落し、SVG
インポートが10バージョン以上にわたり無言で壊れていた事故への対策です。

---

## ⚠️ clone しただけでは動きません

**このリポジトリにはビルド済みバイナリが含まれていません。**
幾何カーネル `cad_server.exe`、`seamless_core.dll`、OCCT の DLL 群、
同梱 `libs/numpy` はいずれも `.gitignore` で除外されています（合計 400MB 超）。

つまり clone 直後に `package_addon.py` を走らせても、PREFLIGHT が
`missing required path: cad_server.exe` で止まります。**先にカーネルを
ビルドする必要があります。**

### カーネルのビルド

必要なもの:

- Rust（`src_rust` は edition 2021）
- MSVC 2022 と Windows SDK
- **OpenCASCADE 8.0.0（vc14 / win64）**

`src_rust/build.rs` は現状これらの場所を**ハードコードしています**。
自分の環境に合わせて書き換えてください。

| 何 | build.rs が期待する場所 |
|---|---|
| OCCT | `../../occt-combined-release-no-pch/opencascade-8.0.0-vc14-64-combined/opencascade-8.0.0-vc14-64`（リポジトリルートからの相対） |
| MSVC | `C:/Program Files/Microsoft Visual Studio/2022/Community/VC/Tools/MSVC/14.44.35207/include` |
| Windows SDK | `C:/Program Files (x86)/Windows Kits/10/include/10.0.26100.0/{ucrt,um,shared}` |

ビルドと配置:

```
cd Blender_CAD_V_8_1_5_1/src_rust
cargo build --release
cd ..
py deploy.py          # cad_server.exe / seamless_core.dll を CAD_* へコピー
```

そのうえで `package_addon.py` を実行してください。

---

## 仕組み

```
Blender (Python アドオン)
      │  TCP
      ▼
cad_server.exe  ── Rust ──> OpenCASCADE (C++)
```

幾何演算は別プロセスの `cad_server.exe` が担当し、Blender とは TCP で
やり取りします。プロキシを動かすたびに**履歴全体**が送られ、サーバ側が
形状を組み直して返す方式です。この「毎回フル送信」のおかげで、
保存した `.blend` を開き直したときも、スタックを作り直すだけで
Feature Tree から形状が完全に復元されます。

ドラッグ中は重い OCC ブーリアンを避け、純 Rust の BSP CSG による
リアルタイムプレビューに切り替わります。

---

## 開発

### 回帰テスト

```
"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe" ^
    --background --factory-startup --python Blender_CAD_V_8_1_5_1/regression_test.py
```

終了コード 0 = 全パス、1 = 失敗あり。アドオンの有効化、プリミティブ追加、
アクティブ同期、削除同期、確定フェーズの契約、保存→再読み込みなどを検査します。

**ドラッグ追従・確定後の描画・WGPU Overlay OFF 時の挙動は自動化できません。**
ネイティブの変形モーダルと GPU 描画が必要なためです。これらを触ったときは
`Blender_CAD_V_8_1_5_1/DEPSGRAPH_STATE_MACHINE.md` §5 の手動チェックリスト
（C・D・H）を実機で通してください。

### 主要なドキュメント

| ファイル | 内容 |
|---|---|
| `Blender_CAD_V_8_1_5_1/DEPSGRAPH_STATE_MACHINE.md` | ドラッグ〜確定の状態機械マップ。フラグの意味、フェーズ構成、既知の注意点、回帰チェックリスト |
| `PERFORMANCE_ROADMAP.md` | 性能面の課題と方針 |
| `PROJECT_STATUS.md` | 実装済み機能の一覧と経緯 |

### リポジトリ構成

```
Blender_CAD_V_8_1_5_1/
  CAD_8_1_5_1/         アドオン本体（これが ZIP になる）
  src_rust/            幾何カーネル（Rust + C++/OCCT）
  package_addon.py     配布 ZIP のビルド（PREFLIGHT 付き）
  deploy.py            ビルドしたバイナリをアドオンへコピー
  regression_test.py   ヘッドレス回帰テスト
```

編集は `CAD_8_1_5_1/` に対して行います。ZIP は必ず `package_addon.py` で
作ってください（手作業のコピーが上記の脱落事故の原因でした）。

---

## 制約

- **Windows 専用。** macOS / Linux 版はありません
- **Beta。** 破壊的な変更が入る可能性があります
- ビルド環境のパスが `build.rs` にハードコードされています
- ライセンス未定（下記）

## ライセンス

**GPL-2.0-or-later**（`LICENSE` に全文）。Blender 本体と同じ条件です。

Blender アドオンは `bpy` を import する時点で Blender の派生物とみなされ、
GPL 互換ライセンスで配布する必要がある、というのが Blender Foundation の
立場です。バージョンを 2.0-or-later に揃えてあるのは、Blender 本体および
エコシステムとの互換性が最も高いためです。

同梱・依存する第三者ソフトウェアには、それぞれのライセンスが適用されます。
いずれも GPL と両立します。

| | ライセンス |
|---|---|
| OpenCASCADE 8.0.0 | LGPL-2.1（例外条項付き） |
| ezpz (KittyCAD) | MIT |
| numpy | BSD-3-Clause ほか |
| svgwrite / svgpathtools | MIT |
