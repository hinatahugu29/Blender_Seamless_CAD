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

import math
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
    rows_ = face.get("rows")
    if nr > 1 and na >= 1 and nb >= 1 and rows_ is not None and "counts" in rows_:
        # cone rows sit on fixed v lines, so each rim must run along one v
        # line: a rim with a notch cut into it (a slot through the wall's
        # edge) would be bridged by the rows, covering the notch with faces
        # that are not on the part
        vs = [p[2] for p in loop]
        h = (max(vs) - min(vs)) or 1.0
        for start, cnt in ((rs, na), (rs + na + nr, nb)):
            rv = [loop[(start + i) % m][2] for i in range(cnt + 1)]
            if max(rv) - min(rv) > 1e-3 * h:
                return _no(why, "a rim is notched (it leaves its v line)")
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
    if rows is not None and "counts" in rows and extra_verts is not None:
        return _fill_cone_rows(face, loop, rs, na, nb, nr, rows, base, extra_verts, why)
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


def _band(face, P, Q, u0, span):
    """Fill between two rows of loop points [vid, u, v] that run between the
    same two rulings, walking both in angle order: a quad where both advance
    together, a triangle where only one does."""
    def frac(p):
        return (p[1] - u0) / span
    out = []
    i = j = 0
    na, nb = len(P) - 1, len(Q) - 1
    while i < na or j < nb:
        ta = frac(P[i + 1]) if i < na else 2.0
        tb = frac(Q[j + 1]) if j < nb else 2.0
        if abs(ta - tb) <= 1e-9 + 1e-6 * abs(ta):
            corners = (P[i], P[i + 1], Q[j + 1], Q[j]); i += 1; j += 1
        elif ta < tb:
            corners = (P[i], P[i + 1], Q[j]); i += 1
        else:
            corners = (P[i], Q[j + 1], Q[j]); j += 1
        q = [_corner(face, p) for p in corners]
        if len({c[0] for c in q}) != len(q):
            return None
        out.append(q)
    return out


def _fill_cone_rows(face, loop, rs, na, nb, nr, rows, base, extra_verts, why):
    """Uniform density on a cone: nr rows whose span counts step from rim A's
    to rim B's (`rows.counts` for the inner rows), each band walked in angle
    order (quads, plus a triangle where a row gains a station; the join pairs
    what it can)."""
    m = len(loop)
    counts = rows["counts"]
    pts, uvs = rows["pts"], rows.get("uv", [])
    if len(counts) != nr - 1 or len(pts) != 3 * sum(c - 1 for c in counts) or len(uvs) * 3 != len(pts) * 2:
        return _no(why, "cone row data does not match the outline")

    def at(k):
        return loop[(rs + k) % m]

    first = base + len(extra_verts)
    for k in range(0, len(pts), 3):
        extra_verts.append((pts[k], pts[k + 1], pts[k + 2]))
    R = [[at(i) for i in range(na + 1)]]
    q = 0
    for k in range(1, nr):
        row = [at(-k)]
        for _ in range(counts[k - 1] - 1):
            row.append([first + q, uvs[2 * q], uvs[2 * q + 1]])
            q += 1
        row.append(at(na + k))
        R.append(row)
    R.append([at(na + nr + nb - j) for j in range(nb + 1)])
    u0, u1 = R[0][0][1], R[0][-1][1]
    if abs(u1 - u0) < 1e-12:
        return _no(why, "the rim has no angular extent")
    polys = []
    for k in range(nr):
        b = _band(face, R[k], R[k + 1], u0, u1 - u0)
        if b is None:
            return _no(why, "a cone band collapses (shared vertex)")
        polys.extend(b)
    return _orient_poly(face, _signed_area([(p[1], p[2]) for p in loop]), polys)


def _fill_tri_plane(face, verts3d, extra_verts, why=None):
    """3-1: a three-sided plane as three quad patches around a centre.

    Sides of n0, n1, n2 spans (n0 + n1 + n2 even) are split so the patches
    match: the spoke from side i to the centre has x_i spans with
    x0 = (n1 + n2 - n0) / 2 and so on, side i = x_(i+2) + x_(i+1) ... each
    patch is an n x m Coons grid in the plane's (u, v); the plane is affine,
    so 3D points come from the same frame as the holed-plane fill."""
    loops = face["loops"]
    if face["kind"] != "plane" or len(loops) != 1:
        return _no(why, "not a one-loop plane")
    loop = loops[0]
    su, sv = face["su"], face["sv"]
    M = len(loop)
    if M < 6:
        return _no(why, "too few points for three patches")
    P = [(p[1] * su, p[2] * sv) for p in loop]
    # corners: turning by more than 30 degrees
    corners = []
    for k in range(M):
        ax, ay = P[k - 1]; bx, by = P[k]; cx, cy = P[(k + 1) % M]
        d1 = (bx - ax, by - ay); d2 = (cx - bx, cy - by)
        l1 = (d1[0] ** 2 + d1[1] ** 2) ** 0.5; l2 = (d2[0] ** 2 + d2[1] ** 2) ** 0.5
        if l1 < 1e-12 or l2 < 1e-12:
            continue
        c = (d1[0] * d2[0] + d1[1] * d2[1]) / (l1 * l2)
        if c < math.cos(math.radians(30.0)):
            corners.append(k)
    if len(corners) != 3:
        return _no(why, "not three corners (%d)" % len(corners))
    c0, c1, c2 = corners
    n = [c1 - c0, c2 - c1, M - c2 + c0]
    if sum(n) % 2 or any(x < 1 for x in n):
        return _no(why, "odd span total %d" % sum(n))
    x = [(n[1] + n[2] - n[0]) // 2, (n[0] + n[2] - n[1]) // 2, (n[0] + n[1] - n[2]) // 2]
    # x[i] = spoke towards side i; side i = (part next to its start) + (part next to its end)
    # side0 (c0->c1) = x[2] + x[1]; side1 (c1->c2) = x[0] + x[2]; side2 (c2->c0) = x[1] + x[0]
    if any(v < 1 for v in x):
        return _no(why, "a side is longer than the other two together")

    base = len(verts3d)

    def pos3(vid):
        return Vector(verts3d[vid] if vid < base else extra_verts[vid - base])

    p0 = (P[0][0], P[0][1], pos3(loop[0][0]))
    best = None
    for i in range(1, M):
        for j in range(i + 1, M):
            area = abs((P[i][0] - p0[0]) * (P[j][1] - p0[1]) - (P[j][0] - p0[0]) * (P[i][1] - p0[1]))
            if best is None or area > best[0]:
                best = (area, i, j)
    if best is None or best[0] < 1e-18:
        return _no(why, "the outline is degenerate (no plane frame)")
    _, i, j = best
    du1, dv1 = P[i][0] - p0[0], P[i][1] - p0[1]
    du2, dv2 = P[j][0] - p0[0], P[j][1] - p0[1]
    det = du1 * dv2 - du2 * dv1
    d1, d2 = pos3(loop[i][0]) - p0[2], pos3(loop[j][0]) - p0[2]
    fa = (d1 * dv2 - d2 * dv1) / det
    fb = (d2 * du1 - d1 * du2) / det

    def to3(U, V):
        return tuple(p0[2] + fa * (U - p0[0]) + fb * (V - p0[1]))

    def L(k):                                  # loop point k as (vid, U, V)
        p = loop[k % M]
        return (p[0], p[1] * su, p[2] * sv)

    # split points on each side
    s0 = c0 + x[2]                             # on side 0
    s1 = c1 + x[0]                             # on side 1
    s2 = (c2 + x[1]) % M                       # on side 2
    S = [L(s0), L(s1), L(s2)]
    C = (sum(p[1] for p in S) / 3.0, sum(p[2] for p in S) / 3.0)
    new_v = {}

    def vert(U, V):
        key = (round(U, 12), round(V, 12))
        if key not in new_v:
            new_v[key] = base + len(extra_verts)
            extra_verts.append(to3(U, V))
        return (new_v[key], U, V)

    cvert = vert(*C)

    def spoke(sp, cnt):
        """points from split point sp to the centre, cnt spans, ends included"""
        out = [sp]
        for t in range(1, cnt):
            f = t / cnt
            out.append(vert(sp[1] + f * (C[0] - sp[1]), sp[2] + f * (C[1] - sp[2])))
        out.append(cvert)
        return out

    sp = [spoke(S[0], x[0]), spoke(S[1], x[1]), spoke(S[2], x[2])]

    def run(a, b):                             # loop points a..b (forward)
        out = []
        k = a
        while True:
            out.append(L(k))
            if k % M == b % M:
                break
            k += 1
        return out

    # patch at corner c1: side0 tail (s0->c1, x[1] spans), side1 head (c1->s1, x[0]),
    # spoke1 (s1->C, x[1]), spoke0 reversed (C->s0, x[0])
    patches = [
        (run(s0, c1), run(c1, s1), sp[1], list(reversed(sp[0]))),
        (run(s1, c2), run(c2, s2), sp[2], list(reversed(sp[1]))),
        (run(s2, c0 + M if c0 < s2 else c0), run(c0, s0), sp[0], list(reversed(sp[2]))),
    ]
    polys = []
    for A, B, Cs, D in patches:
        na, nb = len(A) - 1, len(B) - 1
        if len(Cs) - 1 != na or len(D) - 1 != nb:
            return _no(why, "patch sides do not match (%d/%d, %d/%d)" % (na, len(Cs) - 1, nb, len(D) - 1))
        # boundary of the patch grid G(i, j), i along A, j along B:
        # G(i,0)=A[i]; G(na,j)=B[j]; G(i,nb)=Cs reversed (Cs runs s->C, i.e. from (na,nb) to (0,nb));
        # G(0,j)=D reversed (D runs C->s_prev, i.e. from (0,nb) to (0,0))
        top = list(reversed(Cs))               # i = 0..na at j = nb
        left = list(reversed(D))               # j = 0..nb at i = 0

        def G(i, j):
            if j == 0:
                return A[i]
            if i == na:
                return B[j]
            if j == nb:
                return top[i]
            if i == 0:
                return left[j]
            s_, t_ = i / na, j / nb
            U = ((1 - t_) * A[i][1] + t_ * top[i][1] + (1 - s_) * left[j][1] + s_ * B[j][1]
                 - ((1 - s_) * (1 - t_) * A[0][1] + s_ * (1 - t_) * A[na][1]
                    + (1 - s_) * t_ * top[0][1] + s_ * t_ * top[na][1]))
            V = ((1 - t_) * A[i][2] + t_ * top[i][2] + (1 - s_) * left[j][2] + s_ * B[j][2]
                 - ((1 - s_) * (1 - t_) * A[0][2] + s_ * (1 - t_) * A[na][2]
                    + (1 - s_) * t_ * top[0][2] + s_ * t_ * top[na][2]))
            return vert(U, V)

        grid = [[G(i, j) for j in range(nb + 1)] for i in range(na + 1)]
        for i in range(na):
            for j in range(nb):
                q = [grid[i][j], grid[i + 1][j], grid[i + 1][j + 1], grid[i][j + 1]]
                if len({c[0] for c in q}) != 4:
                    return _no(why, "a patch cell collapses")
                polys.append([(c[0], c[1], c[2]) for c in q])
    area = _signed_area(P)
    for q in polys:
        a2 = _signed_area([(c[1], c[2]) for c in q])
        if a2 * area <= 0.0:
            return _no(why, "a patch cell flips")
    return _orient_poly(face, area, polys)


def _plane_frame(P, loop, pos3):
    """An affine (U, V) -> 3D map for a plane from three well-spread outline
    points, or None when the outline is degenerate."""
    M = len(P)
    best = None
    for i in range(1, M):
        for j in range(i + 1, M):
            area = abs((P[i][0] - P[0][0]) * (P[j][1] - P[0][1]) - (P[j][0] - P[0][0]) * (P[i][1] - P[0][1]))
            if best is None or area > best[0]:
                best = (area, i, j)
    if best is None or best[0] < 1e-18:
        return None
    _, i, j = best
    o = pos3(loop[0][0])
    du1, dv1 = P[i][0] - P[0][0], P[i][1] - P[0][1]
    du2, dv2 = P[j][0] - P[0][0], P[j][1] - P[0][1]
    det = du1 * dv2 - du2 * dv1
    d1, d2 = pos3(loop[i][0]) - o, pos3(loop[j][0]) - o
    fa = (d1 * dv2 - d2 * dv1) / det
    fb = (d2 * du1 - d1 * du2) / det
    U0, V0 = P[0]
    return lambda U, V: tuple(o + fa * (U - U0) + fb * (V - V0))


def _outline_corners(P, deg=30.0):
    """Indices of outline points where the outline turns by more than `deg`."""
    M = len(P)
    out = []
    lim = math.cos(math.radians(deg))
    for k in range(M):
        ax, ay = P[k - 1]; bx, by = P[k]; cx, cy = P[(k + 1) % M]
        d1 = (bx - ax, by - ay); d2 = (cx - bx, cy - by)
        l1 = (d1[0] ** 2 + d1[1] ** 2) ** 0.5; l2 = (d2[0] ** 2 + d2[1] ** 2) ** 0.5
        if l1 < 1e-12 or l2 < 1e-12:
            continue
        if (d1[0] * d2[0] + d1[1] * d2[1]) / (l1 * l2) < lim:
            out.append(k)
    return out


def _fill_plane_taper(face, verts3d, extra_verts, loop, P, cs, side, why=None):
    """A four-cornered plane whose one pair of opposite sides is even and the
    other differs by an even count (a strip between a wall and a fillet:
    11 spans along one side, 3 along the other). Laid row by row; where a row
    loses two spans, one inner point and three quads take them up (a 3-to-1
    transition), so the face stays all quads. Odd differences cannot be all
    quads and are left to the lattice."""
    M = len(loop)
    for rot in (0, 1):
        a, mL, b, mR = side[rot], side[rot + 1], side[(rot + 2) % 4], side[(rot + 3) % 4]
        if mL == mR and a != b and (a - b) % 2 == 0:
            break
    else:
        return _no(why, "opposite sides differ (%s)" % side)
    m = mL
    if m < 1 or min(a, b) < 1:
        return _no(why, "opposite sides differ (%s)" % side)
    su, sv = face["su"], face["sv"]
    base = len(verts3d)

    def pos3(vid):
        return Vector(verts3d[vid] if vid < base else extra_verts[vid - base])

    to3 = _plane_frame(P, loop, pos3)
    if to3 is None:
        return _no(why, "the outline is degenerate (no plane frame)")
    r0 = cs[rot]

    def at(k):
        p_ = loop[(r0 + k) % M]
        return (p_[0], p_[1] * su, p_[2] * sv)

    bottom = [at(i) for i in range(a + 1)]                       # a spans
    right = [at(a + j) for j in range(m + 1)]                    # m spans, bottom -> top
    top = [at(a + m + b - i) for i in range(b + 1)]              # b spans, left -> right
    left = [at((a + m + b + m - j) % M) for j in range(m + 1)]   # m spans, bottom -> top

    def along(pts, f):
        """the point at fraction f of arc length along a polyline"""
        L = [0.0]
        for q in range(1, len(pts)):
            L.append(L[-1] + math.hypot(pts[q][1] - pts[q - 1][1], pts[q][2] - pts[q - 1][2]))
        t = f * L[-1]
        for q in range(1, len(pts)):
            if t <= L[q] or q == len(pts) - 1:
                seg = max(L[q] - L[q - 1], 1e-30)
                u = min(1.0, max(0.0, (t - L[q - 1]) / seg))
                return (pts[q - 1][1] + (pts[q][1] - pts[q - 1][1]) * u,
                        pts[q - 1][2] + (pts[q][2] - pts[q - 1][2]) * u)
        return (pts[-1][1], pts[-1][2])

    red = (a - b) // 2          # signed number of 2-span steps from bottom to top
    counts = [a - 2 * int(round(red * j / m)) for j in range(m + 1)]
    n_extra = len(extra_verts)
    rows = [bottom]
    for j in range(1, m):
        c = counts[j]
        t = j / m
        L_, R_ = left[j], right[j]
        row = [L_]
        for i in range(1, c):
            s_ = i / c
            B_, T_ = along(bottom, s_), along(top, s_)
            c00, c10, c11, c01 = bottom[0], bottom[-1], top[-1], top[0]
            U = ((1 - t) * B_[0] + t * T_[0] + (1 - s_) * L_[1] + s_ * R_[1]
                 - ((1 - s_) * (1 - t) * c00[1] + s_ * (1 - t) * c10[1] + s_ * t * c11[1] + (1 - s_) * t * c01[1]))
            V = ((1 - t) * B_[1] + t * T_[1] + (1 - s_) * L_[2] + s_ * R_[2]
                 - ((1 - s_) * (1 - t) * c00[2] + s_ * (1 - t) * c10[2] + s_ * t * c11[2] + (1 - s_) * t * c01[2]))
            row.append((base + len(extra_verts), U, V))
            extra_verts.append(to3(U, V))
        row.append(R_)
        rows.append(row)
    rows.append(top)

    def mid(pts):
        U = sum(p_[1] for p_ in pts) / len(pts)
        V = sum(p_[2] for p_ in pts) / len(pts)
        v = (base + len(extra_verts), U, V)
        extra_verts.append(to3(U, V))
        return v

    polys = []
    for j in range(m):
        lo, hi_ = rows[j], rows[j + 1]
        if len(lo) < len(hi_):
            lo, hi_, flip = hi_, lo, True
        else:
            flip = False
        r = (len(lo) - len(hi_)) // 2       # transitions in this strip
        nh = len(hi_) - 1
        # spread the transitions over the top spans
        at_k = set(int((q + 0.5) * nh / r) for q in range(r)) if r else set()
        i = 0
        for k in range(nh):
            if k in at_k:
                p0, p1, p2, p3 = lo[i], lo[i + 1], lo[i + 2], lo[i + 3]
                q0, q1 = hi_[k], hi_[k + 1]
                c_ = mid([p0, p1, p2, p3, q0, q1])
                quads = [[p0, p1, c_, q0], [p1, p2, p3, c_], [c_, p3, q1, q0]]
                i += 3
            else:
                quads = [[lo[i], lo[i + 1], hi_[k + 1], hi_[k]]]
                i += 1
            for q in quads:
                polys.append(q[::-1] if flip else q)
        if i != len(lo) - 1:
            del extra_verts[n_extra:]
            return _no(why, "taper rows do not close (%s)" % side)
    area = _signed_area(P)
    for q in polys:
        if len({c[0] for c in q}) != 4 or _signed_area([(c[1], c[2]) for c in q]) * area <= 0.0:
            del extra_verts[n_extra:]
            return _no(why, "a taper cell flips (%s)" % side)
    return _orient_poly(face, area, polys)


DISK_SQUARE = 0.6
DISK_RELAX = 40


TAPER_MIN_DEG = 20.0


def _min_corner_deg(polys):
    """The smallest corner angle (degrees) over the polygons, in their
    (u, v) coordinates."""
    worst = 180.0
    for q in polys:
        k = len(q)
        for t in range(k):
            a, b, c = q[t - 1], q[t], q[(t + 1) % k]
            v1 = (a[1] - b[1], a[2] - b[2]); v2 = (c[1] - b[1], c[2] - b[2])
            l1 = math.hypot(*v1); l2 = math.hypot(*v2)
            if l1 < 1e-15 or l2 < 1e-15:
                return 0.0
            cs_ = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (l1 * l2)))
            worst = min(worst, math.degrees(math.acos(cs_)))
    return worst


def _fill_plane_grid(face, verts3d, extra_verts, why=None, grid_out=None):
    """A one-loop plane with four corners whose opposite sides carry the same
    span count (the uniform pass split its straight sides) as an n x m quad
    grid -- the kernel's Coons analysis covers curved faces only. A plain
    four-point quad is left to the n-gon fill."""
    loops = face["loops"]
    if face["kind"] != "plane" or len(loops) != 1:
        return _no(why, "not a one-loop plane")
    loop = loops[0]
    M = len(loop)
    if M <= 4:
        return _no(why, "already a single quad")
    su, sv = face["su"], face["sv"]
    P = [(p[1] * su, p[2] * sv) for p in loop]
    cs = _outline_corners(P)
    disk = False
    if not cs and M % 2 == 0 and M >= 8:
        # a smooth closed outline (a disk, an oval) with an even point count:
        # four virtual corners about a quarter of the points apart, then the grid is relaxed to round them
        cs = [0, M // 4, M // 2, M // 2 + M // 4]
        disk = True
    if len(cs) != 4:
        return _no(why, "not four corners (%d)" % len(cs))
    side = [(cs[(k + 1) % 4] - cs[k]) % M for k in range(4)]
    n, m = side[0], side[1]
    if side[2] != n or side[3] != m:
        if not disk:
            n_ex = len(extra_verts)
            tp = _fill_plane_taper(face, verts3d, extra_verts, loop, P, cs, side, why)
            if tp and _min_corner_deg(tp) < TAPER_MIN_DEG:
                del extra_verts[n_ex:]
                return _no(why, "the taper layout folds a cell (under %g degrees)" % TAPER_MIN_DEG)
            return tp
        return _no(why, "opposite sides differ (%s)" % side)
    base = len(verts3d)

    def pos3(vid):
        return Vector(verts3d[vid] if vid < base else extra_verts[vid - base])

    to3 = _plane_frame(P, loop, pos3)
    if to3 is None:
        return _no(why, "the outline is degenerate (no plane frame)")
    r0 = cs[0]

    def at(k):
        p = loop[(r0 + k) % M]
        return (p[0], p[1] * su, p[2] * sv)

    n_extra = len(extra_verts)
    area = _signed_area(P)
    ring_polys = []
    if disk:
        # a round outline: a polar-square layout -- an inner four-sided loop
        # (straight sides between virtual corners pulled toward the centre)
        # joined to the outline by several rings of quads, then everything
        # inside the outline is relaxed together, so the inner square rounds
        # off and no outline point sits at a flat 180-degree quad corner; the
        # four inner corners become valence-3 poles
        cx = sum(x for x, _ in P) / M
        cy = sum(y for _, y in P) / M
        step = sum(((P[(k + 1) % M][0] - P[k][0]) ** 2 + (P[(k + 1) % M][1] - P[k][1]) ** 2) ** 0.5
                   for k in range(M)) / M
        corner_k = [0, n, n + m, 2 * n + m]
        C = []
        for k in corner_k:
            _, x, y = at(k)
            sqf = grid_out.get("square", DISK_SQUARE) if grid_out is not None else DISK_SQUARE
            C.append((cx + sqf * (x - cx), cy + sqf * (y - cy)))
        lens = [n, m, n, m]
        sq = []
        for sd in range(4):
            a0, a1 = C[sd], C[(sd + 1) % 4]
            for t in range(lens[sd]):
                f = t / lens[sd]
                sq.append((a0[0] + (a1[0] - a0[0]) * f, a0[1] + (a1[1] - a0[1]) * f))
        gap = sum(((at(k)[1] - sq[k][0]) ** 2 + (at(k)[2] - sq[k][1]) ** 2) ** 0.5 for k in range(M)) / M
        R = max(1, int(round(gap / max(step, 1e-30))))
        rings = [[at(k) for k in range(M)]]
        for r in range(1, R + 1):
            t = r / R
            row = []
            for k in range(M):
                _, x, y = at(k)
                U, V = x + (sq[k][0] - x) * t, y + (sq[k][1] - y) * t
                row.append((base + len(extra_verts), U, V))
                extra_verts.append(to3(U, V))
            rings.append(row)
        for r in range(R):
            for k in range(M):
                k2 = (k + 1) % M
                ring_polys.append([rings[r][k], rings[r][k2], rings[r + 1][k2], rings[r + 1][k]])
        inner_loop = rings[R]
        at = lambda k: inner_loop[k % M]

    first = base + len(extra_verts)
    inner = {}

    def G(i, j):
        if j == 0:
            return at(i)
        if i == n:
            return at(n + j)
        if j == m:
            return at(n + m + (n - i))
        if i == 0:
            return at(2 * n + m + (m - j))
        if (i, j) not in inner:
            s_, t_ = i / n, j / m
            A, B, C, D = G(i, 0), G(n, j), G(i, m), G(0, j)
            c00, c10, c11, c01 = G(0, 0), G(n, 0), G(n, m), G(0, m)
            U = ((1 - t_) * A[1] + t_ * C[1] + (1 - s_) * D[1] + s_ * B[1]
                 - ((1 - s_) * (1 - t_) * c00[1] + s_ * (1 - t_) * c10[1]
                    + s_ * t_ * c11[1] + (1 - s_) * t_ * c01[1]))
            V = ((1 - t_) * A[2] + t_ * C[2] + (1 - s_) * D[2] + s_ * B[2]
                 - ((1 - s_) * (1 - t_) * c00[2] + s_ * (1 - t_) * c10[2]
                    + s_ * t_ * c11[2] + (1 - s_) * t_ * c01[2]))
            inner[(i, j)] = (base + len(extra_verts), U, V)
            extra_verts.append(to3(U, V))
        return inner[(i, j)]

    polys = []
    for i in range(n):
        for j in range(m):
            q = [G(i, j), G(i + 1, j), G(i + 1, j + 1), G(i, j + 1)]
            if len({c[0] for c in q}) != 4 or _signed_area([(c[1], c[2]) for c in q]) * area <= 0.0:
                del extra_verts[n_extra:]
                return _no(why, "a grid cell flips (the outline is too skewed)")
            polys.append(q)
    if disk:
        # Laplacian relax of every point inside the outline (outline fixed)
        allp = ring_polys + polys
        uv = {}
        nb = {}
        for q in allp:
            for k in range(4):
                v, w = q[k], q[(k + 1) % 4]
                for x, y in ((v, w), (w, v)):
                    nb.setdefault(x[0], set()).add(y[0])
                    uv.setdefault(x[0], (x[1], x[2]))
        movable = [vid for vid in uv if vid >= base + n_extra]
        for _ in range(DISK_RELAX):
            nxt = dict(uv)
            for vid in movable:
                ns = nb[vid]
                nxt[vid] = (sum(uv[w][0] for w in ns) / len(ns), sum(uv[w][1] for w in ns) / len(ns))
            uv = nxt
        relaxed = [[(c[0],) + uv[c[0]] for c in q] for q in allp]
        if all(_signed_area([(c[1], c[2]) for c in q]) * area > 0.0 for q in relaxed):
            for vid in movable:
                extra_verts[vid - base] = to3(*uv[vid])
            ring_polys, polys = [], relaxed
        for q in ring_polys + polys:
            if _signed_area([(c[1], c[2]) for c in q]) * area <= 0.0:
                del extra_verts[n_extra:]
                return _no(why, "a disk cell flips")
        if grid_out is not None:
            # the structured layout for _fill_disk_holed: cell (i, j) of the
            # inner grid is polys[cell0 + i * m + j], unoriented
            allq = ring_polys + polys
            grid_out.update(polys=allq, cell0=len(allq) - n * m, n=n, m=m, area=area)
            return allq
    return _orient_poly(face, area, ring_polys + polys)


DISK_HOLED_SQUARES = (0.6, 0.75, 0.9)


def _fill_disk_holed(face, verts3d, extra_verts, why=None):
    """A round plate with holes (uniform density): the round-face layout
    (rings along the outline round a relaxed inner square grid), then for
    every hole a k x k block of grid cells around it is taken out and its
    4k-point edge is joined to the hole's 4k points by rings of quads -- all
    quads when every hole's point count is a multiple of four and its block
    fits in the inner grid. An odd outline gets one temporary midpoint, which
    is folded back at the end (one triangle, which the parity forces)."""
    loops = face["loops"]
    if face["kind"] != "plane" or len(loops) < 2:
        return _no(why, "not a plane with holes")
    su, sv = face["su"], face["sv"]
    xy0 = [(p[1] * su, p[2] * sv) for p in loops[0]]
    if len(xy0) < 8 or _outline_corners(xy0):
        return _no(why, "the outline is not round")
    for L in loops[1:]:
        if len(L) < 8 or len(L) % 4:
            return _no(why, "a hole's point count is not a multiple of four (%d)" % len(L))
    base = len(verts3d)
    n0 = len(extra_verts)
    L0 = [list(p) for p in loops[0]]

    def pos3(vid):
        return Vector(verts3d[vid] if vid < base else extra_verts[vid - base])

    to3 = _plane_frame(xy0, loops[0], pos3)
    if to3 is None:
        return _no(why, "the outline is degenerate (no plane frame)")
    fake = None
    if len(L0) % 2:
        kk = max(range(len(L0)), key=lambda q: (xy0[(q + 1) % len(L0)][0] - xy0[q][0]) ** 2
                 + (xy0[(q + 1) % len(L0)][1] - xy0[q][1]) ** 2)
        a_, b_ = L0[kk], L0[(kk + 1) % len(L0)]
        fake = (base + len(extra_verts), a_[0])
        extra_verts.append(tuple((pos3(a_[0]) + pos3(b_[0])) * 0.5))
        L0.insert(kk + 1, [fake[0], 0.5 * (a_[1] + b_[1]), 0.5 * (a_[2] + b_[2])])
    allq = None
    why_last = "the round-face layout does not fit"
    for sqf in DISK_HOLED_SQUARES:
        g = {"square": sqf}
        n1 = len(extra_verts)
        allq = _fill_plane_grid(dict(face, loops=[L0]), verts3d, extra_verts, grid_out=g)
        if allq and "cell0" in g:
            res = _disk_cut_holes(face, loops, allq, g, base, extra_verts, to3, su, sv, xy0)
            if isinstance(res, list):
                allq = res
                break
            why_last = res
        del extra_verts[n1:]
        allq = None
    if allq is None:
        del extra_verts[n0:]
        return _no(why, why_last)
    polys = allq
    area = g["area"]
    if fake is not None:
        out = []
        for q in polys:
            d = []
            for c in q:
                c = (fake[1],) + tuple(c[1:]) if c[0] == fake[0] else c
                if not d or d[-1][0] != c[0]:
                    d.append(c)
            if len(d) > 1 and d[0][0] == d[-1][0]:
                d.pop()
            if len(d) >= 3:
                out.append(d)
        polys = out
        extra_verts[fake[0] - base] = tuple(pos3(fake[1]))   # folded onto its neighbour
    return _orient_poly(face, area, polys)


def _disk_cut_holes(face, loops, allq, g, base, extra_verts, to3, su, sv, xy0):
    """Cut each hole's block of cells out of the round-face layout and join
    the block's edge to the hole by rings of quads. Returns the polygons, or
    a reason string."""
    n, m, c0, area = g["n"], g["m"], g["cell0"], g["area"]

    def cell(i, j):
        return allq[c0 + i * m + j]

    def node(i, j):
        if i < n and j < m:
            return cell(i, j)[0]
        if i == n and j < m:
            return cell(i - 1, j)[1]
        if i == n and j == m:
            return cell(i - 1, j - 1)[2]
        return cell(i, j - 1)[3]

    step = sum(((q[1][1] - q[0][1]) ** 2 + (q[1][2] - q[0][2]) ** 2) ** 0.5
               for q in allq[c0:]) / max(1, n * m)
    removed = set()
    extra_polys = []

    def fail(msg):
        return msg

    for L in loops[1:]:
        K = len(L)
        k = K // 4
        hx = [(p[1] * su, p[2] * sv) for p in L]
        cx = sum(x for x, _ in hx) / K
        cy = sum(y for _, y in hx) / K
        hit = None
        for i in range(n):
            for j in range(m):
                if _inside(cx, cy, [[(c[1], c[2]) for c in cell(i, j)]]):
                    hit = (i, j)
                    break
            if hit:
                break
        if hit is None:
            return fail("a hole's centre is not in the inner grid")
        ci, cj = hit
        if k % 2 == 0:
            q4 = cell(ci, cj)
            best = min(range(4), key=lambda t: (q4[t][1] - cx) ** 2 + (q4[t][2] - cy) ** 2)
            ni, nj = [(ci, cj), (ci + 1, cj), (ci + 1, cj + 1), (ci, cj + 1)][best]
            i0, j0 = ni - k // 2, nj - k // 2
        else:
            i0, j0 = ci - k // 2, cj - k // 2
        if i0 < 0 or j0 < 0 or i0 + k > n or j0 + k > m:
            return fail("a hole's block of cells runs off the inner grid")
        blk = {(i, j) for i in range(i0, i0 + k) for j in range(j0, j0 + k)}
        if blk & removed:
            return fail("two holes' blocks of cells overlap")
        removed |= blk
        per = ([node(i, j0) for i in range(i0, i0 + k)] + [node(i0 + k, j) for j in range(j0, j0 + k)]
               + [node(i, j0 + k) for i in range(i0 + k, i0, -1)] + [node(i0, j) for j in range(j0 + k, j0, -1)])
        pxy = [(c[1], c[2]) for c in per]
        if not all(_inside(x, y, [pxy]) for x, y in hx):
            return fail("a hole sticks out of its block of cells")
        H = [(p[0], p[1] * su, p[2] * sv) for p in L]
        if (_signed_area(hx) > 0.0) != (_signed_area(pxy) > 0.0):
            H = H[::-1]
        shift = min(range(K), key=lambda sh: sum((per[t][1] - H[(t + sh) % K][1]) ** 2
                                                 + (per[t][2] - H[(t + sh) % K][2]) ** 2 for t in range(K)))
        H = [H[(t + shift) % K] for t in range(K)]
        gap = sum(((per[t][1] - H[t][1]) ** 2 + (per[t][2] - H[t][2]) ** 2) ** 0.5 for t in range(K)) / K
        nr = max(1, int(round(gap / max(step, 1e-30))))
        rings = [per]
        for r in range(1, nr):
            t_ = r / nr
            row = []
            for t in range(K):
                U = per[t][1] + (H[t][1] - per[t][1]) * t_
                V = per[t][2] + (H[t][2] - per[t][2]) * t_
                row.append((base + len(extra_verts), U, V))
                extra_verts.append(to3(U, V))
            rings.append(row)
        rings.append(H)
        for r in range(nr):
            for t in range(K):
                t2 = (t + 1) % K
                q = [rings[r][t], rings[r][t2], rings[r + 1][t2], rings[r + 1][t]]
                if _signed_area([(c[1], c[2]) for c in q]) * area < 0.0:
                    q.reverse()
                extra_polys.append(q)
    polys = [q for idx, q in enumerate(allq)
             if not (idx >= c0 and ((idx - c0) // m, (idx - c0) % m) in removed)] + extra_polys
    # no hole-ring quad may fold over a neighbour: the areas must add up
    tot = sum(abs(_signed_area([(c[1], c[2]) for c in q])) for q in polys)
    want = abs(_signed_area(xy0)) - sum(abs(_signed_area([(p[1] * su, p[2] * sv) for p in L]))
                                        for L in loops[1:])
    if abs(tot - want) > 2e-3 * abs(want):
        return fail("the hole rings fold (area %.4g of %.4g)" % (tot, want))
    return polys


COONS_WINSLOW_ITERS = 200


def _winslow_coons(face, loop, n, m, rs, uvs, su, sv, verts3d=None):
    """Winslow smoothing of a Coons grid on a cylinder / cone, in the
    face's scaled (u, v): the transfinite blend bends its rows into a notched
    rim and squeezes the cells at the notch floor; the Winslow equations
    (the inverse of a harmonic map) spread them and, unlike a plain
    neighbour average, do not fold cells at a concave corner. Kept only when
    no cell flips and the smallest corner angle in (u, v) does not drop.
    Returns (uv, xyz) for the interior or None."""
    prm = face.get("cyl") if face["kind"] == "cylinder" else (
        face.get("cone") if face["kind"] == "cone" else None)
    if not prm or n < 3 or m < 3:
        return None
    M = len(loop)
    X = [[None] * (m + 1) for _ in range(n + 1)]

    def bnd(k):
        p = loop[(rs + k) % M]
        return [p[1] * su, p[2] * sv]
    for i in range(n + 1):
        X[i][0] = bnd(i)
        X[i][m] = bnd(n + m + (n - i))
    for j in range(m + 1):
        X[n][j] = bnd(n + j)
        X[0][j] = bnd((2 * n + m + (m - j)) % M if j else 0)
    for i in range(1, n):
        for j in range(1, m):
            k = (i - 1) * (m - 1) + (j - 1)
            X[i][j] = [uvs[2 * k] * su, uvs[2 * k + 1] * sv]
    # the u seam: a closed rim can jump by 2 pi su between neighbours
    per = 2.0 * math.pi * su

    def cells():
        for i in range(n):
            for j in range(m):
                yield [X[i][j], X[i + 1][j], X[i + 1][j + 1], X[i][j + 1]]

    def min_angle_and_sign():
        worst, sg = 180.0, set()
        for q in cells():
            a = _signed_area(q)
            sg.add(a > 0.0)
            for t in range(4):
                p0, p1, p2 = q[t - 1], q[t], q[(t + 1) % 4]
                v1 = (p0[0] - p1[0], p0[1] - p1[1]); v2 = (p2[0] - p1[0], p2[1] - p1[1])
                l1 = math.hypot(*v1); l2 = math.hypot(*v2)
                if l1 < 1e-15 or l2 < 1e-15:
                    return 0.0, False
                c = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (l1 * l2)))
                worst = min(worst, math.degrees(math.acos(c)))
        return worst, len(sg) == 1
    for q in cells():
        for P in q[1:]:
            if abs(P[0] - q[0][0]) > 0.5 * per:
                return None
    a0, ok0 = min_angle_and_sign()
    if not ok0:
        return None
    # a closed face: sides i = 0 and i = n are the same seam (same vertex
    # ids, u apart by a full turn); its inner points then slide along the
    # seam (v only) with the rows instead of pinning them
    def vid(k):
        return loop[(rs + k) % M][0]
    # (the seam runs along i: rows j = 0 and j = m)
    seam = verts3d is not None and all(vid(i) == vid(n + m + (n - i)) for i in range(1, n))
    shift = (X[1][m][0] - X[1][0][0]) if seam else 0.0
    if seam and abs(abs(shift) - per) > 1e-3 * per:
        seam = False
    for _ in range(COONS_WINSLOW_ITERS):
        for i in range(1, n):
            for j in range(1, m):
                xe = [(X[i + 1][j][c] - X[i - 1][j][c]) * 0.5 for c in (0, 1)]
                xn = [(X[i][j + 1][c] - X[i][j - 1][c]) * 0.5 for c in (0, 1)]
                al = xn[0] ** 2 + xn[1] ** 2
                ga = xe[0] ** 2 + xe[1] ** 2
                be = xe[0] * xn[0] + xe[1] * xn[1]
                den = 2.0 * (al + ga)
                if den < 1e-30:
                    continue
                X[i][j] = [(al * (X[i + 1][j][c] + X[i - 1][j][c]) + ga * (X[i][j + 1][c] + X[i][j - 1][c])
                            - 0.5 * be * (X[i + 1][j + 1][c] - X[i + 1][j - 1][c]
                                          - X[i - 1][j + 1][c] + X[i - 1][j - 1][c])) / den for c in (0, 1)]
        if seam:
            for i in range(1, n):
                D_ = [X[i][m - 1][0] - shift, X[i][m - 1][1]]      # j - 1, across the seam
                U_ = X[i][1]                                        # j + 1
                DL = [X[i - 1][m - 1][0] - shift, X[i - 1][m - 1][1]]
                DR = [X[i + 1][m - 1][0] - shift, X[i + 1][m - 1][1]]
                xe = [(X[i + 1][0][c] - X[i - 1][0][c]) * 0.5 for c in (0, 1)]
                xn = [(U_[c] - D_[c]) * 0.5 for c in (0, 1)]
                al = xn[0] ** 2 + xn[1] ** 2
                ga = xe[0] ** 2 + xe[1] ** 2
                be = xe[0] * xn[0] + xe[1] * xn[1]
                den = 2.0 * (al + ga)
                if den < 1e-30:
                    continue
                Vn = (al * (X[i + 1][0][1] + X[i - 1][0][1]) + ga * (U_[1] + D_[1])
                      - 0.5 * be * (X[i + 1][1][1] - DR[1] - X[i - 1][1][1] + DL[1])) / den
                lo_, hi_ = sorted((X[i - 1][0][1], X[i + 1][0][1]))
                Vn = min(max(Vn, lo_ + 0.1 * (hi_ - lo_)), hi_ - 0.1 * (hi_ - lo_))
                X[i][0] = [X[i][0][0], Vn]
                X[i][m] = [X[i][m][0], Vn]
    a1, ok1 = min_angle_and_sign()
    if not ok1 or a1 < a0:
        return None
    O = Vector(prm[0:3]); Xa = Vector(prm[3:6]); Ya = Vector(prm[6:9]); Za = Vector(prm[9:12]); R = prm[12]
    if face["kind"] == "cone":
        sa_, ca_ = math.sin(prm[13]), math.cos(prm[13])

    def on_surf(U, V):
        u, v = U / su, V / sv
        if face["kind"] == "cone":
            r_ = R + v * sa_
            return O + r_ * (math.cos(u) * Xa + math.sin(u) * Ya) + v * ca_ * Za
        return O + R * (math.cos(u) * Xa + math.sin(u) * Ya) + v * Za
    if seam:
        for i in range(1, n):
            P = on_surf(*X[i][0])
            verts3d[vid(i)] = (P.x, P.y, P.z)
            loop[(rs + i) % M][2] = X[i][0][1] / sv
            loop[(rs + n + m + (n - i)) % M][2] = X[i][0][1] / sv
    out_uv, out_p = [], []
    for i in range(1, n):
        for j in range(1, m):
            U, V = X[i][j]
            u, v = U / su, V / sv
            if face["kind"] == "cone":
                r_ = R + v * sa_
                P = O + r_ * (math.cos(u) * Xa + math.sin(u) * Ya) + v * ca_ * Za
            else:
                P = O + R * (math.cos(u) * Xa + math.sin(u) * Ya) + v * Za
            out_uv += [u, v]
            out_p += [P.x, P.y, P.z]
    return out_uv, out_p


def _fill_coons(face, base, extra_verts, why=None, pole_quads=False, verts3d=None):
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
    su, sv = face["su"], face["sv"]
    uvs = list(uvs)
    pts = list(pts)
    sm = _winslow_coons(face, loop, n, m, rs, uvs, su, sv, verts3d)
    if sm is not None:
        uvs, pts = sm
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
    if pole_quads:
        polys = _pair_pole_fans(polys)
    return _orient_poly(face, _signed_area([(p[1], p[2]) for p in loop]), polys)


def _pair_pole_fans(polys):
    """1-5: the triangles around a pole (one vertex shared by a whole fan) are
    paired with their neighbour into a kite quad (pole, a, b, c). A fan with an
    odd count keeps one triangle."""
    fans = {}
    for k, q in enumerate(polys):
        if len(q) == 3:
            for c in q:
                fans.setdefault(c[0], []).append(k)
    used = set()
    out_extra = []
    for pole, ks in fans.items():
        if len(ks) < 6:
            continue
        nxt = {}
        tri_of = {}
        for k in ks:
            if k in used:
                continue
            q = polys[k]
            r = [c[0] for c in q].index(pole)
            q = q[r:] + q[:r]                  # (pole, a, b), winding kept
            nxt[q[1][0]] = (q[2], k)
            tri_of[k] = q
        # walk the fan in order, pairing (a->b) with (b->c)
        starts = [a for a in nxt if not any(b[0][0] == a for b in nxt.values())] or list(nxt)[:1]
        a = starts[0]
        seen = set()
        while a in nxt and a not in seen:
            seen.add(a)
            b, k1 = nxt[a]
            if b[0] not in nxt:
                break
            c, k2 = nxt[b[0]]
            if k1 in used or k2 in used or k1 == k2:
                break
            t1 = tri_of[k1]
            used.update((k1, k2))
            out_extra.append([t1[0], t1[1], b, c])
            seen.add(b[0])
            a = c[0]
    return [q for k, q in enumerate(polys) if k not in used] + out_extra


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


def _keep_lattice(cands, rings, segs, keep2):
    """The candidate points inside the region (even-odd over `rings`) and at
    least sqrt(keep2) from every segment, in their original order --
    _inside and _seg_dist2 over all points at once."""
    if not cands:
        return []
    try:
        import numpy as np
    except ImportError:
        return [(X, Y) for X, Y in cands if _inside(X, Y, rings)
                and not any(_seg_dist2(X, Y, a[0], a[1], b[0], b[1]) < keep2 for a, b in segs)]
    P = np.asarray(cands, dtype=float)
    px, py = P[:, 0:1], P[:, 1:2]
    E = []
    for R in rings:
        n = len(R)
        E += [(R[k][0], R[k][1], R[(k + 1) % n][0], R[(k + 1) % n][1]) for k in range(n)]
    S_ = np.asarray(segs, dtype=float).reshape(-1, 4) if segs else np.zeros((0, 4))
    E = np.asarray(E, dtype=float).reshape(-1, 4)
    keep = np.zeros(len(P), dtype=bool)
    step = max(1, 4000000 // max(1, len(E) + len(S_)))
    for c0 in range(0, len(P), step):
        x, y = px[c0:c0 + step], py[c0:c0 + step]
        x0, y0, x1, y1 = E[:, 0], E[:, 1], E[:, 2], E[:, 3]
        cross = (y0 > y) != (y1 > y)
        with np.errstate(divide="ignore", invalid="ignore"):
            xi = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
        ins = (np.count_nonzero(cross & (x < xi), axis=1) % 2) == 1
        if len(S_):
            ax, ay, bx, by = S_[:, 0], S_[:, 1], S_[:, 2], S_[:, 3]
            dx, dy = bx - ax, by - ay
            L2 = dx * dx + dy * dy
            with np.errstate(divide="ignore", invalid="ignore"):
                t = np.where(L2 > 0.0, ((x - ax) * dx + (y - ay) * dy) / np.where(L2 > 0.0, L2, 1.0), 0.0)
            t = np.clip(t, 0.0, 1.0)
            ex, ey = ax + t * dx - x, ay + t * dy - y
            far = ((ex * ex + ey * ey) >= keep2).all(axis=1)
        else:
            far = np.ones(len(x), dtype=bool)
        keep[c0:c0 + step] = ins & far
    return [cands[k] for k in np.nonzero(keep)[0]]


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
    cyl = face.get("cyl") if face["kind"] == "cylinder" else None
    cone = face.get("cone") if face["kind"] == "cone" else None
    # a curved wall comes here holed, or (uniform density) notched: a single
    # outline that no row / grid layout took
    curved_ok = len(loops) >= 2 or plain
    if face["kind"] != "plane" and not ((cyl or cone) and curved_ok):
        return _no(why, "not a plane (or a holed / notched cylinder or cone wall)")
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

    # a seam (an edge the outline walks both ways, e.g. a cylinder's seam
    # ruling through a notch) belongs to this face alone, so it may be cut at
    # the outline's typical step; left whole, the lattice fans into slivers
    # along it. Both passes share the new points, keeping the seam closed.
    dirs_ = set()
    for L in loops:
        for k_ in range(len(L)):
            dirs_.add((L[k_][0], L[(k_ + 1) % len(L)][0]))
    lens_ = sorted(((L[(k_ + 1) % len(L)][1] - L[k_][1]) ** 2 * su * su
                    + (L[(k_ + 1) % len(L)][2] - L[k_][2]) ** 2 * sv * sv) ** 0.5
                   for L in loops for k_ in range(len(L)))
    typ = lens_[len(lens_) // 2] if lens_ else 0.0
    cuts = {}
    if typ > 0.0:
        new_loops = []
        for L in loops:
            NL = []
            for k_ in range(len(L)):
                A_, B_ = L[k_], L[(k_ + 1) % len(L)]
                NL.append(A_)
                if (B_[0], A_[0]) not in dirs_ or A_[0] == B_[0]:
                    continue
                ln_ = ((B_[1] - A_[1]) ** 2 * su * su + (B_[2] - A_[2]) ** 2 * sv * sv) ** 0.5
                n_ = int(round(ln_ / typ))
                if n_ < 2:
                    continue
                key_ = (min(A_[0], B_[0]), max(A_[0], B_[0]))
                if key_ not in cuts:
                    pa, pb = pos3(key_[0]), pos3(key_[1])
                    vids = []
                    for t in range(1, n_):
                        vids.append(base + len(extra_verts))
                        extra_verts.append(tuple(pa.lerp(pb, t / n_)))
                    cuts[key_] = vids
                vids = cuts[key_] if A_[0] == key_[0] else cuts[key_][::-1]
                for t, vid in enumerate(vids, 1):
                    f_ = t / n_
                    NL.append([vid, A_[1] + (B_[1] - A_[1]) * f_, A_[2] + (B_[2] - A_[2]) * f_])
            new_loops.append(NL)
        if cuts:
            loops = new_loops
            stats["seam_cuts"] = stats.get("seam_cuts", 0) + len(cuts)

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

    if cyl:
        # unrolled cylinder: (U, V) = (u su, v sv); map through the surface
        cO = Vector(cyl[0:3]); cX = Vector(cyl[3:6]); cY = Vector(cyl[6:9]); cZ = Vector(cyl[9:12])
        rad = cyl[12]

        def to3(U, V):
            u, v = U / su, V / sv
            return tuple(cO + rad * (math.cos(u) * cX + math.sin(u) * cY) + v * cZ)
    elif cone:
        kO = Vector(cone[0:3]); kX = Vector(cone[3:6]); kY = Vector(cone[6:9]); kZ = Vector(cone[9:12])
        kR, ka = cone[12], cone[13]
        sa_, ca_ = math.sin(ka), math.cos(ka)

        def to3(U, V):
            u, v = U / su, V / sv
            r_ = kR + v * sa_
            return tuple(kO + r_ * (math.cos(u) * kX + math.sin(u) * kY) + v * ca_ * kZ)

    xy = [[(p[1] * su, p[2] * sv) for p in L] for L in loops]
    seg_all = []
    for li, R in enumerate(xy):
        for k in range(len(R)):
            seg_all.append((li, R[k], R[(k + 1) % len(R)]))

    polys = []
    region_loops = [outer]          # loops for the triangulation, as [vid, u, v]
    region_xy = [xy[0]]
    steps = []

    def mean_step(R):
        k_ = len(R)
        return sum(((R[(q + 1) % k_][0] - R[q][0]) ** 2 + (R[(q + 1) % k_][1] - R[q][1]) ** 2) ** 0.5
                   for q in range(k_)) / max(1, k_)

    # the lattice step, decided BEFORE the rings so they can grade towards it:
    # the holes' mean step (no holes: the outline's), capped by the chord law on
    # a cylinder, then coarsened until the lattice fits the point budget. When
    # the budget coarsens it, the rings below step up 2:1 to meet it (1-1).
    h_lat = 0.0
    # a round plate with holes (cornerless outline, even point count): the
    # interior takes the points of the round-face layout (rings along the
    # outline round a relaxed inner square) instead of a square lattice, so
    # the outline meets concentric rows rather than a staircase of triangles;
    # the holes' rings step up towards the outline's step
    disk_pts = None
    if (plain and face["kind"] == "plane" and len(loops) > 1 and len(loops[0]) >= 8
            and not _outline_corners(xy[0])):
        tmp_extra = []
        L0 = list(loops[0])
        if len(L0) % 2:
            # the layout needs an even count; its points are only hints for
            # the triangulation, so a midpoint on the longest segment will do
            # (it reuses a neighbour's vertex id and never reaches the mesh)
            kk = max(range(len(L0)), key=lambda q: (xy[0][(q + 1) % len(L0)][0] - xy[0][q][0]) ** 2
                     + (xy[0][(q + 1) % len(L0)][1] - xy[0][q][1]) ** 2)
            a_, b_ = L0[kk], L0[(kk + 1) % len(L0)]
            L0.insert(kk + 1, [a_[0], 0.5 * (a_[1] + b_[1]), 0.5 * (a_[2] + b_[2])])
        dp = _fill_plane_grid(dict(face, loops=[L0]), verts3d, tmp_extra)
        if dp:
            nb = len(verts3d)
            seen = {}
            for q in dp:
                for c in q:
                    if c[0] >= nb:
                        seen[c[0]] = (c[1], c[2])
            disk_pts = list(seen.values())
    hs = [mean_step(xy[i]) for i in range(1, len(loops)) if len(xy[i]) >= 3]
    if disk_pts:
        h_lat = mean_step(xy[0])
    elif hs:
        h_lat = sum(hs) / len(hs)
    elif plain:
        h_lat = mean_step(xy[0])
    if cyl and h_lat > 0.0:
        h_lat = min(h_lat, (8.0 * cyl[12] * max(float(face.get("tol", 0.01)), 1e-6)) ** 0.5)
    if cone and h_lat > 0.0:
        # the chord law at the cone's widest radius on this face
        r_max = max(abs(cone[12] + p[2] * math.sin(cone[13])) for p in loops[0])
        if r_max > 1e-9:
            h_lat = min(h_lat, (8.0 * r_max * max(float(face.get("tol", 0.01)), 1e-6)) ** 0.5)
    if h_lat > 0.0:
        bx = [x for x, _ in xy[0]]
        by_ = [y for _, y in xy[0]]
        area_box = (max(bx) - min(bx)) * (max(by_) - min(by_))
        while area_box / (h_lat * h_lat) > max_steiner:
            h_lat *= 1.5

    def grade(hi, R, H_vids, ring, rv, step, clear):
        """Step the density up 2:1 ring by ring (every other point, offset by
        the new step) until it reaches the lattice step. Each band is a quad
        plus a triangle per pair of inner segments. Returns the last ring as
        (xy, vids)."""
        cur, cv, cstep, used = ring, rv, step, step
        sign = 1.0 if _signed_area(R) > 0.0 else -1.0
        if hi == 0:
            sign = -sign
        while 2.0 * cstep <= 1.05 * h_lat and len(cur) >= 8 and len(cur) % 2 == 0:
            P = cur[0::2]
            n2 = len(P)
            nstep = 2.0 * cstep
            if used + nstep > 0.45 * clear:
                break
            nd = []
            for q in range(n2):
                ax, ay = P[q - 1]; bx_, by2 = P[q]; cx, cy = P[(q + 1) % n2]
                n1 = (sign * (by2 - ay), -sign * (bx_ - ax))
                m2 = (sign * (cy - by2), -sign * (cx - bx_))
                l1 = max((n1[0] ** 2 + n1[1] ** 2) ** 0.5, 1e-30)
                l2 = max((m2[0] ** 2 + m2[1] ** 2) ** 0.5, 1e-30)
                nx, ny = n1[0] / l1 + m2[0] / l2, n1[1] / l1 + m2[1] / l2
                ln = max((nx * nx + ny * ny) ** 0.5, 1e-30)
                nd.append((nx / ln, ny / ln))
            new = [(P[q][0] + nstep * nd[q][0], P[q][1] + nstep * nd[q][1]) for q in range(n2)]
            ok = True
            for q in range(n2):
                for r in range(q + 2, n2):
                    if q == 0 and r == n2 - 1:
                        continue
                    if _segments_cross(new[q], new[(q + 1) % n2], new[r], new[(r + 1) % n2]):
                        ok = False
                        break
                if not ok:
                    break
            if ok:
                inside_outer = [_inside(x, y, [xy[0]]) for x, y in new]
                ok = all(inside_outer) and not any(_inside(x, y, [R]) for x, y in new) if hi else all(inside_outer)
            if ok:
                s0 = _signed_area(R) * (1.0 if hi == 0 else -1.0)
                for q in range(n2):
                    a0, a1, a2 = cur[2 * q], cur[2 * q + 1], cur[(2 * q + 2) % len(cur)]
                    b0, b1 = new[q], new[(q + 1) % n2]
                    if (_signed_area([a1, a2, b1, b0]) * s0 <= 0.0
                            or _signed_area([a0, a1, b0]) * s0 <= 0.0
                            or (b1[0] - b0[0]) ** 2 + (b1[1] - b0[1]) ** 2 < (0.5 * nstep) ** 2):
                        ok = False
                        break
            if not ok:
                break
            nv = []
            for U, V in new:
                nv.append(base + len(extra_verts))
                extra_verts.append(to3(U, V))
            def emit(poly):
                c = [(vid, p[0], p[1]) for vid, p in poly]
                if _signed_area([(x[1], x[2]) for x in c]) < 0.0:
                    c.reverse()
                if face["rev"]:
                    c.reverse()
                polys.append(c)

            L_ = len(cur)
            q = 0
            while q < n2:
                if q + 1 < n2:
                    # two coarse segments over four fine ones: six quads round
                    # three inner points instead of two quads and two triangles
                    f = [(cv[(2 * q + t) % L_], cur[(2 * q + t) % L_]) for t in range(5)]
                    c3 = [(nv[(q + t) % n2], new[(q + t) % n2]) for t in range(3)]
                    def mid(P_, Q_):
                        return (0.5 * (P_[0] + Q_[0]), 0.5 * (P_[1] + Q_[1]))
                    ip = [mid(f[1][1], mid(c3[0][1], c3[1][1])), mid(f[2][1], c3[1][1]),
                          mid(f[3][1], mid(c3[1][1], c3[2][1]))]
                    ivid = [base + len(extra_verts) + t for t in range(3)]
                    A_, E_, B_ = [(ivid[t], ip[t]) for t in range(3)]
                    tmpl = [[f[0], f[1], A_, c3[0]], [f[1], f[2], E_, A_], [f[2], f[3], B_, E_],
                            [f[3], f[4], c3[2], B_], [A_, E_, c3[1], c3[0]], [E_, B_, c3[2], c3[1]]]
                    sg = [_signed_area([x[1] for x in t_]) for t_ in tmpl]
                    if all(v > 0.0 for v in sg) or all(v < 0.0 for v in sg):
                        for U, V in ip:
                            extra_verts.append(to3(U, V))
                        for t_ in tmpl:
                            emit(t_)
                        q += 2
                        continue
                i0, i1, i2 = 2 * q, 2 * q + 1, (2 * q + 2) % L_
                j0, j1 = q, (q + 1) % n2
                emit([(cv[i0], cur[i0]), (cv[i1], cur[i1]), (nv[j0], new[j0])])
                emit([(cv[i1], cur[i1]), (cv[i2], cur[i2]), (nv[j1], new[j1]), (nv[j0], new[j0])])
                q += 1
            stats["graded_rings"] = stats.get("graded_rings", 0) + 1
            cur, cv, cstep, used = new, nv, nstep, used + nstep
        return cur, cv
    # plain (uniform density): the OUTER outline gets an inward quad ring too
    for hi in ([0] if plain and not disk_pts else []) + list(range(1, len(loops))):
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
        fail = "the gap to the next loop leaves %.4g, under a quarter of the step %.4g" % (d, step)
        if ok and clear2 ** 0.5 < 1.5 * step and _outline_corners(R):
            # a narrow strip along a cornered hole (a rim between the outline
            # and the hole; a round hole keeps its ring): one row
            # of the CDT spans it edge to edge and joins into a quad row; a
            # ring would split it into a zipper of slivers
            ok = False
            fail = "the gap to the next loop (%.4g) is a single-row strip" % clear2 ** 0.5
        if ok:
            for q in range(k):
                for r in range(q + 2, k):
                    if q == 0 and r == k - 1:
                        continue
                    if _segments_cross(ring[q], ring[(q + 1) % k], ring[r], ring[(r + 1) % k]):
                        ok = False
                        fail = "the ring would cross itself"
                        break
                if not ok:
                    break
        if ok and hi == 0:
            ok = all(_inside(x, y, [R]) for x, y in ring)
            fail = "the ring leaves the outline"
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
                    fail = "a ring quad flips or collapses (a sharp corner)"
                    break
                # the offsets of a corner's two neighbours must not meet either
                for dq in (1, 2):
                    o = ring[(q + dq) % k]
                    if (o[0] - ring[q][0]) ** 2 + (o[1] - ring[q][1]) ** 2 < (0.25 * step) ** 2:
                        ok = False
                        fail = "two ring points meet at a corner"
                        break
                if not ok:
                    break
        if not ok:
            if hi:
                region_loops.append(H); region_xy.append(R)
            stats["hole_rings_skipped"] = stats.get("hole_rings_skipped", 0) + 1
            if why is not None:
                why.append("note: %s got no quad ring: %s"
                           % ("hole %d" % hi if hi else "the outer outline", fail))
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
        ring, rv = grade(hi, R, H, ring, rv, d, clear2 ** 0.5 if clear2 < 1e299 else 1e300)
        k = len(ring)
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
    h = h_lat
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
        if disk_pts:
            cands = disk_pts
        else:
            cands = [(ox + ix * h, oy + iy * h) for ix in range(nx + 1) for iy in range(ny + 1)]
        for X, Y in _keep_lattice(cands, region_xy, segs, keep2):
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
    stats = {"faces": 0, "ngon": 0, "cdt": 0, "failed": 0, "tri3": 0,
             "ruled": 0, "coons": 0, "holed": 0, "hole_rings": 0, "hole_rings_skipped": 0, "cdt_new_verts": 0, "degenerate_dropped": 0, "ears_flipped": 0,
             "edge_fail": int(data.get("n_edge_fail", 0)), "errors": [], "face_log": []}
    for face in data.get("faces", []):
        face.setdefault("tol", data.get("tol", 0.01))
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
            ("grid", lambda w: _fill_coons(face, len(verts3d), extra, why=w,
                                           pole_quads=bool(data.get("pole_quads")), verts3d=verts3d)),
            ("tri3", lambda w: _fill_tri_plane(face, verts3d, extra, why=w) if uniform
             else _no(w, "three-patch split is a uniform-density layout")),
            ("pgrid", lambda w: _fill_plane_grid(face, verts3d, extra, why=w) if uniform
             else _no(w, "plane grid is a uniform-density layout")),
            ("ngon", lambda w: _fill_ngon(face, why=w, uniform=uniform)),
            ("dholed", lambda w: _fill_disk_holed(face, verts3d, extra, why=w) if uniform
             else _no(w, "the round plate layout is a uniform-density layout")),
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
        stats[{"ruled": "ruled", "grid": "coons", "ngon": "ngon", "holed": "holed", "dholed": "holed", "tri3": "tri3", "pgrid": "coons",
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


def face_signatures(data):
    """2-2: one signature per CAD face that does not depend on the tolerance:
    the surface kind, the face centre and the CAD vertices on its outline
    (rounded to 1e-6). Equal signatures across two bakes = the face did not
    move or change. Returns {face index: signature}."""
    flat = data.get("verts", [])
    n_cad = int(data.get("n_cad_verts", 0))
    out = {}
    for f in data.get("faces", []):
        cad = set()
        for L in f.get("loops", []):
            for p in L:
                v = p[0]
                if v < n_cad:
                    cad.add(tuple(round(flat[3 * v + a], 6) for a in range(3)))
        c = tuple(round(x, 6) for x in f.get("c", (0, 0, 0)))
        out[f["i"]] = "%s|%s|%s" % (f["kind"], c, sorted(cad))
    return out


def compare_signatures(old, new):
    """Faces of `new` whose signature is not among `old` (by value, since face
    indices may shift when the history changes)."""
    old_set = set(old.values()) if isinstance(old, dict) else set(old)
    return sorted(i for i, s in new.items() if s not in old_set)


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
             ]
    q = rep.get("quality")
    if q:
        lines.append("quality: %.1f%% quads, %d poles (inner vertices with valence != 4), "
                     "edge length p5/p95 %.3f" % (q["quad_pct"], q["poles"], q["edge_p5_p95"]))
        if "bad_quads" in q:
            lines.append("quad shape: %d skewed quads (a corner under 30 or over 150 degrees), "
                         "smallest corner %.1f, p5 smallest %.1f, p95 largest %.1f"
                         % (q["bad_quads"], q["min_angle"], q["min_angle_p5"], q["max_angle_p95"]))
        if q.get("open_edges"):
            lines.append("open shape: %d boundary edges -- the part is a sheet, not a closed solid"
                         % q["open_edges"])
    if "changed_faces" in rep:
        lines.append("since the previous bake of this part: %d of %d faces changed"
                     % (len(rep["changed_faces"]), rep["faces"])
                     + (" (%s)" % ", ".join("F%d" % i for i in rep["changed_faces"][:20])
                        if rep["changed_faces"] else ""))
    if "kept_faces" in rep:
        lines.append("kept from the previous bake (unchanged, outline matched): %d faces"
                     % len(rep["kept_faces"]))
    if rep.get("overrides_given"):
        lines.append("edge span overrides: %d of %d matched a CAD edge"
                     % (rep.get("overrides_applied", 0), rep["overrides_given"]))
    lines.append("")
    for f in rep.get("face_log", []):
        line = ("F%-4d %-10s -> %-9s %4d polys (%d quads, %d tris)"
                % (f["i"], f["kind"], f["kernel"], f["polys"], f["quads"], f["tris"]))
        if "poles" in f:
            line += "; after join %d quads, %d tris, %d poles" % (f["final_quads"], f["final_tris"], f["poles"])
        lines.append(line)
        for name, why in f["tried"]:
            lines.append("        %-6s declined: %s" % (name, why))
        for note in f["notes"]:
            lines.append("        " + note)
    for e in rep.get("errors", []):
        lines.append("ERROR " + e)
    return "\n".join(lines)
