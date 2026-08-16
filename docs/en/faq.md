# Frequently asked questions

Short answers, with links to the page that goes into detail.

## Buying and platforms

**Which operating systems are supported?**
Windows 10 and 11, 64-bit. That is the product.

Builds for Linux (x86-64) and macOS (Apple Silicon) exist and are being given to
testers, but they are not on sale and have no release date. Nobody has confirmed
them working inside Blender yet, and macOS notarisation needs a paid Apple
Developer membership that is not funded — that, rather than the code, is the main
obstacle. Buy only if you are on Windows. See [Testing builds](testing-builds.md).

**Which Blender versions work?**
4.2 LTS or newer. Tested on 4.2, 4.3, 4.4 and 5.1.

**Do I need other CAD software or a CAD licence?**
No. The kernel (OpenCASCADE) and everything it needs are bundled. Nothing else
to install. See [Installation](install.md).

**Are updates included?**
All updates in the 8.x series are included.

**Is the source available?**
Yes. Blender add-ons are GPL and this one is no exception — GNU GPL v2 or later,
with the source published openly, including the Rust and C++ geometry kernel.

**What does "beta" actually mean here?**
It works and it is being used for real modelling, but it is under active
development. Expect rough edges, expect behaviour to change between updates, and
save your work. See [Known limitations](limitations.md).

## What it does

**Is this parametric CAD, like Fusion or SolidWorks?**
It is history-based and non-destructive: every operation stays in a
[Feature Tree](feature-tree.md) you can go back and re-edit. It is not as
complete as those packages — see [Known limitations](limitations.md) for the
honest list.

**Can I use Blender's modifiers and mesh tools on a CAD shape?**
Not directly. Shapes are computed by the kernel, not by Blender's mesh system.
**Bake to Mesh** first, and you get an ordinary mesh that all of Blender applies
to. See [Import and export](import-export.md).

**Does <kbd>G</kbd> / <kbd>R</kbd> / <kbd>S</kbd> work?**
Yes. You are moving an ordinary Blender proxy object, and the geometry follows in
real time. See [How it works](concepts.md).

**Does Blender's undo work?**
Yes, for add-on operations. Sketch mode is the exception: it keeps its own undo
stack, so <kbd>Ctrl</kbd>+<kbd>Z</kbd> inside a sketch undoes sketch steps rather
than Blender ones.

**Can I reorder the Feature Tree?**
No. Order is creation order and rows cannot be moved, nor can a new operation be
inserted in the middle. See [The Feature Tree and parts](feature-tree.md) for
what to do instead.

**Is there an assembly or mating system?**
No. Multiple parts exist and are independent, but there are no assembly
constraints between them.

## Files

**Which formats can it read and write?**
STEP in and out, SVG in. Anything else goes through **Bake to Mesh** and Blender's
own exporters. IGES is not supported.

**What scale does STEP export use?**
1 Blender unit is written as 1 mm, with no option to change it. Build at
millimetre scale. See
[How to: exchange files with other CAD software](howto-cad-exchange.md).

**Why does my exported file have no colours?**
Because there is no colour to export. Nothing in this addon lets you give a Part
or a face a colour, so the file has none to carry. Names and assembly structure
*are* written — the Part's collection name becomes the product name, and **All
Parts as Assembly** writes every Part into one structured file. IGES is the
exception: geometry only, on purpose. See [Known limitations](limitations.md).

**Is the exported geometry triangulated?**
No. STEP export writes exact B-Rep surfaces. Display quality settings do not
affect it.

## Using it

**Nothing computes at all. What first?**
`Edit > Preferences > Add-ons`, expand Seamless CAD, and read
**CAD Engine: Running / Not running**. That reflects the real process state. If
it is not running, check whether something else is using port 8080 — see
[Installation](install.md). Then [Troubleshooting](troubleshooting.md).

**Why is a preview wrong while I drag and right when I release?**
That is **Fast Modifier Preview** or **Live Boolean Preview** trading exactness
for responsiveness. The committed result is always computed exactly. See
[Quality and performance](quality.md).

**Why is a fillet broken after I changed something earlier?**
It refers to a specific face or edge identity, and something removed the face it
pointed at — usually **Cleanup (Unify)**. See [How it works](concepts.md).

**My model is slow. What helps most?**
Set a rollback pin partway down the tree; everything below stops being evaluated.
Then turn off the previews, then raise Linear and Curvature. See
[Quality and performance](quality.md).

**I applied a sketch and nothing three-dimensional appeared.**
A sketch produces a face, not a solid. Set **Extrude Height** — it defaults to
`0.0`. See
[How to: turn a sketch into a solid](howto-sketch-to-solid.md).

## Documentation and support

**Which languages is the manual in?**
Full English and Japanese. Quick Start only in Russian and Simplified Chinese,
and those two were translated by AI without review by a native speaker — each
says so at the top. Where a translation and the English disagree, English is
correct. The add-on's interface is in English in all cases.

**How do I report a bug?**
Through the product page, or the project's GitHub issue tracker. Reports go
straight to the developer. What makes a report actionable is described in
[Testing builds](testing-builds.md#reporting) — the same applies on Windows.
