"""Quad Bake P0 — fill the kernel's shared-edge topology into one mesh.

The kernel (src_rust/src/occ_quad.cpp, action ``quad_topology``) discretises
every CAD edge ONCE and hands each face its boundary loops as
``[vertex index, u, v]`` (u, v read from that edge's pcurve on that face), plus
interior points already evaluated on the surface. Because a boundary point is
the same vertex index on both sides of an edge, the result is watertight by
construction — no position-based welding.

Per face (the "kernel ladder", design doc QUAD_TESSELLATION_DESIGN.md §3.5):
  K1  plane, one loop        -> one n-gon
  K9  everything else        -> constrained Delaunay triangulation in UV
                                (mathutils.geometry.delaunay_2d_cdt), boundary
                                verbatim, interior points from the kernel
A face the kernel could not read (missing pcurve, ...) is reported and left
open — P0 does not mix in BRepMesh triangles, which would not weld.

Pure Python + mathutils: no bpy here, so the fill is testable headless.
"""

from mathutils import Vector
from mathutils.geometry import delaunay_2d_cdt
from mathutils.kdtree import KDTree

# delaunay_2d_cdt output_type: inside the input faces, holes by parity
_CDT_INSIDE_WITH_HOLES = 2


def _signed_area(pts):
    a = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        a += x0 * y1 - x1 * y0
    return 0.5 * a


def _dedup_cyclic(vids):
    out = []
    for v in vids:
        if not out or out[-1] != v:
            out.append(v)
    while len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return out


def _fill_ngon(face):
    """K1: a hole-free plane as one n-gon, or None when it is not that."""
    loops = face["loops"]
    if face["kind"] != "plane" or len(loops) != 1:
        return None
    loop = loops[0]
    vids = [p[0] for p in loop]
    uv = [(p[1], p[2]) for p in loop]
    poly = _dedup_cyclic(vids)
    if len(poly) < 3 or len(set(poly)) != len(poly):
        return None
    if _signed_area(uv) < 0.0:
        poly.reverse()
    if face["rev"]:
        poly.reverse()
    return [poly]


def _fill_ruled(face):
    """K3: a ruled wall (cylinder / cone, one wire = rim A, ruling, rim B,
    ruling) as ONE row of quads, station i of rim A to the station facing it on
    rim B. The kernel already made both rims carry the same span count (hard
    rim equality) and marks where rim A starts in the loop (`ruled`). Returns
    None when the loop does not have that shape after all — the caller then
    falls back to the triangulation."""
    rs = face.get("ruled")
    if rs is None or len(face["loops"]) != 1:
        return None
    loop = face["loops"][0]
    m = len(loop)
    if m < 4 or m % 2:
        return None
    n = m // 2 - 1                                  # spans per rim
    A = [loop[(rs + i) % m] for i in range(n + 1)]
    B = [loop[(rs + n + 1 + i) % m] for i in range(n + 1)]
    # pairing by angle: station A[i] must face B[n-i] (same u on the wall)
    pitch = min(abs(A[i + 1][1] - A[i][1]) for i in range(n)) if n else 0.0
    for i in range(n + 1):
        if abs(A[i][1] - B[n - i][1]) > 0.5 * pitch + 1e-12:
            return None
    flip = _signed_area([(p[1], p[2]) for p in loop]) < 0.0
    if face["rev"]:
        flip = not flip
    polys = []
    for i in range(n):
        q = [A[i][0], A[i + 1][0], B[n - 1 - i][0], B[n - i][0]]
        if len(set(q)) != 4:
            return None
        if flip:
            q.reverse()
        polys.append(q)
    return polys


def _fill_coons(face, base, extra_verts):
    """K4: a four-sided curved face as an n x m quad grid. The kernel found
    the four sides, made opposite sides carry the same span count, blended the
    boundary in UV (Coons) and evaluated the interior on the surface
    (`coons.pts`, row-major over i = 1..n-1, j = 1..m-1). A cell on a pole side
    collapses to a triangle. Returns None when the data does not fit."""
    c = face.get("coons")
    if c is None or len(face["loops"]) != 1:
        return None
    loop = face["loops"][0]
    n, m, rs = c["n"], c["m"], c["start"]
    M = len(loop)
    pts = c["pts"]
    if M != 2 * (n + m) or len(pts) != 3 * (n - 1) * (m - 1):
        return None

    def at(k):
        return loop[(rs + k) % M][0]

    interior0 = base + len(extra_verts)
    for k in range(0, len(pts), 3):
        extra_verts.append((pts[k], pts[k + 1], pts[k + 2]))

    def G(i, j):
        if j == 0:
            return at(i)
        if i == n:
            return at(n + j)
        if j == m:
            return at(n + m + (n - i))
        if i == 0:
            return at(2 * n + m + (m - j))
        return interior0 + (i - 1) * (m - 1) + (j - 1)

    flip = _signed_area([(p[1], p[2]) for p in loop]) < 0.0
    if face["rev"]:
        flip = not flip
    polys = []
    for i in range(n):
        for j in range(m):
            q = _dedup_cyclic([G(i, j), G(i + 1, j), G(i + 1, j + 1), G(i, j + 1)])
            if len(q) < 3 or len(set(q)) != len(q):
                continue
            if flip:
                q.reverse()
            polys.append(q)
    return polys


def _orient(a, b, c):
    return (b.x - a.x) * (c.y - a.y) - (c.x - a.x) * (b.y - a.y)


def _flip_edge_ears(tris, out_v, first_in, loop_pos, vid_of, n_cad, stats):
    """Flip away EDGE EARS: a triangle made of three consecutive boundary
    samples (prev, mid, next) of one loop whose middle sample lies INSIDE a CAD
    edge (its vertex index is not a CAD vertex, i.e. >= n_cad). Such a triangle
    cuts one edge's own polyline off with a chord — and on a thin strip (a
    fillet) the face on the other side of that edge cuts the very same ear,
    leaving two identical triangles in the mesh. Flipping the chord with the
    neighbouring triangle ties the edge sample to the far side instead.
    Mutates `tris` (lists of CDT output indices)."""
    def ear(t):
        if any(first_in.get(x) not in loop_pos for x in t):
            return None
        for r in range(3):
            p, m, n = t[r], t[(r + 1) % 3], t[(r + 2) % 3]
            lp, lm, ln = (loop_pos[first_in[x]] for x in (p, m, n))
            if not (lp[0] == lm[0] == ln[0]):
                continue
            size = lm[2]
            if {(lm[1] - 1) % size, (lm[1] + 1) % size} != {lp[1], ln[1]}:
                continue
            if vid_of[first_in[m]] < n_cad:
                continue                         # a corner: a legitimate ear
            return p, m, n
        return None

    for _round in range(4):
        edge_tris = {}
        for ti, t in enumerate(tris):
            for r in range(3):
                edge_tris.setdefault(frozenset((t[r], t[(r + 1) % 3])), []).append(ti)
        changed = False
        done = set()
        for ti in range(len(tris)):
            if ti in done:
                continue
            e = ear(tris[ti])
            if e is None:
                continue
            p, m, n = e
            others = [o for o in edge_tris.get(frozenset((p, n)), ()) if o != ti and o not in done]
            if not others:
                continue
            oi = others[0]
            rest = [v for v in tris[oi] if v not in (p, n)]
            if len(rest) != 1:
                continue
            x = rest[0]
            M, P, N, X = out_v[m], out_v[p], out_v[n], out_v[x]
            # the new diagonal m-x must separate p from n (convex quad)
            if _orient(M, X, P) * _orient(M, X, N) >= 0.0:
                continue
            tris[ti] = [m, p, x]
            tris[oi] = [m, x, n]
            done.update((ti, oi))
            stats["ears_flipped"] = stats.get("ears_flipped", 0) + 1
            changed = True
        if not changed:
            break


def _fill_cdt(face, verts3d, extra_verts, n_cad, stats):
    """K9: constrained Delaunay in metric-scaled UV. New 3D points (interior
    Steiner points, rare CDT intersections) are appended to `extra_verts`
    with indices continuing after `verts3d`."""
    su, sv = face["su"], face["sv"]
    coords = []
    vid_of = []          # input index -> global vertex index
    in_faces = []
    for loop in face["loops"]:
        ring = []
        for vid, u, v in loop:
            ring.append(len(coords))
            coords.append(Vector((u * su, v * sv)))
            vid_of.append(vid)
        if len(ring) >= 3:
            in_faces.append(ring)
    if not in_faces:
        return []
    base = len(verts3d)
    for u, v, x, y, z in face["steiner"]:
        coords.append(Vector((u * su, v * sv)))
        vid_of.append(base + len(extra_verts))
        extra_verts.append((x, y, z))

    xs = [c.x for c in coords]
    ys = [c.y for c in coords]
    ext = max(max(xs) - min(xs), max(ys) - min(ys), 1e-12)
    out_v, _e, out_f, orig_v, _oe, _of = delaunay_2d_cdt(
        coords, [], in_faces, _CDT_INSIDE_WITH_HOLES, ext * 1e-9, True)

    # map CDT output verts to global indices
    kd = None
    gmap = []
    for k, ov in enumerate(orig_v):
        if ov:
            gmap.append(vid_of[ov[0]])
            continue
        # a vertex the CDT created (constraint intersection): place it by
        # inverse-distance weighting of the nearest input points
        if kd is None:
            kd = KDTree(len(coords))
            for i, c in enumerate(coords):
                kd.insert((c.x, c.y, 0.0), i)
            kd.balance()

        def at(i):
            g = vid_of[i]
            return Vector(verts3d[g] if g < base else extra_verts[g - base])
        near = kd.find_n((out_v[k].x, out_v[k].y, 0.0), 3)
        wsum = 0.0
        acc = Vector((0.0, 0.0, 0.0))
        for _co, i, d in near:
            w = 1.0 / max(d, 1e-12)
            acc += at(i) * w
            wsum += w
        gmap.append(base + len(extra_verts))
        extra_verts.append(tuple(acc / wsum))
        stats["cdt_new_verts"] += 1

    tris = []
    for f in out_f:
        for j in range(1, len(f) - 1):           # fan, in case of n-gons
            tris.append([f[0], f[j], f[j + 1]])
    # input index -> (loop no., position in loop) for the edge-ear test
    loop_pos = {}
    k = 0
    for li, loop in enumerate(face["loops"]):
        for j in range(len(loop)):
            loop_pos[k] = (li, j, len(loop))
            k += 1
    first_in = {}
    for kk, ov in enumerate(orig_v):
        if ov:
            first_in[kk] = ov[0]
    _flip_edge_ears(tris, out_v, first_in, loop_pos, vid_of, n_cad, stats)

    polys = []
    for tri in tris:
        a, b, c = (out_v[t] for t in tri)
        g = [gmap[t] for t in tri]
        if len(set(g)) < 3:
            stats["degenerate_dropped"] += 1      # collapsed onto a pole / apex
            continue
        if _orient(a, b, c) < 0.0:
            g.reverse()
        if face["rev"]:
            g.reverse()
        polys.append(g)
    return polys


def build_quad_mesh(data):
    """data: the dict from core_bridge.quad_topology.

    Returns (verts, polys, poly_face_index, report) where poly_face_index is
    the 1-based CAD face index of each polygon."""
    flat = data.get("verts", [])
    verts3d = [(flat[i], flat[i + 1], flat[i + 2]) for i in range(0, len(flat), 3)]
    n_cad = int(data.get("n_cad_verts", 0))
    extra = []
    polys = []
    poly_face = []
    stats = {"faces": 0, "ngon": 0, "cdt": 0, "failed": 0,
             "ruled": 0, "coons": 0, "cdt_new_verts": 0, "degenerate_dropped": 0, "ears_flipped": 0,
             "edge_fail": int(data.get("n_edge_fail", 0)), "errors": []}
    for face in data.get("faces", []):
        stats["faces"] += 1
        if face.get("error"):
            stats["failed"] += 1
            stats["errors"].append("Face %d (%s): %s" % (face["i"], face["kind"], face["error"]))
            continue
        out = _fill_ruled(face)
        if out is not None:
            stats["ruled"] += 1
        if out is None:
            out = _fill_coons(face, len(verts3d), extra)
            if out is not None:
                stats["coons"] += 1
        if out is None:
            out = _fill_ngon(face)
            if out is not None:
                stats["ngon"] += 1
        if out is None:
            out = _fill_cdt(face, verts3d, extra, n_cad, stats)
            stats["cdt"] += 1
            if not out:
                stats["failed"] += 1
                stats["errors"].append("Face %d (%s): empty triangulation" % (face["i"], face["kind"]))
        polys.extend(out)
        poly_face.extend([face["i"]] * len(out))
    return verts3d + extra, polys, poly_face, stats
