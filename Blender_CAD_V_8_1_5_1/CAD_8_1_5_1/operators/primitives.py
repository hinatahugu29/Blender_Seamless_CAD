# SPDX-License-Identifier: GPL-2.0-or-later
#
# Copyright (C) 2026 hinata_hugu
#
# This file is part of Seamless CAD.
#
# Seamless CAD is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation; either version 2 of the License, or (at your
# option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, see <https://www.gnu.org/licenses/>.

import bpy
import uuid
import math
import mathutils
from bpy_extras import view3d_utils
from ..core_bridge import get_core, update_cad_preview, update_cad_preview_high_quality, update_cad_preview_fast, is_core_busy, get_or_create_stack_ptr
from ..drawing import get_wireframe_engine
from .. import utils

RESULT_COLLECTION_NAME = "Result"

# ターゲットプリミティブに対する操作(ミラー面/配列方向/回転軸/複製元)であり、
# 3Dカーソル基準のインタラクティブ配置(サーフェススナップ)が意味を持たないタイプ。
# 常に3Dカーソル位置へ生成し、配置モーダルは起動しない。
PATTERN_TARGET_TYPES = {'MIRROR', 'ARRAY_LINEAR', 'ARRAY_CIRCULAR', 'REVOLVE', 'INSTANCE'}

def ensure_result_collection(parent_col):
    if not parent_col:
        return None
    result_col = bpy.data.collections.get(RESULT_COLLECTION_NAME)
    if result_col is None:
        result_col = bpy.data.collections.new(RESULT_COLLECTION_NAME)
    if result_col.name not in parent_col.children:
        parent_col.children.link(result_col)
    return result_col

class SEAMLESS_OT_AddPrimitive(bpy.types.Operator):
    bl_idname = "seamless.add_primitive"
    bl_label = "Add Primitive"
    bl_options = {'REGISTER', 'UNDO'}
    
    type: bpy.props.StringProperty(default='BOX')
    def execute(self, context):
        # 🌟 1. オブジェクトモード以外（編集モード等）の場合は、自動的かつ安全にオブジェクトモードへ移行し操作エラーを完全に防ぐ！
        if context.active_object and context.active_object.mode != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except Exception as e:
                utils.debug_print(f"DEBUG: Mode-set OBJECT error: {e}")

        props = utils.get_active_props(context)
        if not props:
            self.report({'ERROR'}, "No active Seamless collection found!")
            return {'CANCELLED'}
            
        # 🌟 2. 選択モーダルモードが動作中の場合は、自動的にクリーン終了させて競合や誤作動を完全に防ぐ！
        if props.is_selection_mode:
            props.is_selection_mode = False
            props.preselected_edge_id = ""
            props.preselected_face_id = ""
            utils.redraw_all_view3d(context)

        cursor_loc = tuple(context.scene.cursor.location[:3])
        item = props.primitives.add()
        item.uuid = str(uuid.uuid4())[:8]
        item.location = cursor_loc
        item.type = self.type
        item.name = f"{self.type.capitalize()}_{len(props.primitives)}"
        if len(props.primitives) == 1:
            item.operation = 'BASE'
        if self.type in {'CLEANUP', 'GROUP_START', 'GROUP_END'}:
            item.operation = 'ADD'
        if self.type in {'CURVE', 'POLYLINE'}:
            p1 = item.points.add(); p1.co = (0, 0, 0)
            p2 = item.points.add(); p2.co = (1, 1, 0)
            p3 = item.points.add(); p3.co = (2, 0, 0)
        if self.type == 'ARC':
            item.radius = 1.0
            item.angle_start = 0.0
            item.angle_end = 180.0
            item.use_pipe = True # 円弧は実体化して使うケースが多いためデフォルトON
        if self.type == 'HELIX':
            item.use_pipe = True # ヘリックスも実体化して使うケースが多いためデフォルトON
        if self.type == 'REVOLVE':
            item.distance = 360.0 # 初期値360度
        if self.type == 'ARRAY_CIRCULAR':
            item.count = 6
            item.distance = 360.0
        if self.type in {'FILLET', 'CHAMFER', 'FACE_OFFSET', 'FACE_INSET'}:
            item.radius = 0.0
        if self.type == 'SHELL':
            item.radius = 0.0  # 肉厚のデフォルト: 0.0m
        if self.type == 'DRAFT':
            item.radius = 5.0  # 勾配角のデフォルト: 5度
        if self.type == 'INSTANCE':
            item.operation = 'ADD'  # デフォルトは結合
        props.active_primitive_index = len(props.primitives) - 1
        
        # 1. まずプレビュー更新してプロキシオブジェクトを生成させる
        update_cad_preview(None, context)

        # update_cad_preview は modifier-interactive な高速モード中だと sync_proxies を
        # スキップすることがあり、新規プリミティブのプロキシがまだ存在しない場合がある。
        # set_active_primitive はプロキシが見つからないと黙って選択をあきらめるため、
        # ここで確実に同期してから選択させる。
        utils.sync_proxies(context, props=props)

        # 2. 生成されたプロキシを確実にアクティブにする
        bpy.ops.seamless.set_active_primitive(index=props.active_primitive_index)
        utils.redraw_all_view3d(context)
        
        # 3. モディファイア系の場合は選択モードを起動
        if self.type in {'DRAFT', 'SHELL', 'FILLET', 'CHAMFER', 'FACE_OFFSET', 'FACE_INSET', 'FACE_LOFT'}:
            if self.type == 'DRAFT':
                props.is_selecting_reference = True
            # モディファイア追加時は自動的に選択モードへ
            if self.type in {'DRAFT', 'SHELL', 'FACE_OFFSET', 'FACE_INSET', 'FACE_LOFT'}:
                props.selection_type = 'FACE'
            elif self.type in {'FILLET', 'CHAMFER'}:
                props.selection_type = 'EDGE'
            if self.type == 'DRAFT':
                utils.debug_print(
                    f"[DRAFT_UI] Enter selection modal: selection_type={props.selection_type} "
                    f"is_selecting_reference={props.is_selecting_reference}"
                )
            bpy.ops.seamless.selection_modal('INVOKE_DEFAULT')
            utils.redraw_all_view3d(context)
        elif self.type in {'CLEANUP', 'GROUP_START', 'GROUP_END'}:
            self.report({'INFO'}, f"{self.type.title().replace('_', ' ')} added")
            utils.redraw_all_view3d(context)
        elif self.type in PATTERN_TARGET_TYPES:
            # ミラー/配列/回転体/インスタンスはターゲット形状に対する操作であり、
            # 3Dカーソルへの配置がそのまま最終位置になるべきなので配置モーダルは起動しない
            self.report({'INFO'}, "Placed at Cursor")
            utils.redraw_all_view3d(context)
        else:
            # スナップがONな場合のみ、インタラクティブ配置モードを起動
            if props.use_snapping:
                bpy.ops.seamless.interactive_placement('INVOKE_DEFAULT')
            else:
                self.report({'INFO'}, "Placed at Cursor (Snapping is OFF)")
            utils.redraw_all_view3d(context)
            
        return {'FINISHED'}

class SEAMLESS_OT_AddDynamicLoftHole(bpy.types.Operator):
    bl_idname = "seamless.add_dynamic_loft_hole"
    bl_label = "Add Dynamic Loft Hole"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        # 🌟 オブジェクトモード以外の場合は自動的にオブジェクトモードへ移行
        if context.active_object and context.active_object.mode != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except Exception as e:
                utils.debug_print(f"DEBUG: Mode-set OBJECT error: {e}")

        props = utils.get_active_props(context)
        if not props:
            self.report({'ERROR'}, "No active Seamless collection found!")
            return {'CANCELLED'}

        # 🌟 選択モーダルが動作中の場合は強制終了
        if props.is_selection_mode:
            props.is_selection_mode = False
            props.preselected_edge_id = ""
            props.preselected_face_id = ""
            utils.redraw_all_view3d(context)

        cursor_loc = tuple(context.scene.cursor.location[:3])
        item = props.primitives.add()
        item.uuid = str(uuid.uuid4())[:8]
        item.location = cursor_loc
        item.type = 'VARIABLE_BOX'
        item.name = f"Loft_Hole_{len(props.primitives)}"
        
        # デフォルト値の設定
        item.operation = 'SUB'
        item.size = (1.0, 1.0, 0.0) # Top
        item.radius = 1.0           # Bot W
        item.radius2 = 1.0          # Bot H
        item.extrude_height = 2.0    # 貫通しやすくするためのデフォルト厚み
        
        item.top_shape = 'BOX'
        item.bot_shape = 'BOX'
        
        props.active_primitive_index = len(props.primitives) - 1
        update_cad_preview(None, context)
        bpy.ops.seamless.set_active_primitive(index=props.active_primitive_index)
        utils.redraw_all_view3d(context)
        return {'FINISHED'}

class SEAMLESS_OT_AddCurvePoint(bpy.types.Operator):
    bl_idname = "seamless.add_curve_point"
    bl_label = "Add Curve Point"
    def execute(self, context):
        props = utils.get_active_props(context)
        if not props or props.active_primitive_index < 0 or props.active_primitive_index >= len(props.primitives):
            return {'CANCELLED'}
        prim = props.primitives[props.active_primitive_index]
        if prim.type not in {'CURVE', 'POLYLINE'}: return {'CANCELLED'}
        last_pos = prim.points[-1].co if prim.points else (0,0,0)
        pt = prim.points.add()
        pt.co = (last_pos[0] + 1.0, last_pos[1], last_pos[2])
        update_cad_preview(None, context)
        return {'FINISHED'}

class SEAMLESS_OT_VariableBoxHole(bpy.types.Operator):
    bl_idname = "seamless.variable_box_hole"
    bl_label = "Variable Box Hole"
    bl_options = {'REGISTER', 'UNDO'}

    def modal(self, context, event):
        from .core_bridge import make_variable_box_mesh, update_cad_preview
        from ..drawing import get_wireframe_engine
        from bpy_extras import view3d_utils
        import mathutils
        
        context.area.tag_redraw()

        # レイキャストして現在のマウス位置（3D空間の床面 Z=0）を特定
        coord = event.mouse_region_x, event.mouse_region_y
        region = context.region
        rv3d = context.region_data
        vec = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        dist = -origin.z / vec.z if abs(vec.z) > 1e-6 else 0
        current_pos = origin + vec * dist

        if self.state == 'PLACING':
            # マウスに追従
            self.start_pos = current_pos
            if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
                self.state = 'SIZING'
                self.start_pos_2d = (event.mouse_region_x, event.mouse_region_y)
                return {'RUNNING_MODAL'}

        elif self.state == 'SIZING':
            # マウス位置の差分でサイズを決定（リージョン座標を使用）
            self.pos = (event.mouse_region_x, event.mouse_region_y)
            dx = abs(self.pos[0] - self.start_pos_2d[0]) * 0.05
            dy = abs(self.pos[1] - self.start_pos_2d[1]) * 0.05
            
            # Ctrlキーで下面(Radius2)を調整、それ以外は上面(Size)を調整
            if event.ctrl:
                self.bw, self.bh = dx, dy
            else:
                self.tw, self.th = dx, dy
                # 上面サイズに下面も追従させる（デフォルト挙動）
                if not event.shift:
                    self.bw, self.bh = dx, dy

            # マウスホイールで高さを調整
            if event.type == 'WHEELUP_MOUSE':
                self.h += 0.2
            elif event.type == 'WHEELDOWN_MOUSE':
                self.h = max(0.1, self.h - 0.2)

            if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
                # 確定処理
                props = utils.get_active_props(context)
                if not props:
                    return {'CANCELLED'}
                item = props.primitives.add()
                item.type = 'VARIABLE_BOX'
                item.operation = 'SUB'
                item.location = self.start_pos
                item.size = (self.tw, self.th, self.h)
                item.radius = self.bw
                item.radius2 = self.bh
                item.extrude_height = self.h
                item.name = "VarBox_Hole"
                
                get_wireframe_engine().update_transient_mesh([], [])
                update_cad_preview(None, context)
                return {'FINISHED'}

        # メッシュのプレビュー更新
        if event.type in {'MOUSEMOVE', 'WHEELUP_MOUSE', 'WHEELDOWN_MOUSE'}:
            v, t = make_variable_box_mesh(self.tw, self.th, self.bw, self.bh, self.h, 0.1)
            v_offset = []
            for i in range(0, len(v), 3):
                v_offset.extend([v[i] + self.start_pos.x, v[i+1] + self.start_pos.y, v[i+2] + self.start_pos.z])
            get_wireframe_engine().update_transient_mesh(v_offset, t)

        if event.type in {'RIGHTMOUSE', 'ESC'}:
            get_wireframe_engine().update_transient_mesh([], [])
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        import mathutils
        self.state = 'PLACING'
        self.start_pos = mathutils.Vector((0, 0, 0))
        self.start_pos_2d = (event.mouse_region_x, event.mouse_region_y)
        self.tw, self.th = 1.0, 1.0
        self.bw, self.bh = 1.0, 1.0
        self.h = 2.0
        self.taper_locked = False
        
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}


class SEAMLESS_OT_AddCurvePointAt(bpy.types.Operator):
    bl_idname = "seamless.add_curve_point_at"
    bl_label = "Add Curve Point At"
    
    prim_index: bpy.props.IntProperty(name="Primitive Index", default=0)
    point_index: bpy.props.IntProperty(name="Point Index", default=0)
    
    def execute(self, context):
        from ..core_bridge import update_cad_preview
        from .. import utils
        props = utils.get_active_props(context)
        if not props or self.prim_index < 0 or self.prim_index >= len(props.primitives):
            return {'CANCELLED'}
        prim = props.primitives[self.prim_index]
        if prim.type not in {'CURVE', 'SURFACE', 'POLYLINE'}: return {'CANCELLED'}
        
        if len(prim.points) == 0:
            new_co = (0,0,0)
        elif self.point_index == 0:
            new_co = prim.points[0].co
        elif self.point_index >= len(prim.points):
            last_co = prim.points[-1].co
            new_co = (last_co[0] + 1.0, last_co[1], last_co[2])
        else:
            prev_co = prim.points[self.point_index - 1].co
            next_co = prim.points[self.point_index].co
            new_co = ((prev_co[0] + next_co[0]) / 2.0, (prev_co[1] + next_co[1]) / 2.0, (prev_co[2] + next_co[2]) / 2.0)
            
        pt = prim.points.add()
        pt.co = new_co
        prim.points.move(len(prim.points)-1, self.point_index)
        
        update_cad_preview(None, context)
        return {'FINISHED'}

class SEAMLESS_OT_RemoveCurvePointAt(bpy.types.Operator):
    bl_idname = "seamless.remove_curve_point_at"
    bl_label = "Remove Curve Point"
    
    prim_index: bpy.props.IntProperty(name="Primitive Index", default=0)
    point_index: bpy.props.IntProperty(name="Point Index", default=0)
    
    def execute(self, context):
        from ..core_bridge import update_cad_preview
        from .. import utils
        props = utils.get_active_props(context)
        if not props or self.prim_index < 0 or self.prim_index >= len(props.primitives):
            return {'CANCELLED'}
        prim = props.primitives[self.prim_index]
        if prim.type not in {'CURVE', 'SURFACE', 'POLYLINE'}: return {'CANCELLED'}
        
        if 0 <= self.point_index < len(prim.points):
            prim.points.remove(self.point_index)
            update_cad_preview(None, context)
            
        return {'FINISHED'}
