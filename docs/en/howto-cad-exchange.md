# How to: exchange files with other CAD software

The point of a B-Rep kernel is that the geometry survives the trip. This page is
the practical checklist for getting a part out to SolidWorks, Fusion, Rhino or
FreeCAD — and for bringing one back.

[Import and export](import-export.md) is the reference for the same features.
This page is about the decisions around them.

## Before you model: work in millimetres

**STEP export writes 1 Blender unit as 1 mm, and there is no option to change
it.** A 10-unit box arrives as a 10 mm box.

Decide this before you build, not afterwards. There is no export scale to
compensate with, and rescaling a finished feature tree means retyping every
dimension.

## Getting a part out

1. Finish the model
2. Optionally add **Cleanup (Unify)** as the **last** entry in the tree
3. **Quality & Export > Export > STEP**

**Cleanup merges coplanar faces**, which gives the recipient a tidier model —
one face where you had three. It is worth doing, and it is worth doing *last*:
merging faces destroys the face identities that Fillet, Offset, Shell and Draft
refer to, so an entry below it can break. See [How it works](concepts.md).

Display quality settings do not matter here. STEP carries exact surfaces, not
triangles, so **Linear** and **Curvature** have no effect on the file.

### What the recipient will not get

Say this up front and you will save a round trip:

- **No part names** — entities are unnamed
- **No colours**
- **No assembly structure** — the file is flat

The geometry is exact and correct. The metadata is simply not written. If someone
needs a named, coloured, structured assembly, this export does not meet that need
yet. See [Known limitations](limitations.md).

### Test against the actual target

If a specific application matters, open the file in **that** application before
sending it.

"It opens in FreeCAD" is a weak test worth distrusting: FreeCAD accepts files
that stricter systems reject. It tells you the file is not badly broken. It does
not tell you SolidWorks will take it.

## Bringing a part in

**Quality & Export > Import > STEP**, accepting `.stp` and `.step`.

The dialog's one option is **Scale**:

| Source | Scale |
|---|---|
| A file authored in millimetres | `1.0` |
| A file authored in metres, to keep 1 unit = 1 mm | `0.001` |

Each solid in the file becomes its own Feature Tree entry named `STEP Part …`.
The first one into an empty part gets `Base`; the rest get `Add (Fuse)`.

Imported entries are ordinary tree entries. You can move them, change their
Operation, cut them with booleans, and fillet their edges like anything else —
what you cannot do is edit the parametric history of the original, because a STEP
file does not carry one. It arrives as finished geometry.

The scale you chose is stored with the entry, so reloading stays consistent.

## Bringing in a 2D profile

**Quality & Export > Import > SVG** brings in outlines, also with a **Scale**
option. Use it when the profile already exists as artwork — a logo, a laser-cut
outline, a drawing traced in Illustrator or Inkscape.

Once imported, the profile behaves like any other curve: extrude it, sweep it,
loft it, or revolve it.

## Going to Blender instead

If the destination is a renderer, a game engine, or anything that reads glTF, FBX
or OBJ, do not export STEP. **Bake to Mesh** first, then use Blender's own
exporters on the result.

Enable **Use High Quality Bake** before baking if the mesh is for a render — it
re-tessellates finely rather than reusing your working display quality.

Remember that a bake is a **snapshot**. Change the model afterwards and you must
bake again; the existing `SeamlessBake` object does not update.

## Checklist before you send

- [ ] Dimensions are in millimetres as Blender units
- [ ] **Cleanup (Unify)** is the last entry, if you used it
- [ ] The file opens in the recipient's actual software
- [ ] The recipient knows there are no names, colours or assembly structure
- [ ] For rendering rather than CAD, you baked instead of exporting

## See also

- [Import and export](import-export.md)
- [Known limitations](limitations.md)
- [Quality and performance](quality.md)
