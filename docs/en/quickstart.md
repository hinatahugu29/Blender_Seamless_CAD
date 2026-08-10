# Quick Start

This guide takes you from a fresh install to a finished part exported as STEP.
It should take about ten minutes.

Seamless CAD is in beta and sold for Windows. This guide applies to the macOS
and Linux [testing builds](testing-builds.md) too — the add-on is the same.

---

## 1. Install

1. In Blender, open `Edit > Preferences > Add-ons > Install...`
2. Select the `CAD_<version>_install.zip` file
3. Enable the add-on
4. Press <kbd>N</kbd> in the 3D viewport to open the sidebar. A **Seamless** tab
   appears.

Blender 4.2 or newer is required. Development and testing are done on 5.1.

## 2. Start a session

Open the **Seamless** tab. Before anything else exists, the sidebar shows a
single button:

- **Start Seamless CAD**

Press it. This launches the geometry kernel and creates your first CAD part.

> **What is actually happening:** shapes are not computed by Blender's mesh
> system. They are computed by OpenCASCADE (OCCT) in a separate process, and
> Blender draws the result. This is why the add-on ships an executable and why
> the first start takes a moment.

## 3. Understand the workspace

The **Active CAD Workspace** panel controls which part you are editing.

- The dropdown selects the active part collection
- **Add New CAD Part** creates another, independent part
- The trash icon removes the active part

Everything in the panels below applies to the *active part only*. If the panels
below are missing, no valid part is selected — pick one from the dropdown.

## 4. Create your first shape

Open the **Create** panel and press **Box**.

A box appears in the viewport, and a corresponding entry appears in the
**Feature Tree** panel. These are the same object seen two ways: the viewport
shows the computed result, and the Feature Tree shows the recipe that produced it.

The Create panel is organised in rows:

| Row | Contents |
|---|---|
| Solids | Box, Cyl, Sph, Cone, Torus |
| Curves and profiles | Curv, Plin, Arc, Surf, Slot, Poly, Gear, Helix, Rev |
| Swept shapes | Sweep, Loft |
| Grouping | Group ( , Group ) |
| Sketching | Start Sketch, on Face |

## 5. Edit it after the fact — this is the point

Click the box's entry in the **Feature Tree**. The **Active Property Editor**
panel below now shows its parameters. Change the width.

The shape rebuilds. Nothing was destroyed, and you can change it again.

This is what "non-destructive" means here, and it is the main reason to use this
add-on instead of Blender's own modelling tools. A box you created twenty
operations ago is still a box with editable dimensions.

You can also move a shape directly: select its proxy in the viewport and use
<kbd>G</kbd> / <kbd>R</kbd> / <kbd>S</kbd> as you normally would in Blender. The
geometry follows in real time.

## 6. Cut a hole

1. Press **Cyl** to add a cylinder
2. Position it so it passes through the box
3. Select the cylinder in the Feature Tree, and in the **Active Property
   Editor** change **Operation** from `Add (Fuse)` to `Subtract (Cut)`

The **Operation** dropdown is how every shape combines with what came before it:

| Value | Effect |
|---|---|
| `Base` | Start over. Everything above is discarded from this point. |
| `Add (Fuse)` | Union with the shapes above. This is the default. |
| `Subtract (Cut)` | Cut out of the shapes above. |
| `Intersect (Common)` | Keep only the overlap with the shapes above. |

The Feature Tree is evaluated top to bottom, so the cylinder subtracts from
everything above it. Order matters — this is a history, not a layer stack.

## 7. Round the edges

1. Enter selection mode: **Selection Mode > ENTER Selection Mode**
2. Choose whether you are picking faces or edges using the selection type buttons
3. Click the edges you want in the viewport
4. Open **Modify & Pattern** and press **Fillet**

> **Hint:** while in selection mode, hold <kbd>Alt</kbd> to use the normal
> Blender gizmo without leaving the mode.

**Chamf** does the same with a flat cut instead of a round.

## 8. Control quality and speed

The **Quality & Export** panel governs how finely the kernel's result is
converted into a mesh for display.

- **Linear** and **Curvature** — display tessellation. Lower values are finer
  and slower.
- **Fast Modifier Preview** and **Live Boolean Preview** — trade exactness for
  responsiveness while you drag. Turn these off if a preview looks wrong; the
  final result is always computed exactly.
- **Use High Quality Bake** — a separate, finer setting used only when baking,
  so you can work at a coarse display quality without affecting output.

## 9. Roll back through history

Each Feature Tree row has a pin icon on the right. Pinning a row makes the part
evaluate only up to that point; everything after it is greyed out and ignored.

Use this to inspect an intermediate state, or to keep a long history responsive
while you edit something early in it. Unpin to restore the full tree.

Note that new operations are always added to the *end* of the tree, never at the
pin. If you create a shape while a pin is set, it lands below the pin and is not
evaluated — which looks like nothing happened.

## 10. Get the result out

Two ways, for two different purposes:

**Bake to Mesh** (`Quality & Export > Bake to Mesh`) converts the part into an
ordinary Blender mesh. Use this for rendering, sculpting, or anything that needs
Blender geometry. Enable **Use High Quality Bake** first if the result is for
a render.

**Export STEP** (`Quality & Export > Export STEP`) writes a real B-Rep STEP file
(AP214 IS) for use in other CAD software. This preserves exact surfaces, not a
triangulated approximation.

> **Scale:** on export, 1 Blender unit is written as 1 mm. A 10-unit box arrives
> in FreeCAD or Fusion as a 10 mm box. Set your dimensions with that in mind.
>
> STEP export does not currently carry part names, colours, or assembly
> structure. The geometry is exact; the metadata is not there.

## Where to go next

- **Import STEP** / **Import SVG** bring outside geometry into the tree
- **Start Sketch** draws constrained 2D profiles on a plane or an existing face
- **Modify & Pattern** holds Mirror, Array, Circular array, and linked instances
- **Cleanup (Unify)** merges coplanar faces. It is deliberately opt-in — it is
  not applied automatically, because merging faces destroys the face
  identities that fillets and offsets refer to.

## If something goes wrong

**The Seamless tab is empty below the workspace panel.**
No valid part collection is selected. Pick one from the **Active CAD Workspace**
dropdown, or press **Add New CAD Part**.

**Hide Occluded Edges is greyed out.**
This is intentional. Faces only write depth when the WGPU overlay is off *and*
opacity is fully opaque. Outside those conditions the setting would have no
effect, so it is disabled rather than left as a control that silently does
nothing.

**A shape looks wrong while dragging, but correct when released.**
That is the fast preview. Turn off **Fast Modifier Preview** or **Live Boolean
Preview** to always see the exact result.

**Nothing updates after an edit.**
Press the refresh icon in **Modify & Pattern > Topology** to force a recompute.
