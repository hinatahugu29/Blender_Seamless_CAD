import bpy
import gpu
import blf
import math
import mathutils
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from ..core_bridge import update_cad_preview, get_core
from .. import utils

from . import sketch_globals
from .sketch_history import clear_sketch_temp_states, push_history, perform_undo
from .sketch_solver import solve_gcs_external, find_arc_by_line_id
from .sketch_finalize import is_point_in_polygon, finalize_sketch, calculate_circle_points, calculate_arc_points
from .states import STATE_CLASSES
from .sketch_draw import draw_sketch_3d, draw_sketch_2d







_in_solve = False


def _find_dimension_label_hit(mouse_x, mouse_y):
    """V8.1.5: 寸法駆動スケッチ - マウス座標が寸法ラベルのヒットボックス内かどうかを判定する。
    ヒットすればconstraint.idを返す(先に描画された=リストの先頭側を優先)。"""
    for cid, x0, y0, x1, y1 in sketch_globals._dimension_label_hitboxes:
        if x0 <= mouse_x <= x1 and y0 <= mouse_y <= y1:
            return cid
    return None









class SEAMLESS_OT_StartSketch(bpy.types.Operator):
    bl_idname = "seamless.start_sketch"
    bl_label = "Start 2D Sketch"
    bl_description = "Enter 2D sketch sandbox mode and start interactive drawing tool"
    
    def execute(self, context):
        props = utils.get_active_props(context)
        if not props:
            self.report({'WARNING'}, "Seamless CAD is not active.")
            return {'CANCELLED'}
            
        props.is_sketch_active = True
        props.sketch_points.clear()
        props.sketch_lines.clear()
        props.sketch_arcs.clear()
        props.sketch_circles.clear()
        props.sketch_constraints.clear()
        props.sketch_selected_point_id = -1
        props.sketch_selected_point_id_2 = -1
        props.sketch_selected_line_id = -1
        props.sketch_selected_line_id_2 = -1
        props.sketch_pen_mode = 'SELECT'
        
        # 描画ハンドラの登録
        # Handlers are now centrally managed by gpu_manager.py
        
        sketch_globals._history_stack = []
        sketch_globals._arc_points = []
        sketch_globals._circle_points = []
        sketch_globals._semicircle_points = []
        sketch_globals._rectangle_points = []
        sketch_globals._fully_constrained_pts = set()
        sketch_globals._fully_constrained_lines = set()
        sketch_globals._fully_constrained_circles = set()
        sketch_globals._fully_constrained_arcs = set()
        sketch_globals._inference_lines = []
        
        # 描画モーダルオペレータを自動で起動する
        bpy.ops.seamless.sketch_draw_tool('INVOKE_DEFAULT')
        
        self.report({'INFO'}, "Entered 2D Sketch Sandbox Mode. Use sidebar or viewport to draw.")
        context.area.tag_redraw()
        return {'FINISHED'}


def is_mouse_over_ui(context, event):
    mx = event.mouse_x
    my = event.mouse_y
    area = context.area
    if not area:
        return False
    for r in area.regions:
        if r.type in {'UI', 'TOOLS', 'HEADER'}:
            # パネルが折りたたまれている/非表示の場合は除外
            if r.type in {'UI', 'TOOLS'} and r.width < 10:
                continue
            if r.type == 'HEADER' and r.height < 10:
                continue
            
            if r.x <= mx <= r.x + r.width and r.y <= my <= r.y + r.height:
                return True
    return False

class SEAMLESS_OT_SketchDrawTool(bpy.types.Operator):
    bl_idname = "seamless.sketch_draw_tool"
    bl_label = "Sketch Draw Tool"
    bl_description = "Interactive drawing and editing modal tool for 2D Sketcher"
    
    _is_dragging = False
    _drag_point_id = None
    _last_redraw_mouse = None

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            cur_pos = (event.mouse_region_x, event.mouse_region_y)
            last_pos = self._last_redraw_mouse
            if last_pos is None or abs(cur_pos[0] - last_pos[0]) >= 2 or abs(cur_pos[1] - last_pos[1]) >= 2:
                context.area.tag_redraw()
                self._last_redraw_mouse = cur_pos
        else:
            context.area.tag_redraw()
        props = utils.get_active_props(context)
        if not props or not props.is_sketch_active:
            self.cleanup(props)
            return {'FINISHED'}

        if is_mouse_over_ui(context, event):
            return {'PASS_THROUGH'}

        if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and event.alt:
            if event.type == 'WHEELUPMOUSE':
                sketch_globals._grid_step = max(0.001, sketch_globals._grid_step / 2.0)
            else:
                sketch_globals._grid_step *= 2.0
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}
            
        # 視点操作は必ず Blender 本体へ。Alt+ホイールだけは上でグリッド刻みに
        # 使っているので、この判定より前に処理しておくこと。
        if utils.is_viewport_nav_event(event):
            return {'PASS_THROUGH'}

        mode = props.sketch_pen_mode
        StateClass = STATE_CLASSES.get(mode, STATE_CLASSES['SELECT'])
        active_state = StateClass(context, props, self)

        if event.type in {'MOUSEMOVE', 'LEFTMOUSE'}:
            coord = (event.mouse_region_x, event.mouse_region_y)
            region = context.region
            rv3d = context.region_data
            if region and rv3d:
                ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
                ray_direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
                
                mat = sketch_globals._reference_matrix if sketch_globals._reference_matrix else mathutils.Matrix.Identity(4)
                mat_inv = mat.inverted()
                
                local_origin = mat_inv @ ray_origin
                local_dir = (mat_inv.to_3x3() @ ray_direction).normalized()
                
                if abs(local_dir.z) > 1e-6:
                    t = -local_origin.z / local_dir.z
                    hit_pos = local_origin + local_dir * t
                    hit_pos.z = 0.0
                    
                    if event.shift and sketch_globals._axis_lock_start_co is not None:
                        delta = hit_pos - sketch_globals._axis_lock_start_co
                        if abs(delta.x) > abs(delta.y):
                            sketch_globals._axis_lock = 'X'
                            hit_pos.y = sketch_globals._axis_lock_start_co.y
                        else:
                            sketch_globals._axis_lock = 'Y'
                            hit_pos.x = sketch_globals._axis_lock_start_co.x
                    else:
                        sketch_globals._axis_lock = None
                        
                    hover_pid = props.sketch_hover_point_id
                    should_grid_snap = getattr(props, "sketch_grid_snap", False) and sketch_globals._axis_lock is None
                    
                    if should_grid_snap:
                        is_hovering_other = hover_pid != -1
                        if is_hovering_other and getattr(self, '_is_dragging', False):
                            if hover_pid == getattr(self, '_drag_point_id', None):
                                is_hovering_other = False
                                
                        if not is_hovering_other:
                            step = sketch_globals._grid_step
                            hit_pos.x = round(hit_pos.x / step) * step
                            hit_pos.y = round(hit_pos.y / step) * step
                        
                    sketch_globals._mouse_pos = hit_pos
                    
                    if event.type == 'MOUSEMOVE' and sketch_globals._is_box_selecting:
                        sketch_globals._box_select_end = (event.mouse_region_x, event.mouse_region_y)
                    
                    active_state.handle_mouse_move(event, hit_pos)

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            # V8.1.5: 寸法駆動スケッチ - SELECTモードでのみ寸法ラベルのクリックを
            # 優先的に処理する(描画中モードでのクリックはジオメトリ確定の意味を持つため
            # 対象外。ドラッグ中の点/線のヒットより先に判定すると誤操作になるので、
            # ホバー中の点が無い時だけ寸法ラベルとして扱う)。
            if mode == 'SELECT' and props.sketch_hover_point_id < 0:
                hit_cid = _find_dimension_label_hit(event.mouse_region_x, event.mouse_region_y)
                if hit_cid is not None:
                    bpy.ops.seamless.edit_dimension_value('INVOKE_DEFAULT', constraint_id=hit_cid)
                    return {'RUNNING_MODAL'}
            snap_pos = sketch_globals._mouse_pos.copy()
            if props.sketch_hover_point_id >= 0:
                for pt in props.sketch_points:
                    if pt.id == props.sketch_hover_point_id:
                        snap_pos = mathutils.Vector((pt.co[0], pt.co[1], 0.0))
                        break
            next_state = active_state.handle_left_click_press(event, snap_pos)
            if next_state:
                props.sketch_pen_mode = next_state
                
        elif event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            active_state.handle_left_click_release(event, sketch_globals._mouse_pos)
            
        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            if event.value == 'PRESS':
                next_state = active_state.handle_right_click(event)
                if next_state and next_state != 'CANCELLED':
                    props.sketch_pen_mode = next_state
            # 右クリックやESCのイベント（RELEASE等含む）を完全に消費し、
            # Blender標準のキャンセルやコンテキストメニュー等の挙動をOFF化する
            return {'RUNNING_MODAL'}
                
        # ユーザー要望: 確定・キャンセルはNパネルに限定するため、ショートカットキーでの終了をOFF化
        # elif event.type in {'RET', 'NUMPAD_ENTER', 'SPACE'} and event.value == 'PRESS':
        #     bpy.ops.seamless.sketch_action('INVOKE_DEFAULT', action='APPLY')
        #     return {'FINISHED'}
            
        elif event.type in {'DEL', 'X'} and event.value == 'PRESS':
            bpy.ops.seamless.sketch_action('INVOKE_DEFAULT', action='DELETE_SELECTED')

        # ローカル・アンドゥフック (Ctrl+Z)
        elif event.type == 'Z' and event.ctrl and event.value == 'PRESS':
            bpy.ops.seamless.sketch_action('INVOKE_DEFAULT', action='UNDO')
        elif event.type == 'C' and event.ctrl and event.value == 'PRESS':
            bpy.ops.seamless.sketch_action('INVOKE_DEFAULT', action='COPY_SELECTION')
        elif event.type == 'V' and event.ctrl and event.value == 'PRESS':
            bpy.ops.seamless.sketch_action('INVOKE_DEFAULT', action='PASTE_SELECTION')
        elif event.type == 'A' and event.ctrl and event.value == 'PRESS':
            bpy.ops.seamless.sketch_action('INVOKE_DEFAULT', action='SELECT_ALL')
        elif event.type == 'L' and event.value == 'PRESS' and props.sketch_pen_mode == 'SELECT':
            bpy.ops.seamless.sketch_action('INVOKE_DEFAULT', action='SELECT_CHAIN')

        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        props = utils.get_active_props(context)
        if not props or not props.is_sketch_active:
            self.report({'WARNING'}, "Sketch Mode is not active.")
            return {'CANCELLED'}
            
        props.sketch_is_drawing_line = False
        props.sketch_draw_start_pt_id = -1
        self._is_dragging = False
        self._drag_point_id = None
        sketch_globals._arc_points = []
        sketch_globals._circle_points = []
        sketch_globals._semicircle_points = []
        sketch_globals._rectangle_points = []
        
        context.window_manager.modal_handler_add(self)
        self.report({'INFO'}, f"Sketch Tool Active: {props.sketch_pen_mode} Mode. ESC/Right-Click to exit to Select Mode.")
        return {'RUNNING_MODAL'}
        
    def cleanup(self, props):
        if props:
            props.sketch_is_drawing_line = False
            props.sketch_draw_start_pt_id = -1
            props.sketch_hover_point_id = -1
            props.sketch_hover_line_id = -1
            props.sketch_selected_point_id = -1
            props.sketch_selected_point_id_2 = -1
            props.sketch_selected_line_id = -1
        sketch_globals._axis_lock = None
        sketch_globals._axis_lock_start_co = None
        sketch_globals._box_select_start = None
        sketch_globals._box_select_end = None
        sketch_globals._is_box_selecting = False
        sketch_globals._arc_points = []
        sketch_globals._circle_points = []
        sketch_globals._semicircle_points = []
        sketch_globals._rectangle_points = []
        sketch_globals._fully_constrained_pts = set()
        sketch_globals._fully_constrained_lines = set()
        sketch_globals._fully_constrained_circles = set()
        sketch_globals._fully_constrained_arcs = set()
        sketch_globals._inference_lines = []


