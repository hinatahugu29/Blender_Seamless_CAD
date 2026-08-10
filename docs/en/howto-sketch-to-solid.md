# How to: turn a sketch into a solid

A sketch does not produce a solid by itself. It produces a **face**, and you give
that face a thickness afterwards. This is the step people miss — the sketch
applies, something appears in the tree, and nothing looks three-dimensional.

Before you start: [Sketching](sketching.md) covers the tools and constraints in
full. This page is the path from an empty plane to a solid you can cut.

## 1. Start the sketch

From the **Create** panel:

- **Start Sketch** — sketch on a plane
- **on Face** — select an existing face first, then sketch on it

Use **on Face** whenever the profile belongs to an existing shape. The sketch
inherits that face's plane, so you do not have to place it by hand.

## 2. Draw roughly, then constrain

This is the intended order, and it is faster than it sounds. Draw the shape
approximately with the pen tools, then pin it down:

1. Draw with **Line**, **Circle**, **Rectangle**, and the rest
2. Select geometry and apply constraints — **Distance** for dimensions,
   **Align X** / **Align Y**, **Parallel**, **Tangent**
3. Fix at least one point with **Fixed**, or the whole profile can slide

Snapping is automatic while you draw, and the indicators tell you what caught —
see [Keyboard and mouse](shortcuts.md#sketch-mode).

If the sketch will not move the way you expect, open
**Constraints / Parameters** and look for a constraint you did not intend to
add. Over-constraining is the usual cause.

## 3. Apply

**Apply**, at the bottom of the sidebar. **Cancel** discards the sketch.

<!-- TODO(image): the same sketch before and after Apply, showing the Feature Tree entries it produced -->

What you get depends on what you drew:

| What you drew | What appears in the Feature Tree |
|---|---|
| A closed region | **Sketch Surface** — a face |
| A closed region with a closed region inside it | One **Sketch Surface**, with the inner loop as a hole |
| Three separate closed regions | Three **Sketch Surface** entries |
| An open run of lines | **Sketch Curve** |

Construction geometry produces nothing. That is what it is for.

## 4. Give it thickness

Select the **Sketch Surface** entry and look at the **Active Property Editor**:

| Property | Effect |
|---|---|
| **Extrude Height** | Thickness. **Defaults to `0.0`**, which is why a fresh sketch surface is flat |
| **Fill Closed** | Whether a closed outline gets a face at all. On by default |
| **Use Pipe** / **Pipe Radius** | Instead of extruding, sweep a round tube along the outline |

Set **Extrude Height** to a non-zero value and the face becomes a solid.

**A negative value extrudes the other way.** That is the whole trick to cutting a
pocket into the face you sketched on: sketch **on Face**, set a negative height,
set **Operation** to `Subtract (Cut)`.

## 5. Combine it

Set **Operation** like any other entry — `Add (Fuse)` to join, `Subtract (Cut)`
to cut. It combines with everything above it in the tree. See
[The Feature Tree and parts](feature-tree.md).

## Editing the sketch later

Select the entry and press **Edit Sketch** in the Property Editor. The original
sketch reopens with its constraints intact.

The rebuilt entry **keeps its position in the tree**, so fillets and other
downstream operations stay attached — as long as the sketch still produces the
same number of separate closed regions. Split one region into two and the
rebuilt entries go to the end of the tree instead, and the add-on warns you that
downstream features may need reassigning.

> If **Edit Sketch** is greyed out and says "Hidden by rollback point", the entry
> is below an active pin. Unpin it first.

## See also

- [Sketching](sketching.md)
- [How to: cut holes and pockets](howto-holes.md)
- [The Feature Tree and parts](feature-tree.md)
