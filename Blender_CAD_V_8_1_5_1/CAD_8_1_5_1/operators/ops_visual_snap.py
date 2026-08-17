import bpy
import gpu
import blf
from gpu_extras.batch import batch_for_shader
from mathutils import Vector, Matrix
from bpy_extras import view3d_utils

from .. import core_bridge
from .. import utils

def draw_visual_snap_hud(self, context):
    try:
        if not hasattr(self, "_is_drawing") or not self._is_drawing:
            return
        font_id = 0
        blf.size(font_id, 16)
        blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
        
        state_str = "Selecting SOURCE" if self._state == 'PICK_SOURCE' else "Selecting TARGET"
        snap_str = "Face Center" if self._snap_mode == 'FACE' else "Edge Midpoint" if self._snap_mode == 'EDGE' else "Vertex"
        
        constraint_str = "None"
        if self._constraint_mode == 'AXIS':
            constraint_str = f"Axis Constraint: {','.join(self._constraint_axis)}"
        elif self._constraint_mode == 'PLANE':
            constraint_str = f"Plane Constraint: {','.join(self._constraint_axis)} Plane"
            
        x = 40
        y = 80
        
        lines = [
            "[Visual Snap Move Guide]",
            f"  Current State: {state_str}",
            f"  Snap Mode: {snap_str} (Default: 面 / Shift: 辺 / Ctrl: Vertex)",
            f"  Constraint: {constraint_str} (X/Y/Z for Axis / Shift+X/Y/Z for Plane)",
            "  [LMB] Confirm Position | [RMB/ESC] Cancel"
        ]
        
        for i, line in enumerate(reversed(lines)):
            blf.position(font_id, x, y + i * 22, 0)
            blf.draw(font_id, line)
    except Exception as e:
        print(f"Visual Snap HUD Draw Error: {e}")

def draw_callback(self, context):
    if not self._is_drawing:
        return
        
    # Draw logic here using self._preview_location, self._source_point, etc.
    # GPU drawing setup for points
    shader_points = gpu.shader.from_builtin('POINT_UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE') # ALWAYS DRAW ON TOP
    
    # 1. Draw snap points (Source and Target)
    points = []
    if self._source_point:
        points.append(self._source_point)
    if self._preview_location:
        points.append(self._preview_location)
        
    if points:
        batch = batch_for_shader(shader_points, 'POINTS', {"pos": points})
        shader_points.bind()
        
        size = 10.0
        if self._snap_mode == 'FACE':
            shader_points.uniform_float("color", (1.0, 0.5, 0.0, 1.0)) # Orange
            size = 10.0
        elif self._snap_mode == 'EDGE':
            shader_points.uniform_float("color", (1.0, 1.0, 0.0, 1.0)) # Yellow
            size = 14.0
        elif self._snap_mode == 'VERTEX':
            shader_points.uniform_float("color", (0.0, 1.0, 1.0, 1.0)) # Cyan
            size = 18.0
            
        try:
            shader_points.uniform_float("pointSize", size)
        except Exception:
            gpu.state.point_size_set(size)
            
        batch.draw(shader_points)
        
    gpu.state.depth_test_set('LESS_EQUAL')
        
    # 2. Draw constraint line
    if self._state == 'PICK_TARGET' and self._source_point and self._constraint_mode != 'NONE':
        shader_line = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
        axes_to_draw = []
        if self._constraint_mode == 'AXIS':
            axes_to_draw = list(self._constraint_axis)
        elif self._constraint_mode == 'PLANE':
            axes_to_draw = [a for a in ['X', 'Y', 'Z'] if a not in self._constraint_axis]
            
        gpu.state.line_width_set(2.0)
        
        for ax in axes_to_draw:
            color = (1.0, 0.2, 0.2, 0.6) if ax == 'X' else (0.2, 1.0, 0.2, 0.6) if ax == 'Y' else (0.2, 0.5, 1.0, 0.6)
            direction = Vector((1,0,0)) if ax == 'X' else Vector((0,1,0)) if ax == 'Y' else Vector((0,0,1))
            line_pts = [self._source_point - direction * 10000.0, self._source_point + direction * 10000.0]
            
            batch_line = batch_for_shader(shader_line, 'LINES', {"pos": line_pts})
            shader_line.bind()
            shader_line.uniform_float("color", color)
            try:
                shader_line.uniform_float("viewportSize", (context.area.width, context.area.height))
                shader_line.uniform_float("lineWidth", 2.0)
            except Exception:
                pass # Fail gracefully if API differs slightly
            batch_line.draw(shader_line)
            
    gpu.state.blend_set('NONE')
    gpu.state.depth_test_set('NONE')

class CAD_OT_visual_snap(bpy.types.Operator):
    """Shader-based Visual Snapping Tool for Object Transform"""
    bl_idname = "seamless.visual_snap"
    bl_label = "Visual Snap Move"
    bl_options = {'REGISTER', 'UNDO'}
    
    _handle = None
    _hud_handle = None
    _state = 'PICK_SOURCE' # 'PICK_SOURCE', 'PICK_TARGET'
    
    _source_obj = None
    _source_point = None
    _preview_location = None
    
    _snap_mode = 'FACE' # 'FACE', 'EDGE', 'VERTEX'
    _constraint_axis = set() # 'X', 'Y', 'Z'
    _constraint_mode = 'NONE' # 'NONE', 'AXIS', 'PLANE'
    
    _is_drawing = False

    @classmethod
    def poll(cls, context):
        return context.area.type == 'VIEW_3D' and context.mode == 'OBJECT'

    def invoke(self, context, event):
        self._state = 'PICK_SOURCE'
        self._source_obj = context.active_object if context.active_object and context.active_object.select_get() else None
        
        if not self._source_obj:
            self.report({'WARNING'}, "Please select an object to move.")
            return {'CANCELLED'}
            
        self._source_point = None
        self._preview_location = None
        
        self._snap_mode = 'FACE'
        self._constraint_axis = set()
        self._constraint_mode = 'NONE'
        
        self._is_drawing = True
        
        args = (self, context)
        self._handle = bpy.types.SpaceView3D.draw_handler_add(
            draw_callback, args, 'WINDOW', 'POST_VIEW'
        )
        self._hud_handle = bpy.types.SpaceView3D.draw_handler_add(
            draw_visual_snap_hud, (self, context), 'WINDOW', 'POST_PIXEL'
        )
        context.window_manager.modal_handler_add(self)
        
        self.report({'INFO'}, "Select SOURCE point (Face=Default, Shift=Edge, Ctrl=Vertex)")
        return {'RUNNING_MODAL'}

    def _get_face_center(self, stack_ptr, target_lid):
        from ..drawing import get_wireframe_engine
        wireframe = get_wireframe_engine()
        stack = wireframe.get_stack(stack_ptr)
        if stack._cache_fids is None or stack._cache_verts is None or len(stack._cache_fids) == 0 or len(stack._cache_verts) == 0:
            return None
        
        offset = 0
        verts = []
        for i, lid in enumerate(stack._cache_fids):
            count = stack._cache_counts[i]
            lid_str = str(lid).split("@")[0]
            target_lid_str = str(target_lid).split("@")[0]
            if lid_str == target_lid_str:
                start, end = offset, offset + count
                tris = stack._cache_tris[start : end]
                import numpy as np
                if isinstance(tris, np.ndarray): tris = tris.tolist()
                for idx in tris:
                    v = Vector((stack._cache_verts[idx*3], stack._cache_verts[idx*3+1], stack._cache_verts[idx*3+2]))
                    verts.append(v)
                break
            offset += count
            
        if not verts: return None
        center = Vector((0.0, 0.0, 0.0))
        for v in verts: center += v
        return center / len(verts)

    def _get_edge_midpoint(self, stack_ptr, target_lid):
        from ..drawing import get_wireframe_engine
        wireframe = get_wireframe_engine()
        stack = wireframe.get_stack(stack_ptr)
        if stack.lineages is None or stack.coords is None or len(stack.lineages) == 0 or len(stack.coords) == 0:
            return None
        
        for i, lid in enumerate(stack.lineages):
            lid_str = str(lid).split("@")[0]
            target_lid_str = str(target_lid).split("@")[0]
            if lid_str == target_lid_str:
                indices = stack.edge_indices[i]
                verts = []
                for pair in indices:
                    verts.append(Vector(stack.coords[pair[0]]))
                    verts.append(Vector(stack.coords[pair[1]]))
                if not verts: return None
                center = Vector((0.0, 0.0, 0.0))
                for v in verts: center += v
                return center / len(verts)
        return None

    def _get_nearest_vertex(self, stack_ptr, origin, direction, tolerance=0.1):
        from ..drawing import get_wireframe_engine
        from mathutils import geometry
        wireframe = get_wireframe_engine()
        stack = wireframe.get_stack(stack_ptr)
        if stack.coords is None or len(stack.coords) == 0:
            return None
            
        best_pt = None
        min_dist = float('inf')
        
        p1 = origin
        p2 = origin + direction * 1000.0
        
        for coord in stack.coords:
            v = Vector(coord)
            pt_on_line, _ = geometry.intersect_point_line(v, p1, p2)
            dist_to_ray = (v - pt_on_line).length
            
            if dist_to_ray < tolerance:
                dist_to_cam = (v - origin).length
                if dist_to_cam < min_dist:
                    min_dist = dist_to_cam
                    best_pt = v
                    
        return best_pt

    def get_snap_point(self, context, event):
        """Raycast using core_bridge to get snap point based on _snap_mode"""
        region = context.region
        rv3d = context.region_data
        coord = event.mouse_region_x, event.mouse_region_y
        
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        
        col = context.scene.active_cad_collection
        if not col or col.seamless_cad_stack_ptr == "0":
            return None
            
        stack_ptr = int(col.seamless_cad_stack_ptr)
        
        res = None
        if self._snap_mode == 'FACE':
            res = core_bridge.pick_face(stack_ptr, origin, direction, tolerance=0.1)
        elif self._snap_mode == 'EDGE':
            res = core_bridge.pick_edge(stack_ptr, origin, direction, tolerance=0.5)
        elif self._snap_mode == 'VERTEX':
            # VERTEXはC++側の全体ピックAPIが存在しないため、Python側でキャッシュVertexから最近接点を判定する
            pt = self._get_nearest_vertex(stack_ptr, origin, direction, tolerance=0.5)
            if pt: return pt
            
        if res and len(res) >= 4:
            target_lid = res[0]
            hit_pt = Vector((res[1], res[2], res[3]))
            
            # 幾何中心へのスナップ
            if self._snap_mode == 'FACE':
                center = self._get_face_center(stack_ptr, target_lid)
                if center: return center
            elif self._snap_mode == 'EDGE':
                mid = self._get_edge_midpoint(stack_ptr, target_lid)
                if mid: return mid
                
            return hit_pt
            
        return None

    def apply_constraint(self, raw_target):
        if not self._source_point or self._constraint_mode == 'NONE':
            return raw_target
            
        res = raw_target.copy()
        
        if self._constraint_mode == 'AXIS':
            # Lock to specific axis
            if 'X' in self._constraint_axis:
                res.y = self._source_point.y
                res.z = self._source_point.z
            elif 'Y' in self._constraint_axis:
                res.x = self._source_point.x
                res.z = self._source_point.z
            elif 'Z' in self._constraint_axis:
                res.x = self._source_point.x
                res.y = self._source_point.y
        elif self._constraint_mode == 'PLANE':
            # Lock to specific plane (Shift + Axis) -> Exclude that axis
            if 'X' in self._constraint_axis:
                res.x = self._source_point.x # YZ plane
            elif 'Y' in self._constraint_axis:
                res.y = self._source_point.y # XZ plane
            elif 'Z' in self._constraint_axis:
                res.z = self._source_point.z # XY plane
                
        return res

    def modal(self, context, event):
        context.area.tag_redraw()
        
        if utils.is_viewport_nav_event(event):
            return {'PASS_THROUGH'}
            
        # Modifiers
        prev_mode = self._snap_mode
        if event.ctrl:
            self._snap_mode = 'VERTEX'
        elif event.shift:
            self._snap_mode = 'EDGE'
        else:
            self._snap_mode = 'FACE'
            
        # Constraints
        if self._state == 'PICK_TARGET' and event.value == 'PRESS':
            axis = None
            if event.type == 'X': axis = 'X'
            elif event.type == 'Y': axis = 'Y'
            elif event.type == 'Z': axis = 'Z'
            
            if axis:
                if event.shift:
                    self._constraint_mode = 'PLANE'
                    self._constraint_axis = {axis}
                    self.report({'INFO'}, f"Constraint: {axis} Plane")
                else:
                    self._constraint_mode = 'AXIS'
                    self._constraint_axis = {axis}
                    self.report({'INFO'}, f"Constraint: {axis} Axis")

        # Raycast Update (Update if mouse moves OR if snap mode changes)
        if event.type == 'MOUSEMOVE' or self._snap_mode != prev_mode:
            pt = self.get_snap_point(context, event)
            if pt:
                if self._state == 'PICK_TARGET':
                    self._preview_location = self.apply_constraint(pt)
                else:
                    self._preview_location = pt
            else:
                self._preview_location = None

        # Click
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            if self._state == 'PICK_SOURCE':
                if self._preview_location:
                    self._source_point = self._preview_location.copy()
                    self._state = 'PICK_TARGET'
                    self._preview_location = None
                    self.report({'INFO'}, "Select TARGET point")
            elif self._state == 'PICK_TARGET':
                if self._preview_location:
                    # Move Object
                    diff = self._preview_location - self._source_point
                    from .. import utils
                    self._source_obj.location = utils.smart_round(self._source_obj.location + diff)
                    
                    # Ensure proxy updates
                    if hasattr(self._source_obj, 'seamless_props'):
                        # Optionally trigger core update here
                        pass
                        
                    self.report({'INFO'}, "Snap Applied!")
                    self.finish(context)
                    return {'FINISHED'}

        if event.type in {'RIGHTMOUSE', 'ESC'}:
            self.finish(context)
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}
        
    def finish(self, context):
        self._is_drawing = False
        if self._handle:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
            self._handle = None
        if self._hud_handle:
            bpy.types.SpaceView3D.draw_handler_remove(self._hud_handle, 'WINDOW')
            self._hud_handle = None
        context.area.tag_redraw()
