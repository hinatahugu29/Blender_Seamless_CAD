# 機能の穴 — 何を足すべきか

作成 2026-08-11（8.1.5.5 時点）。

コードとユーザー向けドキュメントを実際に読んで棚卸しした結果。**ユーザーからの
要望を集計したものではない。** 実際の報告が来たら、そちらの優先度が上。
8.1.5.3 の修正が全部ユーザー報告起点だったように、要望のほうが情報として精度が高い。

順番は「実装したい順」ではなく「**放っておくと商品価値を削り続ける順**」。

---

## 現状の守備範囲（穴ではない部分）

先に確認したこと。**操作の品揃えそのものは、この価格帯で不足していない。**

| 分類 | 実装済み |
|---|---|
| プリミティブ | BOX / CYLINDER / SPHERE / CONE / TORUS / SLOT / POLYGON / GEAR / HELIX / VARIABLE_BOX / ARC |
| 押し出し系 | SWEEP / LOFT / REVOLVE / FACE_LOFT / FACE_REVOLVE |
| 面・辺の加工 | FILLET / CHAMFER / SHELL / DRAFT / FACE_OFFSET / FACE_INSET |
| 複製 | MIRROR / ARRAY_LINEAR / ARRAY_CIRCULAR / INSTANCE |
| Boolean | ADD / SUB / INT |
| 取り込み | STEP_PART / SVG_PART |
| 整理 | GROUP_START / GROUP_END / CLEANUP |

穴があるのは**操作の種類ではなく、その周辺**にある。以下はそこの話。

---

## 1. Feature Tree の途中に挿入できない ← 最優先

### 何が起きているか

順序は作成順で固定。行の上下移動ができず、**ロールバックピンを刺していても新しい
操作は必ず末尾に付く**。`docs/en/limitations.md` に自分で明記してある。

- 追加は [`operators/management.py`](Blender_CAD_V_8_1_5_1/CAD_8_1_5_1/operators/management.py:125) ほかの `props.primitives.add()` — CollectionProperty の末尾追加
- ロールバックは「その先を計算しない」だけの実装。[`core_bridge.py:1547`](Blender_CAD_V_8_1_5_1/CAD_8_1_5_1/core_bridge.py:1547) で `i > rollback_index` を捨てている
- UI 側の表示制御は [`ui/ui_main_panel.py:273`](Blender_CAD_V_8_1_5_1/CAD_8_1_5_1/ui/ui_main_panel.py:273) 付近

つまり**ピンは「見せない」だけで、「そこに挿す」ではない**。挿入は
`primitives.add()` の後に `primitives.move()` を呼べば形の上では作れるが、
本当の問題はそこではない（下記）。

### なぜ最優先か

これはパラメトリック CAD の中核体験そのもの。Fusion も SolidWorks も FreeCAD も
「巻き戻して、そこに挿す」ができるから履歴に意味がある。それが無いと、順序を
間違えた時点でやり直しになる。

**「後から編集できる」という商品の主張が、実際には「値を編集できる」までしか
届いていない。** 機能を1つ足すより、ここを直すほうが商品価値は上がる。

### 難所（着手前に考えること）

単純な並べ替えでは済まない。**lineage（辺・面の同一性）が順序に依存している。**

- FILLET / CHAMFER / FACE_OFFSET / SHELL / DRAFT は対象を lineage で持っている
- その lineage は「自分より上の履歴が作った形状」の上で解決される
- 順序を変えると解決先が消える、あるいは別の辺を指す

だから実装の本体は「move する」ことではなく、**順序を変えたときに壊れる参照を
検出して、ユーザーに何が壊れるか見せること**になる。黙って壊すのが最悪。

関連: `CLEANUP`（UnifySameDomain）が面の同一性を破壊する話と根が同じ。
[[cad-unify-cleanup-modifier-design]] / `docs/en/limitations.md` の
"Cleanup (Unify) is destructive to references" を先に読むこと。

### 段階的にやるなら

1. **上下移動だけ**（隣接スワップ）。参照が壊れる場合は拒否して理由を出す
2. ロールバックピン位置への挿入
3. 任意位置へのドラッグ移動

1 だけでも実用価値がある。3 まで行かなくてよい。

---

## 2. スケッチの寸法拘束が足りない ← 費用対効果が一番良い

### 現状

拘束は9種のみ。[`properties.py:504-517`](Blender_CAD_V_8_1_5_1/CAD_8_1_5_1/properties.py:504) の enum が全部:

```
FIXED / DISTANCE / HORIZONTAL / VERTICAL / PARALLEL /
PERPENDICULAR / TANGENT / MIDPOINT / ARC
```

適用ロジックは [`sketch/actions/constraints.py`](Blender_CAD_V_8_1_5_1/CAD_8_1_5_1/sketch/actions/constraints.py)。

### 欠けているもの

| 拘束 | 無いと何が困るか |
|---|---|
| **半径 / 直径** | 円を寸法で決められない。機械部品で最頻出 |
| **角度** | 2直線の角度を数値で拘束できない |
| **同値 (Equal)** | 「この2辺は同じ長さ」が言えず、全部個別に寸法を打つことになる |
| 同心 (Concentric) | 円の中心合わせが手作業 |
| 対称 (直線について) | 今あるのは `POINT` の点対称のみ |

### なぜ効くか

`2D_CAD_ROADMAP.md` が「完全寸法駆動・幾何拘束型の2D CAD エンジン」を掲げている。
**半径と角度が無い状態はまだ寸法駆動と呼びにくい。**

そしてソルバー（ezpz crate）も拘束 UI の器も既にある。1 に比べて格段に安い。
**先にこちらを片付けるのが現実的な判断だと思う。**

---

## 3. 穴（Hole）が専用機能でない

今は円柱を作って Subtract する。ザグリ・皿穴・止まり穴・貫通が1つのパラメータ付き
操作になっていれば、機械系の作業量が体感で変わる。

`docs/en/howto-holes.md` を書いているということは、**聞かれている**ということでもある。

- 実装コストは中程度。既存の SUB を内部で使う複合操作として作れるはず
- 規格穴径（M3 用 φ3.4 など）の表を持たせると一気に「CAD らしく」なる
- ネジ山の実形状は**作らないこと**（重いだけで実用にならない。穴＋表記で足りる）

---

## 4. STEP エクスポートが幾何だけ

### 現状

[`src_rust/src/occ_step.cpp:93`](Blender_CAD_V_8_1_5_1/src_rust/src/occ_step.cpp:93) と同 126 行で
`STEPControl_Writer` に直接 `Transfer` している。素の B-Rep しか出ない。

名前なし・色なし・アセンブリ構造なし。`docs/en/limitations.md` に明記済み。

### なぜ直す価値があるか

**listing で「STEP 相互運用」を看板の1つにしている以上、半分しか届いていない。**
狙っている客層（Engineers & Makers、CNC・金型）に直接効く。

`STEPControl_Writer` から XCAF 系（`TDocStd_Document` + `XCAFDoc_ShapeTool` +
`STEPCAFControl_Writer`）に載せ替える話。小さくはないが、Part 名とグループ構造は
既に Blender 側に存在しているので、渡すものは揃っている。

関連する既存の測定結果は [[step-export-characteristics]] にある。
1 Blender unit = 1 mm 固定でエクスポート側にスケール指定が無い件も同じ場所。
ついでに直すならここ。

---

## 5. 計測がない

距離・角度・体積・重心を測る UI が無い。

カーネル側には既に材料がある:

- `BRepGProp` / `GProp_GProps` — [`occ_core.cpp:58`](Blender_CAD_V_8_1_5_1/src_rust/src/occ_core.cpp:58) で include 済み、面積計算に使用中
- `BRepExtrema_DistShapeShape` — ピッキングで使用中

**つまり体積・重心・面積・2点間距離は、カーネルに機能を足すというより、
既にある呼び出しを UI に出す作業に近い。** 比較的安い。

そして CAD として無いと違和感がある部類。3Dプリント層は体積（材料費）を知りたがる。

---

## 足さないほうがいいと思うもの

一人で beta を回している以上、上の1〜5を潰すほうが新カテゴリを開けるより確実に効く。

| | 理由 |
|---|---|
| アセンブリ拘束（メイト） | 別製品になる。Part とインスタンスで当面足りる |
| ネジ山の実形状生成 | 重いだけで実用にならない |
| 2D 図面出力 | 沼。単体で製品1つ分の工数 |
| サーフェスモデリング | 客層が違う |

---

## 機能ではないが、いずれ効くもの

**Blender Extension 形式（`blender_manifest.toml`）に未対応。**

4.2 以降のユーザーはドラッグ&ドロップ install に慣れていて、「Install from Disk」を
探させるのは初回体験の摩擦になる。`docs/en/limitations.md` に記載済み。

Superhive 販売である以上いま困るわけではないので急ぎではないが、
Extensions プラットフォームに出す判断をするなら前提条件になる。
カーネルを同梱するアドオンなので、プラットフォーム別 wheel の扱いを調べる必要がある。

---

## 着手順の推奨

```
2 (スケッチ寸法拘束)  ← 一番安くて、掲げた看板に直結する
  ↓
5 (計測)              ← 安い。カーネルは既にできている
  ↓
3 (Hole)              ← 中コスト・高頻度
  ↓
4 (STEP メタデータ)   ← 看板の残り半分
  ↓
1 (Tree への挿入)     ← 一番大きい。lineage の設計と正面から向き合う
```

1 が最重要なのに最後なのは、**他の4つを先に片付けてから腰を据えるべき規模**だから。
逆に、1 に手を付ける気になったときは他を止めてよい。それだけの価値がある。
