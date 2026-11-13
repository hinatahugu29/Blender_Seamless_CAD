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
    return {"quad_pct": round(100.0 * rep["quads"] / n, 1), "poles": poles,
            "edge_p5_p95": round(ratio, 3), "open_edges": open_edges}


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
        crease = creases.get(key, -1.0) if creases is not None else -1.0
        if crease >= 0.0:
            sharp = crease > CAD_CREASE_DEG
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
    if join_tris:
        rep["joined"] = pair_triangles(bm, shape_deg=join_shape_deg)
    sizes = [len(f.verts) for f in bm.faces]
    rep["quads"] = sizes.count(4)
    rep["tris"] = sizes.count(3)
    rep["ngons"] = len(sizes) - rep["quads"] - rep["tris"]
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
