# Seamless CAD

Non-destructive CAD modelling inside Blender.

Shapes are computed by **OpenCASCADE (OCCT)**, not by Blender's mesh system, and
the result is drawn in the viewport. Primitives, booleans, fillets and chamfers
are kept as a **Feature Tree** — a history you can go back and re-edit at any
time. Move a proxy with <kbd>G</kbd> / <kbd>R</kbd> / <kbd>S</kbd> and the
geometry follows in real time.

Output goes two ways: **Bake to Mesh** for use inside Blender, or **Export STEP**
for a real B-Rep file other CAD software can open.

> **Beta.** Windows only. macOS and Linux test builds exist but are not a
> released product. See [Known limitations](limitations.md).

## Start here

- **[Quick Start](quickstart.md)** — install to exported STEP file, about ten
  minutes

## Reference

| Page | Contents |
|---|---|
| [How it works](concepts.md) | The kernel, the Feature Tree, why some things behave as they do |
| [Modelling operations](modeling.md) | The Create and Modify & Pattern panels |
| [Sketching](sketching.md) | Sketch mode, tools and constraints |
| [Quality and performance](quality.md) | Display quality, previews, baking, what to do when it feels slow |
| [Import and export](import-export.md) | STEP in and out, SVG in, Bake to Mesh |
| [Troubleshooting](troubleshooting.md) | Symptoms and their causes |
| [Known limitations](limitations.md) | What this does not do yet |

## Other languages

| | |
|---|---|
| [日本語](https://hinatahugu29.github.io/Blender_Seamless_CAD/ja/) | Full translation |
| [Русский](https://hinatahugu29.github.io/Blender_Seamless_CAD/ru/) | Quick Start only — AI translation, not reviewed by a native speaker |
| [中文](https://hinatahugu29.github.io/Blender_Seamless_CAD/zh/) | Quick Start only — AI translation, not reviewed by a native speaker |

English is the source of truth. The add-on's interface is in English, so the
English documentation is what matches the buttons you see on screen.
