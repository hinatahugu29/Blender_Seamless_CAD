# Troubleshooting

## Nothing computes at all

Open `Edit > Preferences > Add-ons` and expand Seamless CAD. The panel reports
**CAD Engine: Running** or **Not running**, based on the real state of the kernel
process rather than a fixed assumption.

If it says Not running, the kernel process failed to start or has exited. Restart
Blender. If it happens repeatedly, enable **Enable ERROR Logs** (it is on by
default) and check Blender's console output.

## The Seamless tab is empty below the workspace panel

No valid part collection is selected. The panels below **Active CAD Workspace**
only appear when there is one.

Pick a part from the dropdown, or press **Add New CAD Part**.

## Panels disappeared and I see "Sketch Mode"

You are in sketch mode. The normal panels are hidden while it is active. Press
**Apply** or **Cancel** at the bottom of the sketch panel to leave.

## A shape looks wrong while dragging, correct when released

That is the fast preview doing its job. **Fast Modifier Preview** and **Live
Boolean Preview** show an approximation during the drag; the released result is
computed exactly.

Turn them off in **Quality & Export** if you would rather always see the exact
shape. See [Quality and performance](quality.md).

## I have two Blenders open and one of them will not preview

Expected, for now. The kernel that computes geometry runs on a fixed local port,
and the first Blender to start claims it. The second one connects to that same
kernel instead of starting its own, so it is asking a process that holds someone
else's model to draw yours.

Bake to Mesh in the file you are only using for reference, or disable the add-on
there, or close one before working in the other. See
[Known limitations](limitations.md).

## Nothing updates after an edit

Press the refresh icon in **Modify & Pattern > Topology** to force a full
recompute.

If that fixes it consistently, the logs are worth capturing — enable
**Enable WARN Logs** in preferences and report what you see.

## Hide Occluded Edges is greyed out

Intentional, not a bug. Faces only write depth when **Use WGPU Overlay** is off
*and* **Opacity** is fully opaque. In any other combination the setting has
nothing to work with.

Turn off the WGPU overlay and set opacity to fully opaque, and it becomes
available.

## Edit Sketch is greyed out

The panel will say "Hidden by rollback point". The entry sits below an active
rollback pin, so it is not currently being evaluated.

Click the pin icon in the Feature Tree to unpin, then edit.

## A fillet or offset broke after I changed something earlier

Fillets, chamfers, offsets, shells and drafts refer to specific face and edge
identities in the kernel's topology. Most edits preserve those identities, which
is why the operations survive dimension changes. Some do not.

The usual culprit is **Cleanup (Unify)** somewhere above the operation in the
tree — merging coplanar faces destroys the identities of the faces it merges.
This is why Cleanup is manual and best kept as a final step before export. See
[How it works](concepts.md).

Reselect the targets for the affected operation to repair it.

## The Distance constraint button vanished in sketch mode

It is only shown when the current selection can take a distance constraint *and*
does not already have one. If it is missing, the constraint already exists.

Look at **Selection Info** — the existing constraint's value is editable there.
For arcs it appears as **Radius** rather than **Length**.

## The sketch will not move the way I want

Usually over-constrained. Turn on **Constraints / Parameters** in the sketch
panel for a full list of constraints with the IDs they act on, and delete the one
that is holding it. See [Sketching](sketching.md).

## Everything is slow, not just one operation

If the whole add-on feels slow regardless of what you do — including on hardware
that should have no trouble — work through these in order:

1. **Check for a leftover kernel process.** Task Manager (Ctrl+Shift+Esc) →
   Details → look for `cad_server.exe`. If there is more than one, or one is left
   over from a session that crashed, close them all and restart Blender. A stale
   kernel keeps answering while holding the wrong state.
2. **Turn off Use WGPU Overlay and set Opacity fully opaque.** These two interact,
   so testing them one at a time can miss the effect. The overlay is experimental
   and the add-on is expected to run faster with it off.
3. **Check whether security software is inspecting local connections.** Blender
   and the kernel talk over a local TCP port. Software that hooks that traffic can
   slow every operation noticeably.
4. **Capture a profile.** Enable **Perf Logging** in preferences, perform the slow
   action once, then look at `seamless_cad_profile.log` in your OS temp directory.
   It shows where the time actually goes, which beats guessing.

When reporting it, say which of drag, release, or startup is the slow part — they
are different parts of the pipeline and the answer narrows things down a lot.

## Editing an early operation is slow

Expected. Everything below the edited operation must be recomputed, so an edit
near the top of a long history costs more than one near the bottom. This is
inherent to history-based CAD.

Set a rollback point just below the operation you are working on. Everything
under the pin stops being evaluated until you unpin.

## Dimensions came out 1000× wrong in another CAD program

On STEP export, **1 Blender unit is written as 1 mm**. A 10-unit box arrives as
10 mm. If your scene was built assuming 1 unit = 1 m, everything will be a
thousand times too small.

There is no export scale option, so the fix is to build at the right scale, or
to rescale in the receiving application.

## The exported STEP has no colours

Correct, and expected. There is nowhere in the addon to set a colour, so there
is nothing for the file to carry.

**Names and assembly structure are written**, though. If your file arrives
unnamed, check that you are exporting STEP and not IGES — IGES carries geometry
only. The product name comes from the Part's collection name, so renaming the
collection renames the part in the file. See
[Import and export](import-export.md).

## Reporting a problem

Useful things to include:

- Blender version, and whether the add-on was installed as a legacy add-on or as
  a Blender 4.2+ Extension
- What **CAD Engine** reports in preferences
- The console output with **Enable WARN Logs** turned on
- If it is a performance problem, enable **Perf Logging** and attach
  `seamless_cad_profile.log` from your OS temp directory

## See also

- [Known limitations](limitations.md)
- [How it works](concepts.md)
