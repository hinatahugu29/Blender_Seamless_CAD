# Known limitations

This page is deliberately blunt. It is better to know these before you build
something important than to discover them afterwards.

## Beta

Seamless CAD is in beta. Behaviour can change between versions, and it can crash.
Save often.

## Windows only

The released product runs on **Windows only**, because the geometry kernel ships
as a bundled executable built for Windows.

Builds for **Linux (x86-64)** and **macOS (Apple Silicon)** now exist and are
being given to testers. They are not on sale and have no release date. There is
no Intel Mac build. See [Testing builds](testing-builds.md) for what has and has
not been verified — the short version is that nobody has yet run them inside
Blender.

What still stands between those builds and a release is not the add-on's Python
code:

- **macOS is not notarised.** The kernel is ad-hoc signed only. Notarisation
  requires an Apple Developer Program membership, which is not currently funded.
  That is the honest reason, and it is the main obstacle to a macOS release
- **Nothing has been confirmed on real hardware.** Whether the viewport draws at
  all through Metal cannot be established by automated builds
- On Linux, glibc 2.34 is the effective floor (Ubuntu 22.04, Debian 12, RHEL 9
  and newer)

## Blender versions

Blender 4.2 or newer. Development and testing happen on 5.1. Versions in between
are expected to work but receive less testing.

The add-on ships as a **classic add-on, not as a Blender Extension**. The zip
carries no `blender_manifest.toml`, so drag-and-drop installation and the
Extensions repository do not apply — use `Install from Disk…`. See
[Installation](install.md).

## The Feature Tree cannot be reordered

Order is creation order. Rows cannot be moved up or down, and a new operation
cannot be inserted into the middle of an existing history — new entries are
always appended to the end, including while a rollback pin is set.

This is a real constraint on how you work: order has to be decided as you build.
[The Feature Tree and parts](feature-tree.md) covers what to do instead.

## STEP export carries geometry only

The exported file has no part names, no colours, and no assembly structure. The
geometry is exact B-Rep in AP214 IS, but everything around it is absent.

If your recipient needs a named, coloured, structured assembly, this export will
not meet that need yet.

## STEP export units

**One Blender unit is written as 1 mm by default.** The export dialog has a
*Scale (1 unit = N mm)* field if you work at another scale: 1000 if a unit is a
metre, 10 if it is a centimetre. It means the same thing as Import's Scale, so
a file brought in at 10 goes back out unchanged at 10.

Leaving it at 1.0 keeps the behaviour of every earlier version.

## Cleanup (Unify) is destructive to references

Merging coplanar faces destroys the face identities that Fillet, Chamfer, Offset,
Shell and Draft depend on. It is not applied automatically for this reason, and
applying it in the middle of a live history can break operations below it.

Treat it as a final step before export. See [How it works](concepts.md).

## Baked meshes do not stay linked

**Bake to Mesh** produces a snapshot. It does not update when the Feature Tree
changes; you have to bake again.

## Editing early history is expensive

Changing an operation near the top of a long Feature Tree requires recomputing
everything below it. This is inherent to history-based CAD rather than a defect,
but it is a real limit on how large a single part can comfortably get.

Rollback points and splitting into multiple parts are the mitigations. See
[Quality and performance](quality.md).

## Blender mesh tools do not apply

CAD shapes are computed by the kernel, not by Blender's mesh system. Blender's
modelling, sculpting and modifier tools cannot act on them directly. **Bake to
Mesh** first.

## Documentation coverage

English is complete and is the source of truth. Japanese mirrors it. Russian and
Chinese are limited to the Quick Start page, and those two translations were
produced by AI without review by a native speaker — they are marked as such at
the top of each page.

## See also

- [Troubleshooting](troubleshooting.md)
- [Import and export](import-export.md)
