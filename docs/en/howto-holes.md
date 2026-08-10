# How to: cut holes and pockets

Cutting is not a separate tool. You add a shape and set its **Operation** to
`Subtract (Cut)`, and it removes itself from everything above it in the tree.

Because the cutting shape stays in the tree as an editable entry, you can change
a hole's diameter later by selecting it and retyping a number.

## A round hole

1. **Create > Cyl** to add a cylinder
2. Position it so it passes through the material — with <kbd>G</kbd> in the
   viewport, or by typing coordinates in the **Active Property Editor**
3. With the cylinder still active, set **Operation** to `Subtract (Cut)`

<!-- TODO(image): a box with a cylinder passing through it, and the same after Subtract -->

**Make the cutter longer than the material.** A cylinder whose end sits exactly
flush with a face is a coincident-surface case, and coincident surfaces are where
boolean operations in any kernel are least reliable. Overshoot on both sides.
Nothing about the result changes; the robustness does.

## A shaped pocket

For anything that is not a circle:

1. Select the face you want to cut into
2. **Create > on Face**
3. Draw and constrain the outline — see
   [How to: turn a sketch into a solid](howto-sketch-to-solid.md)
4. **Apply**
5. Select the **Sketch Surface** entry, set **Extrude Height** to a **negative**
   value — this pushes it into the material rather than out of it
6. Set **Operation** to `Subtract (Cut)`

To make it a through hole rather than a pocket, use a negative height larger than
the material is thick.

## Many holes at once

Do not create the same hole ten times. Cut one, then pattern it:

1. Cut the first hole, as above
2. **Modify & Pattern > Array** (linear) or **Circ** (circular)
3. In the Property Editor, set the pattern's **Target** to the cutting shape —
   with **Pick Target** from the list, or **Pick Target in Viewport**
4. Set the count and spacing
5. Set the pattern entry's own **Operation** to `Subtract (Cut)` as well, so the
   copies cut too

Changing the original hole's diameter afterwards changes every copy, because the
pattern refers to the entry rather than to a copy of its geometry.

> The **Independent** toggle decides whether the pattern's transform stacks on
> top of the source shape's transform or replaces it. If a pattern lands
> somewhere unexpected, that is the setting to look at.

## Rounding the edges of a hole

1. **Selection Mode > ENTER Selection Mode**
2. Set the selection type to edges
3. Click one edge of the hole, then <kbd>Ctrl</kbd>+click an edge further round
   it — the shortest path between them is selected in one go, and the path is
   previewed while you hover
4. **Modify & Pattern > Fillet**, then set the radius

For a hole's rim this is usually two clicks rather than eight.

**Variable radius:** once Fillet has targets, the Property Editor lists each edge
with a **Use Default** / **Custom** toggle. Only the edges you set to Custom get
their own radius.

## Order matters

A fillet applied **before** a boolean rounds the shape as it was then; the same
fillet **after** rounds the result. These are different models, and the tree
cannot be reordered — see
[The Feature Tree and parts](feature-tree.md).

The practical rule: **cut first, round afterwards.** Rounding a hole that has not
been cut yet rounds the cutter, which is rarely what you meant.

## When a cut does not work

**Nothing was removed.** Check the **Operation** is actually `Subtract (Cut)` and
that the cutter overlaps the material. A cutter that only touches the surface
removes nothing.

**The result looks wrong while dragging but right when released.** That is
**Live Boolean Preview**. Turn it off in **Quality & Export** if it bothers you;
the committed result was always exact. See
[Quality and performance](quality.md).

**The cut worked, then broke after an earlier edit.** A fillet or offset below it
lost the face it referred to. See [Troubleshooting](troubleshooting.md).

## See also

- [How to: turn a sketch into a solid](howto-sketch-to-solid.md)
- [Modelling operations](modeling.md)
- [Keyboard and mouse](shortcuts.md#selection-mode)
