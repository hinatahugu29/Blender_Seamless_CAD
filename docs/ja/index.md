# Seamless CAD

Blender の中でノンデストラクティブな CAD モデリングを行うアドオンです。

形状の計算は Blender のメッシュではなく **OpenCASCADE (OCCT)** が行い、その結果が
ビューポートに描画されます。プリミティブ、ブーリアン演算、フィレット・面取りは
**Feature Tree**（履歴）として保持され、後からいつでも数値を編集し直せます。
ビューポート上のプロキシを <kbd>G</kbd> / <kbd>R</kbd> / <kbd>S</kbd> で動かせば、
形状がリアルタイムに追従します。

出力は2通りです。Blender 内で使うなら **Bake to Mesh**、他の CAD ソフトに渡すなら
**Export STEP**（本物の B-Rep）。

> **ベータ版。**販売しているのは Windows 版です。macOS (Apple Silicon) 版と
> Linux 版のビルドはあり、テスターの方にお渡ししていますが、製品ではありません。
> [テストビルド](testing-builds.md) と [既知の制約](limitations.md) を参照して
> ください。

## まずここから

- **[インストール](install.md)** — 動作条件、インストール、更新、初回起動
- **[クイックスタート](quickstart.md)** — インストールから STEP 書き出しまで、約10分

## 使い方

| ページ | 内容 |
|---|---|
| [スケッチから立体を作る](howto-sketch-to-solid.md) | 描く、拘束する、Apply する、厚みを与える |
| [穴とポケットを開ける](howto-holes.md) | ブーリアン、穴のパターン、縁の丸め |
| [他の CAD とファイルをやりとりする](howto-cad-exchange.md) | SolidWorks / Fusion / FreeCAD への受け渡し |

## リファレンス

| ページ | 内容 |
|---|---|
| [Feature Tree と Part](feature-tree.md) | 行の見かた、順序、ロールバック、グループ、ターゲット、Part |
| [モデリング操作](modeling.md) | Create パネルと Modify & Pattern パネル |
| [スケッチ](sketching.md) | スケッチモードのツールと拘束 |
| [キーボードとマウス](shortcuts.md) | モードごとのキー一覧 |
| [品質とパフォーマンス](quality.md) | 表示品質、プレビュー、ベイク、重いときの対処 |
| [読み込みと書き出し](import-export.md) | STEP の入出力、SVG の読み込み、Bake to Mesh |

## 仕組みと制約

| ページ | 内容 |
|---|---|
| [仕組み](concepts.md) | カーネル、Feature Tree、一部の挙動がそうなっている理由 |
| [既知の制約](limitations.md) | 現時点でできないこと |
| [困ったとき](troubleshooting.md) | 症状とその原因 |
| [macOS / Linux テストビルド](testing-builds.md) | 何が検証済みで、何が未検証か |

## 資料

| ページ | 内容 |
|---|---|
| [よくある質問](faq.md) | 短い答えと、詳しいページへのリンク |
| [用語集](glossary.md) | 画面の英語表記と日本語の対応 |

## 言語について

**アドオンの UI は英語です。**このため、用語の正本は
[英語版ドキュメント](https://hinatahugu29.github.io/Blender_Seamless_CAD/) にあります。画面のボタン名と確実に一致するのは
英語版です。日本語版は英語版の翻訳として維持しています。

ロシア語版・中国語版はクイックスタートのみです。
