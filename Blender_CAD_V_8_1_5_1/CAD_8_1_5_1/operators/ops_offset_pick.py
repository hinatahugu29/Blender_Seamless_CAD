import bpy
import gpu
import blf
from gpu_extras.batch import batch_for_shader
from mathutils import Vector
from bpy_extras import view3d_utils

from .. import core_bridge
from .. import utils

def draw_offset_pick_hud(self, context):
    try:
        if not hasattr(self, "_is_drawing") or not self._is_drawing:
            return
        font_id = 0
        blf.size(font_id, 16)
        blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
        
        snap_str = "Face Center" if self._snap_mode == 'FACE' else "Edge Midpoint" if self._snap_mode == 'EDGE' else "Vertex"
        dist_str = f"{self._current_distance:.4f} m" if self._current_distance is not None else "Detecting..."
        
        x = 40
        y = 80
        
        lines = [
            "[Interactive Offset Distance Pick]",
            f"  Pick a snap point to set offset distance via normal projection",
            f"  Current Offset: {dist_str}",
            f"  Snap Mode: {snap_str} (Default: 面 / Shift: 辺 / Ctrl: Vertex)",
            "  [LMB] Confirm | [RMB/ESC] Cancel"
        ]
        
        for i, line in enumerate(reversed(lines)):
            blf.position(font_id, x, y + i * 22, 0)
            blf.draw(font_id, line)
    except Exception as e:
        print(f"Offset Pick HUD Draw Error: {e}")

def draw_callback(self, context):
    if not self._is_drawing:
        return
        
    shader_points = gpu.shader.from_builtin('POINT_UNIFORM_COLOR')
    shader_line = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')
    
    # 1. Draw points
    points = []
    colors = []
    
    # Reference point (Blue)
    if self._ref_point:
        points.append(self._ref_point)
        colors.append((0.2, 0.4, 1.0, 1.0))
        
    # Projected point (Green)
    if self._proj_point:
        points.append(self._proj_point)
        colors.append((0.2, 1.0, 0.2, 1.0))
        
    # Target snap point (Red/Orange/Yellow/Cyan depending on snap mode)
    if self._target_point:
        points.append(self._target_point)
        if self._snap_mode == 'FACE':
            colors.append((1.0, 0.5, 0.0, 1.0)) # Orange
        elif self._snap_mode == 'EDGE':
            colors.append((1.0, 1.0, 0.0, 1.0)) # Yellow
        else:
            colors.append((0.0, 1.0, 1.0, 1.0)) # Cyan

    if points:
        batch_pts = batch_for_shader(shader_points, 'POINTS', {"pos": points})
        shader_points.bind()
        for pt, col in zip(points, colors):
            shader_points.uniform_float("color", col)
            try:
                shader_points.uniform_float("pointSize", 10.0)
            except Exception:
                gpu.state.point_size_set(10.0)
            batch_pts.draw(shader_points)

    # 2. Draw lines
    # Normal direction projection line (dashed / solid green)
    if self._ref_point and self._proj_point:
        line_pts = [self._ref_point, self._proj_point]
        batch_line = batch_for_shader(shader_line, 'LINES', {"pos": line_pts})
        shader_line.bind()
        shader_line.uniform_float("color", (0.2, 1.0, 0.2, 0.8)) # Green
        gpu.state.line_width_set(2.0)
        batch_line.draw(shader_line)
        
    # Connection line from projection to target point (gray/yellow)
    if self._proj_point and self._target_point:
        line_pts = [self._proj_point, self._target_point]
        batch_line = batch_for_shader(shader_line, 'LINES', {"pos": line_pts})
        shader_line.bind()
        shader_line.uniform_float("color", (0.7, 0.7, 0.7, 0.5)) # Semi-transparent Gray
        gpu.state.line_width_set(1.5)
        batch_line.draw(shader_line)

    gpu.state.blend_set('NONE')
    gpu.state.depth_test_set('LESS_EQUAL')

def resolve_depth_attr(prim_type, requested):
    """スポイトが書き込むプロパティ名を、対象の型から決める。

    FACE_OFFSET が持つ深さは `radius` ただ1つ。パネルもそれしか描かない。
    なのに以前は、FACE_OFFSET のボタンだけ depth_attr を渡しておらず、
    StringProperty の既定値 "radius" に頼っていた。オペレータは
    bl_options に REGISTER/UNDO を持つので**前回値が残りうる**。
    FACE_INSET のスポイト(こちらは "extrude_height" を明示的に渡す)を
    先に使っていると、次に Offset のスポイトを使ったときに
    extrude_height へ書き込んでしまう。FACE_OFFSET のパネルは
    extrude_height を描かないので、**拾った数値がどこにも出ない。**

    呼び出し側の渡し忘れに依存しないよう、ここで型から決め直す。
    FACE_INSET だけは radius(インセット量)と extrude_height(押し引き)の
    2つを持つので、渡された値を尊重する。
    """
    if prim_type == 'FACE_OFFSET':
        return 'radius'
    return requested or 'radius'


class SEAMLESS_OT_InteractiveOffsetPick(bpy.types.Operator):
    bl_idname = "seamless.interactive_offset_pick"
    bl_label = "Interactive Offset Pick"
    bl_description = "Pick offset distance along normal using snapping"
    bl_options = {'REGISTER', 'UNDO'}

    index: bpy.props.IntProperty()
    # どのプロパティを高さとして駆動するか。FACE_OFFSET は "radius"、
    # FACE_INSET の押し引き高さは "extrude_height"。どちらも法線方向の
    # 符号付き距離を代入する点は共通(負=凹ませ/ツライチ)。
    depth_attr: bpy.props.StringProperty(default="radius")

    _handle = None
    _hud_handle = None
    _is_drawing = False
    
    _ref_point = None
    _ref_normal = None
    _target_point = None
    _proj_point = None
    
    _snap_mode = 'FACE'
    _current_distance = 0.0
    _initial_radius = 0.0

    @classmethod
    def poll(cls, context):
        return context.area.type == 'VIEW_3D'

    def _get_face_center_and_normal(self, stack_ptr, target_lid):
        from ..drawing import get_wireframe_engine
        wireframe = get_wireframe_engine()
        stack = wireframe.get_stack(stack_ptr)
        if (not hasattr(stack, "_cache_fids") or stack._cache_fids is None or 
            not hasattr(stack, "_cache_verts") or stack._cache_verts is None or 
            len(stack._cache_fids) == 0 or len(stack._cache_verts) == 0):
            return None, None
        
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
                if isinstance(tris, np.ndarray): 
                    tris = tris.tolist()
                for idx in tris:
                    v = Vector((stack._cache_verts[idx*3], stack._cache_verts[idx*3+1], stack._cache_verts[idx*3+2]))
                    verts.append(v)
                break
            offset += count
            
        if not verts: 
            return None, None
            
        # Center
        center = Vector((0.0, 0.0, 0.0))
        for v in verts: 
            center += v
        center /= len(verts)
        
        # Normal
        normal = Vector((0.0, 0.0, 1.0))
        if len(verts) >= 3:
            for idx in range(0, len(verts), 3):
                v0 = verts[idx]
                v1 = verts[idx+1]
                v2 = verts[idx+2]
                n = (v1 - v0).cross(v2 - v0)
                if n.length > 1e-5:
                    normal = n.normalized()
                    break
        return center, normal

    def _get_face_center(self, stack_ptr, target_lid):
        center, _ = self._get_face_center_and_normal(stack_ptr, target_lid)
        return center

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
            pt = self._get_nearest_vertex(stack_ptr, origin, direction, tolerance=0.5)
            if pt: return pt
            
        if res and len(res) >= 4:
            target_lid = res[0]
            hit_pt = Vector((res[1], res[2], res[3]))
            
            if self._snap_mode == 'FACE':
                center = self._get_face_center(stack_ptr, target_lid)
                if center: return center
            elif self._snap_mode == 'EDGE':
                mid = self._get_edge_midpoint(stack_ptr, target_lid)
                if mid: return mid
                
            return hit_pt
            
        return None

    def invoke(self, context, event):
        props = utils.get_active_props(context)
        if not props or self.index < 0 or self.index >= len(props.primitives):
            return {'CANCELLED'}
            
        prim = props.primitives[self.index]
        self.depth_attr = resolve_depth_attr(prim.type, self.depth_attr)
        self._initial_radius = getattr(prim, self.depth_attr, 0.0)

        col = context.scene.active_cad_collection
        if not col or col.seamless_cad_stack_ptr == "0":
            self.report({'WARNING'}, "No valid CAD part found.")
            return {'CANCELLED'}

        stack_ptr = int(col.seamless_cad_stack_ptr)

        # 基準面情報の取得
        if not prim.target_lineages:
            self.report({'WARNING'}, "No face selected for offset.")
            return {'CANCELLED'}
            
        target_lid = prim.target_lineages.split("|")[0]
        
        # キャッシュからFace Centerと法線を取得
        ref_pt, ref_norm = self._get_face_center_and_normal(stack_ptr, target_lid)
        
        # フォールバック処理: キャッシュにない場合は lineage 文字列から座標を復元
        if not ref_pt:
            if "@" in target_lid:
                try:
                    coords_str = target_lid.split("@")[1]
                    coords = [float(x) for x in coords_str.split(";")]
                    ref_pt = Vector(coords)
                except Exception:
                    pass
            if not ref_pt:
                ref_pt = Vector(prim.location) # 最終フォールバック
            ref_norm = Vector((0.0, 0.0, 1.0))
            
        # VERY IMPORTANT: Subtract the current depth to get the original un-offset
        # reference plane. ref_pt is currently displaced by the driven depth
        # (radius / extrude_height) along ref_norm, so subtract it back.
        self._ref_point = ref_pt - ref_norm * self._initial_radius
        self._ref_normal = ref_norm
        
        self._target_point = None
        self._proj_point = None
        self._snap_mode = 'FACE'
        self._current_distance = self._initial_radius
        
        self._is_drawing = True
        args = (self, context)
        self._handle = bpy.types.SpaceView3D.draw_handler_add(
            draw_callback, args, 'WINDOW', 'POST_VIEW'
        )
        self._hud_handle = bpy.types.SpaceView3D.draw_handler_add(
            draw_offset_pick_hud, args, 'WINDOW', 'POST_PIXEL'
        )

        # ドラッグ中だけGPU上のSDFプレビューに切り替え、離したら正式なB-repへ戻す
        context.scene.is_sdf_preview_mode = True
        context.scene.sdf_preview_box_size = tuple(prim.size)
        context.scene.sdf_preview_fillet_radius = self._initial_radius

        context.window_manager.modal_handler_add(self)
        self.report({'INFO'}, "Offset Picker Started: Hover over geometry to snap")
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        context.area.tag_redraw()
        
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            return {'PASS_THROUGH'}
            
        # Modifiers for snap mode
        prev_mode = self._snap_mode
        if event.ctrl:
            self._snap_mode = 'VERTEX'
        elif event.shift:
            self._snap_mode = 'EDGE'
        else:
            self._snap_mode = 'FACE'
            
        # Raycast Update
        if event.type == 'MOUSEMOVE' or self._snap_mode != prev_mode:
            pt = self.get_snap_point(context, event)
            if pt:
                self._target_point = pt.copy()
                
                # Project onto normal vector from ref_point
                to_target = self._target_point - self._ref_point
                d = to_target.dot(self._ref_normal)
                
                self._proj_point = self._ref_point + self._ref_normal * d
                # 符号を保持する。d<0(基準面の法線裏側にスナップ)＝凹ませ/相手面の
                # 高さにツライチで合わせる用途。abs で潰すと正方向にしか出せなかった。
                # radius プロパティは min=-100 で負値を許容済み。
                self._current_distance = d
                
                # Apply distance preview
                props = utils.get_active_props(context)
                if props and 0 <= self.index < len(props.primitives):
                    prim = props.primitives[self.index]
                    # depth_attr(radius / extrude_height)への代入自体が
                    # update_primitive_numeric_preview を経由して SDFプレビュー用の
                    # Scene値を更新するだけなので、ここで重い再計算を追加で呼ばないこと。
                    setattr(prim, self.depth_attr, utils.smart_round(d))
                    # モーダル先頭の context.area.tag_redraw() は「1イベント前の値」を
                    # 反映するため、動きを止めた最後の値がNパネルに乗り切らないことが
                    # ある。値適用の直後に全VIEW_3D(=Nパネル含む)を再描画し、UIの数値
                    # 反映を確実にする(context.area 限定だと対象パネルを取りこぼしうる)。
                    utils.redraw_all_view3d(context)
            else:
                self._target_point = None
                self._proj_point = None
                
        # Confirm
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            self.finish(context)
            # force=True で正式なOCCT B-repを一度だけ確定計算する
            core_bridge.update_cad_preview_forced(context)
            self.report({'INFO'}, f"Offset Distance Picked: {self._current_distance:.4f} m")
            return {'FINISHED'}

        # Cancel
        if event.type in {'RIGHTMOUSE', 'ESC'}:
            props = utils.get_active_props(context)
            if props and 0 <= self.index < len(props.primitives):
                prim = props.primitives[self.index]
                setattr(prim, self.depth_attr, self._initial_radius)
            self.finish(context)
            core_bridge.update_cad_preview_forced(context)
            self.report({'INFO'}, "Offset Pick Cancelled")
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def finish(self, context):
        # ドラッグ終了：SDFプレビューを終了し、正式なB-repジオメトリの表示に戻す
        context.scene.is_sdf_preview_mode = False
        self._is_drawing = False
        if self._handle:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
            self._handle = None
        if self._hud_handle:
            bpy.types.SpaceView3D.draw_handler_remove(self._hud_handle, 'WINDOW')
            self._hud_handle = None
        # 確定/キャンセル後の最終値をNパネルへ確実に反映(全VIEW_3D再描画)。
        utils.redraw_all_view3d(context)
        if getattr(context, "area", None):
            context.area.tag_redraw()
