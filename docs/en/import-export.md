# Import and export

## Import STEP

`Quality & Export > Import STEP`. Accepts `.stp` and `.step`.

The import dialog has one option, **Scale**, a uniform multiplier applied as the
geometry comes in. The dialog itself notes the common cases: `0.001` converts
millimetres to metres, `1.0` imports at native scale.

Each solid in the file becomes its own Feature Tree entry named `STEP Part …`.
The first one imported into an empty part gets `Base`; the rest get
`Add (Fuse)`. Imported parts are ordinary tree entries — you can move them,
change their Operation, and cut them with booleans like anything else.

The scale you chose is stored with the entry, so re-importing or reloading keeps
it consistent.

## Import SVG

`Quality & Export > Import SVG`. Accepts `.svg`, and also takes a **Scale**
multiplier.

This brings in 2D profiles, which can then be swept, lofted or revolved into
solids.

> SVG import depends on the bundled `svgpathtools` and `svgwrite` libraries.
> The packaging script checks that they are actually importable before building
> a release, because they were once silently lost during a directory copy and
> SVG import stayed broken across several versions without anyone noticing.

## Export STEP

`Quality & Export > Export STEP`. Writes `.stp`.

The output is a genuine B-Rep STEP file in **AP214 IS**. Exact surfaces are
written, not a triangulated approximation, so the display quality settings have
no effect on it.

### Scale

**1 Blender unit is written as 1 mm.** A 10-unit box opens as a 10 mm box in
FreeCAD, Fusion or SolidWorks. There is no export scale option — set your
dimensions with this in mind from the start.

### What is not in the file

Be aware before you send a file to someone:

- **No part names.** Entities are unnamed.
- **No colours.**
- **No assembly structure.** The file carries geometry, flat.

The geometry is exact and correct. The metadata simply is not written. If a
recipient needs named, coloured assemblies, this export will not satisfy them
yet.

> "It opens in FreeCAD" is a weak test and worth distrusting. FreeCAD will open
> files that other CAD systems reject. If a specific target application matters
> to you, test against that application.

## Bake to Mesh

`Quality & Export > Bake to Mesh`. This is the other way out, and it stays inside
Blender.

The CAD result is converted into an ordinary Blender mesh object named
`SeamlessBake`, placed in a **Result** collection under `Seamless_CAD`. It is
selected and made active when it is created.

Use it for rendering, sculpting, exporting through Blender's own exporters, or
anything else that needs real Blender geometry.

Enable **Use High Quality Bake** first if the result is destined for a render.
With it on, the kernel re-tessellates at the bake settings before the mesh is
generated. See [Quality and performance](quality.md).

**The bake is a snapshot.** It does not stay linked to the Feature Tree. Change
the model afterwards and you must bake again — the existing `SeamlessBake` object
will not update.

## Choosing between them

| You want to | Use |
|---|---|
| Render, sculpt, or use Blender tools | **Bake to Mesh** |
| Open the part in other CAD software | **Export STEP** |
| Send exact geometry for manufacturing | **Export STEP** |
| Export via Blender's glTF/FBX/OBJ exporters | **Bake to Mesh** first |

## See also

- [Quality and performance](quality.md)
- [Known limitations](limitations.md)
