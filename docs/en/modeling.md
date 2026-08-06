# Modelling operations

A reference for the **Create** and **Modify & Pattern** panels. For the ideas
behind them, see [How it works](concepts.md).

Every operation below adds an entry to the Feature Tree, and every entry can be
re-selected and re-edited later.

---

## Create

### Solids

| Button | Shape |
|---|---|
| **Box** | Rectangular block |
| **Cyl** | Cylinder |
| **Sph** | Sphere |
| **Cone** | Cone (a second radius makes it a truncated cone) |
| **Torus** | Torus |

### Curves and profiles

| Button | Shape |
|---|---|
| **Curv** | Bézier curve |
| **Plin** | Polyline. Individual corners can be flagged for filleting |
| **Arc** | Arc |
| **Surf** | Surface |
| **Slot** | Slot |
| **Poly** | Regular polygon |
| **Gear** | Parametric gear |
| **Helix** | Helix |
| **Rev** | Revolve — sweeps a profile around an axis |

When a **Curv**, **Plin** or **Surf** entry is the active one, the Feature Tree
expands it in place to show each control point as an editable `P0`, `P1`, …
coordinate, with buttons to insert or remove points. For a **Plin**, each point
also carries a fillet toggle.

### Swept shapes

| Button | Shape |
|---|---|
| **Sweep** | Sweeps a profile along a path |
| **Loft** | Blends between two or more profiles |

### Grouping

**Group (** and **Group )** insert a matching pair of markers into the Feature
Tree. Entries between them are treated as one unit, and the tree indents them so
the nesting is visible. Use this when a sequence of operations should combine
with the rest of the model as a single result rather than one at a time.

**Group Selection**, at the top of the Feature Tree panel, wraps the rows you
have ticked in a new group.

### Sketching

| Button | Action |
|---|---|
| **Start Sketch** | Opens sketch mode on a plane |
| **on Face** | Picks an existing face to sketch on first |

See [Sketching](sketching.md).

**Dynamic Box Hole** creates a box-shaped hole driven by a loft, for cases where
a plain boolean is not enough.

---

## Modify & Pattern

### Modification

These operate on faces or edges you have selected in **Selection Mode**, and
their parameter appears in the **Active Property Editor**.

| Button | Parameter | Notes |
|---|---|---|
| **Fillet** | Fillet Radius | Rounds selected edges. Supports a different radius per edge — see below |
| **Chamf** | Chamfer Distance | Flat cut instead of a round |
| **Offset** | Offset Distance | Moves selected faces along their normal |
| **Inset** | Inset Distance, Depth (Push/Pull) | Insets a face and optionally pushes or pulls it |
| **Draft** | Draft Angle | Tapers faces. Needs both a **Neutral Plane** and the **Faces to Taper** |
| **Shell** | Thickness | Hollows the solid. The faces you select under **Faces to Remove** become the opening |
| **Face Loft** | — | Lofts between selected faces |
| **Face Rev** | — | Revolves a selected face |

**Variable fillet.** Once a Fillet has targets, the Property Editor lists each
edge separately with a **Use Default** / **Custom** toggle. Switch an edge to
Custom to give it its own radius while the others follow the main value.

**The eyedropper icon** next to Offset and Inset starts an interactive pick, so
you can set the distance by dragging in the viewport instead of typing it.

**Draft** requires two different selections and will tell you so
("Select base face and draft face") until both are set. The neutral plane is the
reference that stays put; the target faces are the ones that tilt.

### Topology

**Cleanup (Unify)** merges coplanar faces, simplifying the topology.

It is deliberately manual. Merging faces destroys the face identities that
Fillet, Offset and Shell refer to, so applying it in the middle of a live history
can break operations below it. It is most useful as a final step before export.
See [How it works](concepts.md) for the reasoning.

The **refresh icon** beside it forces a full recompute. Use it if a result looks
stale after an edit.

### Layout & Patterns

| Button | Operation |
|---|---|
| **Mirror** | Mirrors the accumulated result |
| **Array** | Linear array |
| **Circ** | Circular array |
| **Link** | Linked instance |

For these four, the Property Editor offers an **Independent** toggle. It controls
whether the pattern's own transform is applied on top of the source geometry's
transform or independently of it.

---

## Placement & Snap

| Control | What it does |
|---|---|
| **Surface Snapping** | Snaps newly placed shapes onto existing surfaces |
| **Interactive Placement** | Place a shape by clicking in the viewport |
| **Visual Snap Move** | Move an existing shape with snapping assistance |

Newly created shapes appear at the 3D cursor. The status message tells you which
rule was applied — including "Placed at Cursor (Snapping is OFF)", so you can
tell the difference between snapping that failed and snapping that was never on.

---

## Transform

For most entry types the Property Editor shows two separate transforms:

- **Global** — the shape's position in the scene
- **Local Offset** — an additional offset applied in the shape's own frame

Keeping them apart lets you nudge a shape relative to its own orientation
without disturbing the placement it inherited.

## See also

- [Sketching](sketching.md)
- [Quality and performance](quality.md)
- [Import and export](import-export.md)
