# The Feature Tree and parts

The Feature Tree is the model. The viewport shows what it currently evaluates
to; the tree is the thing you actually edit.

This page is the reference for the **Feature Tree** panel and for the
**Active CAD Workspace** panel above it. For *why* it works this way, see
[How it works](concepts.md).

## A row

<!-- TODO(image): the Feature Tree panel with a few entries, one active, one pinned -->

Each row is one operation, and carries these controls, left to right:

| Control | What it does |
|---|---|
| Radio button | Makes the entry **active**. The **Active Property Editor** below then shows its parameters |
| Checkbox | Marks the entry for **Group Selection** (see below). Nothing else uses it |
| Name and icon | Also makes the entry active. The icon reflects the operation type |
| Duplicate | Copies the entry and makes the copy active |
| **X** | Deletes the entry |
| Eye | **Suppresses** the entry: it stays in the tree but is left out of the model (see below) |
| Pin | Sets or clears the **rollback point** |

Rows below an active rollback point are greyed out and their buttons are
disabled. A suppressed row is dimmed but stays clickable.

To **rename** an entry, make it active and edit the name at the top of the
**Active Property Editor**. The proxy object in the outliner is renamed with it.
If the name is already taken, Blender adds `.001` and the tree follows.

Entries inside a group are indented, so nesting is visible at a glance.

### Curve entries expand in place

When a **Curv**, **Plin** or **Surf** entry is the active one, the tree expands
underneath it and lists every control point as an editable `P0`, `P1`, … with
add and remove buttons per point, plus **Add Point** at the end. Polyline points
additionally get a per-corner fillet toggle.

This is the only place those points can be edited numerically.

## Order is creation order, and it is fixed

The tree is evaluated **top to bottom**, and position is **creation order**.

Two things follow, and they are worth knowing before you build something long:

- **Rows cannot be reordered.** There is no move-up or move-down.
- **New operations are always appended to the end.** There is no way to insert
  one into the middle. Setting a rollback point does not change this — a new
  entry created while a pin is set still lands at the bottom, *below* the pin,
  where it is greyed out and not evaluated. If a shape you just created did not
  appear, check whether a pin is set.

So think about order as you build. If you need an operation earlier than
everything you have already made, the practical options are to delete and redo
the later entries, or to change what the existing entries do:

- Change an entry's **Operation** — the same shape cutting instead of fusing
  often gets you where reordering would have
- Use a **group** so a run of entries combines as one unit
- Split into two parts with `Base` and **Separate Previous to New Part**
- **Suppress** an entry to see or build the model without it, instead of
  deleting it

The one exception is **Edit Sketch**: re-editing a sketch rebuilds its entry in
place and keeps its original position, so downstream fillets stay attached. That
holds as long as the sketch still produces the same number of separate closed
regions. If that number changes, the rebuilt entry goes to the end and the
add-on warns you that downstream features may need reassigning.

## Operation

Every entry combines with the accumulated result of everything above it,
according to its **Operation**, set in the Property Editor:

| Value | Effect |
|---|---|
| `Base` | Discard everything above and start fresh from here |
| `Add (Fuse)` | Union. The default |
| `Subtract (Cut)` | Cut out of the result so far |
| `Intersect (Common)` | Keep only the overlap |

### Base, and splitting a part

An entry set to `Base` cuts the history in two: everything above it stops
contributing. The Property Editor then offers **Separate Previous to New Part**,
which turns that discarded upper portion into a part of its own instead of
leaving it inert.

It asks which of two things you want:

| Mode | Effect | Risk |
|---|---|---|
| **Move (Clean up original)** | Moves the earlier entries out of this part | Anything below that referred to them — a fillet's target face, a pattern's target — loses its reference |
| **Copy (Keep references)** | Copies them to the new part and leaves them here as history | Safe for references; the original stack keeps growing |

Choose **Copy** unless you have checked that nothing below depends on the
entries being moved.

## Rollback

The pin sets a rollback point. Evaluation stops there; everything below is
ignored and greyed out. Pressing the pin on the row that already holds it clears
it.

Rollback has three distinct uses:

- **Inspecting** an intermediate state
- **Editing safely** — hiding downstream operations while you change something
  they depend on
- **Performance.** Everything below the pin stops being evaluated, which is the
  most effective single thing you can do to keep a long history responsive while
  you work on an early operation

Some controls are deliberately disabled while a rollback point hides their
target — **Edit Sketch** is the one you will meet. The panel says "Hidden by
rollback point" rather than doing nothing silently.

## Suppress

The eye icon takes **one** entry out of the model without deleting it. Press it
again to bring the entry back.

It differs from rollback in one way that matters: rollback stops everything
below the pin, while suppress removes only that row. Everything below it keeps
evaluating.

A suppressed Mirror, Array or other entry that acts on a target no longer uses
that target, so the original shape shows again.

**Fillets and other edge or face picks below a suppressed row can change.**
They refer to specific edges and faces, and removing a shape above them changes
which edges exist. In testing, suppressing one of two fused boxes left a fillet
on only some of its edges, and suppressing the box the fillet was picked on
removed the fillet entirely, with no error. Un-suppressing restores both.

## Parameters

The **Parameters** panel (closed by default) holds named values for the active
part, and lets any entry take a field from an expression.

<!-- TODO(image): Parameters panel with width / hole parameters and a driven Size X -->

**Add Parameter** creates a row with a name and an expression, and shows the
value it evaluates to. Expressions may use:

- numbers and other parameter names: `width / 4 + 1`
- `+ - * / // % **` and parentheses
- `sqrt sin cos tan radians degrees abs min max round floor ceil`, and `pi`

Nothing else is accepted, on purpose — a `.blend` file may come from someone
else, so an expression can never run code.

Below the list, **Drive a Field** binds a field of the active entry to an
expression: Size X/Y/Z, Location X/Y/Z, Rotation X/Y/Z (in degrees), Radius,
Radius 2, Minor Radius, Pipe Radius, Extrude Height, Value/Angle, Count,
Sides/Teeth, Turns, Module, Angle Start and Angle End. The expression starts as
the field's current value, so binding a field does not change the shape.

Things to know:

- **A driven field follows its expression.** If you move it by hand — typing a
  number, or dragging the proxy — it goes back to the expression's value the next
  time any parameter changes. The panel says so when an entry has driven fields.
- **Renaming a parameter updates the expressions that use it.** `width` becomes
  `w` everywhere; `width2` is left alone.
- **Errors do not break the model.** A circular reference, an unknown name or a
  typo is shown in red on that row, and the field keeps its last good value.
- Driven fields are kept when an entry is duplicated or grouped.

## Groups

**Group (** and **Group )** insert a matching pair of markers. Everything between
them is treated as one unit when it combines with the rest of the model, rather
than each entry combining one at a time.

**Group Selection**, at the top of the panel, wraps the rows you have checked in
a new group. It has rules, and it tells you when you break one:

- **At least two rows**, and they must be a **contiguous range**. Checking rows
  with a gap between them is refused
- **Existing group boundaries cannot be crossed.** A new group must nest cleanly
  inside or outside an old one, not straddle its edge
- If a row inside the new group **references a primitive outside it** — a sweep
  path, a loft profile, a pattern target — you are warned, because the reference
  now crosses a group boundary

## Targets: entries that point at other entries

Not every entry contains its own geometry. Mirror, Array, Circ, Link, Sweep and
Loft act on *another* entry, referred to by an internal UUID rather than by
position. Two controls set that reference:

- **Pick Target (list)** — a dialog listing the other entries in this part by
  name
- **Pick Target in Viewport** — click the object in the viewport instead

Because the reference is a UUID, it survives edits above it in the tree. It does
**not** survive the target being deleted, or being moved to another part by
**Separate Previous to New Part** in Move mode.

Modifier entries — Fillet, Chamfer, Offset, Inset, Draft, Shell — work
differently. They refer to specific faces or edges picked in
[Selection Mode](shortcuts.md#selection-mode), not to whole entries.

## Parts

The **Active CAD Workspace** panel, at the top of the sidebar, selects which part
you are editing.

| Control | What it does |
|---|---|
| Dropdown | Chooses the active part |
| **Add New CAD Part** | Creates another, independent part |
| Trash icon | Deletes the active part and frees its geometry |

Every panel below it applies to the **active part only**. If those panels are
missing entirely, no valid part is selected — pick one from the dropdown.

In Blender's outliner, parts are collections: `Part_1`, `Part_2`, … inside a
`Seamless_CAD` collection, plus a `Result` collection that receives baked meshes.
Numbering fills the first free name, so deleting `Part_2` and adding a new part
gives you `Part_2` again, not `Part_3`.

**Only the active part is evaluated.** Splitting a model into several parts is
therefore a performance tool as well as an organisational one — see
[Quality and performance](quality.md).

## See also

- [How it works](concepts.md)
- [Modelling operations](modeling.md)
- [Keyboard and mouse](shortcuts.md)
