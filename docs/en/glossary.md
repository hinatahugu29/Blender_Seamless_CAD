# Glossary

Terms as this add-on uses them. Where a word means something different in
Blender than it does in CAD, that difference is called out — those are the ones
that cause confusion.

## Core concepts

**B-Rep** (Boundary Representation)
: How the kernel describes a solid: exact surfaces, edges and vertices with
  mathematical definitions, not triangles. A cylinder is a cylinder, at any zoom
  level. STEP export writes B-Rep; **Bake to Mesh** throws it away.

**Kernel**
: The geometry engine — OpenCASCADE (OCCT) — running as a separate process
  alongside Blender. Everything you see in the viewport is a picture of what it
  computed. See [How it works](concepts.md).

**Proxy**
: The lightweight Blender object that stands in for a Feature Tree entry. It
  carries position, rotation and scale, and it is what you select and move with
  <kbd>G</kbd> / <kbd>R</kbd> / <kbd>S</kbd>. It is not the geometry.

**Non-destructive**
: A shape stays editable after you make it. A box created twenty operations ago
  is still a box with a width you can retype. The opposite of Blender's mesh
  modelling, where the box stops being a box the moment you edit it.

**Tessellation**
: Converting an exact surface into triangles so it can be drawn. Controlled by
  **Linear** and **Curvature**. It affects display and baking only, never STEP
  export. See [Quality and performance](quality.md).

## The tree

**Feature Tree**
: The ordered list of operations that produces the model. Evaluated top to
  bottom. It is the model; the viewport is its result. See
  [The Feature Tree and parts](feature-tree.md).

**Entry** / **Feature** / **Primitive**
: One row of the Feature Tree. All three words appear in the interface and mean
  the same thing. "Primitive" is the internal name and shows up in a few button
  tooltips even for things that are not primitive shapes, like Fillet.

**Operation**
: How an entry combines with everything above it: `Base`, `Add (Fuse)`,
  `Subtract (Cut)` or `Intersect (Common)`.

**Rollback point**
: The pin. Evaluation stops at that row; everything below is ignored.

**Part**
: One independent Feature Tree, one Blender collection. Only the active part is
  evaluated. Not to be confused with a "part" in the manufacturing sense, though
  they usually coincide.

**Group**
: A `Group (` / `Group )` pair. Entries between them combine with the rest of the
  model as a single unit rather than one at a time.

**Target**
: What an entry acts on. Patterns and sweeps target another *entry*, by UUID.
  Modifiers target specific *faces or edges*, picked in Selection Mode.

**Face and edge identity**
: The kernel's internal reference to a specific face or edge. Fillet stores an
  identity, not coordinates, which is why it survives when you change a dimension
  earlier in the tree — and why **Cleanup (Unify)** can break it.

## Operations

**Fillet** / **Chamfer**
: Rounding an edge / cutting it flat. Both exist twice: in 3D under
  **Modify & Pattern**, and in 2D on sketch corners. They are different
  operations with the same names.

**Draft**
: Tapering a face by an angle, as needed for moulding. Requires two selections:
  the **Neutral Plane** that does not move, and the **Faces to Taper** that tilt.

**Shell**
: Hollowing a solid to a wall thickness. **Faces to Remove** become the openings.

**Inset** / **Offset**
: Insetting takes a face inwards within its own boundary; offsetting moves a face
  along its normal.

**Loft**
: Blending between two or more profiles. **Face Loft** does the same between
  selected faces of existing solids.

**Sweep**
: Running a profile along a path.

**Revolve**
: Rotating a profile around an axis.

**Cleanup (Unify)**
: Merging coplanar faces to simplify topology. Deliberately manual, because
  merging destroys face identities. A final step before export, not a
  mid-history one.

**Instance** / **Link**
: A copy that shares the source body rather than duplicating it.

**Independent**
: A toggle on patterns. It decides whether the pattern's own transform stacks on
  top of the source shape's transform or replaces it.

## Sketching

**Constraint**
: A rule the solver must satisfy — distance, parallel, tangent, and so on. You
  draw roughly, then constrain.

**GCS** (Geometric Constraint Solver)
: The component that finds positions satisfying all the constraints at once.

**Construction geometry**
: Lines kept for reference — to constrain against, to mirror about — that are not
  built into the resulting shape.

**Over-constrained**
: More constraints than the geometry has freedom for, so the sketch stops moving
  the way you expect. The constraint list is where you find the culprit.

**Inference**
: The temporary dotted guide shown when your cursor lines up with an existing
  point.

**Island**
: One closed region of a sketch. A sketch with three separate closed loops
  produces three Feature Tree entries.

## Output

**Bake**
: Converting the CAD result to an ordinary Blender mesh. A snapshot — it does not
  stay linked.

**STEP**
: The neutral CAD exchange format. Export is AP214 IS, and carries part names
  and assembly structure. Colours are not written.

**AP214**
: The STEP application protocol used for export. Recipients occasionally ask
  which one; this is the answer.

## See also

- [How it works](concepts.md)
- [The Feature Tree and parts](feature-tree.md)
- [Modelling operations](modeling.md)
