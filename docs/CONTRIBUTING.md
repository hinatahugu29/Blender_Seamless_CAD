# ドキュメントの書き方・運用

ユーザー向けマニュアルの原稿を `docs/` に置いています。開発者向けのメモ
（`PROJECT_STATUS.md` など）はここには入れません。

## 正本は英語版

**`en/` が正本です。** アドオンの UI 文言がすべて英語なので、用語の基準を英語側に
置かないと、マニュアルとパネルの表記が食い違います。他言語は英語版の翻訳として
扱い、**英語版を先に直します。**

## 構成

```
docs/
  README.md         GitHub でリポジトリを見た人向けの言語入口（サイトには出ない）
  CONTRIBUTING.md   このファイル（サイトには出ない）
  requirements.txt  サイトのビルドに必要なもの
  en/  ← 正本
  ja/
  ru/   クイックスタートのみ
  zh/   クイックスタートのみ
```

このディレクトリ構造は [mkdocs-static-i18n] の `folder` 方式に対応しています。
`README.md` と `CONTRIBUTING.md` は `mkdocs.yml` の `exclude_docs` で除外して
あるので、サイトのページにはなりません。

Sphinx / Read the Docs ではなく MkDocs を使っているのは、Sphinx の多言語が
gettext（`.po` ファイル）経由で、翻訳を手伝ってくれる人に po 編集を強いるためです。
MkDocs のこの方式なら「`ru/quickstart.md` を丸ごと書く」だけで済み、**翻訳を人に
投げやすくなります。**

[mkdocs-static-i18n]: https://github.com/ultrabug/mkdocs-static-i18n

## 言語ごとに範囲を変えている理由

| 言語 | 範囲 | 品質を確認できるか |
|---|---|---|
| `en` | 全部（正本） | できる |
| `ja` | 全部 | できる |
| `ru` | クイックスタートのみ | **できない**（AI 翻訳・母語話者未校閲） |
| `zh` | クイックスタートのみ | **できない**（AI 翻訳・母語話者未校閲） |

ロシア語・中国語は内容の正しさを開発側で検証できません。範囲を広げるほど、検証
できない文章が増え、しかも英語版の更新に追随できずに古くなります。そのため意図的に
クイックスタートだけに固定し、それ以外は英語版へ誘導します。

**`ru` / `zh` の冒頭には、AI 翻訳であり母語話者の校閲を受けていない旨を必ず明記して
ください。**これを書かないと、読者は検証済みの文書だと誤解します。校閲済みだと
偽るより、範囲が狭くても出所が正直な文書のほうが信用されます。将来、母語話者の協力が
得られた時点でこの断り書きを外し、範囲を広げます。

## 翻訳版の冒頭に書くこと

翻訳版のファイルは、対応する英語版のバージョンを必ず書いてください。

```markdown
> 英語版 v8.1.5.4 に対応。最新の情報は [English documentation](...) を参照してください。
```

**バージョンは `CAD_8_1_5_1/__init__.py` の `bl_info["version"]` から取ってください。**
ディレクトリ名（`Blender_CAD_V_8_1_5_1`）はバージョンではありません。初版でここを
取り違え、全翻訳に誤った対応バージョンを書いた実績があります。

英語版を更新したとき翻訳版が古くなること自体は許容します。ただし**「どの時点の
英語版に対応しているか」が分からない状態は許容しません。**

## 更新の順序

1. `en/` を直す
2. `ja/` を追従させる
3. `ru/` `zh/` は、クイックスタートに影響がある変更のときだけ追従させる

## 言語をまたぐリンクは絶対 URL で書く

mkdocs-static-i18n は `../en/quickstart.md` のような**言語をまたぐ相対リンクを解決
できません**（ビルド時に警告が出て、リンク切れになります）。言語をまたぐ場合だけ、
公開サイトの絶対 URL を書いてください。

```markdown
[English documentation](https://hinatahugu29.github.io/Blender_Seamless_CAD/quickstart/)
```

同じ言語の中でのリンクは、これまでどおり相対パス（`concepts.md`）で書きます。

## その他の落とし穴

- **`requirements.txt` は ASCII のみ。** pip はこのファイルをシステムのロケール
  エンコーディング（日本語 Windows では cp932）で読むため、日本語のコメントを
  入れると `UnicodeDecodeError` でインストールが失敗します
- **`theme.features` に `navigation.instant` を入れない。** mkdocs-static-i18n の
  言語切替リンクが動かなくなります
- **`fallback_to_default` は `false` のまま。** `true` にすると `ru` / `zh` のサイトに
  英語のページが埋められ、ナビに無いページが生えます。翻訳の範囲は明示的に保ちます

## ローカルでの確認

```bash
py -m pip install -r docs/requirements.txt
py -m mkdocs serve
```

## 公開

`main` への push で `docs/` か `mkdocs.yml` が変わると、
[`.github/workflows/docs.yml`](../.github/workflows/docs.yml) が GitHub Pages に
publish します。
