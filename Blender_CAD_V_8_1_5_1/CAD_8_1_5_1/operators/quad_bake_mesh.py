"""Quad Bake — turn the filled topology (quad_bake.py) into a Blender mesh.

Kept apart from quad_bake.py because this half needs bpy / bmesh:
  * a "UVMap" layer: one island per CAD face, packed at one texel density
  * UV seams on every CAD edge (exactly where the islands are cut)
  * sharp edges on CAD edges whose two faces meet at more than `sharp_angle`
    (tangent fillet seams stay smooth), smooth shading everywhere else
  * optionally, triangle pairs that form a clean quad are joined — within one
    CAD face only (a seam stops the join), so no polygon straddles a CAD edge
  * a per-polygon "cad_face" INT attribute (1-based CAD face index)
"""

import math

import bmesh
import bpy

from .quad_bake import build_quad_mesh_uv, cad_edge_pairs


def make_quad_bake_mesh(name, data, join_tris=True, sharp_angle_deg=30.0, join_shape_deg=40.0):
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
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.normal_update()
    limit = math.radians(sharp_angle_deg)
    for e in bm.edges:
        key = frozenset((e.verts[0].index, e.verts[1].index))
        if key not in cad_pairs:
            continue
        e.seam = True
        if len(e.link_faces) == 2:
            a, b = e.link_faces
            if a.normal.length > 0 and b.normal.length > 0 and a.normal.angle(b.normal) > limit:
                e.smooth = False
    for f in bm.faces:
        f.smooth = True
    if join_tris:
        tris = [f for f in bm.faces if len(f.verts) == 3]
        before = len(bm.faces)
        if tris:
            bmesh.ops.join_triangles(
                bm, faces=tris, cmp_seam=True, cmp_sharp=True, cmp_uvs=False,
                cmp_vcols=False, cmp_materials=False,
                angle_face_threshold=math.radians(10.0),
                angle_shape_threshold=math.radians(join_shape_deg))
        rep["joined"] = before - len(bm.faces)
    bm.to_mesh(me)
    bm.free()
    me.update()
    return me, rep
