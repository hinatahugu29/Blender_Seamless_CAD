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

- **[クイックスタート](quickstart.md)** — インストールから STEP 書き出しまで、約10分

## リファレンス

| ページ | 内容 |
|---|---|
| [仕組み](concepts.md) | カーネル、Feature Tree、一部の挙動がそうなっている理由 |
| [モデリング操作](modeling.md) | Create パネルと Modify & Pattern パネル |
| [スケッチ](sketching.md) | スケッチモードのツールと拘束 |
| [品質とパフォーマンス](quality.md) | 表示品質、プレビュー、ベイク、重いときの対処 |
| [読み込みと書き出し](import-export.md) | STEP の入出力、SVG の読み込み、Bake to Mesh |
| [困ったとき](troubleshooting.md) | 症状とその原因 |
| [既知の制約](limitations.md) | 現時点でできないこと |

## 言語について

**アドオンの UI は英語です。**このため、用語の正本は
[英語版ドキュメント](https://hinatahugu29.github.io/Blender_Seamless_CAD/) にあります。画面のボタン名と確実に一致するのは
英語版です。日本語版は英語版の翻訳として維持しています。

ロシア語版・中国語版はクイックスタートのみです。
