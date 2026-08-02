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
import mathutils
import json
from bpy_extras import view3d_utils
from .drawing import get_wireframe_engine, get_gizmo_engine
from .core_bridge import get_core, update_cad_preview, is_core_busy, get_or_create_stack_ptr, pick_vertex_from_stack, pick_midpoint_from_stack, pick_face_from_stack
from .core.semantic_targets import get_display_edge_targets, make_semantic_edgeset_loop_token, make_semantic_opening_loop_token, parse_target_coord
from . import utils
from .properties import INTERACTIVE_MODIFIER_TYPES

def _update_target_ref_snapshot(active_prim, current_ids_list, picked_point, props, snapshot_attr='edge_ref_snapshot'):
    """V8.0.1: FILLET/CHAMFER辺の参照プリミティブ相対座標を記録する。
    
    辺を選択した時点で、最も近いプリミティブを「参照」として特定し、
    辺の座標をそのプリミティブのローカル空間に変換して記録する。
    プリミティブが移動しても、ローカル座標から現在位置を再計算できる。
    """
    try:
        # 現在のスナップショットを取得
        snapshot = {}
        snapshot_json = getattr(active_prim, snapshot_attr, '')
        if snapshot_json:
            try:
                snapshot = json.loads(snapshot_json)
            except:
                snapshot = {}
        
        # FILLET/CHAMFERプリミティブのインデックスを取得
        active_idx = -1
        for i, p in enumerate(props.primitives):
            if p == active_prim:
                active_idx = i
                break
        if active_idx < 0:
            return
        
        # 現在のIDリストにないスナップショットを削除（辺削除に対応）
        current_bases = set()
        for lid in current_ids_list:
            current_bases.add(lid.split("@")[0] if "@" in lid else lid)
        
        keys_to_remove = []
        for k in snapshot:
            k_base = k.split("@")[0] if "@" in k else k
            if k_base not in current_bases:
                keys_to_remove.append(k)
        for k in keys_to_remove:
            del snapshot[k]
        
        # 各辺IDに対してスナップショットを更新
        picked_vec = mathutils.Vector(picked_point)
        
        for lid in current_ids_list:
            if lid in snapshot:
                continue  # 既にスナップショットがある辺はスキップ
            
            # 辺IDから座標を抽出
            edge_coord = parse_target_coord(lid)
            if edge_coord is None:
                continue
            
            # FILLETより前の全ての有効なプリミティブに対する相対座標を記録
            refs = {}
            for i in range(active_idx):
                p = props.primitives[i]
                if p.type in INTERACTIVE_MODIFIER_TYPES:
                    continue  # モディファイアは参照対象外
                
                ref_loc = mathutils.Vector(p.location)
                ref_rot = mathutils.Euler(p.rotation, 'XYZ')
                inv_rot = ref_rot.to_matrix().inverted()
                rloc = inv_rot @ (edge_coord - ref_loc)
                
                refs[p.uuid] = {
                    "rloc": [round(rloc.x, 6), round(rloc.y, 6), round(rloc.z, 6)],
                    "ref_loc": [round(ref_loc.x, 6), round(ref_loc.y, 6), round(ref_loc.z, 6)],
                    "ref_rot": [round(p.rotation[0], 6), round(p.rotation[1], 6), round(p.rotation[2], 6)]
                }
            
            if refs:
                # 互換性のため一番近いものもrefとして残しつつ、refsに全データを格納
                best_uuid = min(refs.keys(), key=lambda k: (edge_coord - mathutils.Vector(refs[k]['ref_loc'])).length)
                snapshot[lid] = {
                    "ref": best_uuid,
                    "rloc": refs[best_uuid]["rloc"],
                    "ref_loc": refs[best_uuid]["ref_loc"],
                    "ref_rot": refs[best_uuid]["ref_rot"],
                    "refs": refs
                }
        
        setattr(active_prim, snapshot_attr, json.dumps(snapshot))
    except Exception as e:
        utils.debug_print(f"[V8.1.3.3] _update_target_ref_snapshot({snapshot_attr}) error: {e}")


def _sync_edge_radii(active_prim, current_ids_list):
    """V8.1.5: 可変フィレット - target_lineages の raw エッジトークン集合と
    active_prim.edge_radii (トークン毎の個別半径) を同期する。

    現在選択されていないエッジのエントリを除去し、新規に選択されたエッジには
    radius=-1(未指定＝親プリミティブの radius をフォールバックとして使う)で追加する。
    キーは _update_target_ref_snapshot と同じく座標込みの完全トークン、
    存在チェックはベース部分(Edge:N など)で行う。
    """
    if not active_prim or active_prim.type != 'FILLET':
        return
    try:
        current_bases = set()
        for lid in current_ids_list:
            current_bases.add(lid.split("@")[0] if "@" in lid else lid)

        remove_indices = []
        existing_bases = set()
        for i, er in enumerate(active_prim.edge_radii):
            base = er.token.split("@")[0] if "@" in er.token else er.token
            if base not in current_bases:
                remove_indices.append(i)
            else:
                existing_bases.add(base)
        for i in reversed(remove_indices):
            active_prim.edge_radii.remove(i)
        if active_prim.edge_radii_active_index >= len(active_prim.edge_radii):
            active_prim.edge_radii_active_index = len(active_prim.edge_radii) - 1

        for lid in current_ids_list:
            base = lid.split("@")[0] if "@" in lid else lid
            if base in existing_bases:
                continue
            new_er = active_prim.edge_radii.add()
            new_er.token = lid
            new_er.radius = -1.0
            existing_bases.add(base)
    except Exception as e:
        utils.debug_print(f"[V8.1.5] _sync_edge_radii error: {e}")


def _to_modifier_target_tokens(active_prim, current_ids_list, props=None):
    if not active_prim or active_prim.type not in {'FILLET', 'CHAMFER'}:
        return list(current_ids_list)

    semantic_targets = []
    raw_edge_targets = [lid for lid in current_ids_list if isinstance(lid, str) and lid.startswith("Edge:")]
    edgeset_semantic = ""
    if len(raw_edge_targets) >= 2:
        edgeset_semantic = make_semantic_edgeset_loop_token(raw_edge_targets)
        if edgeset_semantic:
            semantic_targets.append(edgeset_semantic)
    for lid in current_ids_list:
        semantic_targets.append(lid)
        has_loop_payload = isinstance(lid, str) and "@Loop:" in lid
        if not has_loop_payload:
            continue
        semantic = make_semantic_opening_loop_token(lid)
        if semantic and semantic != lid:
            semantic_targets.append(semantic)
    return semantic_targets


def build_edge_graph_from_stack(stack):
    """
    StackRenderData からエッジの接続グラフを構築します。
    """
    if not hasattr(stack, "coords") or not hasattr(stack, "edge_indices") or not hasattr(stack, "lineages"):
        return {}
        
    graph = {}
    vertex_to_edges = {}
    
    # 座標の浮動小数点誤差を丸める関数
    def get_vertex_key(coord):
        return (round(coord[0], 5), round(coord[1], 5), round(coord[2], 5))
        
    # 各エッジ（lineage）ごとに始点と終点の座標を抽出し、Vertexごとにエッジをマップする
    for i, lineage in enumerate(stack.lineages):
        if i >= len(stack.edge_indices):
            break
        indices = stack.edge_indices[i]
        if not indices:
            continue
            
        # 始点のインデックスは最初のペアの最初の要素
        start_idx = indices[0][0]
        # 終点のインデックスは最後のペアの最後の要素
        end_idx = indices[-1][1]
        
        if start_idx < len(stack.coords) and end_idx < len(stack.coords):
            p_start = stack.coords[start_idx]
            p_end = stack.coords[end_idx]
            
            k_start = get_vertex_key(p_start)
            k_end = get_vertex_key(p_end)
            
            vertex_to_edges.setdefault(k_start, []).append(lineage)
            vertex_to_edges.setdefault(k_end, []).append(lineage)
            
    # 隣接リストの初期化
    for lineage in stack.lineages:
        graph[lineage] = set()
        
    # Vertexを共有するエッジ同士を隣接グラフに登録
    for edge_list in vertex_to_edges.values():
        for e1 in edge_list:
            for e2 in edge_list:
                if e1 != e2:
                    graph[e1].add(e2)
                    graph[e2].add(e1)
                    
    return graph

def find_shortest_edge_path(graph, start_lid, end_lid):
    """
    グラフ上で start_lid から end_lid への最短経路（エッジIDリスト）を探索します（BFSを使用）。
    """
    if start_lid == end_lid:
        return [start_lid]
        
    from collections import deque
    queue = deque([[start_lid]])
    visited = {start_lid}
    
    while queue:
        path = queue.popleft()
        node = path[-1]
        
        if node == end_lid:
            return path
            
        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(path + [neighbor])
                
    return []

class SEAMLESS_OT_SelectionModal(bpy.types.Operator):
    bl_idname = "seamless.selection_modal"
    bl_label = "Seamless Selection Mode"
    
    _drag_axis = ""
    _prim_start_pos = (0,0,0)
    _mouse_start_x = 0
    _drag_plane_normal = (0,0,1)

    def get_ray_axis_dist(self, context, ray_origin, ray_direction, axis):
        props = utils.get_active_props(context)
        if not props or props.active_primitive_index < 0 or props.active_primitive_index >= len(props.primitives):
            return 1e10
        prim = props.primitives[props.active_primitive_index]
        pos = mathutils.Vector(prim.location)
        rv3d = context.region_data
        view_matrix = rv3d.view_matrix
        dist_cam = (view_matrix @ pos).z
        scale = abs(dist_cam) * 0.15
        axis_vec = mathutils.Vector((1,0,0)) if axis=="X" else mathutils.Vector((0,1,0)) if axis=="Y" else mathutils.Vector((0,0,1))
        p1, p2 = pos, pos + axis_vec * scale
        p_on_ray = mathutils.geometry.intersect_point_line(p1, ray_origin, ray_origin + ray_direction)[0]
        dist_p1 = (p1 - p_on_ray).length
        res = mathutils.geometry.intersect_line_line(ray_origin, ray_origin + ray_direction, p1, p2)
        if res:
            p_ray, p_axis = res
            return (p_ray - p_axis).length
        return dist_p1

    def modal(self, context, event):
        if not hasattr(self, "_drag_axis"): 
            self._drag_axis = ""
            self._drag_point_idx = -1
        # 🌟 領域外クリック判定：もしクリックイベントであり、マウスが3Dビューポート外（Nパネルなど）にあれば、
        # 選択モードをOFFにしてPASS_THROUGHでモーダルを終了してUIクリックを通す！
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS' and not self._drag_axis:
            x, y = event.mouse_region_x, event.mouse_region_y
            if context.region and (x < 0 or x > context.region.width or y < 0 or y > context.region.height):
                props = utils.get_active_props(context)
                if props:
                    props.is_selection_mode = False
                    props.preselected_edge_id = ""
                    props.preselected_face_id = ""
                context.area.tag_redraw()
                return {'PASS_THROUGH'}

        props = utils.get_active_props(context)
        if not props:
            return {'FINISHED'}
        if not props.is_selection_mode:
            context.area.tag_redraw()
            return {'FINISHED'}

        coord = (event.mouse_region_x, event.mouse_region_y)
        region = context.region
        rv3d = context.region_data
        ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        ray_direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        
        # Allow viewport navigation
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'WHEELINMOUSE', 'WHEELOUTMOUSE'}:
            return {'PASS_THROUGH'}

        # Dragging logic
        if getattr(self, "_drag_point_idx", -1) != -1:
            if event.value == 'PRESS':
                # SキーでスナップON/OFFトグル
                if event.type == 'S':
                    self._snap_enabled = not getattr(self, "_snap_enabled", True)
                    if self._snap_enabled and self._snap_mode == 'NONE':
                        self._snap_mode = 'VERTEX'
                    gizmo = get_gizmo_engine()
                    gizmo.snap_enabled = self._snap_enabled
                    gizmo.snap_mode = self._snap_mode
                    context.area.tag_redraw()
                    return {'RUNNING_MODAL'}
                # V/M/F/Cキーでスナップモードトグル
                elif event.type in {'V', 'M', 'F', 'C'}:
                    if event.type == 'V':
                        self._snap_mode = 'VERTEX'
                        self._snap_enabled = True
                    elif event.type == 'M':
                        self._snap_mode = 'MIDPOINT'
                        self._snap_enabled = True
                    elif event.type == 'F':
                        self._snap_mode = 'FACE'
                        self._snap_enabled = True
                    elif event.type == 'C':
                        self._snap_mode = 'NONE'
                        self._snap_enabled = False
                    
                    gizmo = get_gizmo_engine()
                    gizmo.snap_enabled = self._snap_enabled
                    gizmo.snap_mode = self._snap_mode
                    context.area.tag_redraw()
                    return {'RUNNING_MODAL'}
                    
                key_axis = ""
                if event.type == 'X': key_axis = "X"
                elif event.type == 'Y': key_axis = "Y"
                elif event.type == 'Z': key_axis = "Z"
                
                if key_axis:
                    mode = ("PLANE_" if event.shift else "AXIS_") + key_axis
                    if getattr(self, "_constraint_mode", "") == mode:
                        self._constraint_mode = ""
                    else:
                        self._constraint_mode = mode
                    
                    gizmo = get_gizmo_engine()
                    gizmo.drag_constraint_mode = self._constraint_mode
                    context.area.tag_redraw()
                    return {'RUNNING_MODAL'}
            
            if event.type == 'MOUSEMOVE':
                if 0 <= props.active_primitive_index < len(props.primitives):
                    prim = props.primitives[props.active_primitive_index]
                    if self._drag_point_idx < len(prim.points):
                        start_co = mathutils.Vector(self._prim_start_world_pos)
                        
                        # --- スナッピング判定 ---
                        snap_pos = None
                        snap_type = ""
                        
                        if getattr(self, "_snap_enabled", True) and getattr(self, "_snap_mode", "VERTEX") != "NONE":
                            active_col = utils.get_active_collection(context)
                            stack_ptr = getattr(active_col, "seamless_cad_stack_ptr", "0") if active_col else "0"
                            try:
                                stack_ptr_int = int(stack_ptr)
                            except (ValueError, TypeError):
                                stack_ptr_int = 0
                                
                            if stack_ptr_int != 0:
                                mode = getattr(self, "_snap_mode", "VERTEX")
                                res = None
                                stack_idx = props.active_primitive_index
                                r_orig = list(ray_origin)
                                r_dir = list(ray_direction)
                                
                                if mode == "VERTEX":
                                    res = pick_vertex_from_stack(stack_ptr, stack_idx, r_orig, r_dir, 0.4)
                                    snap_type = "VERTEX"
                                elif mode == "MIDPOINT":
                                    res = pick_midpoint_from_stack(stack_ptr, stack_idx, r_orig, r_dir, 0.4)
                                    snap_type = "MIDPOINT"
                                elif mode == "FACE":
                                    res = pick_face_from_stack(stack_ptr, stack_idx, r_orig, r_dir, 0.4)
                                    snap_type = "FACE"
                                
                                if res:
                                    snap_pos = mathutils.Vector((res[1], res[2], res[3]))
                        
                        # --- 座標の決定 ---
                        gizmo = get_gizmo_engine()
                        if snap_pos:
                            new_world_co = snap_pos
                            gizmo.snap_pos = tuple(snap_pos)
                            gizmo.snap_type = snap_type
                        else:
                            gizmo.snap_pos = None
                            gizmo.snap_type = ""
                            
                            if getattr(self, "_constraint_mode", "").startswith("AXIS_"):
                                axis = self._constraint_mode.split("_")[1]
                                axis_vec = mathutils.Vector((1,0,0)) if axis=="X" else mathutils.Vector((0,1,0)) if axis=="Y" else mathutils.Vector((0,0,1))
                                p1, p2 = ray_origin, ray_origin + ray_direction
                                p3, p4 = start_co, start_co + axis_vec
                                res_l = mathutils.geometry.intersect_line_line(p1, p2, p3, p4)
                                new_world_co = res_l[1] if res_l else start_co
                            elif getattr(self, "_constraint_mode", "").startswith("PLANE_"):
                                axis = self._constraint_mode.split("_")[1]
                                plane_normal = mathutils.Vector((1,0,0)) if axis=="X" else mathutils.Vector((0,1,0)) if axis=="Y" else mathutils.Vector((0,0,1))
                                p_intersect = mathutils.geometry.intersect_line_plane(ray_origin, ray_origin + ray_direction, start_co, plane_normal)
                                new_world_co = p_intersect if p_intersect else start_co
                            else:
                                p_intersect = mathutils.geometry.intersect_line_plane(ray_origin, ray_origin + ray_direction, start_co, self._drag_plane_normal)
                                new_world_co = p_intersect if p_intersect else start_co
                                
                        # 軸/平面拘束とスナップの同時適用
                        if snap_pos and getattr(self, "_constraint_mode", "").startswith("AXIS_"):
                            axis = self._constraint_mode.split("_")[1]
                            axis_vec = mathutils.Vector((1,0,0)) if axis=="X" else mathutils.Vector((0,1,0)) if axis=="Y" else mathutils.Vector((0,0,1))
                            to_snap = snap_pos - start_co
                            proj_dist = to_snap.dot(axis_vec)
                            new_world_co = start_co + axis_vec * proj_dist
                            gizmo.snap_pos = tuple(new_world_co)
                        elif snap_pos and getattr(self, "_constraint_mode", "").startswith("PLANE_"):
                            axis = self._constraint_mode.split("_")[1]
                            plane_normal = mathutils.Vector((1,0,0)) if axis=="X" else mathutils.Vector((0,1,0)) if axis=="Y" else mathutils.Vector((0,0,1))
                            to_snap = snap_pos - start_co
                            proj_dist = to_snap.dot(plane_normal)
                            new_world_co = snap_pos - plane_normal * proj_dist
                            gizmo.snap_pos = tuple(new_world_co)
                            
                        local_co = self._drag_parent_matrix.inverted_safe() @ new_world_co
                        
                        # --- 自動軸アライメントスナップ (X/Y/Z軸揃え) ---
                        gizmo.alignment_guides = []
                        # 揃える対象候補となる他マーカーの座標を収集（アクティブなプリミティブ内の他Vertex）
                        ref_points = []
                        for idx_pt, pt in enumerate(prim.points):
                            if idx_pt != self._drag_point_idx:
                                w_co = self._drag_parent_matrix @ mathutils.Vector(pt.co)
                                ref_points.append(w_co)
                        
                        # 3Dビューポートでのスクリーン投影でスナップ閾値を判定するためのヘルパー
                        from bpy_extras.view3d_utils import location_3d_to_region_2d
                        region = context.region
                        rv3d = context.region_data
                        
                        snap_dist_px = 15.0 # スクリーン上のピクセル距離閾値
                        
                        curr_co_screen = location_3d_to_region_2d(region, rv3d, new_world_co)
                        if curr_co_screen is not None:
                            best_snap_co = mathutils.Vector(new_world_co)
                            snap_x, snap_y, snap_z = False, False, False
                            
                            for ref_w in ref_points:
                                # X軸揃え
                                test_co_x = mathutils.Vector((ref_w.x, new_world_co.y, new_world_co.z))
                                scr_x = location_3d_to_region_2d(region, rv3d, test_co_x)
                                if scr_x is not None:
                                    dist_x = (scr_x - curr_co_screen).length
                                    if dist_x < snap_dist_px:
                                        best_snap_co.x = ref_w.x
                                        snap_x = True
                                        gizmo.alignment_guides.append((tuple(ref_w), tuple(best_snap_co), (1.0, 0.2, 0.2, 0.8))) # 赤線
                                
                                # Y軸揃え
                                test_co_y = mathutils.Vector((new_world_co.x, ref_w.y, new_world_co.z))
                                scr_y = location_3d_to_region_2d(region, rv3d, test_co_y)
                                if scr_y is not None:
                                    dist_y = (scr_y - curr_co_screen).length
                                    if dist_y < snap_dist_px:
                                        best_snap_co.y = ref_w.y
                                        snap_y = True
                                        gizmo.alignment_guides.append((tuple(ref_w), tuple(best_snap_co), (0.2, 1.0, 0.2, 0.8))) # 緑線
                                
                                # Z軸揃え
                                test_co_z = mathutils.Vector((new_world_co.x, new_world_co.y, ref_w.z))
                                scr_z = location_3d_to_region_2d(region, rv3d, test_co_z)
                                if scr_z is not None:
                                    dist_z = (scr_z - curr_co_screen).length
                                    if dist_z < snap_dist_px:
                                        best_snap_co.z = ref_w.z
                                        snap_z = True
                                        gizmo.alignment_guides.append((tuple(ref_w), tuple(best_snap_co), (0.2, 0.5, 1.0, 0.8))) # 青線
                            
                            if snap_x or snap_y or snap_z:
                                new_world_co = best_snap_co
                                local_co = self._drag_parent_matrix.inverted_safe() @ new_world_co

                        prim.points[self._drag_point_idx].co = tuple(local_co)
                context.area.tag_redraw()
            elif event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
                self._drag_point_idx = -1
                self._constraint_mode = ""
                gizmo = get_gizmo_engine()
                gizmo.drag_constraint_mode = ""
                gizmo.snap_pos = None
                gizmo.snap_type = ""
                gizmo.is_dragging_point = False
                gizmo.alignment_guides = []
            return {'RUNNING_MODAL'}
            
        if self._drag_axis:
            if event.type == 'MOUSEMOVE':
                axis_vec = mathutils.Vector((1,0,0)) if self._drag_axis=="X" else mathutils.Vector((0,1,0)) if self._drag_axis=="Y" else mathutils.Vector((0,0,1))
                p1, p2 = ray_origin, ray_origin + ray_direction
                p3, p4 = mathutils.Vector(self._prim_start_pos), mathutils.Vector(self._prim_start_pos) + axis_vec
                res = mathutils.geometry.intersect_line_line(p1, p2, p3, p4)
                if res and 0 <= props.active_primitive_index < len(props.primitives):
                    p_axis = res[1]
                    prim = props.primitives[props.active_primitive_index]
                    
                    # 独立制御: Altキーが押されている場合は、子の世界座標を維持する
                    # (親の移動分を子から差し引くことで、結果的に世界座標での位置を固定する)
                    delta = p_axis - mathutils.Vector(prim.location)
                    
                    props.is_dragging = True
                    prim.location = p_axis
                    
                    if event.alt or prim.use_independent_transform:
                        # 自身をターゲットにしている他のプリミティブ（子）を探す
                        for other in props.primitives:
                            if other.target_uuid == prim.uuid:
                                # 子の座標を逆方向にオフセットして世界座標を維持
                                other.location = mathutils.Vector(other.location) - delta
                                
                    props.is_dragging = False
                context.area.tag_redraw()
            elif event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
                self._drag_axis = ""
            self._drag_point_idx = -1
            return {'RUNNING_MODAL'}

        # Altキーの状態を同期
        props.is_alt_pressed = event.alt

        # Hover check for gizmo
        best_axis, min_dist = "", 0.05
        active_prim = None
        if 0 <= props.active_primitive_index < len(props.primitives):
            active_prim = props.primitives[props.active_primitive_index]

        # Altキーが押されている場合のみギズモの判定を行う
        if event.alt:
            for ax in ["X", "Y", "Z"]:
                d = self.get_ray_axis_dist(context, ray_origin, ray_direction, ax)
                if d < min_dist:
                    min_dist, best_axis = d, ax
        
        get_gizmo_engine().hover_axis = best_axis

        best_pt_idx, pt_min_dist = -1, 0.05
        if active_prim and active_prim.type in {'CURVE', 'SURFACE', 'POLYLINE'}:
            active_col = utils.get_active_collection(context)
            obj_matrix = None
            if active_col:
                target_name = f"{props.active_primitive_index}_{active_prim.type}_Seamless_Proxy"
                for ob in active_col.all_objects:
                    if ob.name == target_name:
                        obj_matrix = ob.matrix_world
                        break
                if obj_matrix is None:
                    for ob in active_col.all_objects:
                        if ("Proxy" in ob.name or "CURVE" in ob.name or "SURFACE" in ob.name or "POLYLINE" in ob.name) and ob.visible_get() and ob.scale.length > 1e-4:
                            obj_matrix = ob.matrix_world
                            break
            
            if obj_matrix:
                loc, rot, scale = obj_matrix.decompose()
                draw_matrix = mathutils.Matrix.Translation(loc) @ rot.to_matrix().to_4x4()
            else:
                draw_matrix = mathutils.Matrix.Translation(active_prim.location) @ mathutils.Euler(active_prim.rotation).to_matrix().to_4x4()

            for i, pt in enumerate(active_prim.points):
                p_co = draw_matrix @ mathutils.Vector(pt.co)
                p_on_ray = mathutils.geometry.intersect_point_line(p_co, ray_origin, ray_origin + ray_direction)[0]
                d = (p_co - p_on_ray).length
                if d < pt_min_dist:
                    pt_min_dist, best_pt_idx = d, i
                    
        get_gizmo_engine().hover_point_idx = best_pt_idx

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            if best_pt_idx != -1:
                self._drag_point_idx = best_pt_idx
                self._prim_start_pos = tuple(active_prim.points[best_pt_idx].co)
                self._drag_plane_normal = rv3d.view_matrix.inverted().to_3x3() @ mathutils.Vector((0, 0, 1))
                self._constraint_mode = ""
                self._snap_enabled = False
                self._snap_mode = "NONE"
                
                gizmo = get_gizmo_engine()
                gizmo.drag_constraint_mode = ""
                gizmo.snap_pos = None
                gizmo.snap_type = ""
                gizmo.is_dragging_point = True
                gizmo.snap_enabled = False
                gizmo.snap_mode = "NONE"
                
                active_col = utils.get_active_collection(context)
                obj_matrix = None
                if active_col:
                    target_name = f"{props.active_primitive_index}_{active_prim.type}_Seamless_Proxy"
                    for ob in active_col.all_objects:
                        if ob.name == target_name:
                            obj_matrix = ob.matrix_world
                            break
                    if obj_matrix is None:
                        for ob in active_col.all_objects:
                            if ("Proxy" in ob.name or "CURVE" in ob.name or "SURFACE" in ob.name or "POLYLINE" in ob.name) and ob.visible_get() and ob.scale.length > 1e-4:
                                obj_matrix = ob.matrix_world
                                break
                if obj_matrix:
                    loc, rot, scale = obj_matrix.decompose()
                    self._drag_parent_matrix = mathutils.Matrix.Translation(loc) @ rot.to_matrix().to_4x4()
                else:
                    self._drag_parent_matrix = mathutils.Matrix.Translation(active_prim.location) @ mathutils.Euler(active_prim.rotation).to_matrix().to_4x4()
                
                local_co = mathutils.Vector(active_prim.points[best_pt_idx].co)
                self._prim_start_world_pos = tuple(self._drag_parent_matrix @ local_co)
                gizmo.drag_start_pos = self._prim_start_world_pos
                
                return {'RUNNING_MODAL'}
            
            if best_axis:
                self._drag_axis = best_axis
                self._prim_start_pos = tuple(props.primitives[props.active_primitive_index].location)
                return {'RUNNING_MODAL'}
            
            # Picking logic (計算中は競合防止のためスキップ)
            core = get_core()
            if core and not is_core_busy():
                res = None
                stack_ptr = get_or_create_stack_ptr(utils.get_active_collection(context))
                if props.selection_type == 'EDGE' and hasattr(core, "pick_edge"):
                    res = core.pick_edge(stack_ptr, list(ray_origin), list(ray_direction), 0.6)
                elif props.selection_type == 'FACE' and hasattr(core, "pick_face"):
                    res = core.pick_face(stack_ptr, list(ray_origin), list(ray_direction), 0.6)
                
                if res:
                    if props.selection_type == 'EDGE':
                        lid, px, py, pz = res
                        nx, ny, nz = 0.0, 0.0, 1.0 # Edgeにはまだ法線がないためデフォルト
                    else:
                        lid, px, py, pz, nx, ny, nz = res
                    
                    print(f"====================================")
                    print(f"[DEBUG] Selection Modal Picked ID: {lid}")
                    print(f"====================================")
                    
                    props.preselected_point = (px, py, pz)
                    
                    # Target selection string: global or per-primitive if FILLET
                    target_obj = props
                    active_prim = None
                    if 0 <= props.active_primitive_index < len(props.primitives):
                        active_prim = props.primitives[props.active_primitive_index]
                    
                    if active_prim and props.is_selecting_reference:
                        # 特殊ケース: ドラフトの基準面選択
                        active_prim.reference_lineage = lid
                        if active_prim.type == 'DRAFT' and props.selection_type == 'FACE':
                            _update_target_ref_snapshot(
                                active_prim,
                                [lid],
                                (px, py, pz),
                                props,
                                snapshot_attr='reference_ref_snapshot'
                            )
                        props.is_selecting_reference = False
                        if active_prim.type == 'DRAFT':
                            utils.debug_print(
                                f"[DRAFT_PICK] reference set: {lid} selection_type={props.selection_type} "
                                f"ref_snapshot={'yes' if getattr(active_prim, 'reference_ref_snapshot', '') else 'no'}"
                            )
                    elif active_prim and active_prim.type in {'FILLET', 'CHAMFER', 'FACE_OFFSET', 'FACE_INSET', 'DRAFT', 'SHELL', 'FACE_LOFT', 'FACE_REVOLVE', 'SWEEP'}:
                        target_obj = active_prim
                        target_prop = "target_lineages"

                        if active_prim.type in {'FILLET', 'CHAMFER'} and props.selection_type == 'EDGE':
                            current_ids_list = get_display_edge_targets(active_prim)
                        else:
                            current_ids_list = [x.strip() for x in getattr(target_obj, target_prop).split("|") if x.strip()]
                        
                        # IDのベース部分（Edge:N や Face:N）で一致を確認する
                        lid_base = lid.split("@")[0] if "@" in lid else lid
                        found_idx = -1
                        for i, existing_id in enumerate(current_ids_list):
                            ex_base = existing_id.split("@")[0] if "@" in existing_id else existing_id
                            if ex_base == lid_base:
                                found_idx = i
                                break
                        
                        if found_idx != -1:
                            # 既にある場合は削除
                            current_ids_list.pop(found_idx)
                        else:
                            # ない場合は追加
                            if event.ctrl and props.selection_type == 'EDGE' and current_ids_list:
                                # Ctrlクリックによる最短経路一括追加
                                start_lid = current_ids_list[-1]
                                stack = get_wireframe_engine().get_stack(stack_ptr)
                                start_base = start_lid.split("@")[0] if "@" in start_lid else start_lid
                                for lin in stack.lineages:
                                    if (lin.split("@")[0] if "@" in lin else lin) == start_base:
                                        start_lid = lin
                                        break
                                if start_lid != lid:
                                    graph = build_edge_graph_from_stack(stack)
                                    lid_graph = lid.split("#")[0]
                                    path = find_shortest_edge_path(graph, start_lid, lid_graph)
                                    utils.debug_print(f"DEBUG PATH: start_lid={start_lid}")
                                    utils.debug_print(f"DEBUG PATH: lid_graph={lid_graph}")
                                    utils.debug_print(f"DEBUG PATH: graph_keys count={len(graph.keys())}, path_found={bool(path)}")
                                    if path:
                                        for p_id in path:
                                            p_base = p_id.split("@")[0] if "@" in p_id else p_id
                                            if not any((x.split("@")[0] if "@" in x else x) == p_base for x in current_ids_list):
                                                current_ids_list.append(p_id)
                                    else:
                                        current_ids_list.append(lid)
                                else:
                                    current_ids_list.append(lid)
                            elif not event.shift:
                                current_ids_list = [lid]
                            else:
                                current_ids_list.append(lid)
                        stored_ids_list = _to_modifier_target_tokens(active_prim, current_ids_list, props)
                        new_str = "|".join(stored_ids_list)
                        setattr(target_obj, target_prop, new_str)
                        
                        # V8.0.1: FILLET/CHAMFER辺の参照スナップショット記録
                        if (
                            props.selection_type == 'EDGE' and active_prim.type in {'FILLET', 'CHAMFER'}
                        ) or (
                            props.selection_type == 'FACE' and active_prim.type in {'FACE_OFFSET', 'FACE_INSET', 'DRAFT', 'SHELL', 'FACE_LOFT', 'FACE_REVOLVE', 'SWEEP'}
                        ):
                            _update_target_ref_snapshot(active_prim, current_ids_list, (px, py, pz), props)
                        if active_prim.type == 'FILLET' and props.selection_type == 'EDGE':
                            _sync_edge_radii(active_prim, current_ids_list)
                        if active_prim.type == 'DRAFT':
                            utils.debug_print(
                                f"[DRAFT_PICK] targets set: selection_type={props.selection_type} "
                                f"targets={getattr(active_prim, 'target_lineages', '')!r} "
                                f"reference={getattr(active_prim, 'reference_lineage', '')!r}"
                            )
                        
                        # Always sync global for highlighting
                        if props.selection_type == 'EDGE': props.selected_edges_str = "|".join(current_ids_list)
                        else: props.selected_faces_str = new_str
                    
                context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        if event.type == 'MOUSEMOVE':
            # 計算中は競合防止のためスキップ
            core = get_core()
            if core and not is_core_busy():
                res = None
                stack_ptr = get_or_create_stack_ptr(utils.get_active_collection(context))
                if props.selection_type == 'EDGE' and hasattr(core, "pick_edge"):
                    res = core.pick_edge(stack_ptr, list(ray_origin), list(ray_direction), 0.6)
                elif props.selection_type == 'FACE' and hasattr(core, "pick_face"):
                    res = core.pick_face(stack_ptr, list(ray_origin), list(ray_direction), 0.6)

                if res:
                    if props.selection_type == 'EDGE':
                        lid, px, py, pz = res
                        
                        # Ctrlキー押下時の最短経路ハイライトプレビュー
                        if event.ctrl:
                            start_lid = None
                            active_prim = None
                            if 0 <= props.active_primitive_index < len(props.primitives):
                                active_prim = props.primitives[props.active_primitive_index]
                            if active_prim and active_prim.type in {'FILLET', 'CHAMFER', 'FACE_OFFSET', 'FACE_INSET', 'DRAFT', 'SHELL', 'FACE_LOFT', 'FACE_REVOLVE'}:
                                current_ids = get_display_edge_targets(active_prim) if active_prim.type in {'FILLET', 'CHAMFER'} else [x.strip() for x in active_prim.target_lineages.split("|") if x.strip()]
                                if current_ids:
                                    start_lid = current_ids[-1]
                                    stack = get_wireframe_engine().get_stack(stack_ptr)
                                    start_base = start_lid.split("@")[0] if "@" in start_lid else start_lid
                                    for lin in stack.lineages:
                                        if (lin.split("@")[0] if "@" in lin else lin) == start_base:
                                            start_lid = lin
                                            break
                            
                            if start_lid and start_lid != lid:
                                graph = build_edge_graph_from_stack(stack)
                                lid_graph = lid.split("#")[0]
                                path = find_shortest_edge_path(graph, start_lid, lid_graph)
                                utils.debug_print(f"DEBUG PATH MOUSEMOVE: start_lid={start_lid}")
                                utils.debug_print(f"DEBUG PATH MOUSEMOVE: lid_graph={lid_graph}")
                                utils.debug_print(f"DEBUG PATH MOUSEMOVE: graph_keys count={len(graph.keys())}, path_found={bool(path)}")
                                if path:
                                    props.preselected_edge_id = "|".join(path)
                                else:
                                    props.preselected_edge_id = lid
                            else:
                                props.preselected_edge_id = lid
                        else:
                            props.preselected_edge_id = lid
                            
                        props.preselected_face_id = ""
                    else:
                        lid, px, py, pz, nx, ny, nz = res
                        props.preselected_edge_id = ""
                        props.preselected_face_id = lid
                    
                    utils.debug_print(f"DEBUG: Pick Result: {lid}")
                    props.preselected_point = (px, py, pz)
                else:
                    props.preselected_edge_id = ""; props.preselected_face_id = ""
            context.area.tag_redraw()

        if event.type == 'D' and event.shift and event.value == 'PRESS':
            bpy.ops.seamless.duplicate_primitive(index=props.active_primitive_index)
            self.report({'INFO'}, "Primitive Duplicated")
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        if event.type in {'ESC', 'RIGHTMOUSE'}:
            props.is_selection_mode = False
            props.preselected_edge_id = ""
            context.area.tag_redraw()
            return {'FINISHED'}
        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        if context.area.type == 'VIEW_3D':
            # Initialize instance state
            self._drag_axis = ""
            self._drag_point_idx = -1
            self._prim_start_pos = (0,0,0)
            self._mouse_start_x = 0
            self._drag_plane_normal = (0,0,1)
            
            props = utils.get_active_props(context)
            if not props:
                return {'CANCELLED'}
            props.is_selection_mode = True
            
            # 🌟 古い選択状態をクリアして、別プリミティブ作成時のIDキャリーオーバー（重複蓄積）を防ぐ
            props.selected_edges_str = ""
            props.selected_faces_str = ""
            props.preselected_edge_id = ""
            props.preselected_face_id = ""
            
            get_gizmo_engine().update_gizmo(context, props.active_primitive_index)
            utils.redraw_all_view3d(context)
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        return {'CANCELLED'}
