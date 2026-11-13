import bpy
import uuid
import math
import mathutils
from bpy_extras import view3d_utils
from ..core_bridge import get_core, update_cad_preview, update_cad_preview_high_quality, update_cad_preview_fast, is_core_busy, get_or_create_stack_ptr
from ..drawing import get_wireframe_engine
from .. import utils

RESULT_COLLECTION_NAME = "Result"

def ensure_result_collection(parent_col):
    if not parent_col:
        return None
    result_col = bpy.data.collections.get(RESULT_COLLECTION_NAME)
    if result_col is None:
        result_col = bpy.data.collections.new(RESULT_COLLECTION_NAME)
    if result_col.name not in parent_col.children:
        parent_col.children.link(result_col)
    return result_col

QUAD_BAKE_POLY_WARN = 200000   # 0-3: warn above this many polygons


class SEAMLESS_OT_BakeMesh(bpy.types.Operator):
    bl_idname = "seamless.bake_mesh"
    bl_label = "Bake to Mesh"
    def execute(self, context):
        props = utils.get_active_props(context)
        if not props:
            self.report({'ERROR'}, "No active Seamless collection found!")
            return {'CANCELLED'}
        # C1: "Leave Out of Bake" の行を外した形状から Bake し、終わったら戻す
        if not any(getattr(p, "bake_suppressed", False) and not p.suppressed for p in props.primitives):
            return self._execute(context, props)
        from .. import core_bridge
        # Bake 後は結果メッシュがアクティブになるので、戻す側は元の CAD コレクションを直接指す
        col = utils.get_active_collection(context)
        if col is None:
            return self._execute(context, props)

        def rebuild():
            core_bridge._update_cad_preview_internal_for_col(col, context, force=True, sync=True)
        core_bridge._bake_suppress_active = True
        try:
            rebuild()
            return self._execute(context, props)
        finally:
            core_bridge._bake_suppress_active = False
            rebuild()

    def _execute(self, context, props):
        core = get_core()
        if not core or not hasattr(core, "generate_mesh"):
            self.report({'ERROR'}, "Core generate_mesh not found")
            return {'CANCELLED'}
        
        deflection = props.mesh_quality
        angular_deflection = props.mesh_angular_quality
        if props.use_high_quality_bake:
            deflection = props.bake_quality
            angular_deflection = props.bake_angular_quality
            # ベイク前に高精度で再計算を要求（Rust側のキャッシュをOFF化して再テセレーションさせる）
            update_cad_preview_high_quality(context, deflection_override=deflection, angular_override=angular_deflection)
        
        # 度からラジアンへ変換
        angular_deflection_rad = math.radians(angular_deflection)
        stack_ptr = get_or_create_stack_ptr(utils.get_active_collection(context))
        if getattr(props, "bake_topology", 'TRIS') == 'QUAD':
            return self._bake_quad(context, core, props, stack_ptr)
        result = core.generate_mesh(stack_ptr, deflection, angular_deflection_rad)
        if result is None:
            self.report({'ERROR'}, "Mesh generation failed (server did not respond)")
            return {'CANCELLED'}
        v, t, f_ids, f_t_counts = result
        
        mesh = bpy.data.meshes.new("SeamlessBake")
        obj = bpy.data.objects.new("SeamlessBake", mesh)
        parent_col = bpy.data.collections.get("Seamless_CAD")
        if parent_col is None:
            parent_col = bpy.data.collections.new("Seamless_CAD")
            context.scene.collection.children.link(parent_col)
        result_col = ensure_result_collection(parent_col)
        if result_col is None:
            self.report({'ERROR'}, "Failed to prepare Result collection")
            return {'CANCELLED'}
        result_col.objects.link(obj)
        verts = [(v[i], v[i+1], v[i+2]) for i in range(0, len(v), 3)]
        faces = [(t[i], t[i+1], t[i+2]) for i in range(0, len(t), 3)]
        mesh.from_pydata(verts, [], faces)
        mesh.update()
        
        # 全ての選択を解除し、生成したメッシュを選択・アクティブにする
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        context.view_layer.objects.active = obj
        
        return {'FINISHED'}

    def _bake_quad(self, context, core, props, stack_ptr):
        """Quad Bake: shared-edge topology from the kernel, filled in
        operators/quad_bake.py, turned into a mesh with UVs / seams / sharp
        edges in operators/quad_bake_mesh.py."""
        from .quad_bake_mesh import make_quad_bake_mesh
        from .. import core_bridge
        # 0-1: an edit that has not settled yet leaves the kernel stack half
        # built (it read 0 faces in tests). Rebuild this part synchronously first.
        # The proxies' matrix_world are read for the stack; right after a
        # property edit the depsgraph has not run yet and they still hold the
        # old transform (a SUB tool at its old size carved the whole box away).
        col = utils.get_active_collection(context)
        if col is not None:
            utils.sync_proxies(context)       # props -> proxy transforms
            context.view_layer.update()       # -> matrix_world
            core_bridge._update_cad_preview_internal_for_col(col, context, force=True, sync=True)
            stack_ptr = get_or_create_stack_ptr(col)
        import json
        from .quad_bake import report_text
        overrides = parse_span_overrides(getattr(props, "quad_span_overrides", ""))
        runs = [(props.quad_bake_tol, "SeamlessQuadBake")]
        if getattr(props, "quad_bake_pair", False):
            # 2-4: the dense copy at a quarter of the tolerance. Both come from
            # the same CAD faces, so each UV island has the same box and the
            # shelf packing lays them out identically.
            runs = [(props.quad_bake_tol, "SeamlessQuadBake_low"),
                    (props.quad_bake_tol / 4.0, "SeamlessQuadBake_high")]
        parent_col = bpy.data.collections.get("Seamless_CAD")
        if parent_col is None:
            parent_col = bpy.data.collections.new("Seamless_CAD")
            context.scene.collection.children.link(parent_col)
        result_col = ensure_result_collection(parent_col)
        if result_col is None:
            self.report({'ERROR'}, "Failed to prepare Result collection")
            return {'CANCELLED'}
        made = []
        for tol, name in runs:
            data = core.quad_topology(stack_ptr, tol, getattr(props, "quad_bake_uniform", True), overrides)
            if not data:
                self.report({'ERROR'}, "Quad Bake: kernel returned no topology")
                return {'CANCELLED'}
            data["pole_quads"] = bool(getattr(props, "quad_bake_pole_quads", False))
            mesh, rep = make_quad_bake_mesh(
                name, data,
                join_tris=props.quad_bake_join_tris,
                sharp_angle_deg=props.quad_bake_sharp_angle,
                join_shape_deg=props.quad_bake_join_shape,
                sharp_mode=props.quad_bake_sharp_mode,
                crease=bool(getattr(props, "quad_bake_subd", False)))
            if mesh is None:
                self.report({'ERROR'}, "Quad Bake: no faces could be filled")
                return {'CANCELLED'}
            obj = bpy.data.objects.new(name, mesh)
            result_col.objects.link(obj)
            if getattr(props, "quad_bake_subd", False):
                mod = obj.modifiers.new("Subdivision", 'SUBSURF')
                mod.levels = 2
                mod.render_levels = 2
            # 2-2: which CAD faces changed since the previous bake of this part
            import time
            from .quad_bake import face_signatures, compare_signatures
            sigs = face_signatures(data)
            # a pair bake's high copy compares with earlier high copies only (and
            # the low / single bake with earlier low / single ones): the other
            # role of the SAME bake is not "the previous bake"
            role = "high" if name.endswith("_high") else "low"
            prev = None
            if col is not None:
                for m in bpy.data.meshes:
                    if (m is mesh or m.users == 0 or m.get("quad_bake_part") != col.name
                            or not m.get("quad_bake_sigs") or m.get("quad_bake_role", "low") != role):
                        continue
                    if prev is None or m.get("quad_bake_time", 0.0) > prev.get("quad_bake_time", 0.0):
                        prev = m
            if prev is not None:
                changed = compare_signatures(json.loads(prev["quad_bake_sigs"]), sigs)
                rep["changed_faces"] = changed
                ch = set(changed)
                lay = mesh.attributes.get("cad_face")
                if lay is not None:
                    fidx = [0] * len(mesh.polygons)
                    lay.data.foreach_get("value", fidx)
                    attr = mesh.attributes.new("quad_changed", 'BOOLEAN', 'FACE')
                    attr.data.foreach_set("value", [fi in ch for fi in fidx])
            if prev is not None and getattr(props, "quad_bake_keep", False):
                from .quad_bake_mesh import keep_unchanged_faces
                rep["kept_faces"] = keep_unchanged_faces(
                    mesh, prev, json.loads(prev["quad_bake_sigs"]), sigs, set(rep.get("changed_faces", [])))
            mesh["quad_bake_sigs"] = json.dumps({str(k): v for k, v in sigs.items()})
            mesh["quad_bake_time"] = time.time()
            mesh["quad_bake_role"] = role
            rep["overrides_applied"] = int(data.get("overrides_applied", 0))
            rep["overrides_given"] = len(overrides) // 4
            mesh["quad_bake_report"] = json.dumps(rep)
            if col is not None:
                mesh["quad_bake_part"] = col.name          # 2-1: where Set Edge Spans writes
            print(report_text(rep))
            made.append((obj, rep))
        bpy.ops.object.select_all(action='DESELECT')
        for obj, _ in made:
            obj.select_set(True)
        context.view_layer.objects.active = made[0][0]

        obj, rep = made[0]
        n_poly = len(obj.data.polygons)
        msg = ("Quad Bake: %d faces (%d ruled, %d grid, %d n-gon, %d triangulated), %d polygons"
               % (rep["faces"], rep["ruled"], rep["coons"], rep["ngon"], rep["cdt"], n_poly))
        if len(made) > 1:
            msg += " + high %d polygons" % len(made[1][0].data.polygons)
        if rep.get("overrides_given"):
            msg += "; edge spans %d/%d applied" % (rep["overrides_applied"], rep["overrides_given"])
        heavy = max(len(o.data.polygons) for o, _ in made)
        if heavy > QUAD_BAKE_POLY_WARN:
            msg += " — %d polygons is heavy: raise Quad Tol or use the Low preset" % heavy
            self.report({'WARNING'}, msg)
        elif rep["failed"] or rep["edge_fail"]:
            msg += " — %d face(s) / %d edge(s) failed, see console" % (rep["failed"], rep["edge_fail"])
            self.report({'WARNING'}, msg)
        elif rep.get("quality", {}).get("open_edges"):
            msg += " — the shape is open (%d boundary edges)" % rep["quality"]["open_edges"]
            self.report({'WARNING'}, msg)
        else:
            self.report({'INFO'}, msg)
        return {'FINISHED'}


def parse_span_overrides(text):
    """'x,y,z,n;...' -> flat [x, y, z, n, ...] (bad entries skipped)."""
    out = []
    for item in (text or "").split(";"):
        parts = item.split(",")
        if len(parts) != 4:
            continue
        try:
            vals = [float(x) for x in parts]
        except ValueError:
            continue
        if all(math.isfinite(x) for x in vals):
            out.extend(vals)
    return out


class SEAMLESS_OT_QuadBakeSetSpans(bpy.types.Operator):
    """Set the span count of the CAD edges selected on a Quad Bake mesh (Edit Mode); applied on the next bake"""
    bl_idname = "seamless.quad_bake_set_spans"
    bl_label = "Set Quad Edge Spans"
    bl_options = {'REGISTER', 'UNDO'}

    spans: bpy.props.IntProperty(name="Spans", default=8, min=1, max=256)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return bool(obj and obj.type == 'MESH' and obj.mode == 'EDIT'
                    and obj.data.get("quad_bake_part"))

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        import bmesh
        obj = context.active_object
        part = bpy.data.collections.get(obj.data.get("quad_bake_part", ""))
        if part is None or not getattr(part, "seamless_props", None):
            self.report({'ERROR'}, "The CAD part of this bake is gone")
            return {'CANCELLED'}
        bm = bmesh.from_edit_mesh(obj.data)
        lay = bm.edges.layers.int.get("cad_edge")
        if lay is None:
            self.report({'ERROR'}, "This mesh has no CAD edge data (bake it again)")
            return {'CANCELLED'}
        picked = {e[lay] for e in bm.edges if e.select and e[lay] >= 0}
        if not picked:
            self.report({'WARNING'}, "Select edges that lie on CAD edges")
            return {'CANCELLED'}
        groups = {}
        for e in bm.edges:
            if e[lay] in picked:
                groups.setdefault(e[lay], set()).update(v.co.copy() for v in e.verts)
        entries = [x for x in part.seamless_props.quad_span_overrides.split(";") if x.strip()]
        # the mesh's own coordinates ARE the CAD coordinates (the bake object is
        # made at the origin); the object's transform is ignored so a bake moved
        # aside for comparison still records the right edges
        for pts in groups.values():
            P = list(pts)
            c = [0.5 * (min(p[a] for p in P) + max(p[a] for p in P)) for a in range(3)]
            # replace an override already sitting on this edge (its centre may
            # have shifted a little with the span count: within a quarter of
            # the edge's extent, as the kernel matches)
            ext = max(max(p[a] for p in P) - min(p[a] for p in P) for a in range(3))
            lim2 = max(0.25 * ext, 1e-5) ** 2
            keep = []
            for it in entries:
                try:
                    x, y, z, _n = (float(t) for t in it.split(","))
                except ValueError:
                    continue
                if (x - c[0]) ** 2 + (y - c[1]) ** 2 + (z - c[2]) ** 2 > lim2:
                    keep.append(it)
            entries = keep + ["%.6f,%.6f,%.6f,%d" % (c[0], c[1], c[2], self.spans)]
        part.seamless_props.quad_span_overrides = ";".join(entries)
        self.report({'INFO'}, "%d edge(s) set to %d spans; bake again to apply" % (len(groups), self.spans))
        return {'FINISHED'}


class SEAMLESS_OT_QuadBakeClearSpans(bpy.types.Operator):
    """Forget all per-edge span overrides of the active CAD part"""
    bl_idname = "seamless.quad_bake_clear_spans"
    bl_label = "Clear Quad Edge Spans"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = utils.get_active_props(context)
        if props:
            props.quad_span_overrides = ""
        return {'FINISHED'}


class SEAMLESS_OT_CopyQuadBakeReport(bpy.types.Operator):
    """Copy the per-face Quad Bake report of the active baked mesh to the clipboard"""
    bl_idname = "seamless.copy_quad_bake_report"
    bl_label = "Copy Quad Bake Report"

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return bool(obj and obj.type == 'MESH' and obj.data.get("quad_bake_report"))

    def execute(self, context):
        import json
        from .quad_bake import report_text
        obj = context.active_object
        rep = json.loads(obj.data["quad_bake_report"])
        text = report_text(rep, title="Quad Bake report: %s" % obj.name)
        context.window_manager.clipboard = text
        self.report({'INFO'}, "Quad Bake report copied (%d faces)" % rep.get("faces", 0))
        return {'FINISHED'}
