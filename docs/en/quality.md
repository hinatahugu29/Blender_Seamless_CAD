# Quality and performance

All of the settings on this page live in the **Quality & Export** panel. None of
them change your model — they change how it is displayed and how it is baked.

## Display quality

| Setting | Meaning |
|---|---|
| **Linear** | Maximum deviation between the display mesh and the exact surface |
| **Curvature** | Maximum angular deviation, in degrees |

Lower values mean a finer display mesh and slower updates. Curved surfaces are
the ones that notice; a model made only of flat faces is largely unaffected.

These settings do **not** affect STEP export, which writes exact surfaces rather
than triangles. See [Import and export](import-export.md).

## Previews

| Setting | Trade-off |
|---|---|
| **Fast Modifier Preview** | Approximates modifier results while you drag |
| **Live Boolean Preview** | Approximates boolean results while you drag |
| **Show Boolean Ghost Preview** | Shows the cutting shape as a ghost. Only available while Live Boolean Preview is on |

**These affect what you see during a drag, never the committed result.** When you
release, the kernel computes the shape exactly. If a preview looks wrong — a
boolean that seems not to have cut, a fillet that looks faceted — turn the
preview off and check whether the final result was correct all along. It usually
was.

Turning them off is also the first thing to try if dragging feels unstable.

## Baking

**Use High Quality Bake** enables a second, independent pair of settings:

| Setting | Meaning |
|---|---|
| **Bake Linear** | Linear deviation used only when baking |
| **Bake Curvature** | Angular deviation used only when baking |

This exists so display quality and output quality can differ. You can work at a
coarse, responsive display setting and still bake a fine mesh for rendering,
without switching settings back and forth.

With High Quality Bake enabled, **Bake to Mesh** re-tessellates at the bake
settings before generating the mesh, so the baked result is genuinely finer —
it is not the display mesh smoothed after the fact.

## Viewport Display

The **Viewport Display** panel is separate and affects only drawing.

| Setting | Meaning |
|---|---|
| **Opacity** | Face opacity |
| **Use WGPU Overlay** | Alternative rendering path |
| **Hide Occluded Edges** | Hides edges behind faces |

**Hide Occluded Edges is greyed out much of the time, and that is intentional.**
Faces only write depth when the WGPU overlay is **off** and opacity is fully
opaque. Outside those conditions there is no depth information for the setting to
use, so it would do nothing. Rather than leave a control that silently has no
effect, the add-on disables it. To use it: turn off **Use WGPU Overlay** and set
**Opacity** to fully opaque.

## When things feel slow

In rough order of what to try:

1. **Turn off the previews** if the slowness is during dragging
2. **Raise Linear and Curvature** if the slowness is constant and the model has
   many curved surfaces
3. **Set a rollback point** partway down the Feature Tree. Everything below it
   stops being evaluated, which is the single most effective way to keep a long
   history responsive while you work on an early operation
4. **Split into multiple parts** using **Add New CAD Part**. Only the active
   part is evaluated

Editing an operation near the *top* of a long Feature Tree is inherently more
expensive than editing one near the bottom, because everything after it must be
recomputed. This is a property of history-based CAD, not a bug.

## Logging

The add-on's preferences (`Edit > Preferences > Add-ons`, expand Seamless CAD)
carry logging switches. **ERROR** is on by default; the rest are off.

| Setting | Purpose |
|---|---|
| **Enable ERROR Logs** | On by default. Leave it on |
| **Enable WARN / INFO / DEBUG Logs** | Progressively more verbose. DEBUG can affect performance |
| **Perf Logging** | Writes timing data for the preview pipeline to `seamless_cad_profile.log` in your OS temp directory |

The same preferences screen shows **CAD Engine: Running / Not running**. This
reflects the actual state of the kernel process, so it is a reliable first check
when nothing is computing at all.

## See also

- [Import and export](import-export.md)
- [Troubleshooting](troubleshooting.md)
