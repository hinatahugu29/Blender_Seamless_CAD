# Seamless CAD

Non-destructive CAD modelling inside Blender.

Shapes are computed by **OpenCASCADE (OCCT)**, not by Blender's mesh system, and
the result is drawn in the viewport. Primitives, booleans, fillets and chamfers
are kept as a **Feature Tree** — a history you can go back and re-edit at any
time. Move a proxy with <kbd>G</kbd> / <kbd>R</kbd> / <kbd>S</kbd> and the
geometry follows in real time.

Output goes two ways: **Bake to Mesh** for use inside Blender, or **Export STEP**
for a real B-Rep file other CAD software can open.

> **Beta.** Sold for Windows. macOS (Apple Silicon) and Linux builds exist and
> are being given to testers, but are not a product — see
> [Testing builds](testing-builds.md) and [Known limitations](limitations.md).

## Start here

- **[Installation](install.md)** — requirements, install, update, first start
- **[Quick Start](quickstart.md)** — install to exported STEP file, about ten
  minutes

## How to

| Page | Contents |
|---|---|
| [Turn a sketch into a solid](howto-sketch-to-solid.md) | Sketch, constrain, apply, and give the result thickness |
| [Cut holes and pockets](howto-holes.md) | Booleans, patterned holes, rounding the edges |
| [Exchange files with other CAD](howto-cad-exchange.md) | Getting a part out to SolidWorks, Fusion or FreeCAD, and back |

## Reference

| Page | Contents |
|---|---|
| [The Feature Tree and parts](feature-tree.md) | Rows, order, rollback, groups, targets, parts |
| [Modelling operations](modeling.md) | The Create and Modify & Pattern panels |
| [Sketching](sketching.md) | Sketch mode, tools and constraints |
| [Keyboard and mouse](shortcuts.md) | Every key, per interactive mode |
| [Quality and performance](quality.md) | Display quality, previews, baking, what to do when it feels slow |
| [Import and export](import-export.md) | STEP in and out, SVG in, Bake to Mesh |

## Background and limits

| Page | Contents |
|---|---|
| [How it works](concepts.md) | The kernel, the Feature Tree, why some things behave as they do |
| [Known limitations](limitations.md) | What this does not do yet |
| [Troubleshooting](troubleshooting.md) | Symptoms and their causes |
| [Testing builds](testing-builds.md) | macOS and Linux, and what has not been verified |

## Resources

| Page | Contents |
|---|---|
| [FAQ](faq.md) | Short answers, with links to the detail |
| [Glossary](glossary.md) | Terms as this add-on uses them |

## Other languages

| | |
|---|---|
| [日本語](https://hinatahugu29.github.io/Blender_Seamless_CAD/ja/) | Full translation |
| [Русский](https://hinatahugu29.github.io/Blender_Seamless_CAD/ru/) | Quick Start only — AI translation, not reviewed by a native speaker |
| [中文](https://hinatahugu29.github.io/Blender_Seamless_CAD/zh/) | Quick Start only — AI translation, not reviewed by a native speaker |

English is the source of truth. The add-on's interface is in English, so the
English documentation is what matches the buttons you see on screen.
