# How it works

Reading this page is optional, but it explains why Seamless CAD behaves the way
it does. Most surprises people report turn out to be consequences of the design
described here.

## Blender does not compute the shapes

Blender's own modelling tools operate on polygon meshes. Seamless CAD does not.
Shapes are computed by **OpenCASCADE (OCCT)**, an industrial B-Rep kernel, which
runs as a **separate process** alongside Blender. Blender receives the result and
draws it.

This has consequences worth knowing:

- The add-on ships an executable (`cad_server.exe`). This is the kernel, not
  a network service — it is why the add-on is currently Windows-only.
- The first **Start Seamless CAD** takes a moment because the process is starting.
- Surfaces are exact. A cylinder is a mathematical cylinder, not a many-sided
  prism. What you see in the viewport is a mesh *approximation* of that exact
  surface, generated for display only.
- Blender's mesh editing tools do not apply to CAD shapes. To get a real Blender
  mesh you must **Bake to Mesh**.

## The proxy and the result

Each entry in the Feature Tree has a lightweight **proxy** object in the
viewport. The proxy is what you select and move; it carries position, rotation
and scale.

When you move a proxy with <kbd>G</kbd> / <kbd>R</kbd> / <kbd>S</kbd>, Blender
tells the add-on the proxy moved, the kernel recomputes, and the drawn result
follows. This is why standard Blender navigation and transform keys work
normally — they are acting on ordinary Blender objects.

## The Feature Tree is a program, not a layer stack

The Feature Tree is evaluated **top to bottom**. Each entry's **Operation**
(`Base` / `Add (Fuse)` / `Subtract (Cut)` / `Intersect (Common)`) says how it
combines with the accumulated result of everything above it.

This means **order is meaningful**, and changing it changes the result. A fillet
placed before a boolean rounds a different edge than the same fillet placed
after it.

`Base` is worth singling out: it discards the accumulated result and starts
fresh. An entry set to `Base` partway down the tree effectively cuts the history
in two. The Property Editor offers **Separate Previous to New Part** at that
point, which splits the discarded portion into its own part rather than leaving
it inert.

### Rollback

The pin icon at the right of each Feature Tree row sets a **rollback point**.
Evaluation stops there; rows below are greyed out and ignored.

Use it to inspect an intermediate state, or to insert an operation into the
middle of an existing history. Unpin to restore full evaluation.

Some controls are disabled while a rollback point hides them — **Edit Sketch**
is one. The panel says "Hidden by rollback point" rather than silently doing
nothing.

## Face and edge identity — why Cleanup is manual

Operations like Fillet, Chamfer, Shell and Draft do not store "the edge at these
coordinates." They store a reference to a specific face or edge **identity** in
the kernel's topology. That is what makes them survive when you go back and
change a dimension: the fillet still refers to the same edge, even though the
edge has moved.

This is also the reason **Cleanup (Unify)** is opt-in and never applied
automatically. Merging coplanar faces destroys the identities of the faces it
merges. Any fillet or offset referring to one of them loses its target. It is a
useful operation before export, and a destructive one in the middle of a live
history, so the decision is left to you.

The same mechanism explains why selection happens in a dedicated **Selection
Mode** rather than through Blender's normal selection: you are picking kernel
topology, not mesh elements.

## Display quality is separate from real quality

The **Linear** and **Curvature** settings control how finely the exact surface is
converted into display triangles. They affect only what you see. They do not
change the model, and they do not change STEP export, which writes the exact
surfaces.

**Bake to Mesh** is the one place display quality matters for output, which is
why **Use High Quality Bake** exists as a separate setting — you can work at a
coarse, responsive display quality and still bake finely.

The **Fast Modifier Preview** and **Live Boolean Preview** options go further:
during a drag they show an approximate result computed by a faster path. The
result you get when you release is always computed exactly. If a preview ever
looks wrong, that is what these options are; turn them off.

## See also

- [Quick Start](quickstart.md)
- [Modelling operations](modeling.md)
- [Known limitations](limitations.md)
