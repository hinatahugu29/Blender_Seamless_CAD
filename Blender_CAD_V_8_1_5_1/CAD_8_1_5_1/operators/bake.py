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
        data = core.quad_topology(stack_ptr, props.quad_bake_tol,
                                  getattr(props, "quad_bake_uniform", True))
        if not data:
            self.report({'ERROR'}, "Quad Bake: kernel returned no topology")
            return {'CANCELLED'}
        mesh, rep = make_quad_bake_mesh(
            "SeamlessQuadBake", data,
            join_tris=props.quad_bake_join_tris,
            sharp_angle_deg=props.quad_bake_sharp_angle,
            join_shape_deg=props.quad_bake_join_shape,
            sharp_mode=props.quad_bake_sharp_mode)
        if mesh is None:
            self.report({'ERROR'}, "Quad Bake: no faces could be filled")
            return {'CANCELLED'}
        polys = mesh.polygons
        obj = bpy.data.objects.new("SeamlessQuadBake", mesh)
        parent_col = bpy.data.collections.get("Seamless_CAD")
        if parent_col is None:
            parent_col = bpy.data.collections.new("Seamless_CAD")
            context.scene.collection.children.link(parent_col)
        result_col = ensure_result_collection(parent_col)
        if result_col is None:
            self.report({'ERROR'}, "Failed to prepare Result collection")
            return {'CANCELLED'}
        result_col.objects.link(obj)
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        context.view_layer.objects.active = obj

        import json
        from .quad_bake import report_text
        mesh["quad_bake_report"] = json.dumps(rep)
        print(report_text(rep))
        msg = ("Quad Bake: %d faces (%d ruled, %d grid, %d n-gon, %d triangulated), %d polygons"
               % (rep["faces"], rep["ruled"], rep["coons"], rep["ngon"], rep["cdt"], len(polys)))
        if len(polys) > QUAD_BAKE_POLY_WARN:
            msg += " — %d polygons is heavy: raise Quad Tol or use the Low preset" % len(polys)
            self.report({'WARNING'}, msg)
        elif rep["failed"] or rep["edge_fail"]:
            msg += " — %d face(s) / %d edge(s) failed, see console" % (rep["failed"], rep["edge_fail"])
            self.report({'WARNING'}, msg)
        else:
            self.report({'INFO'}, msg)
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
