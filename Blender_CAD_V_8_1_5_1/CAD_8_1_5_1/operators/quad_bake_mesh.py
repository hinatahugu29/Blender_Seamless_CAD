"""Quad Bake — turn the filled topology (quad_bake.py) into a Blender mesh.

Kept apart from quad_bake.py because this half needs bpy / bmesh:
  * a "UVMap" layer: one island per CAD face, packed at one texel density
  * UV seams on every CAD edge (exactly where the islands are cut)
  * sharp edges where the CAD is creased (its two faces' exact normals differ
    by more than CAD_CREASE_DEG — tangent fillet seams stay smooth, however
    coarse the mesh); where the kernel cannot judge an edge, or with
    sharp_mode 'ANGLE', the mesh's own face angle against `sharp_angle`
  * optionally, triangle pairs are joined into quads by a GLOBAL maximum-
    weight matching over each CAD face (pair_triangles) — within one CAD face
    only (a seam stops it), so no polygon straddles a CAD edge
  * a per-polygon "cad_face" INT attribute (1-based CAD face index)
"""

import math

import bmesh
import bpy
from mathutils import Vector

from . import vendor_blossom
from .quad_bake import build_quad_mesh_uv, cad_edge_creases, cad_edge_pairs

# A CAD edge is a crease when its two faces' exact CAD normals differ by more
# than this. Tangent (G1) fillet seams measure 0; a real crease is far above.
CAD_CREASE_DEG = 1.0

# Triangle pairing: a pair may become a quad when the two triangles' normals
# differ by at most PAIR_FACE_DEG, the quad is convex, and no corner is more
# than `shape_deg` away from 90 degrees. Groups larger than PAIR_BLOSSOM_CAP
# triangles are paired greedily (best quads first) — the exact matching is
# cubic and took 14 s on 3,000 triangles.
PAIR_FACE_DEG = 40.0
PAIR_BLOSSOM_CAP = 1200


def _quad_worst(a, b, p1, p2, face_deg, shape_deg):
    """Two triangles (a, b, p1) and (b, a, p2) sharing edge a-b: the worst
    corner deviation from 90 degrees of the quad they would make, or None when
    that quad is not allowed (folded, non-convex, degenerate, too skewed)."""
    A, B, P, Q = a.co, b.co, p1.co, p2.co
    n1 = (B - A).cross(P - A)
    n2 = (A - B).cross(Q - B)
    if n1.length < 1e-14 or n2.length < 1e-14:
        return None
    if math.degrees(n1.angle(n2)) > face_deg:
        return None
    ref = (n1.normalized() + n2.normalized())
    if ref.length < 1e-12:
        return None
    loop = (A, Q, B, P)                       # the quad, diagonal a-b removed
    worst = 0.0
    sign = 0
    for i in range(4):
        q0, q1, q2 = loop[i - 1], loop[i], loop[(i + 1) % 4]
        e0, e1 = q0 - q1, q2 - q1
        if e0.length < 1e-12 or e1.length < 1e-12:
            return None
        turn = e1.cross(e0).dot(ref)
        s_ = 1 if turn > 0.0 else -1 if turn < 0.0 else 0
        if s_ == 0 or (sign and s_ != sign):
            return None                       # straight or reflex corner
        sign = s_
        worst = max(worst, abs(math.degrees(e0.angle(e1)) - 90.0))
    return worst if worst <= shape_deg else None


NATIVE_MATCHING = True
MATCH_SCALE = 1000000          # weights in [1, 2) -> integers for the kernel


def _native_matching(nodes, keys, cand):
    """The maximum-weight matching from the kernel (src_rust/src/matching.rs,
    the same Edmonds blossom as vendor_blossom, in Rust): a set of pairs, or
    None when the kernel is not reachable (the caller falls back to Python)."""
    if not NATIVE_MATCHING or len(keys) < 64:
        return None
    try:
        from .. import core_bridge
        ids = sorted(nodes)
        at = {x: k for k, x in enumerate(ids)}
        mate = core_bridge.max_weight_matching(
            len(ids), [(at[i], at[j], int(round(cand[(i, j)] * MATCH_SCALE))) for i, j in keys])
        if not isinstance(mate, list) or len(mate) != len(ids):
            return None
        out = set()
        for k, m in enumerate(mate):
            if m is not None and m >= 0 and m > k:
                out.add((ids[k], ids[m]))
        return out
    except Exception:
        return None


def pair_triangles(bm, shape_deg=60.0, face_deg=PAIR_FACE_DEG, cap=PAIR_BLOSSOM_CAP):
    """Join triangles into quads by maximum-weight matching (Edmonds' blossom,
    vendor_blossom). Node = triangle, edge = a shared NON-seam mesh edge whose
    two triangles may form a quad (_quad_worst), weight = 1 + quality in [0, 1),
    so the matching first maximises the NUMBER of quads and then their quality
    — instead of a greedy pass whose result depends on traversal order and
    strands triangles at the corners. Deterministic. Returns pairs joined."""
    tris = [f for f in bm.faces if len(f.verts) == 3]
    if len(tris) < 2:
        return 0
    bm.faces.index_update()
    node = {f.index: f for f in tris}
    cand = {}                                 # (i, j) -> weight
    for f in tris:
        for e in f.edges:
            if e.seam or len(e.link_faces) != 2:
                continue
            g, h = e.link_faces
            if g.index not in node or h.index not in node:
                continue
            if g.index > h.index:
                g, h = h, g
            key = (g.index, h.index)
            if key in cand:
                continue
            a, b = e.verts
            p1 = next(v for v in g.verts if v is not a and v is not b)
            p2 = next(v for v in h.verts if v is not a and v is not b)
            worst = _quad_worst(a, b, p1, p2, face_deg, shape_deg)
            if worst is not None:
                cand[key] = 1.0 + (shape_deg - worst) / max(shape_deg, 1e-9)
    if not cand:
        return 0
    # connected groups of pairable triangles, each matched on its own
    parent = {}

    def root(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x
    for i, j in sorted(cand):
        ri, rj = root(i), root(j)
        if ri != rj:
            parent[max(ri, rj)] = min(ri, rj)
    groups = {}
    for key in sorted(cand):
        groups.setdefault(root(key[0]), []).append(key)
    pairs = []
    for _r, keys in sorted(groups.items()):
        nodes = {x for k in keys for x in k}
        if len(nodes) <= cap:
            got = _native_matching(nodes, keys, cand)
            if got is None:
                g = vendor_blossom.Graph()
                for i, j in keys:
                    g.add_edge(i, j, weight=cand[(i, j)])
                got = vendor_blossom.max_weight_matching(g)
            pairs += sorted(tuple(sorted(p)) for p in got)
        else:
            used = set()
            for key in sorted(keys, key=lambda k: (-cand[k], k)):
                if key[0] not in used and key[1] not in used:
                    used.update(key)
                    pairs.append(key)
    for i, j in pairs:
        f1, f2 = node[i], node[j]
        if f1.is_valid and f2.is_valid:
            bmesh.utils.face_join([f1, f2])
    return len(pairs)


def _poly_worst(vs, shape_deg):
    """Worst corner deviation from 90 degrees of the convex quad `vs` (BMVerts
    in winding order), or None when it is folded, reflex or too skewed."""
    P = [v.co for v in vs]
    n = P[0].copy() * 0.0
    for i in range(4):
        n += P[i].cross(P[(i + 1) % 4])
    if n.length < 1e-14:
        return None
    worst = 0.0
    for i in range(4):
        q0, q1, q2 = P[i - 1], P[i], P[(i + 1) % 4]
        e0, e1 = q0 - q1, q2 - q1
        if e0.length < 1e-12 or e1.length < 1e-12:
            return None
        if e1.cross(e0).dot(n) <= 0.0:
            return None
        worst = max(worst, abs(math.degrees(e0.angle(e1)) - 90.0))
    return worst if worst <= shape_deg else None


def _merge_cycles(c, q):
    """Two faces' vertex cycles (same winding) sharing one edge -> the cycle
    of their union, or None when they do not share exactly one edge."""
    n = len(c)
    for i in range(n):
        u, v = c[i], c[(i + 1) % n]
        m = len(q)
        for j in range(m):
            if q[j] is v and q[(j + 1) % m] is u:
                cr = [c[(i + 1 + k) % n] for k in range(n)]        # v ... u
                qr = [q[(j + 2 + k) % m] for k in range(m - 2)]    # after u, before v
                out = cr + qr
                return out if len(set(out)) == len(out) else None
    return None


MIGRATE_SLACK_DEG = 20.0


def migrate_triangles(bm, shape_deg=60.0, max_path=12, only=None):
    """Triangles the matching left stranded inside one CAD face are walked
    towards each other through the quads between them: a triangle and the
    next quad make a pentagon, re-split into a quad and a triangle one face
    further on, until the two triangles meet and join into a quad. Every
    quad made must pass the pairing's shape test; the faces are replaced only
    when the whole walk does. Never crosses a seam (CAD edge). Returns the
    number of triangle pairs removed."""
    cad = bm.faces.layers.int.get("cad_face")
    uvl = bm.loops.layers.uv.get("UVMap")
    done = 0
    for _round in range(4):
        moved = False
        tris = sorted((f for f in bm.faces if len(f.verts) == 3), key=lambda f: f.index)
        for t0 in tris:
            if not t0.is_valid or len(t0.verts) != 3:
                continue
            if only is not None and (cad is None or t0[cad] not in only):
                continue
            # breadth-first through quads to the nearest other triangle
            prev = {t0: None}
            front = [t0]
            goal = None
            for _d in range(max_path):
                nxt = []
                for f in front:
                    for e in f.edges:
                        if e.seam or len(e.link_faces) != 2:
                            continue
                        g = e.link_faces[0] if e.link_faces[1] is f else e.link_faces[1]
                        if g in prev:
                            continue
                        if cad is not None and g[cad] != t0[cad]:
                            continue
                        if len(g.verts) == 3:
                            prev[g] = f
                            goal = g
                            break
                        if len(g.verts) == 4:
                            prev[g] = f
                            nxt.append(g)
                    if goal:
                        break
                if goal or not nxt:
                    break
                front = nxt
            if goal is None:
                continue
            path = [goal]
            while prev[path[-1]] is not None:
                path.append(prev[path[-1]])
            path.reverse()                       # t0, quads..., goal
            # simulate the walk
            cur = list(t0.verts)
            out = []
            ok = True
            for k in range(1, len(path) - 1):
                pent = _merge_cycles(cur, list(path[k].verts))
                if pent is None or len(pent) != 5:
                    ok = False
                    break
                nf = set(path[k + 1].verts)
                i = next((i for i in range(5) if pent[i] in nf and pent[(i + 1) % 5] in nf), None)
                if i is None:
                    ok = False
                    break
                P = lambda j: pent[(i + j) % 5]
                opts = []
                for tri, quad in (([P(0), P(1), P(2)], [P(2), P(3), P(4), P(0)]),
                                  ([P(-1), P(0), P(1)], [P(1), P(2), P(3), P(-1)])):
                    w = _poly_worst(quad, shape_deg)
                    if w is not None:
                        opts.append((w, tri, quad))
                if not opts:
                    ok = False
                    break
                opts.sort(key=lambda o: o[0])
                _, cur, quad = opts[0]
                out.append(quad)
            if ok:
                last = _merge_cycles(cur, list(goal.verts))
                if last is None or len(last) != 4 or _poly_worst(last, shape_deg) is None:
                    ok = False
                else:
                    out.append(last)
            if not ok:
                continue
            # apply: replace the path's faces by the new quads
            uv = {}
            if uvl is not None:
                for f in path:
                    for lo in f.loops:
                        uv[lo.vert] = lo[uvl].uv.copy()
            c_val = t0[cad] if cad is not None else None
            smooth = t0.smooth
            old_edges = {e for f in path for e in f.edges}
            for f in path:
                bm.faces.remove(f)
            for vs in out:
                g = bm.faces.new(vs)
                if cad is not None:
                    g[cad] = c_val
                g.smooth = smooth
                if uvl is not None:
                    for lo in g.loops:
                        if lo.vert in uv:
                            lo[uvl].uv = uv[lo.vert]
            for e in old_edges:
                if e.is_valid and not e.link_faces:
                    bm.edges.remove(e)
            done += 1
            moved = True
        if not moved:
            break
    return done


def _surface_projectors(data):
    """CAD face index -> a function that puts a point back on that face's
    cylinder / cone (radially, at the same axial height)."""
    from mathutils import Vector
    out = {}
    flat = data.get("verts", [])
    for f in data.get("faces", []):
        if f.get("kind") == "sphere":
            # no sphere parameters in the topology: fit one to the outline
            # (|p|^2 = 2 c.p + k, least squares)
            import numpy as np
            ids = {p[0] for L in f.get("loops", []) for p in L}
            P = np.array([flat[3 * i:3 * i + 3] for i in ids if 3 * i + 2 < len(flat)], dtype=float)
            if len(P) < 6:
                continue
            A = np.hstack([2.0 * P, np.ones((len(P), 1))])
            sol = np.linalg.lstsq(A, (P * P).sum(axis=1), rcond=None)[0]
            ctr = sol[:3]
            r2 = sol[3] + ctr.dot(ctr)
            if not r2 > 0.0:
                continue
            rad = float(r2) ** 0.5
            res = np.abs(np.linalg.norm(P - ctr, axis=1) - rad).max()
            if res > 1e-3 * rad:
                continue
            C = Vector(tuple(ctr))

            def proj_s(co, C=C, rad=rad):
                d = co - C
                L = d.length
                return co if L < 1e-12 else C + d * (rad / L)
            out[f.get("i")] = proj_s
            continue
        prm = f.get("cyl") if f.get("kind") == "cylinder" else (
            f.get("cone") if f.get("kind") == "cone" else None)
        if not prm or len(prm) < 13:
            continue
        O = Vector(prm[0:3]); Z = Vector(prm[9:12]).normalized()
        r0 = prm[12]
        tn = math.tan(prm[13]) if f.get("kind") == "cone" and len(prm) > 13 else 0.0

        def proj(co, O=O, Z=Z, r0=r0, tn=tn):
            d = co - O
            h = d.dot(Z)
            rad = d - h * Z
            L = rad.length
            if L < 1e-12:
                return co
            return O + h * Z + rad * (abs(r0 + h * tn) / L)
        out[f.get("i")] = proj
    return out


SPLIT_MIN_ANGLE = math.radians(25.0)
SPLIT_UNDO_ANGLE = math.radians(12.0)
SPLIT_RIM_TURN_ANGLE = math.radians(30.0)
SPLIT_TURNS = True
SPLIT_TURN_PATH = 12


def _sharp_outline_vert(v, c0, cad, max_bend_deg=30.0):
    """True when v sits on the outline of CAD face c0 and the outline bends
    there by more than max_bend_deg (a corner), or the outline around v is
    not a plain two-edge run."""
    bnd = [e for e in v.link_edges if e.seam or len(e.link_faces) != 2]
    if not bnd:
        return False
    own = [e for e in bnd if any(f[cad] == c0 for f in e.link_faces)]
    if len(own) != 2:
        return True
    a = own[0].other_vert(v).co - v.co
    b = own[1].other_vert(v).co - v.co
    if a.length < 1e-12 or b.length < 1e-12:
        return True
    return 180.0 - math.degrees(a.angle(b)) > max_bend_deg


def split_pair_triangles(bm, planes, max_path=40, curved=None, mids_out=None, records_out=None):
    """Two triangles left on one flat CAD face, joined by a straight strip of
    quads (each crossed through opposite sides): every crossed edge gets its
    midpoint and every quad of the strip is cut in two along the midpoints,
    so both triangles gain a fourth corner and the strip stays quads. The
    new corners sit at 180 degrees until relax_planes (which runs after this)
    moves them. On a cylinder / cone (`curved`: face -> projector) the new
    points go onto the surface and are relaxed here, alone. Never crosses a
    seam. Returns the number of pairs removed."""
    cad = bm.faces.layers.int.get("cad_face")
    curved = curved or {}
    if cad is None or not (planes or curved):
        return 0
    allowed = set(planes or ()) | set(curved)
    done = 0
    new_curved = []
    for _round in range(4):
        moved = False
        tris = sorted((f for f in bm.faces if len(f.verts) == 3 and f[cad] in allowed),
                      key=lambda f: f.index)
        for t0 in tris:
            if not t0.is_valid or len(t0.verts) != 3:
                continue
            c0 = t0[cad]
            best = None
            for e0 in t0.edges:
                # walk straight across quads from this side of the triangle
                chain = [e0]
                f = t0
                e = e0
                seen_f = {t0}
                for _d in range(max_path):
                    if e.seam or len(e.link_faces) != 2:
                        break
                    g = e.link_faces[0] if e.link_faces[1] is f else e.link_faces[1]
                    if g[cad] != c0 or g in seen_f:
                        break
                    seen_f.add(g)
                    if len(g.verts) == 3:
                        # two triangles side by side would only make a doublet
                        if len(chain) > 1 and (best is None or len(chain) < len(best[1])):
                            best = (g, list(chain))
                        break
                    if len(g.verts) != 4:
                        break
                    opp = [x for x in g.edges if x is not e and not (set(x.verts) & set(e.verts))]
                    if len(opp) != 1:
                        break
                    f, e = g, opp[0]
                    chain.append(e)
            if best is None and SPLIT_TURNS:
                # no straight strip: the shortest strip that may turn (a turn
                # quad is cut into three quads round its centre)
                prev = {t0: None}
                front = [(t0, None)]
                for _d in range(SPLIT_TURN_PATH):
                    nxt = []
                    for f, ein in front:
                        for e in f.edges:
                            if e is ein or e.seam or len(e.link_faces) != 2:
                                continue
                            g = e.link_faces[0] if e.link_faces[1] is f else e.link_faces[1]
                            if g in prev or g[cad] != c0:
                                continue
                            if len(g.verts) == 3:
                                if f is t0:
                                    continue
                                prev[g] = (f, e)
                                best = (g, None)
                                break
                            if len(g.verts) == 4:
                                prev[g] = (f, e)
                                nxt.append((g, e))
                        if best:
                            break
                    if best or not nxt:
                        break
                    front = nxt
                if best:
                    g = best[0]
                    ch = []
                    while prev[g] is not None:
                        f, e = prev[g]
                        ch.append(e)
                        g = f
                    best = (best[0], ch[::-1])
            if best is None:
                continue
            goal, chain = best
            # quads of the strip, in order, between consecutive crossed edges
            strip = []
            f = t0
            for e in chain[:-1]:
                g = e.link_faces[0] if e.link_faces[1] is f else e.link_faces[1]
                strip.append(g)
                f = g
            # a skewed quad in the strip would leave a skewed half: keep the
            # triangles then
            if any(min(lo.calc_angle() for lo in q.loops) < SPLIT_MIN_ANGLE for q in strip):
                continue
            turn_far, turn_ctr = {}, {}
            touch_rim = False
            for k, q in enumerate(strip):
                sh = set(chain[k].verts) & set(chain[k + 1].verts)
                if sh:
                    # turning round a point of the outline would wedge a
                    # sliver into that corner
                    # a turn may touch the outline where it runs smoothly (the
                    # rim of a round hole), never at a sharp corner of it
                    if any(_sharp_outline_vert(v, c0, cad) for v in q.verts):
                        turn_far = None
                        break
                    if any(e.seam or len(e.link_faces) != 2 for v in q.verts for e in v.link_edges):
                        touch_rim = True
                    used = set(chain[k].verts) | set(chain[k + 1].verts)
                    far = [v for v in q.verts if v not in used]
                    if len(far) != 1:
                        turn_far = None
                        break
                    turn_far[k] = far[0]
                    turn_ctr[k] = q.calc_center_median()
            if turn_far is None:
                continue
            mids = []
            for e in chain:
                v0 = e.verts[0]
                _ne, nv = bmesh.utils.edge_split(e, v0, 0.5)
                mids.append(nv)
                if mids_out is not None:
                    mids_out.append((nv, c0))
                if c0 in curved:
                    nv.co = curved[c0](nv.co)
                    new_curved.append((nv, c0))
            ok = True
            new_edges = []
            for k, q in enumerate(strip):
                try:
                    if k not in turn_far:
                        res = bmesh.utils.face_split(q, mids[k], mids[k + 1])
                        if not res or res[0] is None:
                            ok = False
                        else:
                            new_edges.append(res[1].edge)
                        continue
                    # a turn: cut off (m_in, a, w) towards the far corner w,
                    # put the centre c on that cut, then cut c to m_out
                    w = turn_far[k]
                    ctr = turn_ctr[k]
                    res = bmesh.utils.face_split(q, mids[k], w)
                    if not res or res[0] is None:
                        ok = False
                        continue
                    cut = res[1].edge
                    _ne, cv = bmesh.utils.edge_split(cut, mids[k], 0.5)
                    cv.co = curved[c0](ctr) if c0 in curved else ctr
                    mids.append(cv)
                    if mids_out is not None:
                        mids_out.append((cv, c0))
                    if c0 in curved:
                        new_curved.append((cv, c0))
                    hexf = next((f2 for f2 in cv.link_faces if mids[k + 1] in f2.verts), None)
                    if hexf is None:
                        ok = False
                        continue
                    res2 = bmesh.utils.face_split(hexf, cv, mids[k + 1])
                    if not res2 or res2[0] is None:
                        ok = False
                        continue
                    new_edges += [e2 for e2 in cv.link_edges]
                except (ValueError, RuntimeError):
                    ok = False
            if ok and (c0 in curved or turn_far):
                # a turn can wedge a sliver into a corner of a flat face too
                proj = curved.get(c0, lambda co: co)
                # on a curved face settle the new points now (they never see
                # relax_planes) and take the split back when a quad folds
                for _ in range(10):
                    for v in mids:
                        if any(e.seam or len(e.link_faces) != 2 for e in v.link_edges):
                            continue
                        fs = v.link_faces
                        co = fs[0].calc_center_median()
                        for f2 in fs[1:]:
                            co += f2.calc_center_median()
                        v.co = proj(co / len(fs))
                around = {f2 for v in mids for f2 in v.link_faces}
                # a turn along a hole's rim must leave decent quads, not just
                # unfolded ones
                lim_ = SPLIT_RIM_TURN_ANGLE if touch_rim else SPLIT_UNDO_ANGLE
                if any(min(lo.calc_angle() for lo in f2.loops) < lim_ for f2 in around):
                    try:
                        bmesh.ops.dissolve_edges(bm, edges=[e for e in new_edges if e.is_valid])
                        bmesh.ops.dissolve_verts(bm, verts=[v for v in mids if v.is_valid])
                    except (ValueError, RuntimeError):
                        pass
                    new_curved[:] = [(v, c) for v, c in new_curved if v.is_valid]
                    if mids_out is not None:
                        mids_out[:] = [(v, c) for v, c in mids_out if v.is_valid]
                    continue
            if records_out is not None and ok:
                records_out.append((list(mids), list(new_edges)))
            done += 1
            moved = True
            if not ok:
                break
        if not moved:
            break
    for _ in range(10):
        for v, c0 in new_curved:
            if not v.is_valid or any(e.seam or len(e.link_faces) != 2 for e in v.link_edges):
                continue
            nb = [e.other_vert(v) for e in v.link_edges]
            co = nb[0].co.copy()
            for o in nb[1:]:
                co += o.co
            v.co = curved[c0](co / len(nb))
    return done


def dissolve_doublets(bm):
    """An inner point held by just two quads of one CAD face (a doublet: both
    quads fold flat at it) is dissolved; the two quads become one quad."""
    cad = bm.faces.layers.int.get("cad_face")
    n = 0
    for _ in range(4):
        dv = []
        for v in bm.verts:
            if len(v.link_edges) != 2 or len(v.link_faces) != 2:
                continue
            if any(e.seam or len(e.link_faces) != 2 for e in v.link_edges):
                continue
            f0, f1 = v.link_faces
            if len(f0.verts) != 4 or len(f1.verts) != 4:
                continue
            if cad is not None and f0[cad] != f1[cad]:
                continue
            if set(f0.verts) == set(f1.verts):
                continue
            dv.append(v)
        if not dv:
            break
        done = set()
        for v in dv:
            if not v.is_valid or any(f in done for f in v.link_faces):
                continue
            done.update(v.link_faces)
            bmesh.ops.dissolve_verts(bm, verts=[v])
            n += 1
    return n


def centroid_relax(verts, projs, iters=10):
    """The points the strip split added have valence 3, where a plain
    neighbour average pushes them out of the triangle they cut and leaves a
    dent; the mean of the adjacent faces' centres keeps every face convex.
    On a cylinder / cone the point goes back onto the surface. A point
    whose move folds a neighbouring quad (worse than before, under 10
    degrees) goes back to where it was."""
    lim = math.radians(10.0)

    def worst(v):
        return min((min(lo.calc_angle() for lo in f.loops) for f in v.link_faces if len(f.verts) == 4),
                   default=math.pi)
    start = {v: (v.co.copy(), worst(v)) for v, _c in verts if v.is_valid}
    for _ in range(iters):
        for v, c0 in verts:
            if not v.is_valid or any(e.seam or len(e.link_faces) != 2 for e in v.link_edges):
                continue
            fs = v.link_faces
            if not fs:
                continue
            co = fs[0].calc_center_median()
            for f in fs[1:]:
                co += f.calc_center_median()
            co /= len(fs)
            v.co = projs[c0](co) if c0 in projs else co
    for v, (co0, w0) in start.items():
        if v.is_valid:
            w1 = worst(v)
            if w1 < lim and w1 < w0:
                v.co = co0


def plane_uv_affine(bm, planes):
    """A flat face's UV is affine in position: fit it on each flat CAD face's
    points that sit on a seam / the outline (their UV is exact) and give every
    inner point its exact UV. Run after anything that moves inner points."""
    import numpy as np
    cad = bm.faces.layers.int.get("cad_face")
    uvl = bm.loops.layers.uv.get("UVMap")
    if cad is None or uvl is None or not planes:
        return
    inner_of, fixed_uv = {}, {}
    for v in bm.verts:
        fs = v.link_faces
        if not fs:
            continue
        c = fs[0][cad]
        if c not in planes or any(f[cad] != c for f in fs):
            continue
        if any(e.seam or len(e.link_faces) != 2 for e in v.link_edges):
            continue
        inner_of.setdefault(c, []).append(v)
    inner = {v for vs in inner_of.values() for v in vs}
    for f in bm.faces:
        c = f[cad]
        if c not in inner_of:
            continue
        d_ = fixed_uv.setdefault(c, {})
        for lo in f.loops:
            if lo.vert not in inner and lo.vert not in d_:
                d_[lo.vert] = (tuple(lo.vert.co) + (1.0,), tuple(lo[uvl].uv))
    for c, vs in inner_of.items():
        X = [a for a, _ in fixed_uv.get(c, {}).values()]
        Y = [b for _, b in fixed_uv.get(c, {}).values()]
        if len(X) < 4:
            continue
        A = np.linalg.lstsq(np.array(X), np.array(Y), rcond=None)[0]
        for v in vs:
            uv = np.array(tuple(v.co) + (1.0,)) @ A
            for lo in v.link_loops:
                lo[uvl].uv = uv


def relax_planes(bm, planes, iters=10):
    """Laplacian relax of the inner vertices of flat CAD faces (every linked
    polygon on one plane face, no seam / open edge at the vertex): the
    lattice-and-CDT fill leaves slivers where its axis-aligned rows meet a
    slanted outline, which the pairing's shape test refuses. Averaging stays
    on the plane, and the UV (affine in position there) is averaged with it.
    Returns the number of vertices moved."""
    cad = bm.faces.layers.int.get("cad_face")
    if cad is None or not planes:
        return 0
    uvl = bm.loops.layers.uv.get("UVMap")
    inner = []
    for v in bm.verts:
        fs = v.link_faces
        if not fs:
            continue
        c = fs[0][cad]
        if c not in planes or any(f[cad] != c for f in fs):
            continue
        if any(e.seam or len(e.link_faces) != 2 for e in v.link_edges):
            continue
        inner.append(v)
    if not inner:
        return 0
    import numpy as np
    # neighbours as index arrays: inner points are unknowns, the rest fixed
    idx = {v: k for k, v in enumerate(inner)}
    fixed = {}
    nb_i, nb_j = [], []           # (inner row, column): column < len(inner) is inner, else fixed
    nf = len(inner)
    fixed_v = []
    for k, v in enumerate(inner):
        cv = v.link_faces[0][cad]
        for e in v.link_edges:
            o = e.other_vert(v)
            if o in idx:
                col = idx[o]
            else:
                # one column per (point, CAD face): a point on the edge
                # between two plates has a UV in each
                col = fixed.get((o, cv))
                if col is None:
                    col = nf + len(fixed_v)
                    fixed[(o, cv)] = col
                    fixed_v.append(o)
            nb_i.append(k)
            nb_j.append(col)
    nb_i = np.array(nb_i)
    nb_j = np.array(nb_j)
    deg = np.bincount(nb_i, minlength=nf).astype(float)[:, None]
    P = np.array([tuple(v.co) for v in inner] + [tuple(v.co) for v in fixed_v], dtype=float)
    P0 = P.copy()
    for _ in range(iters):
        acc = np.zeros((nf, 3))
        np.add.at(acc, nb_i, P[nb_j])
        P[:nf] = acc / deg
    # a CAD face where the averaging folds a cell (against a concave corner of
    # its outline) that the fill had not folded keeps the fill's points
    lim = math.radians(10.0)

    def worst(c):
        return min((min(lo.calc_angle() for lo in f.loops) for f in faces_of.get(c, ())
                    if len(f.verts) == 4), default=math.pi)
    faces_of = {}
    for f in bm.faces:
        if f[cad] in planes:
            faces_of.setdefault(f[cad], []).append(f)
    by_c = {}
    for k, v in enumerate(inner):
        by_c.setdefault(v.link_faces[0][cad], []).append(k)
    before = {c: worst(c) for c in by_c}
    for k, v in enumerate(inner):
        v.co = P[k]
    for c, ks in by_c.items():
        after = worst(c)
        if after < lim and after < before[c]:
            for k in ks:
                inner[k].co = P0[k]
    if uvl is not None:
        plane_uv_affine(bm, planes)
    return len(inner)


def mesh_quality(bm, cad_pairs, rep):
    """0-4: numbers to answer "where is it bad" with.

    Per CAD face (into rep["face_log"]): final quads / triangles after the
    join, and poles -- vertices inside the face (not on a CAD edge) whose
    valence is not 4. Overall: quad share, pole count, and the edge-length
    spread p5 / p95 (1 = all edges alike)."""
    lay = bm.faces.layers.int.get("cad_face")
    on_cad = set()
    for key in cad_pairs:
        on_cad.update(key)
    per = {}
    for f in bm.faces:
        fi = f[lay] if lay is not None else 0
        d = per.setdefault(fi, {"quads": 0, "tris": 0, "poles": 0})
        n = len(f.verts)
        if n == 4:
            d["quads"] += 1
        elif n == 3:
            d["tris"] += 1
    poles = 0
    for v in bm.verts:
        if v.index in on_cad or not v.link_faces:
            continue
        if len(v.link_edges) != 4:
            poles += 1
            fi = v.link_faces[0][lay] if lay is not None else 0
            per.setdefault(fi, {"quads": 0, "tris": 0, "poles": 0})["poles"] += 1
    for f in rep.get("face_log", []):
        d = per.get(f["i"])
        if d:
            f["final_quads"], f["final_tris"], f["poles"] = d["quads"], d["tris"], d["poles"]
    L = sorted(e.calc_length() for e in bm.edges)
    ratio = 1.0
    if len(L) >= 20 and L[-(len(L) // 20) - 1] > 0.0:
        ratio = L[len(L) // 20] / L[-(len(L) // 20) - 1]
    n = max(1, len(bm.faces))
    open_edges = sum(1 for e in bm.edges if len(e.link_faces) == 1)   # 3-4
    # quad shape: corner angles (a square is 90 everywhere); "bad" quads
    # have a corner under 30 or over 150 degrees
    mins, maxs, bad = [], [], 0
    for f in bm.faces:
        if len(f.verts) != 4:
            continue
        angs = []
        for lo in f.loops:
            a = lo.calc_angle()
            angs.append(math.degrees(a))
        lo_, hi_ = min(angs), max(angs)
        mins.append(lo_)
        maxs.append(hi_)
        if lo_ < 30.0 or hi_ > 150.0:
            bad += 1
    mins.sort()
    maxs.sort()
    k5 = len(mins) // 20
    return {"quad_pct": round(100.0 * rep["quads"] / n, 1), "poles": poles,
            "edge_p5_p95": round(ratio, 3), "open_edges": open_edges,
            "bad_quads": bad,
            "min_angle_p5": round(mins[k5], 1) if mins else 90.0,
            "max_angle_p95": round(maxs[-k5 - 1], 1) if maxs else 90.0,
            "min_angle": round(mins[0], 1) if mins else 90.0}


def keep_unchanged_faces(mesh, prev, old_sigs, new_sigs, changed, eps=1e-6):
    """2-2: replace the polygons of every unchanged CAD face of `mesh` with
    that face's polygons from the previous bake `prev` (hand edits included).

    A face is swapped only when the old polygons' outline vertices (those on
    the face's boundary edges) land exactly on the new outline vertices --
    otherwise a neighbour's edge spacing moved and the copy would not weld.
    Interior vertices come along as new vertices; UVs, smooth flags and the
    cad_face attribute are carried. Returns the list of kept face indices."""
    sig_to_old = {}
    for k, v in old_sigs.items():
        sig_to_old.setdefault(v, int(k))
    nb = bmesh.new(); nb.from_mesh(mesh)
    ob = bmesh.new(); ob.from_mesh(prev)
    n_lay = nb.faces.layers.int.get("cad_face")
    o_lay = ob.faces.layers.int.get("cad_face")
    n_edge = nb.edges.layers.int.get("cad_edge")
    n_uv = nb.loops.layers.uv.get("UVMap")
    o_uv = ob.loops.layers.uv.get("UVMap")
    if n_lay is None or o_lay is None:
        nb.free(); ob.free()
        return []
    n_faces, o_faces = {}, {}
    for f in nb.faces:
        n_faces.setdefault(f[n_lay], []).append(f)
    for f in ob.faces:
        o_faces.setdefault(f[o_lay], []).append(f)

    def outline(faces):
        fs = set(faces)
        out = set()
        for f in faces:
            for e in f.edges:
                if sum(1 for g in e.link_faces if g in fs) == 1:
                    out.update(e.verts)
        return out

    def key(co):
        return (round(co.x / eps), round(co.y / eps), round(co.z / eps))

    kept = []
    for fi, sig in new_sigs.items():
        if fi in changed or sig not in sig_to_old:
            continue
        old_list = o_faces.get(sig_to_old[sig])
        new_list = n_faces.get(fi)
        if not old_list or not new_list:
            continue
        o_out, n_out = outline(old_list), outline(new_list)
        n_by_key = {key(v.co): v for v in n_out}
        if len(o_out) != len(n_out) or any(key(v.co) not in n_by_key for v in o_out):
            continue
        # drop the fresh polygons, their interior edges and interior vertices
        fs = set(new_list)
        inner_e = {e for f in new_list for e in f.edges
                   if sum(1 for g in e.link_faces if g in fs) != 1}
        inner = {v for f in new_list for v in f.verts} - n_out
        for f in new_list:
            nb.faces.remove(f)
        for e in inner_e:
            if e.is_valid and not e.link_faces:
                nb.edges.remove(e)
        for v in inner:
            if v.is_valid and not v.link_faces:
                nb.verts.remove(v)
        vmap = {v: n_by_key[key(v.co)] for v in o_out}
        n_out_edges = {e for v in n_out for e in v.link_edges}
        for f in old_list:
            vs = []
            for v in f.verts:
                if v not in vmap:
                    vmap[v] = nb.verts.new(v.co)
                vs.append(vmap[v])
            try:
                g = nb.faces.new(vs)
            except ValueError:
                continue
            g[n_lay] = fi
            g.smooth = f.smooth
            if n_edge is not None:
                for e in g.edges:
                    if e not in n_out_edges:          # created here: inside the face
                        e[n_edge] = -1
            if n_uv is not None and o_uv is not None:
                for lo, ln in zip(f.loops, g.loops):
                    ln[n_uv].uv = lo[o_uv].uv
        kept.append(fi)
    nb.to_mesh(mesh)
    nb.free(); ob.free()
    mesh.update()
    return sorted(kept)


POLAR_CAPS = True
POLAR_CAP_MIN_FAN = 8


def _fit_sphere(points):
    """Centre and radius of the sphere through the points (least squares), or
    None when they do not lie on one."""
    import numpy as np
    P = np.array([tuple(p) for p in points], dtype=float)
    if len(P) < 8:
        return None
    A = np.hstack([2.0 * P, np.ones((len(P), 1))])
    sol = np.linalg.lstsq(A, (P * P).sum(axis=1), rcond=None)[0]
    c = sol[:3]
    r2 = sol[3] + c.dot(c)
    if not r2 > 0.0:
        return None
    r = float(r2) ** 0.5
    if np.abs(np.linalg.norm(P - c, axis=1) - r).max() > 2e-3 * r:
        return None
    return Vector(tuple(c)), r


def _rings_from(pole, inside):
    """Vertex rings round a pole by edge steps: ring 0 = the pole, ring i =
    the points first reached in i steps (latitude rows on a lat / long
    grid), walking only through points `inside` accepts."""
    rings = [[pole]]
    seen = {pole}
    while True:
        nxt = []
        for v in rings[-1]:
            for e in v.link_edges:
                w = e.other_vert(v)
                if w not in seen and inside(w):
                    seen.add(w)
                    nxt.append(w)
        if not nxt:
            return rings
        rings.append(nxt)


def _ring_cycle(ring):
    """The points of a ring in order along its own edges, or None when they
    do not form one simple loop."""
    rs = set(ring)
    adj = {v: [e.other_vert(v) for e in v.link_edges if e.other_vert(v) in rs] for v in ring}
    if any(len(a) != 2 for a in adj.values()):
        return None
    out = [ring[0]]
    prev = None
    while True:
        a, b = adj[out[-1]]
        w = b if a is prev else a
        if w is out[0]:
            break
        prev = out[-1]
        out.append(w)
        if len(out) > len(ring):
            return None
    return out if len(out) == len(ring) else None


def polar_caps(bm, data):
    """A sphere laid in latitude / longitude rows ends in a fan of thin
    triangles at each pole, which pinches under subdivision. Round each pole
    (a point held by >= POLAR_CAP_MIN_FAN faces of one sphere face) the rows
    down to about k / (2 pi) steps (k points per row: where a cap's cells
    come out square) are taken out and the row there is filled with the
    round-plate layout (rings along the rim round a relaxed inner square),
    laid in the pole's azimuthal-equidistant plane and put back on the
    sphere: all quads, four valence-3 corners instead of one valence-k pole
    -- a cube-sphere cap. The cap gets its own UV island (the same plane at
    the sphere's texel density) beside the others. Returns the caps made."""
    from .quad_bake import _fill_plane_grid
    cad = bm.faces.layers.int.get("cad_face")
    uvl = bm.loops.layers.uv.get("UVMap")
    if cad is None or not POLAR_CAPS:
        return []
    spheres = {f.get("i") for f in data.get("faces", []) if f.get("kind") == "sphere"}
    caps = []
    cap_sphere = []
    capped = set()
    for c in spheres:
        ffaces = [f for f in bm.faces if f[cad] == c]
        fverts = {v for f in ffaces for v in f.verts}
        fit = _fit_sphere([v.co for v in fverts])
        if fit is None:
            continue
        C, R = fit
        dens = []
        if uvl is not None:
            for f in ffaces[:400]:
                for lo in f.loops:
                    l3 = (lo.vert.co - lo.link_loop_next.vert.co).length
                    if l3 > 1e-12:
                        dens.append((lo[uvl].uv - lo.link_loop_next[uvl].uv).length / l3)
        dens = sorted(dens)[len(dens) // 2] if dens else 1.0

        def own(v):
            # a point of this sphere face only, on no outline but its own seam,
            # and not in a cap made already
            if not v.is_valid or v in capped or not v.link_faces or any(f[cad] != c for f in v.link_faces):
                return False
            return all(all(f[cad] == c for f in e.link_faces) and len(e.link_faces) == 2 for e in v.link_edges)
        for pole in [v for v in fverts if v.is_valid]:
            if not pole.is_valid or len(pole.link_faces) < POLAR_CAP_MIN_FAN or not own(pole):
                continue
            axis = (pole.co - C).normalized()
            # the pairing may have joined fan triangles into kites at the
            # pole; cut them back along the pole's diagonal so ring 1 is the
            # whole fan rim
            cut = []
            for f in [f for f in pole.link_faces if len(f.verts) == 4]:
                lo = next(l for l in f.loops if l.vert is pole)
                far = lo.link_loop_next.link_loop_next.vert
                try:
                    res = bmesh.utils.face_split(f, pole, far)
                    if res and res[1] is not None:
                        cut.append(res[1].edge)
                except (ValueError, RuntimeError):
                    pass

            def uncut():
                # no cap here after all: the kites come back
                for e in cut:
                    if e.is_valid and len(e.link_faces) == 2:
                        try:
                            bmesh.utils.face_join(list(e.link_faces))
                        except (ValueError, RuntimeError):
                            pass
            rings = _rings_from(pole, own)
            if len(rings) < 2:
                uncut()
                continue
            k = len(rings[1])
            want = max(1, int(round(k / (2.0 * math.pi))))
            ring = None
            jj = None
            for j in range(min(want, len(rings) - 1), 0, -1):
                cyc = _ring_cycle(rings[j])
                if cyc is not None and len(cyc) % 2 == 0 and len(cyc) >= 8:
                    ring, jj = cyc, j
                    break
            if ring is None:
                # no clean row (an odd fan rim, or a cut close by): lay the
                # pole's neighbourhood, up to any outline, as a lattice
                got = _lattice_cap(bm, cad, c, C, R, pole, rings, want, own, fverts)
                if got:
                    caps.append((got[0], got[1], dens))
                    cap_sphere.append((C, R))
                    capped.update(v for g in got[0] for v in g.verts)
                else:
                    uncut()
                continue
            ring_set = set(ring)
            inner = {v for r in rings[:jj] for v in r}
            region = {f for v in inner for f in v.link_faces}
            if any(f[cad] != c or any(w not in inner and w not in ring_set for w in f.verts) for f in region):
                uncut()
                continue
            ex = ring[0].co - C
            ex = ex - ex.dot(axis) * axis
            if ex.length < 1e-12:
                uncut()
                continue
            ex.normalize()
            ey = axis.cross(ex)

            def az(co, C=C, R=R, axis=axis, ex=ex, ey=ey):
                d = (co - C).normalized()
                th = math.acos(max(-1.0, min(1.0, d.dot(axis))))
                ph = math.atan2(d.dot(ey), d.dot(ex))
                return R * th * math.cos(ph), R * th * math.sin(ph)

            def from_az(x, y, C=C, R=R, axis=axis, ex=ex, ey=ey):
                th = math.hypot(x, y) / R
                ph = math.atan2(y, x)
                d = math.cos(th) * axis + math.sin(th) * (math.cos(ph) * ex + math.sin(ph) * ey)
                return C + R * d
            loop = [[n, *az(v.co)] for n, v in enumerate(ring)]
            v3 = [(p_[1], p_[2], 0.0) for p_ in loop]
            extra = []
            face = {"kind": "plane", "loops": [loop], "su": 1.0, "sv": 1.0, "rev": False, "i": c}
            polys = _fill_plane_grid(face, v3, extra)
            if not polys:
                uncut()
                continue
            smooth = next(iter(region)).smooth
            nb = len(ring)
            new_v = [bm.verts.new(from_az(co[0], co[1])) for co in extra]
            for f in region:
                bm.faces.remove(f)
            for v in inner:
                if v.is_valid:
                    bm.verts.remove(v)

            def vert(vid):
                return ring[vid] if vid < nb else new_v[vid - nb]
            made = []
            for q in polys:
                try:
                    g = bm.faces.new([vert(x[0]) for x in q])
                except ValueError:
                    continue
                g[cad] = c
                g.smooth = smooth
                made.append(g)
            for g in made:
                g.normal_update()
                if g.normal.dot(g.calc_center_median() - C) < 0.0:
                    g.normal_flip()
            caps.append((made, az, dens))
            cap_sphere.append((C, R))
            capped.update(v for g in made for v in g.verts)
    # a cap is a UV island of its own: its rim is a seam, which the pairing,
    # the walks and the strip split never cross
    keep = [n for n, (made, _a, _d) in enumerate(caps) if any(g.is_valid for g in made)]
    caps = [([g for g in caps[n][0] if g.is_valid], caps[n][1], caps[n][2]) for n in keep]
    cap_sphere = [cap_sphere[n] for n in keep]
    for made, _az, _d in caps:
        ms = set(made)
        for g in made:
            for e in g.edges:
                if any(h not in ms for h in e.link_faces):
                    e.seam = True
    uvmaps = _place_cap_islands(bm, uvl, caps) if (uvl is not None and caps) else [None] * len(caps)
    info = []
    for (made, _az, _d), um, cr in zip(caps, uvmaps, cap_sphere):
        info.append(({v for g in made for v in g.verts}, cr[0], cr[1], um))
    return info


def _lattice_cap(bm, cad, c, C, R, pole, rings, want, own, fverts):
    """A pole whose rows are cut by an outline nearby: the faces round the
    pole up to `want` rows (stopping at the outline) are taken out and their
    outline -- rows and the cut together -- is laid again with the flat
    plate's lattice fill in the pole's azimuthal-equidistant plane (so the
    lattice is square round the pole instead of a fan); the triangles it
    leaves go through the usual pairing afterwards. UVs: the azimuthal plane,
    as an island of its own like a ring cap. Returns (faces, azimuthal map) when the region was
    replaced, for its own UV island, else None."""
    from .quad_bake import _fill_holed_plane
    uvl = bm.loops.layers.uv.get("UVMap")
    inner = set()
    for r in rings[:max(2, want)]:
        inner.update(v for v in r if own(v))
    if pole not in inner:
        return False
    region = {f for v in inner for f in v.link_faces}
    if any(f[cad] != c for f in region):
        return False
    # the region's outline as one loop
    bnd = {}
    for f in region:
        for e in f.edges:
            if sum(1 for g in e.link_faces if g in region) == 1:
                lo = next(l for l in f.loops if l.edge is e)
                bnd[lo.vert] = lo.link_loop_next.vert
    if len(bnd) < 8:
        return False
    start = next(iter(bnd))
    loopv = [start]
    while True:
        w = bnd.get(loopv[-1])
        if w is None:
            return False
        if w is start:
            break
        loopv.append(w)
        if len(loopv) > len(bnd):
            return False
    if len(loopv) != len(bnd) or any(v in inner for v in loopv):
        return False
    axis = (pole.co - C).normalized()
    ex = loopv[0].co - C
    ex = ex - ex.dot(axis) * axis
    if ex.length < 1e-12:
        return False
    ex.normalize()
    ey = axis.cross(ex)

    def az(co):
        d = (co - C).normalized()
        th = math.acos(max(-1.0, min(1.0, d.dot(axis))))
        ph = math.atan2(d.dot(ey), d.dot(ex))
        return R * th * math.cos(ph), R * th * math.sin(ph)

    def from_az(x, y):
        th = math.hypot(x, y) / R
        ph = math.atan2(y, x)
        d = math.cos(th) * axis + math.sin(th) * (math.cos(ph) * ex + math.sin(ph) * ey)
        return C + R * d
    # the fill walks its outline counter-clockwise for a front-facing face
    pts = [az(v.co) for v in loopv]
    area = sum(pts[n][0] * pts[(n + 1) % len(pts)][1] - pts[(n + 1) % len(pts)][0] * pts[n][1]
               for n in range(len(pts)))
    order = list(range(len(loopv)))
    loop = [[n, pts[n][0], pts[n][1]] for n in order]
    v3 = [(p_[1], p_[2], 0.0) for p_ in loop]
    face = {"kind": "plane", "loops": [loop], "su": 1.0, "sv": 1.0, "rev": area < 0.0, "i": c,
            "lattice": True, "steiner": []}
    stats = {"hole_rings": 0, "hole_rings_skipped": 0, "cdt_new_verts": 0, "degenerate_dropped": 0,
             "ears_flipped": 0, "graded_rings": 0, "notes": []}
    extra = []
    try:
        polys = _fill_holed_plane(face, v3, extra, len(v3), stats, plain=True)
    except Exception:
        polys = None
    if not polys:
        return False
    # keep the outer UV of the loop points (from the faces that stay)
    uv_keep = {}
    if uvl is not None:
        for v in loopv:
            for lo in v.link_loops:
                if lo.face not in region:
                    uv_keep.setdefault(v, tuple(lo[uvl].uv))
    smooth = next(iter(region)).smooth
    nb = len(loopv)
    new_v = [bm.verts.new(from_az(co[0], co[1])) for co in extra]
    for f in region:
        bm.faces.remove(f)
    for v in inner:
        if v.is_valid and not v.link_faces:
            bm.verts.remove(v)

    def vert(vid):
        return loopv[vid] if vid < nb else new_v[vid - nb]
    made = []
    for q in polys:
        vs = [vert(x[0]) for x in q]
        if len(set(vs)) != len(vs):
            continue
        try:
            g = bm.faces.new(vs)
        except ValueError:
            continue
        g[cad] = c
        g.smooth = smooth
        made.append(g)
    for g in made:
        g.normal_update()
        if g.normal.dot(g.calc_center_median() - C) < 0.0:
            g.normal_flip()
    return made, az



def _place_cap_islands(bm, uvl, caps):
    """Each cap's UVs: its azimuthal plane at the sphere's texel density, as
    an island of its own in a row to the right of the existing islands; then
    all UVs are scaled together back into the unit square."""
    cap_faces = {g for made, _a, _d in caps for g in made}
    rest = [(lo[uvl].uv.x, lo[uvl].uv.y) for f in bm.faces if f not in cap_faces for lo in f.loops]
    x1 = max((x for x, _ in rest), default=0.0)
    y0 = min((y for _, y in rest), default=0.0)
    gap = 0.02
    cursor = x1 + gap
    maps = []
    for made, az, dens in caps:
        P = {lo: az(lo.vert.co) for g in made for lo in g.loops}
        mx = min(p[0] for p in P.values())
        my = min(p[1] for p in P.values())
        Mx = max(p[0] for p in P.values())
        for lo, (x, y) in P.items():
            lo[uvl].uv = (cursor + (x - mx) * dens, y0 + (y - my) * dens)
        maps.append((az, cursor, mx, y0, my, dens))
        cursor += (Mx - mx) * dens + gap
    allx = [lo[uvl].uv.x for f in bm.faces for lo in f.loops]
    ally = [lo[uvl].uv.y for f in bm.faces for lo in f.loops]
    lo_x, lo_y = min(allx), min(ally)
    span = max(max(allx) - lo_x, max(ally) - lo_y, 1e-12)
    sc = 0.98 / span
    for f in bm.faces:
        for lo in f.loops:
            lo[uvl].uv = (0.01 + (lo[uvl].uv.x - lo_x) * sc, 0.01 + (lo[uvl].uv.y - lo_y) * sc)
    out = []
    for az, cx, mx, y0, my, dens in maps:
        def uvmap(co, az=az, cx=cx, mx=mx, y0=y0, my=my, dens=dens):
            x, y = az(co)
            return (0.01 + (cx + (x - mx) * dens - lo_x) * sc, 0.01 + (y0 + (y - my) * dens - lo_y) * sc)
        out.append(uvmap)
    return out


def relax_caps(bm, cap_info, iters=30):
    """Laplacian relax of the points inside each sphere cap (the cap's rim
    and anything on a seam stay), each sweep put back on the sphere; a cap
    whose worst quad corner would drop under 10 degrees and below where it
    was keeps its points. Then the cap's UVs follow its azimuthal map."""
    uvl = bm.loops.layers.uv.get("UVMap")
    lim = math.radians(10.0)
    for verts, C, R, uvmap in cap_info:
        inner = [v for v in verts if v.is_valid and v.link_faces
                 and not any(e.seam or len(e.link_faces) != 2 for e in v.link_edges)]
        if not inner:
            continue
        faces = {f for v in inner for f in v.link_faces}

        def worst():
            return min((min(lo.calc_angle() for lo in f.loops) for f in faces if len(f.verts) == 4),
                       default=math.pi)
        w0 = worst()
        old = {v: v.co.copy() for v in inner}
        for _ in range(iters):
            new = []
            for v in inner:
                nb = [e.other_vert(v) for e in v.link_edges]
                co = nb[0].co.copy()
                for o in nb[1:]:
                    co += o.co
                d = co / len(nb) - C
                new.append(C + d * (R / max(d.length, 1e-12)))
            for v, co in zip(inner, new):
                v.co = co
        w1 = worst()
        if w1 < lim and w1 < w0:
            for v, co in old.items():
                v.co = co
        if uvl is not None and uvmap is not None:
            for f in faces:
                for lo in f.loops:
                    if lo.vert in old:
                        lo[uvl].uv = uvmap(lo.vert.co)


def make_quad_bake_mesh(name, data, join_tris=True, sharp_angle_deg=30.0, join_shape_deg=60.0,
                        sharp_mode='CAD', crease=False):
    """Build and return (mesh, report) from a quad_topology dict, or
    (None, report) when nothing could be filled."""
    verts, polys, poly_face, poly_uvs, rep = build_quad_mesh_uv(data)
    rep["joined"] = 0
    if not polys:
        return None, rep

    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], polys)
    attr = me.attributes.new("cad_face", 'INT', 'FACE')
    attr.data.foreach_set("value", poly_face)
    uv_layer = me.uv_layers.new(name="UVMap")
    flat = [c for uvs in poly_uvs for uv in uvs for c in uv]
    uv_layer.data.foreach_set("uv", flat)
    me.validate(clean_customdata=False)

    cad_pairs = cad_edge_pairs(data)
    creases = cad_edge_creases(data) if sharp_mode == 'CAD' else None
    rep["sharp_source"] = "CAD continuity" if creases is not None else "mesh angle %.0f deg" % sharp_angle_deg
    n_sharp = 0
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.normal_update()
    # 2-1: which CAD edge each mesh edge lies on (-1: inside a face)
    edge_of = {}
    for k, rec in enumerate(data.get("edges", [])):
        vids = rec[1:]
        for a, b in zip(vids, vids[1:]):
            if a != b:
                edge_of[frozenset((a, b))] = k
    cad_lay = bm.edges.layers.int.new("cad_edge")
    for e in bm.edges:
        e[cad_lay] = edge_of.get(frozenset((e.verts[0].index, e.verts[1].index)), -1)
    sharp_edges = []
    limit = math.radians(sharp_angle_deg)
    for e in bm.edges:
        key = frozenset((e.verts[0].index, e.verts[1].index))
        if key not in cad_pairs:
            continue
        e.seam = True
        # (not `crease`: that name is the caller's subdivision switch)
        bend = creases.get(key, -1.0) if creases is not None else -1.0
        if bend >= 0.0:
            sharp = bend > CAD_CREASE_DEG
        elif len(e.link_faces) == 2:
            a, b = e.link_faces
            sharp = (a.normal.length > 0 and b.normal.length > 0
                     and a.normal.angle(b.normal) > limit)
        else:
            sharp = True                       # an open boundary
        if sharp:
            e.smooth = False
            n_sharp += 1
            sharp_edges.append(e)
    rep["sharp"] = n_sharp
    for f in bm.faces:
        f.smooth = True
    # sphere poles first, so what a lattice cap leaves is paired like the rest
    cap_info = polar_caps(bm, data)
    rep["polar_caps"] = len(cap_info)
    if join_tris:
        rep["joined"] = pair_triangles(bm, shape_deg=join_shape_deg)
        # stranded triangles walk to each other through the quads; the second
        # pass may pass skewed quads (MIGRATE_SLACK_DEG past the shape limit) --
        # the relax below evens them out on flat faces, and on curved faces
        # (a notched cone, a holed cylinder) a slightly skewed quad still
        # beats a pair of triangles
        planes = {f.get("i") for f in data.get("faces", []) if f.get("kind") == "plane"}
        rep["migrated"] = migrate_triangles(bm, shape_deg=join_shape_deg)
        rep["migrated"] += migrate_triangles(bm, shape_deg=join_shape_deg + MIGRATE_SLACK_DEG,
                                             only=None)
        projs = _surface_projectors(data)
        split_mids = []
        split_recs = []
        rep["split_pairs"] = split_pair_triangles(bm, planes, curved=projs, mids_out=split_mids,
                                                  records_out=split_recs)
        # the split moves triangles' neighbourhoods: a second walk may now
        # bring stranded ones onto a straight strip
        rep["migrated"] += migrate_triangles(bm, shape_deg=join_shape_deg + MIGRATE_SLACK_DEG, only=None)
        rep["split_pairs"] += split_pair_triangles(bm, planes, curved=projs, mids_out=split_mids,
                                                   records_out=split_recs)
        relax_planes(bm, planes, iters=20)
        centroid_relax(split_mids, projs)
        rep["doublets"] = dissolve_doublets(bm)
        plane_uv_affine(bm, planes)          # the split points moved after the relax
    relax_caps(bm, cap_info)
    sizes = [len(f.verts) for f in bm.faces]
    rep["quads"] = sizes.count(4)
    rep["tris"] = sizes.count(3)
    rep["ngons"] = len(sizes) - rep["quads"] - rep["tris"]
    # points no face uses (a round plate's grid points inside a hole's
    # block, a folded temporary midpoint) leave the mesh
    loose = [v for v in bm.verts if not v.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context='VERTS')
        bm.verts.index_update()
    rep["quality"] = mesh_quality(bm, cad_pairs, rep)
    sharp_keys = {frozenset((e.verts[0].index, e.verts[1].index)) for e in sharp_edges if e.is_valid}
    bm.to_mesh(me)
    bm.free()
    me.update()
    if crease and sharp_keys:
        # 2-3: subdivision keeps the CAD creases sharp
        attr = me.attributes.get("crease_edge") or me.attributes.new("crease_edge", 'FLOAT', 'EDGE')
        vals = [1.0 if frozenset(e.vertices) in sharp_keys else 0.0 for e in me.edges]
        attr.data.foreach_set("value", vals)
        rep["creased"] = int(sum(vals))
    return me, rep
