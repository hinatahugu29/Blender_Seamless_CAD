# Keyboard and mouse

Seamless CAD adds **no global shortcuts**. It installs no keymap entries, so
nothing you already use in Blender changes.

Every key on this page works only while one of the add-on's interactive modes is
running. Outside those modes, Blender behaves exactly as it always does — which
is also why <kbd>G</kbd> / <kbd>R</kbd> / <kbd>S</kbd> move a CAD shape: you are
moving an ordinary Blender object, and the geometry follows.

Viewport navigation — middle mouse, the wheel, and the numpad views — is passed
through in every mode below. You never have to leave a mode to orbit.

---

## Sketch mode

Active from **Start Sketch** or **on Face** until you press **Apply** or
**Cancel**.

### Drawing and editing

| Input | Action |
|---|---|
| Left click | Place a point / confirm the current step of the active tool |
| Left drag on geometry | Move a point, a line, or the whole current selection. Constraints stay satisfied while it moves |
| Left drag on empty space | Box select. **Select tool only** |
| <kbd>Shift</kbd>+drag on empty space | Box select, adding to the selection |
| <kbd>Shift</kbd> (held) | Axis lock — constrains the point to horizontal or vertical from where the drag began |
| Right click or <kbd>Esc</kbd> | Leave the current pen tool and return to **Select** |
| <kbd>Del</kbd> or <kbd>X</kbd> | Delete the selection |
| <kbd>Ctrl</kbd>+<kbd>Z</kbd> | Undo — sketch mode has **its own undo stack**, separate from Blender's |
| <kbd>Ctrl</kbd>+<kbd>C</kbd> / <kbd>Ctrl</kbd>+<kbd>V</kbd> | Copy / paste the selection |
| <kbd>Ctrl</kbd>+<kbd>A</kbd> | Select all |
| <kbd>L</kbd> | Chain select — the connected run of geometry. **Select tool only** |
| <kbd>Alt</kbd>+wheel | Halve or double the grid step |
| Left click on a dimension label | Edit that dimension's value. **Select tool only** |

> **Right click and <kbd>Esc</kbd> are consumed.** Neither opens Blender's
> context menu nor cancels the modal operator while sketching. This is
> deliberate — losing an unapplied sketch to a stray right click would be
> expensive.

> **<kbd>Enter</kbd> and <kbd>Space</kbd> do not apply the sketch.** Ending a
> sketch is only possible through the **Apply** and **Cancel** buttons in the
> sidebar, on purpose.

### Snapping while drawing

Snapping is automatic; there is no modifier to hold. Indicators tell you which
one caught:

| Indicator | Meaning |
|---|---|
| Highlighted point | Snapped to an existing point |
| Green triangle | Snapped to the midpoint of a line |
| White dotted guide | Inference — your cursor lines up in X or Y with an existing point |

**Grid Snap** is a toggle in the sidebar rather than a held key, and it is
suspended while <kbd>Shift</kbd> axis lock is active — the two would otherwise
fight over the same coordinate.

---

## Selection Mode

Active from **Selection Mode > ENTER Selection Mode**, used to pick the faces and
edges that Fillet, Chamfer, Offset, Inset, Draft and Shell act on.

| Input | Action |
|---|---|
| Left click | Pick the highlighted face or edge, **replacing** the selection. Clicking an already-picked element removes it |
| <kbd>Shift</kbd>+click | Add to the selection instead of replacing it |
| <kbd>Ctrl</kbd>+click | **Edges only.** Select the shortest edge path from the last picked edge to this one. Hovering with <kbd>Ctrl</kbd> held previews that path before you commit |
| <kbd>Alt</kbd> (held) | Show and use the transform gizmo without leaving selection mode |
| <kbd>Shift</kbd>+<kbd>D</kbd> | Duplicate the active Feature Tree entry |
| Right click or <kbd>Esc</kbd> | Leave selection mode |

<kbd>Ctrl</kbd>+click is the one worth learning: picking every edge around a
pocket one at a time is slow, and the path preview shows you what you are about
to get.

### Dragging a curve control point

While you drag a control point of a **Curv**, **Plin** or **Surf** entry:

| Key | Action |
|---|---|
| <kbd>X</kbd> / <kbd>Y</kbd> / <kbd>Z</kbd> | Constrain to that axis. Press again to release |
| <kbd>Shift</kbd>+<kbd>X</kbd> / <kbd>Y</kbd> / <kbd>Z</kbd> | Constrain to that **plane** instead |
| <kbd>S</kbd> | Toggle snapping on / off |
| <kbd>V</kbd> | Snap to vertices |
| <kbd>M</kbd> | Snap to midpoints |
| <kbd>F</kbd> | Snap to faces |
| <kbd>C</kbd> | Snapping off |

---

## Interactive Placement and Interactive Transform

Active from **Placement & Snap**. The status bar reminds you of the keys.

| Key | Action |
|---|---|
| <kbd>S</kbd> | Toggle snapping |
| <kbd>N</kbd> | Toggle **Align to Normal** — orient the shape to the surface it lands on |
| <kbd>X</kbd> / <kbd>Y</kbd> / <kbd>Z</kbd> | Constrain movement to that axis |
| <kbd>Ctrl</kbd> (held) | Snap to vertices for this moment |
| <kbd>Shift</kbd> (held) | Snap to midpoints for this moment |
| Left click | Confirm |
| Right click or <kbd>Esc</kbd> | Cancel |

---

## Visual Snap Move

Active from **Placement & Snap > Visual Snap Move**. You pick a point on the
shape you are moving, then the point it should land on.

| Input | Action |
|---|---|
| Default | Snap to **faces** |
| <kbd>Shift</kbd> (held) | Snap to **edges** |
| <kbd>Ctrl</kbd> (held) | Snap to **vertices** |
| <kbd>X</kbd> / <kbd>Y</kbd> / <kbd>Z</kbd> | Constrain to that axis — while picking the target only |
| <kbd>Shift</kbd>+<kbd>X</kbd> / <kbd>Y</kbd> / <kbd>Z</kbd> | Constrain to that plane |
| Left click | Confirm the current point |
| Right click or <kbd>Esc</kbd> | Cancel |

The same held-modifier scheme applies to the **eyedropper** beside Offset and
Inset, which picks a distance from the geometry instead of typing one.

## See also

- [Sketching](sketching.md)
- [Modelling operations](modeling.md)
- [The Feature Tree and parts](feature-tree.md)
