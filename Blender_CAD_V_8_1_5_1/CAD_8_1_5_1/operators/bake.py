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

class SEAMLESS_OT_BakeMesh(bpy.types.Operator):
    bl_idname = "seamless.bake_mesh"
    bl_label = "Bake to Mesh"
    def execute(self, context):
        props = utils.get_active_props(context)
        if not props:
            self.report({'ERROR'}, "No active Seamless collection found!")
            return {'CANCELLED'}
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
        """Quad Bake P0: shared-edge topology from the kernel, filled in
        operators/quad_bake.py (n-gon planes, constrained triangulation)."""
        from .quad_bake import build_quad_mesh
        data = core.quad_topology(stack_ptr, props.quad_bake_tol)
        if not data:
            self.report({'ERROR'}, "Quad Bake: kernel returned no topology")
            return {'CANCELLED'}
        verts, polys, poly_face, rep = build_quad_mesh(data)
        if not polys:
            self.report({'ERROR'}, "Quad Bake: no faces could be filled")
            return {'CANCELLED'}

        mesh = bpy.data.meshes.new("SeamlessQuadBake")
        mesh.from_pydata(verts, [], polys)
        attr = mesh.attributes.new("cad_face", 'INT', 'FACE')
        attr.data.foreach_set("value", poly_face)
        mesh.validate(clean_customdata=False)
        mesh.update()
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

        for line in rep["errors"][:20]:
            print("[QuadBake]", line)
        msg = ("Quad Bake: %d faces (%d n-gon, %d triangulated), %d polygons"
               % (rep["faces"], rep["ngon"], rep["cdt"], len(polys)))
        if rep["failed"] or rep["edge_fail"]:
            msg += " — %d face(s) / %d edge(s) failed, see console" % (rep["failed"], rep["edge_fail"])
            self.report({'WARNING'}, msg)
        else:
            self.report({'INFO'}, msg)
        return {'FINISHED'}

