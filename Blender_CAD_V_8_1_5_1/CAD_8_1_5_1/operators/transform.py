import bpy
import uuid
import math
import mathutils
import blf
from bpy_extras import view3d_utils
from ..core_bridge import get_core, update_cad_preview, update_cad_preview_high_quality, update_cad_preview_fast, update_cad_preview_fast_throttled, update_cad_preview_forced, is_core_busy, get_or_create_stack_ptr
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

def _placement_engage_bsp(context, prim):
    """配置/カスタム移動モーダル開始時に、対象プリミティブの純Rust BSP ライブCSG
    プレビューを起動する(best-effort)。起動できれば True。失敗時は静かに False を返し、
    従来の OCC 高速プレビュー(fallback)に委ねる。BSP作動中は core_bridge 側の
    ガードでドラッグ中OCC往復も抑止されるため、ブーリアン二重叩きが消える。"""
    try:
        col = utils.get_active_collection(context)
        if not col or not getattr(prim, "uuid", ""):
            return False
        obj = None
        for o in col.objects:
            if o.get("is_seamless_proxy") and o.get("primitive_uuid") == prim.uuid:
                obj = o
                break
        if obj is None:
            return False
        utils._proxy_initial_matrices[prim.uuid] = obj.matrix_world.copy()
        utils._csg_preview_state.pop(col.name, None)
        utils._csg_preview_try_begin(col)
        return bool(utils._csg_preview_state.get(col.name))
    except Exception:
        return False


def _placement_preview_tick(context):
    """ドラッグ中tick。BSPプレビュー作動中なら BSP を駆動して True を返す。
    未作動なら False を返し、呼び出し側が従来の throttled OCC(fallback)を実行する。"""
    try:
        col = utils.get_active_collection(context)
        if col and utils._csg_preview_state.get(col.name):
            utils._csg_preview_tick(col)
            return True
    except Exception:
        pass
    return False


def draw_hud_callback(self, context):
    try:
        if not hasattr(self, "is_snapping"):
            return
        font_id = 0
        blf.size(font_id, 16)
        
        # テキストカラー
        blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
        
        snap_str = "ON" if self.is_snapping else "OFF"
        normal_str = "ON" if self.align_to_normal else "OFF"
        axis_str = self.axis_constraint
        
        x = 40
        y = 80
        
        lines = [
            "[Operation Guide]",
            f"  [S] Snapping: {snap_str} (Default: OFF)",
            f"  [N] Align to Normal: {normal_str}",
            f"  [X/Y/Z] Axis Constraint: {axis_str}",
            "  [LMB] Confirm | [RMB/ESC] Cancel"
        ]
        
        for i, line in enumerate(reversed(lines)):
            blf.position(font_id, x, y + i * 22, 0)
            blf.draw(font_id, line)
    except Exception as e:
        print(f"Seamless CAD HUD Draw Error: {e}")

class SEAMLESS_OT_InteractivePlacement(bpy.types.Operator):
    bl_idname = "seamless.interactive_placement"
    bl_label = "Interactive Placement"
    bl_description = "Snap primitive to face and align with normal"

    _hud_handle = None

    def _arm_settle(self, context, delay=0.2):
        """手が止まったら結果を再描画するセトルタイマーを(再)セットする。
        最新トークンだけが発火し、モーダル終了後は無効化される。"""
        self._settle_token = getattr(self, "_settle_token", 0) + 1
        token = self._settle_token

        def settle_cb(tok=token):
            try:
                finished = getattr(self, "_finished", False)
            except ReferenceError:
                finished = True
                
            try:
                settle_token = getattr(self, "_settle_token", -1)
            except ReferenceError:
                settle_token = -1

            if finished or tok != settle_token:
                return None
            props = utils.get_active_props(bpy.context)
            if props:
                props.is_placing = False
                try:
                    update_cad_preview_forced(bpy.context)
                except Exception:
                    pass
                utils.redraw_all_view3d(bpy.context)
            return None

        bpy.app.timers.register(settle_cb, first_interval=max(0.05, float(delay)))

    def modal(self, context, event):
        # 領域外クリック判定
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            x, y = event.mouse_region_x, event.mouse_region_y
            if context.region and (x < 0 or x > context.region.width or y < 0 or y > context.region.height):
                self.finish(context)
                return {'PASS_THROUGH'}

        props = utils.get_active_props(context)
        if not props:
            self.finish(context)
            return {'FINISHED'}
        core = get_core()

        if props.active_primitive_index < 0 or props.active_primitive_index >= len(props.primitives):
            self.finish(context)
            return {'FINISHED'}
            
        prim = props.primitives[props.active_primitive_index]

        if not context.region or not context.region_data:
            self.finish(context)
            return {'PASS_THROUGH'}

        # 1. レイキャストの準備
        coord = (event.mouse_region_x, event.mouse_region_y)
        region = context.region
        rv3d = context.region_data
        ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        ray_direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)

        # 'S'キーでスナップのON/OFF切り替え
        if event.type == 'S' and event.value == 'PRESS':
            self.is_snapping = not self.is_snapping
            self.report({'INFO'}, f"Snapping: {'ON' if self.is_snapping else 'OFF'}")
            context.area.tag_redraw()

        # 'N'キーで法線整合のON/OFF切り替え
        if event.type == 'N' and event.value == 'PRESS':
            self.align_to_normal = not self.align_to_normal
            self.report({'INFO'}, f"Align to Normal: {'ON' if self.align_to_normal else 'OFF'}")
            context.area.tag_redraw()

        # 'X', 'Y', 'Z'キーで軸制限
        if event.value == 'PRESS' and event.type in {'X', 'Y', 'Z'}:
            if self.axis_constraint == event.type:
                self.axis_constraint = 'NONE'
            else:
                self.axis_constraint = event.type
            self.report({'INFO'}, f"Axis Constraint: {self.axis_constraint}")
            context.area.tag_redraw()

        if event.type == 'MOUSEMOVE':
            hit = False
            # スナップON時のみ面検出を試行
            if self.is_snapping and self.prim_index > 0:
                if core and not is_core_busy():
                    stack_ptr = get_or_create_stack_ptr(utils.get_active_collection(context))
                    res = None
                    if event.ctrl:
                        if hasattr(core, "pick_vertex_from_stack"):
                            res = core.pick_vertex_from_stack(stack_ptr, self.prim_index - 1, list(ray_origin), list(ray_direction), 0.6)
                            if res: self.report({'INFO'}, "Vertex Snap")
                    elif event.shift:
                        if hasattr(core, "pick_midpoint_from_stack"):
                            res = core.pick_midpoint_from_stack(stack_ptr, self.prim_index - 1, list(ray_origin), list(ray_direction), 0.6)
                            if res: self.report({'INFO'}, "Midpoint Snap")
                    
                    if not res:
                        if hasattr(core, "pick_face_from_stack"):
                            res = core.pick_face_from_stack(stack_ptr, self.prim_index - 1, list(ray_origin), list(ray_direction), 0.6)
                        elif hasattr(core, "pick_face"):
                            res = core.pick_face(stack_ptr, list(ray_origin), list(ray_direction), 0.6)
                    
                    if res:
                        lid, px, py, pz, nx, ny, nz = res
                        if prim.uuid and (prim.uuid in lid):
                            pass
                        else:
                            wf = get_wireframe_engine()
                            stype = "VERTEX" if event.ctrl else ("CENTER" if "FaceCenter" in lid else "MIDPOINT")
                            wf.set_snap_info((px, py, pz), stype)

                            # 軸制限を考慮して座標を決定
                            new_loc = [px, py, pz]
                            if self.axis_constraint == 'X':
                                new_loc[1] = self.initial_loc[1]
                                new_loc[2] = self.initial_loc[2]
                            elif self.axis_constraint == 'Y':
                                new_loc[0] = self.initial_loc[0]
                                new_loc[2] = self.initial_loc[2]
                            elif self.axis_constraint == 'Z':
                                new_loc[0] = self.initial_loc[0]
                                new_loc[1] = self.initial_loc[1]
                            
                            prim.location = tuple(new_loc)
                            
                            if self.align_to_normal:
                                normal = mathutils.Vector((nx, ny, nz))
                                up = mathutils.Vector((0, 0, 1))
                                if normal.length > 0.001:
                                    rot_quat = up.rotation_difference(normal)
                                    euler = rot_quat.to_euler()
                                    prim.rotation = (euler.x, euler.y, euler.z)
                            else:
                                prim.rotation = self.initial_rot

                            hit = True
            
            if not hit:
                # スナップしない、または見つからない場合はフォールバック移動（スナップON時のみ）
                get_wireframe_engine().set_snap_info(None, "")
                
                if self.is_snapping:
                    # 初期位置をベースにマウス移動による座標計算
                    z_level = self.initial_loc[2]
                    if abs(ray_direction.z) > 1e-6:
                        dist = (z_level - ray_origin.z) / ray_direction.z
                        pos = ray_origin + ray_direction * dist
                        
                        new_loc = [pos.x, pos.y, z_level]
                        # 軸制限の適用
                        if self.axis_constraint == 'X':
                            new_loc[1] = self.initial_loc[1]
                            new_loc[2] = self.initial_loc[2]
                        elif self.axis_constraint == 'Y':
                            new_loc[0] = self.initial_loc[0]
                            new_loc[2] = self.initial_loc[2]
                        elif self.axis_constraint == 'Z':
                            new_loc[0] = self.initial_loc[0]
                            new_loc[1] = self.initial_loc[1]
                            
                        prim.location = tuple(new_loc)
                    prim.rotation = self.initial_rot
                else:
                    # スナップがOFFな場合は一切オブジェクトを動かさない（開始時の位置を維持）
                    prim.location = self.initial_loc
                    prim.rotation = self.initial_rot

            # プロキシ同期
            old_drag = props.is_dragging
            props.is_dragging = False
            utils.sync_proxies(context, props=props)
            props.is_dragging = old_drag

            # A+セトル方式。live_boolean_preview=ON で BSP ライブプレビューが
            # 作動していればそのままライブ結果を見せる(重いが意図的)。既定(未作動)は
            # 結果ワイヤーを is_placing で隠して軽く動かし、手が止まったらセトルタイマーが
            # 正確な OCC 結果を1回だけ再計算して太線で描画する。
            if _placement_preview_tick(context):
                props.is_placing = False
            else:
                props.is_placing = True
                self._arm_settle(context)
            context.area.tag_redraw()

        elif event.type in {'LEFTMOUSE', 'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            utils._csg_preview_end_all()
            self.finish(context)
            if event.type == 'LEFTMOUSE':
                prim.location = utils.smart_round(prim.location)
                prim.rotation = utils.smart_round(prim.rotation)
                utils.sync_proxies(context, props=props)
                self.report({'INFO'}, "Placement Confirmed")
                return {'FINISHED'}
            else:
                # キャンセル時は初期状態に戻す
                prim.location = self.initial_loc
                prim.rotation = self.initial_rot
                utils.sync_proxies(context, props=props)
                update_cad_preview_forced(context)
                return {'CANCELLED'}

        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'WHEELINMOUSE', 'WHEELOUTMOUSE'}:
            return {'PASS_THROUGH'}

        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        if context.area.type == 'VIEW_3D':
            props = utils.get_active_props(context)
            if not props:
                return {'CANCELLED'}
            self.prim_index = props.active_primitive_index
            prim = props.primitives[self.prim_index]
            
            # 初期化
            self.is_snapping = False
            self.align_to_normal = True
            self.axis_constraint = 'NONE'
            self.initial_loc = prim.location.copy()
            self.initial_rot = prim.rotation.copy()
            self._settle_token = 0
            self._finished = False
            props.is_placing = False

            # 配置ドラッグを純Rust BSP ライブプレビューに載せる(best-effort)。
            # 対象外(BASE等)/起動失敗時は従来のOCC高速プレビューに自動フォールバック。
            _placement_engage_bsp(context, prim)

            # HUD登録
            self._hud_handle = bpy.types.SpaceView3D.draw_handler_add(
                draw_hud_callback, (self, context), 'WINDOW', 'POST_PIXEL'
            )

            context.window_manager.modal_handler_add(self)
            self.report({'INFO'}, "Placing: [S] Toggle Snap, [N] Align Normal, [X/Y/Z] Constrain Axis")
            return {'RUNNING_MODAL'}
        return {'CANCELLED'}

    def finish(self, context):
        self._finished = True
        props = utils.get_active_props(context)
        if props:
            props.is_placing = False
        get_wireframe_engine().set_snap_info(None, "")
        # 確定時は force=True。非force だと dispatch_sig 重複スキップ(core_bridge)で
        # 再計算が省かれ、Python側 stack.batch が再構築されず WGPU OFF で辺が消える。
        update_cad_preview_forced(context)
        if self._hud_handle:
            bpy.types.SpaceView3D.draw_handler_remove(self._hud_handle, 'WINDOW')
            self._hud_handle = None
        context.area.tag_redraw()

class SEAMLESS_OT_InteractiveTransform(bpy.types.Operator):
    bl_idname = "seamless.interactive_transform"
    bl_label = "Interactive Transform"
    bl_description = "Move existing object with snapping"

    _hud_handle = None

    def modal(self, context, event):
        # 領域外クリック判定
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            x, y = event.mouse_region_x, event.mouse_region_y
            if context.region and (x < 0 or x > context.region.width or y < 0 or y > context.region.height):
                self.finish(context)
                return {'PASS_THROUGH'}

        props = utils.get_active_props(context)
        if not props:
            self.finish(context)
            return {'FINISHED'}
        core = get_core()
        
        if self.prim_index < 0 or self.prim_index >= len(props.primitives):
            self.finish(context)
            return {'FINISHED'}
            
        prim = props.primitives[self.prim_index]

        if not context.region or not context.region_data:
            self.finish(context)
            return {'PASS_THROUGH'}

        coord = (event.mouse_region_x, event.mouse_region_y)
        region = context.region
        rv3d = context.region_data
        ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        ray_direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)

        # 'S'キーでスナップのON/OFF切り替え
        if event.type == 'S' and event.value == 'PRESS':
            self.is_snapping = not self.is_snapping
            self.report({'INFO'}, f"Snapping: {'ON' if self.is_snapping else 'OFF'}")
            context.area.tag_redraw()

        # 'N'キーで法線整合のON/OFF切り替え
        if event.type == 'N' and event.value == 'PRESS':
            self.align_to_normal = not self.align_to_normal
            self.report({'INFO'}, f"Align to Normal: {'ON' if self.align_to_normal else 'OFF'}")
            context.area.tag_redraw()

        # 'X', 'Y', 'Z'キーで軸制限
        if event.value == 'PRESS' and event.type in {'X', 'Y', 'Z'}:
            if self.axis_constraint == event.type:
                self.axis_constraint = 'NONE'
            else:
                self.axis_constraint = event.type
            self.report({'INFO'}, f"Axis Constraint: {self.axis_constraint}")
            context.area.tag_redraw()

        if event.type == 'MOUSEMOVE':
            hit = False
            if self.is_snapping and self.prim_index > 0:
                if core and not is_core_busy():
                    res = None
                    stack_ptr = get_or_create_stack_ptr(utils.get_active_collection(context))
                    if event.ctrl and hasattr(core, "pick_vertex_from_stack"):
                        res = core.pick_vertex_from_stack(stack_ptr, self.prim_index - 1, list(ray_origin), list(ray_direction), 0.6)
                    elif event.shift and hasattr(core, "pick_midpoint_from_stack"):
                        res = core.pick_midpoint_from_stack(stack_ptr, self.prim_index - 1, list(ray_origin), list(ray_direction), 0.6)
                    
                    if not res and hasattr(core, "pick_face_from_stack"):
                        res = core.pick_face_from_stack(stack_ptr, self.prim_index - 1, list(ray_origin), list(ray_direction), 0.6)
                    
                    if res:
                        lid, px, py, pz, nx, ny, nz = res
                        if prim.uuid and (prim.uuid in lid):
                            pass
                        else:
                            wf = get_wireframe_engine()
                            stype = "VERTEX" if event.ctrl else ("CENTER" if "FaceCenter" in lid else "MIDPOINT")
                            wf.set_snap_info((px, py, pz), stype)

                            # 軸制限の適用
                            new_loc = [px, py, pz]
                            if self.axis_constraint == 'X':
                                new_loc[1] = self.initial_loc[1]
                                new_loc[2] = self.initial_loc[2]
                            elif self.axis_constraint == 'Y':
                                new_loc[0] = self.initial_loc[0]
                                new_loc[2] = self.initial_loc[2]
                            elif self.axis_constraint == 'Z':
                                new_loc[0] = self.initial_loc[0]
                                new_loc[1] = self.initial_loc[1]
                            
                            prim.location = tuple(new_loc)
                            
                            if self.align_to_normal:
                                up = mathutils.Vector((0, 0, 1))
                                target_norm = mathutils.Vector((nx, ny, nz))
                                rot_quat = up.rotation_difference(target_norm)
                                prim.rotation = rot_quat.to_euler()
                            else:
                                prim.rotation = self.initial_rot
                            hit = True

            if not hit:
                # 平面フォールバック移動
                get_wireframe_engine().set_snap_info(None, "")
                
                if self.is_snapping:
                    z_plane = self.initial_loc[2]
                    if abs(ray_direction.z) > 1e-6:
                        t = (z_plane - ray_origin.z) / ray_direction.z
                        pos = ray_origin + ray_direction * t
                        
                        new_loc = [pos.x, pos.y, z_plane]
                        if self.axis_constraint == 'X':
                            new_loc[1] = self.initial_loc[1]
                            new_loc[2] = self.initial_loc[2]
                        elif self.axis_constraint == 'Y':
                            new_loc[0] = self.initial_loc[0]
                            new_loc[2] = self.initial_loc[2]
                        elif self.axis_constraint == 'Z':
                            new_loc[0] = self.initial_loc[0]
                            new_loc[1] = self.initial_loc[1]
                            
                        prim.location = tuple(new_loc)
                    prim.rotation = self.initial_rot
                else:
                    # スナップがOFFな場合は一切オブジェクトを動かさない（開始時の位置を維持）
                    prim.location = self.initial_loc
                    prim.rotation = self.initial_rot

            # プロキシ同期
            old_drag = props.is_dragging
            props.is_dragging = False
            utils.sync_proxies(context, props=props)
            props.is_dragging = old_drag

            # BSPプレビュー作動中はそれを駆動(OCC往復なし)。未作動なら従来のOCC高速プレビュー。
            if not _placement_preview_tick(context):
                update_cad_preview_fast_throttled(
                    context,
                    throttle_key=f"transform:{getattr(self, 'prim_index', -1)}",
                    min_interval=0.08,
                )
            context.area.tag_redraw()

        elif event.type in {'LEFTMOUSE', 'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            utils._csg_preview_end_all()
            self.finish(context)
            if event.type == 'LEFTMOUSE':
                prim.location = utils.smart_round(prim.location)
                prim.rotation = utils.smart_round(prim.rotation)
                utils.sync_proxies(context, props=props)
                self.report({'INFO'}, "Transform Confirmed")
                return {'FINISHED'}
            else:
                # キャンセル時は初期状態に復元
                prim.location = self.initial_loc
                prim.rotation = self.initial_rot
                utils.sync_proxies(context, props=props)
                update_cad_preview_forced(context)
                return {'CANCELLED'}

        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'WHEELINMOUSE', 'WHEELOUTMOUSE'}:
            return {'PASS_THROUGH'}

        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        props = utils.get_active_props(context)
        if not props or props.active_primitive_index < 0:
            self.report({'WARNING'}, "No primitive selected")
            return {'CANCELLED'}
            
        self.prim_index = props.active_primitive_index
        prim = props.primitives[self.prim_index]
        
        # 初期状態バックアップ
        self.is_snapping = False
        self.align_to_normal = True
        self.axis_constraint = 'NONE'
        self.initial_loc = prim.location.copy()
        self.initial_rot = prim.rotation.copy()

        # 移動ドラッグを純Rust BSP ライブプレビューに載せる(best-effort)。
        # 対象外/起動失敗時は従来のOCC高速プレビューに自動フォールバック。
        _placement_engage_bsp(context, prim)

        # HUD登録
        self._hud_handle = bpy.types.SpaceView3D.draw_handler_add(
            draw_hud_callback, (self, context), 'WINDOW', 'POST_PIXEL'
        )

        context.window_manager.modal_handler_add(self)
        self.report({'INFO'}, "Transform: [S] Toggle Snap, [N] Align Normal, [X/Y/Z] Constrain Axis")
        return {'RUNNING_MODAL'}

    def finish(self, context):
        get_wireframe_engine().set_snap_info(None, "")
        # 確定時は force=True。非force だと dispatch_sig 重複スキップ(core_bridge)で
        # 再計算が省かれ、Python側 stack.batch が再構築されず WGPU OFF で辺が消える。
        update_cad_preview_forced(context)
        if self._hud_handle:
            bpy.types.SpaceView3D.draw_handler_remove(self._hud_handle, 'WINDOW')
            self._hud_handle = None
        context.area.tag_redraw()


