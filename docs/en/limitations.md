# Known limitations

This page is deliberately blunt. It is better to know these before you build
something important than to discover them afterwards.

## Beta

Seamless CAD is in beta. Behaviour can change between versions, and it can crash.
Save often.

## Windows only

The released product runs on **Windows only**, because the geometry kernel ships
as a bundled executable built for Windows.

macOS and Linux builds exist and are being worked on, but they are **test builds,
not a product**:

- No guarantee of correct operation
- The binaries are **not code-signed**. macOS will warn that the developer cannot
  be verified and will block the first launch
- Work in progress may be lost. Do not use them for anything that matters
- Support is limited to accepting bug reports

Code signing on macOS requires an Apple Developer Program membership, which is
not currently funded. That is the honest reason, and it is the main obstacle to
a macOS release — not the code.

## Blender versions

Blender 4.2 or newer. Development and testing happen on 5.1. Versions in between
are expected to work but receive less testing.

The add-on can be installed either as a legacy add-on or as a Blender 4.2+
Extension. Both are supported; mention which one you used when reporting a
problem, because the two are loaded differently.

## STEP export carries geometry only

The exported file has no part names, no colours, and no assembly structure. The
geometry is exact B-Rep in AP214 IS, but everything around it is absent.

If your recipient needs a named, coloured, structured assembly, this export will
not meet that need yet.

## STEP export scale is fixed

**1 Blender unit is written as 1 mm**, and there is no option to change it.
Import has a scale option; export does not. Build at millimetre scale.

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
