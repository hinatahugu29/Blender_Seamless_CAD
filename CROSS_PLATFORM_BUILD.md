# macOS / Linux 対応 — 仕組みと手順

Seamless CAD を Windows 以外でビルド・配布するための開発者向け文書。
2026-08-08〜09 に実際に移植して得た結果をまとめたもので、推測は含めていない。
確かめていないことは「未検証」と明記してある。

対象読者は自分（と将来の自分）。ユーザー向けの記述は `docs/` 側にある。

---

## 1. 現在地

| プラットフォーム | 状態 | ビルド場所 | ZIP |
|---|---|---|---|
| Windows x64 | 出荷中 | 手元（MSVC + 同梱 OCCT ドロップ） | 45.9 MB |
| Linux x64 | CI で完走 | GitHub Actions `ubuntu-22.04` | 26.9 MB |
| macOS arm64 | CI で完走 | GitHub Actions `macos-14` | 20.5 MB |
| macOS x64 (Intel) | 対象外 | — | — |

「完走」の意味は、**ビルド → OCCT ライブラリ同梱 → カーネルを実際に起動して
TCP 8080 に応答することを確認 → PREFLIGHT → ZIP 生成**まで通ったということ。

**まだ配布はしていない。** macOS は署名・公証が無い。CI 成果物があることと、
出荷できることは別。

**実機の状況（2026-08-18）:** テスターの方から数件、macOS / Linux ともに
「動いた」という報告を受けている。いずれも肯定的。ただし**どこまで触ったかは
不明**で、検証の深さは測れていない。0か1かで言えば1寄りだが、程度が分からない。
**これをもって「動作確認済み」と書かないこと。**分かったのは「そもそも起動しない」
という最悪の場合が消えたことで、どの機能が動くかは依然として未検証。

Linux / macOS の ZIP が Windows より小さいのは、Windows が OCCT の DLL を
約120個そのまま同梱しているのに対し、CI 側は依存を辿って実際に要るものだけを
入れているため。機能差ではない。

---

## 2. なぜ移植が軽く済んだのか

**幾何カーネルが別プロセスだから。** `cad_server` は TCP 8080 で待ち受ける
独立した実行ファイルで、Python 側はネイティブコードを一切 import しない。
Python↔ネイティブの ABI 境界が存在しないので、Blender の Python バージョンや
ビルド構成に縛られない。

**C++ が最初から移植可能だったから。** `occ_*.cpp` に `#ifdef _WIN32` は1つも
無く、純粋な OCCT API しか使っていない。実際に非互換だったのは後述の1件だけ。

移植で本当に手間なのは、コードではなく **OCCT のビルドと、共有ライブラリの
同梱・探索パス**の部分だった。

---

## 3. ビルド手順

### 3.0 OCCT の版（2026-08-11 に 8.0.0 → 8.0.1）

3プラットフォームで**必ず同じ版に揃える**。ずれると、Windows でしか出ない
（あるいは Windows でだけ出ない）不具合の切り分けが原理的にできなくなる。
揃える先は2箇所:

- Windows: `build.rs` の `occt_root()` 既定値と `compile*.bat` の `-I`
- Linux / macOS: `build-kernel.yml` の `OCCT_TAG` と、その直後の版検証 grep

8.0.1 に上げた理由は、こちらのコード変更なしに直る不具合が3つあったため:

| 修正 | 効く場所 |
|---|---|
| Boolean の section で無限ループ | `BRepAlgoAPI_Cut/Fuse/Common` — ハングなので実害が一番大きい |
| `BRepFill_CompatibleWires` のイテレータ過進行 | `BRepOffsetAPI_ThruSections`（Loft）。断面の頂点数が食い違うとクラッシュしていた |
| `BRepExtrema_DistanceSS` の null 参照 | `BRepExtrema_DistShapeShape`（計測・スナップ） |

同時に BRepGraph（8.0 のトポロジ土台）が広く作り替えられている。API は
変わらないのでビルドは通るが、**挙動の回帰はここから出る**と思って検証する。

8.0.0 のドロップは `occt-combined-release-no-pch/` にそのまま残してある。
戻すのは上記2箇所を書き戻して再ビルドするだけ。

### 3.1 Windows（手元）

従来どおり。変更なし。

```bash
cd Blender_CAD_V_8_1_5_1/src_rust && cargo build --release
cd .. && py deploy.py
py package_addon.py
```

`build.rs` は `OCCT_ROOT` が未設定なら、これまでどおりリポジトリ同梱の
`occt-combined-release-no-pch_801/.../opencascade-8.0.1-vc14-64` を相対パスで見る。
`package_addon.py` の `--platform` は既定でホスト（Windows）になり、
出力名も従来の `CAD_<version>_install.zip` のまま。**既存の運用は何も変わらない。**

ビルド前に既存バイナリを退避すること（`*.exe` `*.dll` は `.gitignore` 対象）。

### 3.2 Linux / macOS（GitHub Actions）

実機が無く、OCCT と wgpu はクロスコンパイルが現実的でないため、
**ランナーがビルド環境そのもの**。

- ワークフロー: [.github/workflows/build-kernel.yml](.github/workflows/build-kernel.yml)
- 同梱スクリプト: [.github/scripts/bundle_kernel.sh](.github/scripts/bundle_kernel.sh)
- トリガー: `workflow_dispatch`、または `port/**` ブランチへの push
- 成果物: run の Artifacts に `CAD-linux-x64` / `CAD-macos-arm64`

サードパーティ製 action は使っていない（`actions/*` のみ）。配布物になる
バイナリを作る以上、CI に持ち込む依存は少ない方がよい。

ステップの並びと、それぞれが何を守っているか:

| # | ステップ | 目的 |
|---|---|---|
| 1 | checkout | — |
| 2-3 | 依存インストール | Linux は `patchelf` を含む（後述） |
| 4 | OCCT を restore | `cache/restore`。`cache` 一体型ではない（後述） |
| 5 | OCCT をソースビルド | キャッシュミス時のみ。初回30〜60分 |
| 6 | OCCT を検証 | 掴んだ版が 8.0.1 か。壊れたキャッシュを焼き付けない |
| 7 | OCCT を save | 検証を通ってから保存 |
| 8 | カーネルをビルド | `OCCT_ROOT` を渡して `cargo build --release` |
| 9 | 同梱 | `bundle_kernel.sh` |
| 10 | **スモークテスト** | 起動して 8080 に応答するか。同梱漏れの唯一の検出手段 |
| 11-12 | setup-python + numpy | PREFLIGHT が同梱ライブラリを実 import するため |
| 13 | パッケージ | `package_addon.py --platform` |
| 14 | artifact upload | — |

#### OCCT のビルド設定

タグ `V8_0_1`（同梱 Windows 版の `Standard_Version.hxx` が 8.0.1 なので合わせた）。

```
-DCMAKE_BUILD_TYPE=Release
-DBUILD_LIBRARY_TYPE=Shared
-DBUILD_MODULE_Draw=OFF
-DBUILD_DOC_Overview=OFF
-DINSTALL_DIR_LAYOUT=Unix
```

`BUILD_MODULE_Visualization` は **切っていない**。`TKDESTEP` が
ApplicationFramework 側に依存しており、モジュールを削ると configure 段階で
崩れる懸念があったため、確実に通る構成を選んだ。使わないライブラリは
同梱段階で自然に落ちるので、成果物には影響しない。

`ubuntu-22.04` を使うのは意図的。**glibc は前方互換しかない**ので、新しい
ランナーでビルドすると古いディストリで動かない。

---

## 4. コード側の分岐点（全部）

Windows 依存は5ファイルに閉じている。増やさないこと。

### `src_rust/build.rs`

- [`occt_root()`](Blender_CAD_V_8_1_5_1/src_rust/build.rs:20) — `OCCT_ROOT` 環境変数が最優先。未設定なら同梱の相対パス
- [`find_subdir()`](Blender_CAD_V_8_1_5_1/src_rust/build.rs:33) — include/lib の階層を**探索**する。
  Windows ドロップは `inc` / `win64/vc14/lib`、cmake の Unix レイアウトは
  `include/opencascade` / `lib`。決め打ちすると「ヘッダが無い」という遠い場所の
  コンパイルエラーになって原因を追いにくい
- コンパイラフラグ: MSVC は `/std:c++17 /utf-8`、それ以外は
  `-std=c++17 -DOCC_CONVERT_SIGNALS`
- **`-DOCC_CONVERT_SIGNALS` は Unix 側の生命線。** OCCT の
  `Standard_ErrorHandler.hxx` は、これが定義されていなければ
  `OCC_CATCH_SIGNALS` を**空に展開する**。8.1.5.10 まで付けていなかったため、
  コード中の13箇所は Linux / macOS では1つも存在せず、OCCT 内部のフォールトが
  そのままカーネルを殺していた。Windows は MSVC が SE translator から直接
  C++ 例外を投げるので不要（ヘッダにもそう書いてある）。詳細は §7
- MSVC / Windows SDK の include パスは Windows でのみ渡す
- [Unix の rpath](Blender_CAD_V_8_1_5_1/src_rust/build.rs:114) — `$ORIGIN`（macOS は `@loader_path`）

### `src_rust/src/main.rs`

- [`watch_parent_and_exit`](Blender_CAD_V_8_1_5_1/src_rust/src/main.rs:696) の Windows 版（`OpenProcess` / `WaitForSingleObject`）
- [同 Unix 版](Blender_CAD_V_8_1_5_1/src_rust/src/main.rs:731)

Unix 版は **`kill(pid, 0)` だけでは不十分**。Blender が終了しても、その親が
回収するまでゾンビとして残り、`kill` は成功し続ける。`cad_server` は Blender の
直接の子なので、親の終了で init/launchd に再親付けされる → `getppid()` の変化で
判定できる。両方見ている。

これを落とすと、Blender がクラッシュしたときにサーバーが孤児化してポート 8080 を
掴み続け、次のセッションが古い形状を描く。Windows 版がまさにその不具合のために
書かれたもので、Unix でだけ再発させる意味はない。

### `CAD_8_1_5_1/core_bridge.py`

- [`_IS_WINDOWS` / `_SERVER_EXE_NAME` / `_POPEN_PLATFORM_KWARGS`](Blender_CAD_V_8_1_5_1/CAD_8_1_5_1/core_bridge.py:33)
- `subprocess.CREATE_NO_WINDOW` は **Windows 専用属性で、他 OS では参照した瞬間に
  `AttributeError`**。フラグを渡さないだけでは足りず、属性アクセス自体を避ける必要がある
- [実行ビットの復元](Blender_CAD_V_8_1_5_1/CAD_8_1_5_1/core_bridge.py:607) — ZIP はパーミッションを保存しない。
  Blender のインストーラ経由で展開されたカーネルは実行ビットを持たないので、起動前に付ける

### `package_addon.py`

- [`PLATFORMS`](Blender_CAD_V_8_1_5_1/package_addon.py:65) — カーネル名と ZIP のサフィックス。
  **Windows のサフィックスが空なのは意図的**で、購入者とドキュメントが参照している
  `CAD_<version>_install.zip` を変えないため
- [`required_paths()`](Blender_CAD_V_8_1_5_1/package_addon.py:80) — PREFLIGHT の必須ファイルにカーネルを足す
- [実行ビット付きで ZIP に書く](Blender_CAD_V_8_1_5_1/package_addon.py:334) — `0o755`。
  Windows 上で macOS/Linux 向け ZIP を作る場合に効く

### `deploy.py`

カーネル名と共有ライブラリ名（`.dll` / `.so` / `.dylib`）の分岐、Unix では chmod。

---

## 5. 共有ライブラリの同梱 — 3つの OS で成立の仕組みが違う

配置の方針は同じ（**カーネルと同じディレクトリに置く**）だが、
「なぜ見つかるのか」は3者3様で、ここが移植で一番はまった。

### Windows

exe と同じフォルダの DLL を自動で拾う。何もしなくてよい。

> `av*.dll`（FFmpeg）を外してはいけない。見た目は無関係だが `cad_server.exe` の
> ロード時依存で、抜くとカーネルが一切応答しない。

### macOS

OCCT は install name を `@rpath/libTK*.dylib` の形で持つ。これを
`install_name_tool -change` で **`@loader_path/...` に全部書き換える**。
書き換えてしまうので rpath の継承には依存しない。

**書き換えたら `codesign --force --sign -` で再署名すること。**
`install_name_tool` はバイナリを書き換えるため ad-hoc 署名が無効になり、
**Apple Silicon は署名不正の実行ファイルを起動時に SIGKILL する**。
再署名を忘れると「理由も出さずカーネルが死ぬ」という追いにくい失敗になる。

### Linux

**`DT_RUNPATH` は推移的に効かない。** リンカが既定で吐くのは RUNPATH で、
これはそのバイナリの**直接の依存にしか使われず、推移的な依存には引き継がれない**。

`build.rs` が `cad_server` に付けた `$ORIGIN` は、
`TKBO` → `TKBRep` → `TKMath` という連鎖には届かない。各ライブラリは自分の rpath で
相手を探し、OCCT が焼き込んだ rpath はビルドマシンの prefix を指しているので、
配布先では全滅する。

→ **`patchelf --set-rpath '$ORIGIN'` を、同梱する全ファイルに当てる。**
`cad_server` だけでは意味がない。

症状は「ライブラリは全部隣にあるのに、`libTKernel.so.8.0` を含む全部が
not found」という形で出る。

### 同梱対象は「OS 付属でない絶対パス」全部

OCCT の prefix 由来だけを同梱対象にしてはいけない。macOS の `TKService` /
`TKV3d` は **Homebrew の freetype** を参照しており、この連鎖は避けられない:

```
cad_server → TKDESTEP → TKXCAF → TKV3d → TKService → libfreetype
```

STEP を触れば必ず読まれる。`/opt/homebrew` はユーザーの Mac に存在しないので、
そのまま配ると起動しない。

OCCT の Visualization モジュールを切れば依存ごと消えるが、上の連鎖のとおり
`TKDESTEP` が `TKXCAF` 経由で `TKV3d` に依存しているため **STEP が壊れる**。
切るのではなく同梱するのが正解。

規則は「`/usr/lib` と `/System` 以外の絶対パスは出所を問わず同梱」。
freetype 自身の依存連鎖（libpng / brotli 等）も再帰で拾える。

### 検証は配布先と同じ条件で

依存を辿る間は `LD_LIBRARY_PATH` を OCCT の prefix に向けている。この状態のまま
検証すると、**まだコピーしていないライブラリまで解決できてしまい、漏れが漏れとして
見えない。** 実際にこれで `libTKG2d.so.8.0` の欠落を CI が素通しした。

最後の確認は `LD_LIBRARY_PATH` を外して行う。prefix が存在せず `$ORIGIN` だけが
頼りという、ユーザーの環境と同じ条件になる。

macOS 側も同じ趣旨で、`install_name` に `@loader_path` / `/usr/lib` / `/System`
以外が残っていないかを確認する。**スモークテストではこれを検出できない** —
ランナーには Homebrew が入っているので、参照先が実在してしまい起動する。

> **一般則**: ビルドマシンには、配布先に無いものが入っている。
> 検証は必ず「無い側」の条件を作って行うこと。この文書に出てくる同梱の失敗は
> 3件とも、この一点を守らなかったことが原因だった。

---

## 6. 検証の関門

同梱漏れは**実行するまで表に出ない**。人間の目視では捕まらないので、機械的な
関門を4段構えにしてある。

1. **未解決チェック**（Linux、`bundle_kernel.sh`）
   `LD_LIBRARY_PATH` 無しで `ldd` して "not found" が残っていないか。
   残っていれば soname を頼りに prefix から補い、補えなければ失敗させる
2. **`libTKernel` の存在確認**（`bundle_kernel.sh` 末尾）
   1つも同梱できていないのに成功扱いで進むのが一番まずい
3. **スモークテスト**（ワークフロー）
   カーネルを実際に起動し、20秒以内に TCP 8080 へ応答するか。
   Windows で `av*.dll` を外したときの「一切応答しない」を捕まえるための関門

4. **install_name の残留チェック**（macOS、`bundle_kernel.sh`）
   `@loader_path` / `/usr/lib` / `/System` 以外が残っていたら失敗させる。
   スモークテストでは検出できない種類の欠陥を捕まえるための関門

さらにパッケージ段階で `package_addon.py` の PREFLIGHT が走る。同梱ライブラリを
**実際に import して**確かめる検査で、8.1.2.5 の `svgpathtools` 脱落
（SVG インポートが10バージョン以上にわたり無言で壊れていた）の再発を止めている。
CI を通すためにこれを緩めてはいけない。numpy が無くて落ちたときも、検査ではなく
CI 側の環境を Blender に合わせて直した。

### 手元で Linux を動かす（WSL）

CI は1周 3〜40分かかる。**Unix でしか出ない不具合を追うときは、手元に Linux が
無いこと自体が最大の障害**になる（2026-09-05 の Face Inset クラッシュでは、
利用者に何度も試してもらう以外に確かめる手段が無かった）。WSL2 を入れると
同じ検証が数秒で回る。

```powershell
wsl --install -d Ubuntu     # 管理者 PowerShell。再起動が要る
```

```bash
bash tools/wsl/setup.sh                                        # 一度だけ
bash tools/wsl/verify_linux_build.sh ../MAC_LINUX/CAD_8.1.5.11_install_LINUX.zip
```

`verify_linux_build.sh` が見るもの:

- `bl_info` とカーネルのサイズ（版の取り違えの検出）
- `LD_LIBRARY_PATH` **無し**での `ldd`（"not found" が残っていないか）
- `libs/svgpathtools` と `libs/svgwrite` の同梱
- `tools/replay_kernel_requests.py` の再生（カーネルが生き残るか）

CI との違いは、**配布する ZIP そのものを展開して動かす**点。CI はビルドツリーの
カーネルを叩くので、ZIP に詰める過程で壊れた場合を見られない。

Blender を渡せば、回帰テスト52件を**Linux のカーネルで**回せる。
これは現時点で一度も実施していない（§8）。

```bash
bash tools/wsl/verify_linux_build.sh <zip> --download-blender       # 既定 5.2 系の最新
bash tools/wsl/verify_linux_build.sh <zip> --download-blender 5.1.2 # 版を指定
bash tools/wsl/verify_linux_build.sh <zip> --blender /path/to/blender
```

`--download-blender` は blender.org の公式アーカイブからのみ取得し、
**同じ場所が公開している `blender-<版>.sha256` と必ず照合する**（検証用に
落としたものを検証せずに使っては意味が無い。後で「Blender が壊れていたのか
こちらのカーネルが壊れていたのか」を切り分けられなくなる）。約 300MB を
`~/.cache/seamless-cad/blender` に置き、2回目以降は再取得しない。

既定を 5.2 系にしてあるのは、**利用者の報告がこの系列で来ているから**。
手元の Windows は Steam の 5.1.2 で、そこと揃えることに意味は無い。

**WSL2 の GPU は実機の Mesa と同じではない。** 描画まわりの検証には使えない。
カーネル（`cad_server`）の検証には十分で、これまでの不具合はすべてそこだった。

---

## 7. 実際に踏んだ罠

移植そのものより、ここで時間を使った。同じ穴に落ちないための記録。

### C++

`occ_modifiers.cpp` の[二段階名前解決](Blender_CAD_V_8_1_5_1/src_rust/src/occ_modifiers.cpp:399)。
テンプレート関数が、70行下で定義される関数を呼んでいた。Clang / GCC は非依存名を
テンプレート**定義時点**で解決する。ヘルパーは `occ_core` 名前空間にあり、引数の
OCCT ビルダー型の関連名前空間はグローバルなので ADL でも見つからない。
MSVC だけが後方の定義を拾うため、Windows でしか成り立っていなかった。

前方宣言1つで解決。並べ替えも挙動変更も不要。

手元に Clang / GCC が無いのでこの種は CI 往復でしか潰せない。テンプレート本体から
後方定義の関数を呼ぶ箇所を機械的に走査したところ、検出はこの1件だけだった。

#### `OCC_CATCH_SIGNALS` が Unix では丸ごと消えていた（2026-09-06）

**移植で一番高くついた罠。** 利用者から Linux でカーネルが落ちる報告が来て、
版を跨いで3回追いかけた。

`OCC_CATCH_SIGNALS` は OCCT が用意しているフォールト捕捉の入口で、この
コードベースには13箇所ある。ところが `Standard_ErrorHandler.hxx` の定義は:

```c
#if defined(OCC_CONVERT_SIGNALS)
  #define OCC_CATCH_SIGNALS Standard_ErrorHandler _aHandler;     if (setjmp(_aHandler.Label())) { _aHandler.Raise(); }
#else
  #define OCC_CATCH_SIGNALS
#endif
```

`OCC_CONVERT_SIGNALS` を渡していなかったので、**Linux / macOS では13箇所すべてが
空文字列**だった。`OSD::SetSignal`（8.1.5.9 で追加）はフォールトを例外に変換
できていたが、飛び先が存在しないため
`*** Abort *** an exception was raised, but no catch was found.` でプロセスごと死ぬ。
囲ってある `try/catch` も無力で、**Unix では C のシグナルハンドラから C++ 例外を
投げられない**ため、この longjmp 経路が唯一の手段になる。

Windows は MSVC が SE translator から直接投げるので、この定義なしで成立していた。
つまり**「Windows でだけ例外処理が効いている」**状態が、移植の当初から続いていた。

追い方も記録しておく。症状が出るのは Linux/macOS だけで、手元では一切再現しない。
`tools/record_face_inset_sweep.py`（Windows で本物のリクエストを録音）と
`tools/replay_kernel_requests.py`（Blender 無しでカーネルへ再生）を作って CI に
組み込み、`[MOD_TRACE]` のログを足しては CI を回して、ログが途切れる場所を
詰めた。OCCT がキャッシュ済みなら1周3分で、この方法なら実機なしでも追える。

### CI

- **`actions/cache` はジョブが失敗するとキャッシュを保存しない。**
  `cache/restore` + `cache/save` に分け、OCCT の検証直後に保存すること。
  分ける前に 30〜60 分のビルドを2回捨てた
- **`set -euo pipefail` の下で `grep` が空振りすると、出力ゼロで exit 1。**
  原因が何も残らず切り分けができない。`|| true` を付けるか、この形を避ける
- **macOS ランナーの `/bin/bash` は 3.2。** 配列や `${arr[@]}` に頼らない。
  `bundle_kernel.sh` が worklist ではなく「増えなくなるまで走査を繰り返す」
  形になっているのはこのため
- **macOS ランナーの python3 は Homebrew 管理で、PEP 668 により pip を拒む。**
  `--break-system-packages`（エラー文自身が Homebrew を壊しうると警告している）
  ではなく `actions/setup-python` を挟む
- **未認証の GitHub API は 60回/時。** ポーリングは5分以上空ける。
  超えるとエラー応答が返り、それを「完了」と誤読する作りだと嘘の結果を出す
- **`macos-13`（Intel）はランナーの順番が回ってこない。** 30分以上待って着手すら
  しなかった。GitHub が縮小中

---

## 8. 残っている壁

コードではない。2026-08-02 時点の評価と変わっていない。

1. **macOS の署名・公証** — Apple Developer Program（年 $99）が未加入。
   CI 内の ad-hoc 署名は動作確認には足りるが、配布物は Gatekeeper に止められる。
   **これが macOS リリースの最大の障壁で、コードではない**
2. **Metal での実描画** — `renderer.rs` は `wgpu::Backends::PRIMARY` なので
   Metal / Vulkan は自動選択されるが、**カーネルが応答することと、wgpu が正しく
   描くことは別問題**。CI では原理的に確認できず、実機が要る
3. **Blender 上での実動作確認** — 一部は壁でなくなった。2026-09-06、WSL2 の
   Ubuntu 26.04 + Blender 5.2.1 で、**配布 ZIP の Linux カーネルに対して
   回帰テストを初めて走らせた: 52 passed（3回連続）**（`tools/wsl/`）。
   幾何・測定・STEP/IGES/STL 書き出し・スケッチソルバ・保存再読込は、
   Linux のカーネルでも Windows と同じ結果を返す。

   残るのは3つ。**C/D/H（ドラッグ追従・確定後の固まり・WGPU Overlay OFF）は
   そもそもヘッドレスでは検証できない**。**macOS は依然として1件も走らせて
   いない**（Apple Silicon の実機が無い。CI はカーネルの生死しか見ない）。
   そして **undo（チェックリスト I）は Linux で飛ばしている** — 下記 6
4. **Linux の動作要件** — 成果物を実測した下限は **glibc 2.34 / GLIBCXX 3.4.30
   / CXXABI 1.3.9**。Ubuntu 22.04、Debian 12、RHEL 9 以降に相当する。
   ホスト任せの依存は `libc` `libstdc++` `libgcc_s` `libm` `ld-linux` `libX11`
   `libfontconfig` `libfreetype` で、いずれも Blender 自身が要求するもの。
   下限を下げたいなら `libstdc++` の同梱が候補になる（カーネルは別プロセスなので
   Blender 側との衝突は起きない）。未検証
5. **Linux の undo（再現しなくなった／原因不明のまま）** —
   2026-09-06 の調査中、バックグラウンドの `ed.undo()` で Blender ごと落ちるのを
   何度か見た。掴んだトレースは

   ```
   _bpy_types.py users_collection
   utils.py _find_proxy_cad_collection
   utils.py depsgraph_update_handler
   ```

   で、`depsgraph.updates` が渡す ID をそのまま `users_collection`
   （`bpy.data.collections` を総なめする）に通すのは危険なので、**名前で
   `bpy.data` から引き直す形に直した**（8.1.5.11 以降）。

   **その後は一度も再現していない。** 実測: 素の版で 20/20 生存、undo 検査を
   単独で 5/5、**フルスイートで 52/52 を3回連続**（undo を実際に走らせて）。
   修正版と素の版で発生率に差は出なかったので、**直したのは危険な触り方で
   あって、クラッシュの原因ではない**。

   検証した仮説と、その結末:

   | 仮説 | 結果 |
   |---|---|
   | ハンドラが原因 | 無効化しても 20/20。**1回の観測で「確定」と書いたのは誤り** |
   | `users_collection` が原因 | 触らない版も 20/20 |
   | `undo_pre`/`undo_post` で止めれば防げる | 効かない（問題の更新は `undo_post` の**後**に来る） |
   | 古い `cad_server` が 8080 に残っていると落ちる | 残した状態でも 5/5。**外れ** |

   落ちたのは、Blender とカーネルを何重にも走らせていた時だけ。**Linux で
   落ちる条件は分かっていない。** 回帰テストでは飛ばさず、走らせている
   （再現しないものを飛ばしても検出力を落とすだけ）。ここが Linux で落ちたら
   本物の手がかりなので、その時は上の表から先へ進めること。次の一手は
   valgrind（配布 Blender はシンボルが無いので、こちらのハンドラに足跡を
   打って突き合わせる）。

   ---

   **条件が分かった（2026-09-14）。変数は Blender の版だった。**

   WSL2 / Ubuntu、同じ ZIP・同じカーネルで、Blender の版だけを変えて実測:

   | Blender | 結果 |
   |---|---|
   | **5.1.1** | `one undo = one step` で **必ず** abort（`terminate called after throwing an instance of 'std::bad_optional_access'`）。6/6 |
   | **5.2.1 LTS** | **59 passed / 0 failed / 0 skipped**。完走 |

   **アドオンの版とは無関係。** 8.1.5.15 の配布 ZIP を 8.1.5.15 当時の
   `regression_test.py`（こちらの変更が1行も入っていないもの）で回しても、
   5.1.1 では 2/2 で落ちる。つまり 8.1.5.16 が持ち込んだ回帰ではなく、
   **5.1.1 で前から落ちていたのを、誰も Linux で走らせていなかったから
   見えていなかった**だけ。

   Python のトレースは出ない。Blender が C++ 側で abort するので、
   `bpy.ops.ed.undo()` のアサートまで到達しない。

   ---

   **「5.2 なら安全」は 2026-10-31 に崩れた。5.2.3 でも 5.2.1 でも落ちる。**

   8.1.5.22 を配る前に Linux を確かめたところ、`one undo = one step` で
   同じ `std::bad_optional_access` が出た。そこで**版の総当たり**を取った
   （WSL2 / Ubuntu、ZIP を展開して実行、同じ `regression_test.py`）。

   | Python | カーネル | Blender | 結果 |
   |---|---|---|---|
   | 8.1.5.22 | 8.1.5.22 | 5.2.1 | abort |
   | 8.1.5.22 | 8.1.5.22 | 5.2.3 | **1回 完走 (62 passed) / 6回 abort** |
   | 8.1.5.16 | 8.1.5.16 | 5.2.3 | **1回 完走 (59 passed) / 6回 abort** |
   | 8.1.5.22 | 8.1.5.16 | 5.2.3 | 完走 |
   | 8.1.5.16 | 8.1.5.22 | 5.2.3 | abort |

   **発生率が新旧で完全に一致した（どちらも 1/7 で完走）。** 8.1.5.18〜8.1.5.21
   で入れた変更（スナップ・投影・Split）は**無関係**。カーネルを入れ替えても
   結果が反転しないので、カーネルでもない。

   **2026-09-14 の「変数は Blender の版だった」は誤りだった。** あのとき
   5.2.1 が 59 passed で完走したのは、**たまたま引いた 1/7 の側**だったと
   考えるほうが、今日の数字と整合する。1回の観測で条件を断定したのは、
   §8-5 の上のほうで一度やった失敗（「ハンドラが原因」）と同じ型。

   **連続で回すとほぼ必ず落ちる。** 交互に5回ずつ、WSL を落としてからの
   1回ずつ、いずれも 10/10・2/2 で abort した。**再現しないという前提は
   もう成り立たない**ので、valgrind まで進める条件は揃っている。

   **原因を `sync_proxies` まで絞った（2026-10-31）。**

   再現が狙って作れるようになったので、条件を削って詰めた。使ったのは
   `regression_test.py` の関数を選んで順に呼ぶドライバ（単体スクリプトでは
   再現しない。**スイートの先頭3本のうち `t_add_primitives` が要る**）。

   | 流す順番 | 結果 |
   |---|---|
   | register → prims → undo | abort 3/3 |
   | register → kernel → undo（prims を外す） | 完走 3/3 |
   | register → prims → **depsgraph ハンドラを外す** → undo | **完走 3/3** |
   | register → prims → undo_post ハンドラを外す → undo | abort 3/3 |
   | register → prims → `sync_proxies` を無効化 → undo | **完走 3/3** |
   | 同上で `_handle_settle` / `_handle_nonmodal_sync` / `_handle_modal_drag` / `update_parenting` を無効化 | いずれも abort 3/3 |

   **`sync_proxies` だけが効く。** undo の適用中に depsgraph ハンドラが走り、
   そこからプロキシの生成・削除で Blender のデータを書き換えるのが引き金。
   素の Blender（アドオン無し）と、import だけして register しない場合は
   どちらも 3/3 で完走するので、**Blender 単体の不具合ではない。**

   §8-5 の上の表にある「ハンドラが原因 → 無効化しても 20/20」は、
   **再現しない状態で数えた結果**だった。狙って再現できる今は逆の答えが出る。

   **修正を試して外した（2026-10-31）。絞り込みの読み方が間違っていた。**

   `sync_proxies` を無効化すると落ちない、という結果から「undo の最中に
   `sync_proxies` が走るのが引き金」と読んだが、**それは誤り**だった。
   `undo_pre` / `undo_post` にフックを置き、その間 `sync_proxies` を
   止める実装を入れたところ、**5/5 で落ちたまま**。

   そこで `sync_proxies` の呼び出し元を全部スタック付きで記録したところ、
   実際の並びはこうだった:

   ```
   [probe] sync_proxies  <- add_primitive (CYLINDER) の中、undo の前
   [probe] sync_proxies  <- depsgraph ハンドラ、これも undo の前
   [probe] undo_pre fired
   [probe] undo_post fired
   terminate called after throwing an instance of 'std::bad_optional_access'
   ```

   **undo の最中に `sync_proxies` は一度も呼ばれていない。** Python のフレームは
   どこにも無く、落ちているのは Blender が undo を畳み終えるところ。
   `sync_proxies` を無効化すると落ちなくなるのは、**undo より前に作られる
   プロキシのデータが違うものになるから**で、undo 中に何かをしているからではない。

   つまり犯人は「undo 中の書き換え」ではなく「`sync_proxies` が残すデータ」。
   `undo_pre`/`undo_post` で窓を切る方針は、この並びでは原理的に効かない。
   入れた変更は revert 済み（効かないガードを残すと、次の人が「対策済み」と
   読んでしまう）。

   **`sync_proxies` の中をさらに割った（2026-10-31）。改名が怪しいが、確定しない。**

   | 無効化したもの | 結果 |
   |---|---|
   | `_sync_proxy_mesh_geometry`（メッシュ差し替え） | abort 3/3 |
   | `bpy.data.objects.remove` を unlink だけに | abort 3/3 |
   | プロキシの改名を元に戻す（**prims の後**に仕掛ける） | **完走 3/3** |
   | プロキシの改名を元に戻す（**prims の前**に仕掛ける） | abort 3/3 |
   | 改名はさせるが名前を uuid 付きで一意にする | abort 3/3 |

   改名を潰すと落ちない組み合わせがある一方、**同じ細工を仕掛ける位置を
   変えるだけで結果が反転する**。つまりこのプローブは、測りたいものを
   自分で揺らしている。**「改名が原因」と書ける段階ではない。**

   分かったことだけ書くと:

   - プロキシの名前は `{index}_{type}_Seamless_Proxy` で、**Part を作り直すと
     消えたオブジェクトと同じ名前が再び使われる**（trace で確認）
   - その名前の状態をいじると、落ちるか落ちないかが変わる
   - メッシュの差し替えと ID 削除は、単独では効かない

   名前と ID の対応が undo の復元で食い違う、という筋は残っているが、
   **Python 側のプローブではこれ以上詰められない。** 次は gdb で
   `__cxa_throw` に止めて、どこから投げられているかを見るのが筋。
   WSL には gdb も valgrind も入っていないので、導入から。

   **gdb を入れて実際のスタックを取った（2026-10-31）。**

   WSL に gdb 17.1 を導入し、abort の瞬間で止めた。配布 Blender は
   シンボルが無いので関数名はほとんど出ないが、**出た部分が決定的**だった。

   ```
   #5  std::terminate()
   #6  __cxa_throw
   #7  blender 0x4d1065          <- RNA 側。ここが投げている
   #8  blender 0x567a7e
   #9  PyObject_GetAttr          <- Python の属性アクセス
   #10 _PyObject_GetMethod
   #11 _PyEval_EvalFrameDefault  <- Blender から呼ばれた Python
   ...
   #17 _PyObject_MakeTpCall      <- bpy.ops.ed.undo()
   #19 PyEval_EvalCode           <- こちらのスクリプト
   ```

   **落ちているのは「undo の最中に Blender が呼び出した Python が、RNA の
   属性を読んだ瞬間」。** RNA が `std::bad_optional_access` を投げ、Python の
   例外に変換されないまま terminate する。`catch throw` で止めた最初の
   throw と、abort 時のスタックが一致したので、途中で握り潰された別の
   throw ではない。

   **その Python が誰なのかは、まだ特定できていない。** 消去済み:

   | 候補 | 結果 |
   |---|---|
   | `update_active_cad_collection`（PointerProperty の update） | **外すと完走 3/3**。ただし計測すると、このコールバックが走るのは `ed.undo()` の**前**(Part 生成時)で、undo 中には呼ばれていない |
   | 同コールバックを「undo の窓の中だけ」素通りさせる | abort 5/5（窓に入らない＝undo 中に呼ばれていないことの裏付け） |
   | depsgraph ハンドラを undo 中だけ素通りさせる | abort 3/3 |
   | msgbus の購読を外す | abort 3/3 |
   | PointerProperty の poll を無害なものに差し替え | abort 3/3 |

   つまり **「外すと直る」ものと「undo 中に呼ばれている」ものが一致しない。**
   外して直るコールバックは、undo より前に作る状態を変えているだけ。

   **ここで2回、効かない修正を書いて revert した。** 1回目は undo の窓で
   `sync_proxies` を止めるもの、2回目は同じ窓で update コールバックを
   止めるもの。どちらも「無効化すると直る」を「undo 中に悪さをしている」と
   読み替えたのが誤り。**この取り違えはこの節で3回目**なので、次に触る人は
   まず「それは undo 中に本当に呼ばれているか」を計測すること。

   次は、undo 中に呼ばれる Python を**全部**列挙するところから。
   `sys.settrace` を仕掛けて `ed.undo()` の間だけ記録するのが素直。

   **`sys.settrace` で経路が確定した（2026-10-31）。**

   推測で候補を潰すのをやめ、`ed.undo()` の間だけ `sys.settrace` を仕掛けて
   呼ばれた Python を全部記録した。**undo の最中に、こちらのハンドラは
   確かに呼ばれている**:

   ```
   depsgraph_update_handler
     -> core_bridge.trigger_dependent_updates
     -> core_bridge._update_cad_preview_internal_for_col
   ```

   記録が途切れる直前の行は `utils.py:1617` 付近、つまり

   ```python
   any_dragging = is_transform_modal or any(
       getattr(getattr(col, "seamless_props", None), "is_dragging", False)
       for col in changed_cols)
   ```

   **`col.seamless_props` が gdb の言う `PyObject_GetAttr`。** `changed_cols` は
   ハンドラの前半で掴んだ Collection の集合で、undo の復元中にはそれが
   もう有効でない。`getattr` に既定値を渡していても意味がない ―
   例外は Python のものではなく C++ の `std::bad_optional_access` なので、
   既定値に落ちる前に terminate する。

   **タイミングも確定した。** undo_pre と undo_post の間にハンドラは
   一度も呼ばれない。危ないのは **undo_post の後、まだ `ed.undo()` の中に
   いる間に来る1回**。§8-5 冒頭の「問題の更新は undo_post の後に来る」は
   正しかった。

   **対症療法は効くが、代償がある。** 「undo_pre/post のあと最初の1回だけ
   ハンドラを素通りさせる」を入れると:

   | | 結果 |
   |---|---|
   | Linux 再現手順 | **abort 0/5**（完全に止まる） |
   | Linux フルスイート | abort 0/3、**61 passed / 1 failed** |
   | Windows フルスイート | **61 passed / 1 failed** |

   落ちる1本はどちらも `one undo = one step`（`['BOX']` のはずが
   `['BOX', 'CYLINDER']`）。**undo の粒度が変わってしまう。** これは
   2026-07-30 に直した「Ctrl+Z を2回押さないと戻らない」の再発そのもので、
   クラッシュと引き換えにして良いものではない。実装は revert 済み。

   **「名前で引き直す」も試して外した（2026-10-31）。** `_handle_nonmodal_sync`
   と `_commit_pending_step_scales` が Collection ではなく名前を返すようにし、
   使う直前に `bpy.data.collections.get()` で引き直す形へ書き換えたが、
   **abort 5/5 のまま**。revert 済み。

   **そして、そもそも `utils.py:1617` を犯人と読んだのが早とちりだった。**
   settrace の記録が 1622〜1626 行で途切れていたのを「そこで落ちた」と
   読んだが、**あの実行は完走している**（settrace を仕掛けると落ちない）。
   トレースの末尾は、単にハンドラが正常に return した場所だった。
   settrace から言えるのは「undo 中にハンドラとプレビュー更新が走る」こと
   までで、どの行で落ちるかは分かっていない。

   **今日の時点で確実なこと**:

   - Linux で `ed.undo()` 中に `std::bad_optional_access` で abort する
     （WSL2 / Blender 5.2.1・5.2.3、7回に6回）
   - **8.1.5.16 でも同率で落ちる。今回の変更とは無関係**
   - 落ちているのは、undo 中に Blender が呼んだ Python の属性アクセス
     （gdb: `__cxa_throw` <- `PyObject_GetAttr` <- Python フレーム）
   - 危ない呼び出しは **undo_post の後**、まだ `ed.undo()` の中
   - depsgraph ハンドラを**その1回だけ**素通りさせると abort は完全に消える
     が、`one undo = one step` が壊れる（undo の粒度が変わる）
   - `sys.settrace` を仕掛けると再現しない（観測が挙動を変える）

   **分かっていないこと**: どの属性アクセスが投げているのか。

   **次の一手**: settrace は使えないので、観測を軽くする。
   `faulthandler.register()` ではこの経路は拾えない（abort であって
   シグナルではない）。gdb を `__cxa_throw` で止めたうえで、
   Python フレームのポインタから関数名を引く（`PyFrameObject` を手で辿るか、
   Blender の Python を含む debug symbols を入れる）のが筋。
   あるいは、ハンドラ本体を上から順に return で分割して、どこまで進めば
   落ちるかを二分する — 一番泥臭いが、観測を変えずに済む。

   **4回連続で「無効化すると直る＝そこが原因」と読み違えた。** この節で
   同じ型の誤りは通算6回目。次に触る人は、**修正を書く前に「その行が
   実際に実行されているか」を独立に確かめること。**

   **次の一手はここから。** プロキシのどの作り方が undo を壊すのかを見る。
   `sync_proxies` の中を段階的に無効化する（オブジェクト生成だけ / メッシュ
   差し替えだけ / カスタムプロパティだけ）のが、同じドライバで続けられる。
   Blender 側のシンボルが要る段階に入ったら gdb か valgrind（WSL には未導入）。

   **まだ直していない。** `undo_pre`/`undo_post` の間だけ止める案は上の表の
   とおり効かない（問題の更新は `undo_post` の後に来る）。`sync_proxies` は
   プロキシ同期そのもの＝チェックリスト A/B の土台なので、**雑に抑止すると
   アドオンの根幹が壊れる**。次の一手は、undo 直後の一定期間だけ
   `sync_proxies` を遅延させる（既存の `_arm_drag_settle` と同じ作り）か、
   ハンドラ内で「いま undo の適用中か」を判定する手段を探すか。

   **これは配布判断に効く。** 「Linux は回帰テストが通る」と言える状態では
   なく、`SUPERHIVE_FAQ.html` などの記述はこの事実に合わせてある。
   利用者の実機で Ctrl+Z がどうなるかは**別問題**（背景実行の undo と
   GUI の undo は経路が違う）。実機の報告は今のところ来ていない。

   **未検証:** 実機の Linux（WSL ではない）で 5.1.1 が同じか。Blender 5.1.1 側の
   不具合なのか、こちらの触り方が 5.1.1 でだけ露呈するのかも未分離。
   利用者が 5.1.x を使っている場合は効く話なので、**`docs` の動作環境に
   5.2 以降を推奨と書くか、原因を追うかは要判断**。

6. **Intel Mac** — 現在対象外。必要なら `macos-14` 上でクロスビルドできるが
   （`CMAKE_OSX_ARCHITECTURES=x86_64` + `cargo --target x86_64-apple-darwin`）、
   arm64 上で x86_64 バイナリは起動できないため、**スモークテストの関門が
   Intel 版だけ効かなくなる**

---

## 9. 次にやるなら

1. Linux と macOS の ZIP を実機の Blender に入れて動かす（1〜3 の壁のうち最も安い）
2. ヘッドレス回帰テストを CI に載せる（Blender をランナーに落として `--background`）
3. Apple Developer Program に加入し、署名・公証をワークフローに足す
4. Intel Mac のクロスビルド

関連文書: [DEPSGRAPH_STATE_MACHINE.md](Blender_CAD_V_8_1_5_1/DEPSGRAPH_STATE_MACHINE.md)（依存グラフ側の状態機械と手動チェックリスト）
