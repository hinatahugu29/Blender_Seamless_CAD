# Sketching

Sketch mode draws a constrained 2D profile that becomes a Feature Tree entry.
It is a solver-backed sketcher: you draw roughly, then add constraints that
pin the geometry down.

## Entering and leaving

From the **Create** panel:

- **Start Sketch** — sketch on a plane
- **on Face** — pick an existing face first, then sketch on it

While sketch mode is active the normal panels are replaced by **Seamless CAD -
Sketch Mode**. Two buttons at the bottom end it:

- **Apply** — turns the sketch into a Feature Tree entry
- **Cancel** — discards it

A sketch-derived entry keeps its link to the sketch. Selecting it later shows an
**Edit Sketch** button in the Property Editor, which reopens the original sketch
rather than making you rebuild it.

> If **Edit Sketch** is disabled and the panel says "Hidden by rollback point",
> the entry is below an active rollback pin. Unpin it first.

## Grid

| Control | Effect |
|---|---|
| **Show Grid** | Displays the sketch grid |
| **Grid Snap** | Snaps drawing to the grid |
| **Vertex Snap** | Reuses a nearby existing point instead of creating a new one |

Show Grid and Grid Snap are independent — you can snap to a grid you are not
displaying, and display one you are not snapping to.

**Vertex Snap** is on by default and is what joins your new geometry to what is
already drawn. Turn it off when you want points to stay separate even where they
sit close together, or hold <kbd>Ctrl</kbd> to skip it for one click. Selecting
vertices still works with it off.

## Pen tools

One tool is active at a time.

| Tool | Draws |
|---|---|
| **Select** | Nothing — selects existing geometry |
| **Point** | A single point |
| **Line** | A line segment |
| **Arc** | An arc |
| **Circle** | A circle |
| **Semi-circle** | A half circle |
| **Rectangle** | A rectangle from corner to corner |
| **Center Rect** | A rectangle from its centre outwards |
| **Trim / Extend** | Trims or extends by clicking |
| **Slot** | A slot |

## Selection Info

This box reports what is currently selected — a point, two points, a line, or
two lines — with the internal IDs. The IDs matter because constraints are listed
by the IDs they act on.

With a single point selected you get editable **X** and **Y** fields. With a line
selected you see its start and end point IDs.

When the selection already has a **Distance** constraint on it, its value becomes
editable right here. For an arc the same field is labelled **Radius** instead of
**Length**, because the constraint is between the arc's centre and its midpoint.

## Constraints

| Constraint | Meaning |
|---|---|
| **Fixed** | Pins the selection in place |
| **Distance** | Sets a distance. Only offered when the selection can take one and does not already have one |
| **Align X** | Makes the selection horizontal |
| **Align Y** | Makes the selection vertical |
| **Parallel** | Two lines parallel |
| **Perpendicular** | Two lines at right angles |
| **Coincident (Point Merge)** | Merges two points into one |
| **Midpoint** | Constrains a point to a midpoint |
| **Tangent** | Tangency |

**Distance appears and disappears on purpose.** The button is only shown when the
current selection can take a distance constraint *and* does not already have one.
If it is missing, the constraint already exists — look in Selection Info, where
its value is editable.

### The constraint list

**Constraints / Parameters** toggles a list of every constraint in the sketch.
Each row shows the type and the IDs it acts on, its value if it has an editable
one (Distance and Arc Radius do; the rest show `-`), and a trash icon to delete
it.

This list is the place to go when the sketch will not move the way you expect.
Over-constraining is the usual cause, and this is where you find and remove the
constraint responsible.

## Geometry and actions

| Action | Shortcut | Notes |
|---|---|---|
| **Toggle Construction** | — | Turns geometry into construction geometry, used for reference but not built |
| **Select All** | <kbd>Ctrl</kbd>+<kbd>A</kbd> | |
| **Chain Select** | <kbd>L</kbd> | Selects a connected chain |
| **Copy** | <kbd>Ctrl</kbd>+<kbd>C</kbd> | |
| **Paste** | <kbd>Ctrl</kbd>+<kbd>V</kbd> | Greyed out until something has been copied |
| **Trim** | — | Trims the selection |
| **Extend** | — | Extends the selection |
| **Offset Lines** | — | Offsets by the **Offset** value beside the button |
| **Mirror X** / **Mirror Y** | — | Mirrors the selection |
| **Undo** | <kbd>Ctrl</kbd>+<kbd>Z</kbd> | Sketch mode has its own undo, separate from Blender's |

## Corner tools

| Tool | Value |
|---|---|
| **Fillet** | Fillet Radius |
| **Chamfer** | Chamfer Distance |

Set the value first, then press the button. These act on sketch corners, and are
distinct from the 3D Fillet and Chamfer in **Modify & Pattern**.

## See also

- [Modelling operations](modeling.md)
- [How it works](concepts.md)
