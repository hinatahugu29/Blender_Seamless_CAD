"""Quad Bake — fill the kernel's shared-edge topology into one mesh.

The kernel (src_rust/src/occ_quad.cpp, action ``quad_topology``) discretises
every CAD edge ONCE and hands each face its boundary loops as
``[vertex index, u, v]`` (u, v read from that edge's pcurve on that face), plus
interior points already evaluated on the surface. Because a boundary point is
the same vertex index on both sides of an edge, the result is watertight by
construction — no position-based welding.

Per face, the first kernel whose preconditions hold wins (design doc
QUAD_TESSELLATION_DESIGN.md §3.5):
  K3  ruled wall (cylinder / cone, rim-ruling-rim-ruling) -> one row of quads
  K4  four-sided curved face                                -> Coons quad grid
  K1  plane, one loop                                       -> one n-gon
  K9  everything else                                       -> constrained
      Delaunay triangulation in UV (mathutils.geometry.delaunay_2d_cdt)
A face the kernel could not read (missing pcurve, ...) is reported and left
open — no BRepMesh triangles are mixed in, they would not weld.

Every polygon corner carries the face's own parametrisation, scaled to model
units (u·|dS/du|, v·|dS/dv|), so each CAD face is one UV island cut along its
CAD edges; `pack_islands` lays the islands out without overlap at one common
texel density.

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


def _dedup_cyclic(corners):
    """Drop consecutive corners on the same vertex (a pole, an apex)."""
    out = []
    for c in corners:
        if not out or out[-1][0] != c[0]:
            out.append(c)
    while len(out) > 1 and out[0][0] == out[-1][0]:
        out.pop()
    return out


def _corner(face, p):
    """A loop point [vid, u, v] as a corner (vid, U, V) in model units."""
    return (p[0], p[1] * face["su"], p[2] * face["sv"])


def _orient_poly(face, loop_area, polys):
    """Corners were built in the loop's direction; make them face outward."""
    flip = loop_area < 0.0
    if face["rev"]:
        flip = not flip
    if flip:
        for q in polys:
            q.reverse()
    return polys


NGON_MAX_UNIFORM = 8   # uniform density: a plane outline above this is laid as a lattice


def _fill_ngon(face, why=None, uniform=False):
    """K1: a hole-free plane as one n-gon, or None when it is not that.
    With uniform density a plane the kernel marked `lattice` (its straight
    edges were cut to the pitch of its dense edges) with more than
    NGON_MAX_UNIFORM points is declined, so the lattice fill lays it as quads.
    An all-curve outline (a cylinder cap) stays one n-gon."""
    loops = face["loops"]
    if face["kind"] != "plane":
        return _no(why, "not a plane")
    if len(loops) != 1:
        return _no(why, "the plane has holes")
    loop = loops[0]
    if uniform and len(loop) > NGON_MAX_UNIFORM:
        return _no(why, "uniform density: the outline has %d points, laid as a lattice" % len(loop))
    poly = _dedup_cyclic([_corner(face, p) for p in loop])
    vids = [c[0] for c in poly]
    if len(poly) < 3 or len(set(vids)) != len(vids):
        return _no(why, "the outline touches itself")
    return _orient_poly(face, _signed_area([(p[1], p[2]) for p in loop]), [poly])


def _no(why, reason):
    """Record why a kernel declined, and decline."""
    if why is not None:
        why.append(reason)
    return None


def _fill_ruled(face, base=0, extra_verts=None, why=None):
    """K3: a ruled wall (cylinder / cone, one wire = rim A, ruling, rim B,
    ruling) as ONE row between the rims. The kernel marks where rim A starts in
    the loop (`ruled`) and how many spans it has (`ruled_a`; absent = the rims
    are equal). A cylinder's rims are forced equal by the kernel, so every
    station faces one on the other rim and the row is all quads. A cone keeps
    each rim's own count (HardCraft 0.8.8: no densifying the narrow rim); the
    row then walks both rims in angle order — a quad where both advance
    together, a triangle where only the denser rim does (the triangle join
    pairs what it can afterwards). Returns None when the loop does not have
    that shape after all — the caller then falls back to the triangulation."""
    rs = face.get("ruled")
    if rs is None:
        return _no(why, "not a ruled wall (a cylinder / cone whose one outline is rim, ruling, rim, ruling)")
    if len(face["loops"]) != 1:
        return _no(why, "the wall has holes")
    loop = face["loops"][0]
    m = len(loop)
    nr = int(face.get("ruled_r", 1))                # spans along each ruling
    if nr < 1:
        return _no(why, "the two rulings carry different span counts")
    na = face.get("ruled_a")
    if na is None:
        if m % 2:
            return _no(why, "the two rims carry different span counts (%d points)" % m)
        na = m // 2 - 1
    nb = m - na - 2 * nr                            # loop = A, ruling, B, ruling
    if nr > 1:
        return _fill_ruled_rows(face, loop, rs, na, nb, nr, base, extra_verts, why)
    if na < 1 or nb < 1:
        return _no(why, "a rim has no span (%d / %d)" % (na, nb))
    A = [loop[(rs + i) % m] for i in range(na + 1)]
    Br = [loop[(rs + na + 1 + nb - j) % m] for j in range(nb + 1)]   # B, walked like A
    # both rims run between the same two rulings: same u at the ends
    for a_, b_ in ((A[0], Br[0]), (A[-1], Br[-1])):
        if abs(a_[1] - b_[1]) > 1e-6 * max(1.0, abs(a_[1])):
            return _no(why, "the rims do not start and end on the same rulings")
    u0, u1 = A[0][1], A[-1][1]
    span = u1 - u0
    if abs(span) < 1e-12:
        return _no(why, "the rim has no angular extent")

    def frac(p):
        return (p[1] - u0) / span

    polys = []
    i = j = 0
    eps = 1e-9
    while i < na or j < nb:
        ta = frac(A[i + 1]) if i < na else 2.0
        tb = frac(Br[j + 1]) if j < nb else 2.0
        if abs(ta - tb) <= eps + 1e-6 * abs(ta):
            corners = (A[i], A[i + 1], Br[j + 1], Br[j])
            i += 1
            j += 1
        elif ta < tb:
            corners = (A[i], A[i + 1], Br[j])
            i += 1
        else:
            corners = (A[i], Br[j + 1], Br[j])
            j += 1
        q = [_corner(face, p) for p in corners]
        if len({c[0] for c in q}) != len(q):
            return _no(why, "a wall polygon collapses (shared vertex)")
        polys.append(q)
    return _orient_poly(face, _signed_area([(p[1], p[2]) for p in loop]), polys)


def _fill_ruled_rows(face, loop, rs, na, nb, nr, base, extra_verts, why):
    """Uniform density: a cylinder wall in nr rows. Row 0 is rim A, row nr rim
    B (walked like A), rows between run from ruling 2's point k to ruling 1's
    point k through the kernel's interior stations (`rows.pts` / `rows.uv`,
    row-major over k = 1..nr-1, i = 1..na-1)."""
    rows = face.get("rows")
    m = len(loop)
    if rows is None or na != nb or extra_verts is None:
        return _no(why, "rows along the wall need equal rims and the kernel's interior stations")
    pts, uvs = rows["pts"], rows.get("uv", [])
    n_in = (nr - 1) * (na - 1)
    if len(pts) != 3 * n_in or len(uvs) != 2 * n_in:
        return _no(why, "row data does not match the outline")
    first = base + len(extra_verts)
    for k in range(0, len(pts), 3):
        extra_verts.append((pts[k], pts[k + 1], pts[k + 2]))

    def at(k):
        return _corner(face, loop[(rs + k) % m])

    su, sv = face["su"], face["sv"]

    def G(k, i):
        if k == 0:
            return at(i)
        if k == nr:
            return at(na + nr + nb - i)
        if i == 0:
            return at(-k)
        if i == na:
            return at(na + k)
        q = (k - 1) * (na - 1) + (i - 1)
        return (first + q, uvs[2 * q] * su, uvs[2 * q + 1] * sv)

    polys = []
    for k in range(nr):
        for i in range(na):
            q = [G(k, i), G(k, i + 1), G(k + 1, i + 1), G(k + 1, i)]
            if len({c[0] for c in q}) != 4:
                return _no(why, "a wall polygon collapses (shared vertex)")
            polys.append(q)
    return _orient_poly(face, _signed_area([(p[1], p[2]) for p in loop]), polys)


def _fill_coons(face, base, extra_verts, why=None):
    """K4: a four-sided curved face as an n x m quad grid. The kernel found
    the four sides, made opposite sides carry the same span count, blended the
    boundary in UV (Coons) and evaluated the interior on the surface
    (`coons.pts` xyz and `coons.uv`, row-major over i = 1..n-1, j = 1..m-1). A
    cell on a pole side collapses to a triangle. Returns None when the data
    does not fit."""
    c = face.get("coons")
    if c is None:
        return _no(why, "not a four-sided grid (needs one outline with exactly 4 corners, "
                        "opposite sides evened out, no cell flipping)")
    if len(face["loops"]) != 1:
        return _no(why, "the face has holes")
    loop = face["loops"][0]
    n, m, rs = c["n"], c["m"], c["start"]
    M = len(loop)
    pts = c["pts"]
    uvs = c.get("uv", [])
    n_in = (n - 1) * (m - 1)
    if M != 2 * (n + m) or len(pts) != 3 * n_in or len(uvs) != 2 * n_in:
        return _no(why, "grid data does not match the outline")

    def at(k):
        return _corner(face, loop[(rs + k) % M])

    interior0 = base + len(extra_verts)
    for k in range(0, len(pts), 3):
        extra_verts.append((pts[k], pts[k + 1], pts[k + 2]))
    su, sv = face["su"], face["sv"]

    def G(i, j):
        if j == 0:
            return at(i)
        if i == n:
            return at(n + j)
        if j == m:
            return at(n + m + (n - i))
        if i == 0:
            return at(2 * n + m + (m - j))
        k = (i - 1) * (m - 1) + (j - 1)
        return (interior0 + k, uvs[2 * k] * su, uvs[2 * k + 1] * sv)

    polys = []
    for i in range(n):
        for j in range(m):
            q = _dedup_cyclic([G(i, j), G(i + 1, j), G(i + 1, j + 1), G(i, j + 1)])
            vids = [x[0] for x in q]
            if len(q) < 3 or len(set(vids)) != len(vids):
                continue
            polys.append(q)
    return _orient_poly(face, _signed_area([(p[1], p[2]) for p in loop]), polys)


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
        q = [(gmap[t], out_v[t].x, out_v[t].y) for t in tri]
        if len({x[0] for x in q}) < 3:
            stats["degenerate_dropped"] += 1      # collapsed onto a pole / apex
            continue
        if _orient(a, b, c) < 0.0:
            q.reverse()
        if face["rev"]:
            q.reverse()
        polys.append(q)
    return polys


def _seg_dist2(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = ((px - ax) * dx + (py - ay) * dy) / L2 if L2 > 0.0 else 0.0
    t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
    ex, ey = ax + t * dx - px, ay + t * dy - py
    return ex * ex + ey * ey


def _inside(px, py, rings):
    """Even-odd point-in-region over several closed rings of (x, y)."""
    inside = False
    for R in rings:
        n = len(R)
        for k in range(n):
            x0, y0 = R[k]
            x1, y1 = R[(k + 1) % n]
            if (y0 > py) != (y1 > py):
                if px < x0 + (py - y0) * (x1 - x0) / (y1 - y0):
                    inside = not inside
    return inside


def _segments_cross(a, b, c, d):
    def o(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    return (o(a, b, c) * o(a, b, d) < 0.0) and (o(c, d, a) * o(c, d, b) < 0.0)


def _fill_holed_plane(face, verts3d, extra_verts, n_cad, stats, max_steiner=20000, why=None, plain=False):
    """K2: a plane with holes. Each hole gets a ring of quads one hole-step
    wide (hole point i, its neighbour, and their offsets into the material);
    the rest — outer loop plus the rings as holes — is triangulated with a
    lattice of interior points at that same step, so the mesh stage's triangle
    join can pair it into quads. The kernel already cut the plate's straight
    edges at the holes' step. A plane is affine in (u, v), so new points are
    placed exactly from three boundary points. Returns None when the face is
    not a holed plane or the plane frame is degenerate."""
    loops = face["loops"]
    if face["kind"] != "plane":
        return _no(why, "not a plane")
    if len(loops) < 2 and not plain:
        return _no(why, "the plane has no holes")
    su, sv = face["su"], face["sv"]
    base = len(verts3d)
    # the outer loop is the one enclosing the largest area — never trust the
    # order alone: a hole ring laid around the OUTER loop would leave the part
    areas = [abs(_signed_area([(p[1] * su, p[2] * sv) for p in L])) for L in loops]
    big = max(range(len(loops)), key=lambda k: areas[k])
    if big != 0:
        loops = [loops[big]] + [L for k, L in enumerate(loops) if k != big]

    def pos3(vid):
        return Vector(verts3d[vid] if vid < base else extra_verts[vid - base])

    # affine frame UV -> 3D from the outer loop: origin + U*a + V*b
    outer = loops[0]
    P = [(p[1] * su, p[2] * sv, pos3(p[0])) for p in outer]
    p0 = P[0]
    best = None
    for i in range(1, len(P)):
        for j in range(i + 1, len(P)):
            area = abs((P[i][0] - p0[0]) * (P[j][1] - p0[1]) - (P[j][0] - p0[0]) * (P[i][1] - p0[1]))
            if best is None or area > best[0]:
                best = (area, i, j)
    if best is None or best[0] < 1e-18:
        return _no(why, "the outline is degenerate (no plane frame)")
    _, i, j = best
    du1, dv1 = P[i][0] - p0[0], P[i][1] - p0[1]
    du2, dv2 = P[j][0] - p0[0], P[j][1] - p0[1]
    det = du1 * dv2 - du2 * dv1
    d1, d2 = P[i][2] - p0[2], P[j][2] - p0[2]
    a = (d1 * dv2 - d2 * dv1) / det
    b = (d2 * du1 - d1 * du2) / det

    def to3(U, V):
        return tuple(p0[2] + a * (U - p0[0]) + b * (V - p0[1]))

    xy = [[(p[1] * su, p[2] * sv) for p in L] for L in loops]
    seg_all = []
    for li, R in enumerate(xy):
        for k in range(len(R)):
            seg_all.append((li, R[k], R[(k + 1) % len(R)]))

    polys = []
    region_loops = [outer]          # loops for the triangulation, as [vid, u, v]
    region_xy = [xy[0]]
    steps = []
    # plain (uniform density): the OUTER outline gets an inward quad ring too
    for hi in ([0] if plain else []) + list(range(1, len(loops))):
        H = loops[hi]
        R = xy[hi]
        k = len(R)
        if k < 3:
            if hi:
                region_loops.append(H); region_xy.append(R)
            continue
        seglen = [((R[(q + 1) % k][0] - R[q][0]) ** 2 + (R[(q + 1) % k][1] - R[q][1]) ** 2) ** 0.5 for q in range(k)]
        step = sum(seglen) / k
        steps.append(step)
        sign = 1.0 if _signed_area(R) > 0.0 else -1.0
        if hi == 0:
            sign = -sign                    # into the material = inward for the outer loop
        dirs = []
        for q in range(k):
            ax, ay = R[q - 1]; bx, by = R[q]; cx, cy = R[(q + 1) % k]
            n1 = (sign * (by - ay), -sign * (bx - ax))
            n2 = (sign * (cy - by), -sign * (cx - bx))
            l1 = max((n1[0] ** 2 + n1[1] ** 2) ** 0.5, 1e-30)
            l2 = max((n2[0] ** 2 + n2[1] ** 2) ** 0.5, 1e-30)
            nx, ny = n1[0] / l1 + n2[0] / l2, n1[1] / l1 + n2[1] / l2
            ln = max((nx * nx + ny * ny) ** 0.5, 1e-30)
            dirs.append((nx / ln, ny / ln))
        # clearance: the ring may use at most 45% of the gap to anything else
        clear2 = 1e300
        for q in range(k):
            x, y = R[q]
            for li, s0, s1 in seg_all:
                if li == hi:
                    continue
                clear2 = min(clear2, _seg_dist2(x, y, s0[0], s0[1], s1[0], s1[1]))
        d = min(step, 0.45 * clear2 ** 0.5)
        ring = [(R[q][0] + d * dirs[q][0], R[q][1] + d * dirs[q][1]) for q in range(k)]
        ok = d >= 0.25 * step
        if ok:
            for q in range(k):
                for r in range(q + 2, k):
                    if q == 0 and r == k - 1:
                        continue
                    if _segments_cross(ring[q], ring[(q + 1) % k], ring[r], ring[(r + 1) % k]):
                        ok = False
                        break
                if not ok:
                    break
        if ok and hi == 0:
            ok = all(_inside(x, y, [R]) for x, y in ring)
        if ok:
            # every ring quad must keep the loop's winding and a real area: at a
            # convex corner of the OUTER loop the offsets of the two sides meet
            # in one point and the ring collapses (a box face) -- no ring then
            s0 = _signed_area(R) * (1.0 if hi == 0 else -1.0)   # a hole's ring lies outside its loop
            for q in range(k):
                q2 = (q + 1) % k
                qa = _signed_area([R[q], R[q2], ring[q2], ring[q]])
                if qa * s0 <= 0.0 or abs(qa) < 0.05 * step * step:
                    ok = False
                    break
                # the offsets of a corner's two neighbours must not meet either
                for dq in (1, 2):
                    o = ring[(q + dq) % k]
                    if (o[0] - ring[q][0]) ** 2 + (o[1] - ring[q][1]) ** 2 < (0.25 * step) ** 2:
                        ok = False
                        break
                if not ok:
                    break
        if not ok:
            if hi:
                region_loops.append(H); region_xy.append(R)
            stats["hole_rings_skipped"] = stats.get("hole_rings_skipped", 0) + 1
            if why is not None:
                why.append("note: hole %d got no quad ring (gap %.4g < a quarter of its step %.4g, "
                           "or the ring would cross itself)" % (hi, d, step))
            continue
        rv = []
        for U, V in ring:
            rv.append(base + len(extra_verts))
            extra_verts.append(to3(U, V))
        for q in range(k):
            q2 = (q + 1) % k
            quad = [(H[q][0], R[q][0], R[q][1]), (H[q2][0], R[q2][0], R[q2][1]),
                    (rv[q2], ring[q2][0], ring[q2][1]), (rv[q], ring[q][0], ring[q][1])]
            if _signed_area([(c[1], c[2]) for c in quad]) < 0.0:
                quad.reverse()
            if face["rev"]:
                quad.reverse()
            polys.append(quad)
        ring_loop = [[rv[q], ring[q][0] / su, ring[q][1] / sv] for q in range(k)]
        if hi == 0:
            region_loops[0] = ring_loop
            region_xy[0] = ring
        else:
            region_loops.append(ring_loop)
            region_xy.append(ring)
        stats["hole_rings"] = stats.get("hole_rings", 0) + 1

    # interior lattice at the holes' step, kept half a step off every boundary
    # (no holes: the outline's own mean step)
    h = sum(steps) / len(steps) if steps else 0.0
    if h <= 0.0 and plain:
        R0 = xy[0]
        h = sum(((R0[(q + 1) % len(R0)][0] - R0[q][0]) ** 2 + (R0[(q + 1) % len(R0)][1] - R0[q][1]) ** 2) ** 0.5
                for q in range(len(R0))) / max(1, len(R0))
    steiner = []
    if h > 0.0:
        xs = [x for R in region_xy for x, _ in R]
        ys = [y for R in region_xy for _, y in R]
        while (max(xs) - min(xs)) * (max(ys) - min(ys)) / (h * h) > max_steiner:
            h *= 1.5
        segs = [(R[k], R[(k + 1) % len(R)]) for R in region_xy for k in range(len(R))]
        keep2 = (0.5 * h) ** 2
        nx = int((max(xs) - min(xs)) / h)
        ny = int((max(ys) - min(ys)) / h)
        ox = min(xs) + 0.5 * ((max(xs) - min(xs)) - nx * h)
        oy = min(ys) + 0.5 * ((max(ys) - min(ys)) - ny * h)
        for ix in range(nx + 1):
            for iy in range(ny + 1):
                X, Y = ox + ix * h, oy + iy * h
                if not _inside(X, Y, region_xy):
                    continue
                if any(_seg_dist2(X, Y, s0[0], s0[1], s1[0], s1[1]) < keep2 for s0, s1 in segs):
                    continue
                x3 = to3(X, Y)
                steiner.append([X / su, Y / sv, x3[0], x3[1], x3[2]])
    sub = dict(face)
    sub["loops"] = region_loops
    sub["steiner"] = steiner
    polys.extend(_fill_cdt(sub, verts3d, extra_verts, n_cad, stats))
    return polys


def pack_islands(poly_uvs, poly_face, margin_frac=0.02):
    """Lay the per-face UV islands into the unit square without overlap.

    poly_uvs: per polygon, a list of (U, V) in model units. Every island keeps
    its size relative to the others (one texel density for the whole mesh);
    islands are sorted by height and placed on shelves, then everything is
    scaled by one factor to fit. Mutates and returns `poly_uvs`."""
    boxes = {}
    for uvs, fi in zip(poly_uvs, poly_face):
        b = boxes.setdefault(fi, [1e300, 1e300, -1e300, -1e300])
        for u, v in uvs:
            b[0] = min(b[0], u); b[1] = min(b[1], v)
            b[2] = max(b[2], u); b[3] = max(b[3], v)
    if not boxes:
        return poly_uvs
    area = sum((b[2] - b[0]) * (b[3] - b[1]) for b in boxes.values())
    width = max(max(b[2] - b[0] for b in boxes.values()), area ** 0.5 * 1.2, 1e-12)
    gap = margin_frac * width
    order = sorted(boxes, key=lambda f: (-(boxes[f][3] - boxes[f][1]), f))
    offset = {}
    x = y = shelf_h = 0.0
    for fi in order:
        b = boxes[fi]
        w, h = b[2] - b[0], b[3] - b[1]
        if x > 0.0 and x + w > width:
            x = 0.0
            y += shelf_h + gap
            shelf_h = 0.0
        offset[fi] = (x - b[0], y - b[1])
        x += w + gap
        shelf_h = max(shelf_h, h)
    total = max(width, y + shelf_h, 1e-12)
    s = 1.0 / total
    for k, (uvs, fi) in enumerate(zip(poly_uvs, poly_face)):
        ox, oy = offset[fi]
        poly_uvs[k] = [((u + ox) * s, (v + oy) * s) for u, v in uvs]
    return poly_uvs


def build_quad_mesh_uv(data):
    """data: the dict from core_bridge.quad_topology.

    Returns (verts, polys, poly_face_index, poly_uvs, report): poly_face_index
    is the 1-based CAD face index of each polygon, poly_uvs the packed UV of
    each polygon corner."""
    flat = data.get("verts", [])
    verts3d = [(flat[i], flat[i + 1], flat[i + 2]) for i in range(0, len(flat), 3)]
    n_cad = int(data.get("n_cad_verts", 0))
    uniform = bool(data.get("uniform", False))
    extra = []
    polys = []
    uvs = []
    poly_face = []
    stats = {"faces": 0, "ngon": 0, "cdt": 0, "failed": 0,
             "ruled": 0, "coons": 0, "holed": 0, "hole_rings": 0, "hole_rings_skipped": 0, "cdt_new_verts": 0, "degenerate_dropped": 0, "ears_flipped": 0,
             "edge_fail": int(data.get("n_edge_fail", 0)), "errors": [], "face_log": []}
    for face in data.get("faces", []):
        stats["faces"] += 1
        if face.get("error"):
            stats["failed"] += 1
            stats["errors"].append("Face %d (%s): %s" % (face["i"], face["kind"], face["error"]))
            stats["face_log"].append({"i": face["i"], "kind": face["kind"], "kernel": "FAILED",
                                      "polys": 0, "quads": 0, "tris": 0,
                                      "tried": [("kernel", face["error"])], "notes": []})
            continue
        tried = []
        kernel = None
        ladder = (
            ("ruled", lambda w: _fill_ruled(face, len(verts3d), extra, why=w)),
            ("grid", lambda w: _fill_coons(face, len(verts3d), extra, why=w)),
            ("ngon", lambda w: _fill_ngon(face, why=w, uniform=uniform)),
            ("holed", lambda w: _fill_holed_plane(face, verts3d, extra, n_cad, stats, why=w,
                                                 plain=uniform)),
        )
        out = None
        notes = []
        for name, fill in ladder:
            w = []
            out = fill(w)
            notes += [x for x in w if x.startswith("note:")]
            if out is not None:
                kernel = name
                break
            tried.append((name, "; ".join(x for x in w if not x.startswith("note:")) or "declined"))
        if out is None:
            kernel = "triangles"
            out = _fill_cdt(face, verts3d, extra, n_cad, stats)
            if not out:
                stats["failed"] += 1
                stats["errors"].append("Face %d (%s): empty triangulation" % (face["i"], face["kind"]))
        stats[{"ruled": "ruled", "grid": "coons", "ngon": "ngon", "holed": "holed",
               "triangles": "cdt"}[kernel]] += 1
        sizes = [len(q) for q in out]
        stats["face_log"].append({
            "i": face["i"], "kind": face["kind"], "kernel": kernel,
            "polys": len(out), "quads": sizes.count(4), "tris": sizes.count(3),
            "tried": tried, "notes": notes})
        for q in out:
            polys.append([c[0] for c in q])
            uvs.append([(c[1], c[2]) for c in q])
            poly_face.append(face["i"])
    pack_islands(uvs, poly_face)
    return verts3d + extra, polys, poly_face, uvs, stats


def build_quad_mesh(data):
    """Like build_quad_mesh_uv without the UVs: (verts, polys, poly_face, report)."""
    verts, polys, poly_face, _uvs, stats = build_quad_mesh_uv(data)
    return verts, polys, poly_face, stats


def cad_edge_pairs(data):
    """Every mesh edge that lies on a CAD edge, as a set of frozenset vid pairs
    (consecutive points of a face loop). Used for UV seams / sharp edges."""
    pairs = set()
    for face in data.get("faces", []):
        for loop in face.get("loops", []):
            n = len(loop)
            for k in range(n):
                a, b = loop[k][0], loop[(k + 1) % n][0]
                if a != b:
                    pairs.add(frozenset((a, b)))
    return pairs


def cad_edge_creases(data):
    """{frozenset(vid pair): crease degrees} for every mesh edge on a CAD edge,
    from the kernel's exact CAD normals (0 = tangent, -1 = not judged). None
    when the kernel is too old to send creases."""
    edges = data.get("edges")
    if edges is None:
        return None
    out = {}
    for rec in edges:
        crease, vids = rec[0], rec[1:]
        for a, b in zip(vids, vids[1:]):
            if a != b:
                k = frozenset((a, b))
                out[k] = max(out.get(k, -1.0), crease)
    return out


def report_text(rep, title="Quad Bake report"):
    """The per-face report as plain text (what the Copy button puts on the
    clipboard): a summary line, then one block per CAD face — the kernel that
    filled it, its polygons, and why each earlier kernel declined."""
    lines = [title,
             "faces %d: ruled %d, grid %d, n-gon %d, holed plane %d, triangles %d, failed %d"
             % (rep["faces"], rep["ruled"], rep["coons"], rep["ngon"], rep["holed"], rep["cdt"], rep["failed"]),
             "polygons: %d quads, %d triangles, %d other; triangles joined: %d; sharp edges: %d (%s)"
             % (rep.get("quads", 0), rep.get("tris", 0), rep.get("ngons", 0), rep.get("joined", 0),
                rep.get("sharp", 0), rep.get("sharp_source", "?")),
             ""]
    for f in rep.get("face_log", []):
        lines.append("F%-4d %-10s -> %-9s %4d polys (%d quads, %d tris)"
                     % (f["i"], f["kind"], f["kernel"], f["polys"], f["quads"], f["tris"]))
        for name, why in f["tried"]:
            lines.append("        %-6s declined: %s" % (name, why))
        for note in f["notes"]:
            lines.append("        " + note)
    for e in rep.get("errors", []):
        lines.append("ERROR " + e)
    return "\n".join(lines)
