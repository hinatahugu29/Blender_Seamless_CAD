# Import and export

## Import STEP

`Quality & Export > Import > STEP`. Accepts `.stp` and `.step`.

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

`Quality & Export > Import > SVG`. Accepts `.svg`, and also takes a **Scale**
multiplier.

This brings in 2D profiles, which can then be swept, lofted or revolved into
solids.

> SVG import depends on the bundled `svgpathtools` and `svgwrite` libraries.
> The packaging script checks that they are actually importable before building
> a release, because they were once silently lost during a directory copy and
> SVG import stayed broken across several versions without anyone noticing.

## Export STEP

`Quality & Export > Export > STEP`. Writes `.stp`.

The output is a genuine B-Rep STEP file in **AP214 IS**. Exact surfaces are
written, not a triangulated approximation, so the display quality settings have
no effect on it.

### Scale

**One Blender unit is written as 1 mm by default.** A 10-unit box opens as a
10 mm box in FreeCAD, Fusion or SolidWorks.

Set *Scale (1 unit = N mm)* in the export dialog if you work at another scale —
1000 if a unit is a metre, 10 if it is a centimetre. It is the same quantity as
Import's Scale, so a file brought in at 10 goes back out unchanged at 10.
Leaving it at 1.0 matches every earlier version.

### Part names and assemblies

**The Part's collection name is written as the product name.** Open the file in
FreeCAD, Fusion or SolidWorks and the part arrives called what you called it,
rather than as an unnamed body.

Tick **All Parts as Assembly** to write every CAD Part in the scene into one
file, related as a proper assembly:

```
Assembly
  ├─ Bracket
  └─ Housing
```

Set **Assembly Name** for the top-level name. Parts with no geometry yet are
skipped rather than written as empty entries. Leave the option off — the default
— and you export just the Part you are working on.

### What is not in the file

**No colours.** The addon has no notion of colour to export: there is no colour
to set on a Part or a face anywhere in the interface, so there is nothing to
write into the file. Geometry, names and structure are all present.

> "It opens in FreeCAD" is a weak test and worth distrusting. FreeCAD will open
> files that other CAD systems reject. If a specific target application matters
> to you, test against that application.

## Export STL

`Quality & Export > Export > STL`. Writes `.stl`, binary by default.

This goes straight from the kernel to the file. You do **not** need to Bake
first, and the result is better if you do not: the tessellation uses the quality
settings in this panel, so turning on **Use High Quality Bake** produces a finer
STL than the route through a Blender mesh.

*Scale (1 unit = N mm)* means the same thing as it does for STEP. **ASCII**
writes a text STL instead — far larger, and only worth it if you want to read
the file yourself.

If the part is empty, or tessellation produces nothing, **no file is written**
and you get an error. An STL that opens and turns out to be empty is a worse
outcome than a refusal.

## Export IGES

`Quality & Export > Export > IGES`. Writes `.igs`.

**Geometry only — no names, no assembly structure.** IGES readers vary too much
in how they handle names for it to be dependable. **Prefer STEP.** IGES is here
for recipients whose software cannot read anything else.

*Scale* works as above. Turn off **Solid (BRep)** to write a collection of
trimmed surfaces instead of solids; some older readers cope with that better.

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
| Send several parts as one assembly | **Export STEP**, All Parts as Assembly |
| 3D print, or send to a slicer | **Export STL** |
| The recipient can only read IGES | **Export IGES** |
| Export via Blender's glTF/FBX/OBJ exporters | **Bake to Mesh** first |

Reach for **Export STL** rather than Bake to Mesh when the destination is a
printer. Both produce triangles, but the direct export skips the round trip
through Blender's mesh and keeps the kernel's tessellation.

## See also

- [Quality and performance](quality.md)
- [Known limitations](limitations.md)
