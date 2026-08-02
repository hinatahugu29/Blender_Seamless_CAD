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
import json
import mathutils
import math
from ... import utils
from ..sketch_history import push_history, perform_undo
from ..sketch_solver import solve_gcs_external, find_arc_by_line_id
from ..sketch_finalize import finalize_sketch, calculate_arc_points, calculate_circle_points, is_point_in_polygon
from .. import sketch_globals

from ...core_bridge import update_cad_preview


def action_delete_selected(op, context, props):
    push_history(props)
    deleted = False
    
    sel_pts_list = [int(x) for x in props.sketch_selected_points_str.split(",") if x]
    sel_lines_list = [int(x) for x in props.sketch_selected_lines_str.split(",") if x]
    
    if sel_pts_list or sel_lines_list:
        pts_to_delete = set(sel_pts_list)
        lines_to_delete = set(sel_lines_list)
        
        # Cascade 1: lines -> is_segment points, points -> lines
        changed = True
        while changed:
            changed = False
            # lines -> points (only is_segment points die when their lines die)
            for l in props.sketch_lines:
                if l.id in lines_to_delete:
                    for pid in (l.start_point_id, l.end_point_id):
                        pt = next((p for p in props.sketch_points if p.id == pid), None)
                        if pt and pt.is_segment and pid not in pts_to_delete:
                            pts_to_delete.add(pid)
                            changed = True
            # points -> lines (any line connected to a deleted point must die)
            for l in props.sketch_lines:
                if l.id not in lines_to_delete:
                    if l.start_point_id in pts_to_delete or l.end_point_id in pts_to_delete:
                        lines_to_delete.add(l.id)
                        changed = True
        
        # Identify broken arcs/circles
        broken_arcs = set()
        for arc in props.sketch_arcs:
            if (arc.start_point_id in pts_to_delete or 
                arc.end_point_id in pts_to_delete or 
                arc.mid_point_id in pts_to_delete or 
                arc.center_point_id in pts_to_delete):
                broken_arcs.add(arc.id)
                
        broken_circles = set()
        for circ in props.sketch_circles:
            if circ.center_point_id in pts_to_delete or circ.radius_point_id in pts_to_delete:
                broken_circles.add(circ.id)
                
        # Identify which is_segment points belong to UNBROKEN arcs
        import collections
        adj = collections.defaultdict(list)
        for l in props.sketch_lines:
            if l.id not in lines_to_delete:
                adj[l.start_point_id].append(l.end_point_id)
                adj[l.end_point_id].append(l.start_point_id)
                
        valid_segment_pts = set()
        for arc in props.sketch_arcs:
            if arc.id not in broken_arcs:
                stack = [(arc.start_point_id, [arc.start_point_id])]
                visited = {arc.start_point_id}
                path = None
                while stack:
                    node, curr_path = stack.pop()
                    if node == arc.end_point_id:
                        path = curr_path
                        break
                    for n in adj[node]:
                        if n not in visited:
                            pt = next((p for p in props.sketch_points if p.id == n), None)
                            if n == arc.end_point_id or (pt and pt.is_segment):
                                visited.add(n)
                                stack.append((n, curr_path + [n]))
                if path:
                    valid_segment_pts.update(path)
                else:
                    # Path is broken, so the arc is actually broken!
                    broken_arcs.add(arc.id)
                    
        # Any is_segment point NOT in valid_segment_pts should be deleted
        for pt in props.sketch_points:
            if pt.is_segment and pt.id not in valid_segment_pts and pt.id not in pts_to_delete:
                pts_to_delete.add(pt.id)
                
        # Cascade again (points -> lines)
        changed = True
        while changed:
            changed = False
            for l in props.sketch_lines:
                if l.id not in lines_to_delete:
                    if l.start_point_id in pts_to_delete or l.end_point_id in pts_to_delete:
                        lines_to_delete.add(l.id)
                        changed = True
                        
        # Apply deletions
        lines_to_keep = [{"id": l.id, "start": l.start_point_id, "end": l.end_point_id, "is_construction": getattr(l, "is_construction", False)} 
                         for l in props.sketch_lines if l.id not in lines_to_delete]
        props.sketch_lines.clear()
        for l in lines_to_keep:
            nl = props.sketch_lines.add()
            nl.id = l["id"]
            nl.start_point_id = l["start"]
            nl.end_point_id = l["end"]
            if l["is_construction"]:
                nl.is_construction = True
                
        points_to_keep = [{"id": p.id, "co": p.co[:], "is_segment": p.is_segment} 
                          for p in props.sketch_points if p.id not in pts_to_delete]
        props.sketch_points.clear()
        for p in points_to_keep:
            np = props.sketch_points.add()
            np.id = p["id"]
            np.co = p["co"]
            np.is_segment = p["is_segment"]
            
        arcs_to_keep = [{"id": a.id, "start": a.start_point_id, "end": a.end_point_id, 
                         "mid": a.mid_point_id, "center": a.center_point_id, "is_construction": getattr(a, "is_construction", False)} 
                        for a in props.sketch_arcs if a.id not in broken_arcs]
        props.sketch_arcs.clear()
        for a in arcs_to_keep:
            na = props.sketch_arcs.add()
            na.id = a["id"]
            na.start_point_id = a["start"]
            na.end_point_id = a["end"]
            na.mid_point_id = a["mid"]
            na.center_point_id = a["center"]
            if a["is_construction"]:
                na.is_construction = True
                
        circles_to_keep = [{"id": c.id, "center": c.center_point_id, "radius": c.radius_point_id, "is_construction": getattr(c, "is_construction", False)} 
                           for c in props.sketch_circles if c.id not in broken_circles]
        props.sketch_circles.clear()
        for c in circles_to_keep:
            nc = props.sketch_circles.add()
            nc.id = c["id"]
            nc.center_point_id = c["center"]
            nc.radius_point_id = c["radius"]
            if c["is_construction"]:
                nc.is_construction = True
                
        # Remove constraints involving deleted points
        constraints_to_keep = []
        for c in props.sketch_constraints:
            keep = True
            parts = [int(x.strip()) for x in c.target_ids_str.split(",") if x.strip()]
            for tid in parts:
                if tid in pts_to_delete:
                    keep = False
                    break
            if keep:
                constraints_to_keep.append({
                    "id": c.id,
                    "type": c.type,
                    "target_ids_str": c.target_ids_str,
                    "value": c.value
                })
                
        props.sketch_constraints.clear()
        for c in constraints_to_keep:
            nc = props.sketch_constraints.add()
            nc.id = c["id"]
            nc.type = c["type"]
            nc.target_ids_str = c["target_ids_str"]
            nc.value = c["value"]
            
        props.sketch_selected_points_str = ""
        props.sketch_selected_lines_str = ""
        props.sketch_selected_point_id = -1
        props.sketch_selected_point_id_2 = -1
        props.sketch_selected_line_id = -1
        props.sketch_selected_line_id_2 = -1
        deleted = True
        op.report({'INFO'}, "Deleted selected items and cleaned up topology.")
        
    if deleted:
        solve_gcs_external(props, context)
        update_cad_preview(None, context)
    else:
        op.report({'WARNING'}, "No selection to delete.")
        

def action_toggle_construction(op, context, props):
    toggled = False
    sel_pts = [int(x) for x in props.sketch_selected_points_str.split(",") if x]
    sel_lines = [int(x) for x in props.sketch_selected_lines_str.split(",") if x]
    
    for line_id in sel_lines:
        arc = None
        line = next((l for l in props.sketch_lines if l.id == line_id), None)
        if line:
            for a in props.sketch_arcs:
                if line.start_point_id in {a.start_point_id, a.end_point_id, a.mid_point_id} and \
                   line.end_point_id in {a.start_point_id, a.end_point_id, a.mid_point_id}:
                    arc = a
                    break
        if arc:
            arc.is_construction = not getattr(arc, "is_construction", False)
            toggled = True
        else:
            if line:
                line.is_construction = not getattr(line, "is_construction", False)
                toggled = True
    
    if not toggled and sel_pts:
        # 選択されたVertexが円や円弧の制御点であれば、その円・円弧の補助線状態を切り替える
        for pt_id in sel_pts:
            for circ in props.sketch_circles:
                if pt_id in (circ.center_point_id, circ.radius_point_id):
                    circ.is_construction = not getattr(circ, "is_construction", False)
                    toggled = True
            for arc in props.sketch_arcs:
                if pt_id in (arc.start_point_id, arc.end_point_id, arc.mid_point_id, arc.center_point_id):
                    arc.is_construction = not getattr(arc, "is_construction", False)
                    toggled = True
        
    if toggled:
        op.report({'INFO'}, "Toggled construction geometry.")
        update_cad_preview(None, context)
    else:
        op.report({'WARNING'}, "Select a line or arc to toggle construction.")


def action_mirror(op, context, props, axis='X'):
    push_history(props)
    
    sel_pts_list = [int(x) for x in props.sketch_selected_points_str.split(",") if x]
    sel_lines_list = [int(x) for x in props.sketch_selected_lines_str.split(",") if x]
    
    if not sel_pts_list and not sel_lines_list:
        op.report({'WARNING'}, "No selection to mirror.")
        return
        
    # ミラー後のIDマッピング
    pt_id_map = {}
    max_pt_id = max([p.id for p in props.sketch_points] + [-1])
    max_line_id = max([l.id for l in props.sketch_lines] + [-1])
    max_arc_id = max([a.id for a in props.sketch_arcs] + [-1])
    max_circle_id = max([c.id for c in props.sketch_circles] + [-1])
    
    # 円弧と円を構成するVertexも全て選択リストに追加する
    for a in props.sketch_arcs:
        if a.start_point_id in sel_pts_list or a.end_point_id in sel_pts_list or a.mid_point_id in sel_pts_list or a.center_point_id in sel_pts_list:
            if a.start_point_id not in sel_pts_list: sel_pts_list.append(a.start_point_id)
            if a.end_point_id not in sel_pts_list: sel_pts_list.append(a.end_point_id)
            if a.mid_point_id not in sel_pts_list: sel_pts_list.append(a.mid_point_id)
            if a.center_point_id not in sel_pts_list: sel_pts_list.append(a.center_point_id)
            
    for c in props.sketch_circles:
        if c.center_point_id in sel_pts_list or c.radius_point_id in sel_pts_list:
            if c.center_point_id not in sel_pts_list: sel_pts_list.append(c.center_point_id)
            if c.radius_point_id not in sel_pts_list: sel_pts_list.append(c.radius_point_id)
    
    # 線の両端のVertexが選択されていなければ、選択されている線の端点をリストに追加する
    for lid in sel_lines_list:
        line = next((l for l in props.sketch_lines if l.id == lid), None)
        if line:
            if line.start_point_id not in sel_pts_list:
                sel_pts_list.append(line.start_point_id)
            if line.end_point_id not in sel_pts_list:
                sel_pts_list.append(line.end_point_id)
                
    new_pts_ids = []
    
    # Vertexのコピーと反転
    for pid in sel_pts_list:
        pt = next((p for p in props.sketch_points if p.id == pid), None)
        if pt:
            max_pt_id += 1
            new_pt = props.sketch_points.add()
            new_pt.id = max_pt_id
            if axis == 'X':
                new_pt.co = (pt.co[0], -pt.co[1]) # X軸対称 = Y座標を反転
            else: # 'Y'
                new_pt.co = (-pt.co[0], pt.co[1]) # Y軸対称 = X座標を反転
            new_pt.is_segment = pt.is_segment
            pt_id_map[pid] = max_pt_id
            new_pts_ids.append(str(max_pt_id))
            
    # 線のコピー
    new_lines_ids = []
    for lid in sel_lines_list:
        line = next((l for l in props.sketch_lines if l.id == lid), None)
        if line and line.start_point_id in pt_id_map and line.end_point_id in pt_id_map:
            max_line_id += 1
            new_line = props.sketch_lines.add()
            new_line.id = max_line_id
            new_line.start_point_id = pt_id_map[line.start_point_id]
            new_line.end_point_id = pt_id_map[line.end_point_id]
            new_line.is_construction = getattr(line, "is_construction", False)
            new_lines_ids.append(str(max_line_id))
            
    # 円弧のコピー
    for a in props.sketch_arcs:
        if a.start_point_id in pt_id_map and a.end_point_id in pt_id_map and a.mid_point_id in pt_id_map and a.center_point_id in pt_id_map:
            max_arc_id += 1
            new_arc = props.sketch_arcs.add()
            new_arc.id = max_arc_id
            # 反転すると時計回り・反時計回りが逆転するため、始点と終点を入れ替えておくとソルバーで都合が良い場合があるが、
            # まずはそのままマッピングする。
            new_arc.start_point_id = pt_id_map[a.start_point_id]
            new_arc.end_point_id = pt_id_map[a.end_point_id]
            new_arc.mid_point_id = pt_id_map[a.mid_point_id]
            new_arc.center_point_id = pt_id_map[a.center_point_id]
            new_arc.is_construction = getattr(a, "is_construction", False)
            
    # 円のコピー
    for c in props.sketch_circles:
        if c.center_point_id in pt_id_map and c.radius_point_id in pt_id_map:
            max_circle_id += 1
            new_circle = props.sketch_circles.add()
            new_circle.id = max_circle_id
            new_circle.center_point_id = pt_id_map[c.center_point_id]
            new_circle.radius_point_id = pt_id_map[c.radius_point_id]
            new_circle.is_construction = getattr(c, "is_construction", False)
            
    # UIの選択状態を新しく作った要素に変更する
    props.sketch_selected_points_str = ",".join(new_pts_ids)
    props.sketch_selected_lines_str = ",".join(new_lines_ids)
    
    solve_gcs_external(props, context)
    update_cad_preview(None, context)
    op.report({'INFO'}, f"Mirrored along {axis}-Axis.")

def action_mirror_x(op, context, props):
    action_mirror(op, context, props, axis='X')

def action_mirror_y(op, context, props):
    action_mirror(op, context, props, axis='Y')


def action_select_all(op, context, props):
    point_ids = [str(pt.id) for pt in props.sketch_points if not pt.is_segment]
    line_ids = []
    for line in props.sketch_lines:
        start_pt = next((pt for pt in props.sketch_points if pt.id == line.start_point_id), None)
        end_pt = next((pt for pt in props.sketch_points if pt.id == line.end_point_id), None)
        if start_pt and end_pt and not start_pt.is_segment and not end_pt.is_segment:
            line_ids.append(str(line.id))

    props.sketch_selected_points_str = ",".join(point_ids)
    props.sketch_selected_lines_str = ",".join(line_ids)
    props.sketch_selected_point_id = int(point_ids[0]) if point_ids else -1
    props.sketch_selected_point_id_2 = int(point_ids[1]) if len(point_ids) > 1 else -1
    props.sketch_selected_line_id = int(line_ids[0]) if line_ids else -1
    props.sketch_selected_line_id_2 = int(line_ids[1]) if len(line_ids) > 1 else -1
    op.report({'INFO'}, f"Selected {len(point_ids)} points and {len(line_ids)} lines.")


def action_select_chain(op, context, props):
    visible_line_lookup = {}
    for line in props.sketch_lines:
        start_pt = next((pt for pt in props.sketch_points if pt.id == line.start_point_id), None)
        end_pt = next((pt for pt in props.sketch_points if pt.id == line.end_point_id), None)
        if not start_pt or not end_pt:
            continue
        if start_pt.is_segment or end_pt.is_segment:
            continue
        visible_line_lookup[line.id] = line

    seed_line_ids = [int(x) for x in props.sketch_selected_lines_str.split(",") if x and int(x) in visible_line_lookup]
    if not seed_line_ids and props.sketch_hover_line_id in visible_line_lookup:
        seed_line_ids = [props.sketch_hover_line_id]

    if not seed_line_ids:
        op.report({'WARNING'}, "Select or hover a line to chain-select connected edges.")
        return

    point_to_lines = {}
    for line in visible_line_lookup.values():
        point_to_lines.setdefault(line.start_point_id, set()).add(line.id)
        point_to_lines.setdefault(line.end_point_id, set()).add(line.id)

    queue = list(seed_line_ids)
    selected_line_ids = set(seed_line_ids)
    while queue:
        line_id = queue.pop(0)
        line = visible_line_lookup[line_id]
        neighbor_line_ids = point_to_lines.get(line.start_point_id, set()) | point_to_lines.get(line.end_point_id, set())
        for neighbor_id in neighbor_line_ids:
            if neighbor_id not in selected_line_ids:
                selected_line_ids.add(neighbor_id)
                queue.append(neighbor_id)

    selected_point_ids = set()
    for line_id in selected_line_ids:
        line = visible_line_lookup[line_id]
        selected_point_ids.add(line.start_point_id)
        selected_point_ids.add(line.end_point_id)

    line_ids_sorted = sorted(selected_line_ids)
    point_ids_sorted = sorted(selected_point_ids)
    props.sketch_selected_lines_str = ",".join(str(line_id) for line_id in line_ids_sorted)
    props.sketch_selected_points_str = ",".join(str(point_id) for point_id in point_ids_sorted)
    props.sketch_selected_line_id = line_ids_sorted[0] if line_ids_sorted else -1
    props.sketch_selected_line_id_2 = line_ids_sorted[1] if len(line_ids_sorted) > 1 else -1
    props.sketch_selected_point_id = point_ids_sorted[0] if point_ids_sorted else -1
    props.sketch_selected_point_id_2 = point_ids_sorted[1] if len(point_ids_sorted) > 1 else -1
    op.report({'INFO'}, f"Chain-selected {len(line_ids_sorted)} connected lines.")


def _line_intersection_2d(p1, p2, p3, p4):
    x1, y1 = p1.x, p1.y
    x2, y2 = p2.x, p2.y
    x3, y3 = p3.x, p3.y
    x4, y4 = p4.x, p4.y
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-8:
        return None
    det1 = x1 * y2 - y1 * x2
    det2 = x3 * y4 - y3 * x4
    px = (det1 * (x3 - x4) - (x1 - x2) * det2) / denom
    py = (det1 * (y3 - y4) - (y1 - y2) * det2) / denom
    return mathutils.Vector((px, py, 0.0))


def _line_intersection_with_params(p1, p2, p3, p4):
    r = p2 - p1
    s = p4 - p3
    denom = (r.x * s.y) - (r.y * s.x)
    if abs(denom) < 1e-8:
        return None, None, None
    qp = p3 - p1
    t = ((qp.x * s.y) - (qp.y * s.x)) / denom
    u = ((qp.x * r.y) - (qp.y * r.x)) / denom
    point = p1 + (r * t)
    return point, t, u


def _visible_line_data(props, line_id):
    line = next((ln for ln in props.sketch_lines if ln.id == line_id), None)
    if not line:
        return None
    start_pt = next((pt for pt in props.sketch_points if pt.id == line.start_point_id), None)
    end_pt = next((pt for pt in props.sketch_points if pt.id == line.end_point_id), None)
    if not start_pt or not end_pt or start_pt.is_segment or end_pt.is_segment:
        return None
    p1 = mathutils.Vector((start_pt.co[0], start_pt.co[1], 0.0))
    p2 = mathutils.Vector((end_pt.co[0], end_pt.co[1], 0.0))
    return line, start_pt, end_pt, p1, p2


def _resolve_trim_extend_pair(props):
    selected_line_ids = [int(x) for x in props.sketch_selected_lines_str.split(",") if x]
    target_id = selected_line_ids[0] if selected_line_ids else -1
    reference_id = selected_line_ids[1] if len(selected_line_ids) > 1 else -1
    if target_id < 0:
        target_id = props.sketch_hover_line_id
    if reference_id < 0 and props.sketch_hover_line_id >= 0 and props.sketch_hover_line_id != target_id:
        reference_id = props.sketch_hover_line_id
    if target_id < 0 or reference_id < 0 or target_id == reference_id:
        return None, None
    return target_id, reference_id


def _is_point_used_elsewhere(props, point_id, skip_line_id):
    for line in props.sketch_lines:
        if line.id == skip_line_id:
            continue
        if point_id in {line.start_point_id, line.end_point_id}:
            return True
    for arc in props.sketch_arcs:
        if point_id in {arc.start_point_id, arc.end_point_id, arc.mid_point_id, arc.center_point_id}:
            return True
    for circle in props.sketch_circles:
        if point_id in {circle.center_point_id, circle.radius_point_id}:
            return True
    return False


def _apply_endpoint_to_point(props, line, endpoint_attr, old_point, intersection):
    if _is_point_used_elsewhere(props, old_point.id, line.id):
        new_point = props.sketch_points.add()
        new_point.id = max([pt.id for pt in props.sketch_points] + [0]) + 1
        new_point.co = (intersection.x, intersection.y)
        new_point.is_segment = False
        setattr(line, endpoint_attr, new_point.id)
        return new_point.id

    old_point.co = (intersection.x, intersection.y)
    return old_point.id


def _finalize_line_edit(op, context, props, line, point_id):
    props.sketch_selected_lines_str = str(line.id)
    props.sketch_selected_points_str = str(point_id)
    props.sketch_selected_line_id = line.id
    props.sketch_selected_line_id_2 = -1
    props.sketch_selected_point_id = point_id
    props.sketch_selected_point_id_2 = -1
    pt = next((p for p in props.sketch_points if p.id == point_id), None)
    if pt:
        props.sketch_selected_point_x = pt.co[0]
        props.sketch_selected_point_y = pt.co[1]
    solve_gcs_external(props, context)
    update_cad_preview(None, context)


def action_trim_selection(op, context, props):
    target_id, reference_id = _resolve_trim_extend_pair(props)
    if target_id is None:
        op.report({'WARNING'}, "Select two lines, or select one line and hover another line to trim.")
        return

    target_data = _visible_line_data(props, target_id)
    reference_data = _visible_line_data(props, reference_id)
    if not target_data or not reference_data:
        op.report({'WARNING'}, "Trim currently supports visible sketch lines only.")
        return

    target_line, start_pt, end_pt, p1, p2 = target_data
    _, _, _, p3, p4 = reference_data
    intersection, t, u = _line_intersection_with_params(p1, p2, p3, p4)
    if intersection is None:
        op.report({'WARNING'}, "Selected lines are parallel or coincident.")
        return
    if not (1e-4 < t < 1.0 - 1e-4) or not (-1e-4 <= u <= 1.0 + 1e-4):
        op.report({'WARNING'}, "Trim needs an intersection on the target segment and reference line.")
        return

    mouse_pos = sketch_globals._mouse_pos if sketch_globals._mouse_pos is not None else intersection
    start_dist = (mouse_pos - p1).length
    end_dist = (mouse_pos - p2).length
    endpoint_attr = "start_point_id" if start_dist <= end_dist else "end_point_id"
    old_point = start_pt if endpoint_attr == "start_point_id" else end_pt

    push_history(props)
    point_id = _apply_endpoint_to_point(props, target_line, endpoint_attr, old_point, intersection)
    _finalize_line_edit(op, context, props, target_line, point_id)
    op.report({'INFO'}, "Trimmed line to intersection.")


def action_extend_selection(op, context, props):
    target_id, reference_id = _resolve_trim_extend_pair(props)
    if target_id is None:
        op.report({'WARNING'}, "Select two lines, or select one line and hover another line to extend.")
        return

    target_data = _visible_line_data(props, target_id)
    reference_data = _visible_line_data(props, reference_id)
    if not target_data or not reference_data:
        op.report({'WARNING'}, "Extend currently supports visible sketch lines only.")
        return

    target_line, start_pt, end_pt, p1, p2 = target_data
    _, _, _, p3, p4 = reference_data
    intersection, t, u = _line_intersection_with_params(p1, p2, p3, p4)
    if intersection is None:
        op.report({'WARNING'}, "Selected lines are parallel or coincident.")
        return
    if not (-1e-4 <= u <= 1.0 + 1e-4):
        op.report({'WARNING'}, "Extend needs an intersection on the reference line.")
        return
    if -1e-4 <= t <= 1.0 + 1e-4:
        op.report({'WARNING'}, "Target line already reaches that intersection.")
        return

    if t < 0.0:
        endpoint_attr = "start_point_id"
        old_point = start_pt
    else:
        endpoint_attr = "end_point_id"
        old_point = end_pt

    push_history(props)
    point_id = _apply_endpoint_to_point(props, target_line, endpoint_attr, old_point, intersection)
    _finalize_line_edit(op, context, props, target_line, point_id)
    op.report({'INFO'}, "Extended line to intersection.")


def _ordered_line_chain(props, selected_line_ids):
    line_lookup = {}
    adjacency = {}
    for line_id in selected_line_ids:
        line = next((ln for ln in props.sketch_lines if ln.id == line_id), None)
        if not line:
            continue
        start_pt = next((pt for pt in props.sketch_points if pt.id == line.start_point_id), None)
        end_pt = next((pt for pt in props.sketch_points if pt.id == line.end_point_id), None)
        if not start_pt or not end_pt or start_pt.is_segment or end_pt.is_segment:
            continue
        line_lookup[line.id] = line
        adjacency.setdefault(line.start_point_id, []).append(line.id)
        adjacency.setdefault(line.end_point_id, []).append(line.id)

    if not line_lookup:
        return None, None, "Select visible sketch lines to offset."

    degrees = {point_id: len(line_ids) for point_id, line_ids in adjacency.items()}
    branch_points = [point_id for point_id, degree in degrees.items() if degree > 2]
    if branch_points:
        return None, None, "Offset currently supports a single non-branching line chain."

    endpoints = [point_id for point_id, degree in degrees.items() if degree == 1]
    is_closed = len(endpoints) == 0
    if not is_closed and len(endpoints) != 2:
        return None, None, "Select one connected open chain or one closed loop."

    start_point_id = endpoints[0] if endpoints else next(iter(adjacency.keys()))
    ordered_point_ids = [start_point_id]
    ordered_line_ids = []
    visited_lines = set()
    current_point_id = start_point_id

    while True:
        next_line_id = next((line_id for line_id in adjacency[current_point_id] if line_id not in visited_lines), None)
        if next_line_id is None:
            break
        visited_lines.add(next_line_id)
        ordered_line_ids.append(next_line_id)
        line = line_lookup[next_line_id]
        next_point_id = line.end_point_id if line.start_point_id == current_point_id else line.start_point_id
        ordered_point_ids.append(next_point_id)
        current_point_id = next_point_id
        if is_closed and current_point_id == start_point_id:
            break

    if len(visited_lines) != len(line_lookup):
        return None, None, "Offset currently supports one connected chain at a time."

    return ordered_point_ids, ordered_line_ids, None


def action_offset_selection(op, context, props):
    selected_line_ids = [int(x) for x in props.sketch_selected_lines_str.split(",") if x]
    if not selected_line_ids:
        op.report({'WARNING'}, "Select one connected line chain to offset.")
        return

    ordered_point_ids, ordered_line_ids, error_message = _ordered_line_chain(props, selected_line_ids)
    if error_message:
        op.report({'WARNING'}, error_message)
        return

    distance = float(props.sketch_offset_distance)
    if abs(distance) < 1e-8:
        op.report({'WARNING'}, "Offset distance is too small.")
        return

    point_lookup = {pt.id: mathutils.Vector((pt.co[0], pt.co[1], 0.0)) for pt in props.sketch_points}
    ordered_points = [point_lookup[point_id] for point_id in ordered_point_ids]
    is_closed = ordered_point_ids[0] == ordered_point_ids[-1]

    segment_offsets = []
    segment_count = len(ordered_points) - 1
    for idx in range(segment_count):
        start = ordered_points[idx]
        end = ordered_points[idx + 1]
        direction = end - start
        if direction.length <= 1e-8:
            op.report({'WARNING'}, "Offset cannot use zero-length lines.")
            return
        normal = mathutils.Vector((-direction.y, direction.x, 0.0)).normalized() * distance
        segment_offsets.append((start + normal, end + normal))

    offset_points = []
    vertex_count = segment_count if is_closed else len(ordered_points)
    for idx in range(vertex_count):
        if is_closed:
            prev_idx = (idx - 1) % segment_count
            next_idx = idx % segment_count
            intersection = _line_intersection_2d(
                segment_offsets[prev_idx][0], segment_offsets[prev_idx][1],
                segment_offsets[next_idx][0], segment_offsets[next_idx][1]
            )
            if intersection is None:
                intersection = segment_offsets[next_idx][0]
            offset_points.append(intersection)
        else:
            if idx == 0:
                offset_points.append(segment_offsets[0][0])
            elif idx == vertex_count - 1:
                offset_points.append(segment_offsets[-1][1])
            else:
                intersection = _line_intersection_2d(
                    segment_offsets[idx - 1][0], segment_offsets[idx - 1][1],
                    segment_offsets[idx][0], segment_offsets[idx][1]
                )
                if intersection is None:
                    intersection = (segment_offsets[idx - 1][1] + segment_offsets[idx][0]) * 0.5
                offset_points.append(intersection)

    push_history(props)
    max_point_id = max([pt.id for pt in props.sketch_points] + [0])
    max_line_id = max([ln.id for ln in props.sketch_lines] + [0])

    new_point_ids = []
    for co in offset_points:
        max_point_id += 1
        new_pt = props.sketch_points.add()
        new_pt.id = max_point_id
        new_pt.co = (co.x, co.y)
        new_pt.is_segment = False
        new_point_ids.append(max_point_id)

    new_line_ids = []
    line_total = len(new_point_ids) if is_closed else len(new_point_ids) - 1
    for idx in range(line_total):
        start_id = new_point_ids[idx]
        end_id = new_point_ids[(idx + 1) % len(new_point_ids)]
        max_line_id += 1
        new_line = props.sketch_lines.add()
        new_line.id = max_line_id
        new_line.start_point_id = start_id
        new_line.end_point_id = end_id
        new_line_ids.append(max_line_id)

    props.sketch_selected_points_str = ",".join(str(point_id) for point_id in new_point_ids)
    props.sketch_selected_lines_str = ",".join(str(line_id) for line_id in new_line_ids)
    props.sketch_selected_point_id = new_point_ids[0] if new_point_ids else -1
    props.sketch_selected_point_id_2 = new_point_ids[1] if len(new_point_ids) > 1 else -1
    props.sketch_selected_line_id = new_line_ids[0] if new_line_ids else -1
    props.sketch_selected_line_id_2 = new_line_ids[1] if len(new_line_ids) > 1 else -1
    if new_point_ids:
        first_point = next((pt for pt in props.sketch_points if pt.id == new_point_ids[0]), None)
        if first_point:
            props.sketch_selected_point_x = first_point.co[0]
            props.sketch_selected_point_y = first_point.co[1]

    update_cad_preview(None, context)
    op.report({'INFO'}, f"Created offset chain with {len(new_line_ids)} lines.")


def _collect_sketch_selection(props):
    selected_points = {int(x) for x in props.sketch_selected_points_str.split(",") if x}
    selected_lines = {int(x) for x in props.sketch_selected_lines_str.split(",") if x}

    for line in props.sketch_lines:
        if line.id in selected_lines:
            selected_points.add(line.start_point_id)
            selected_points.add(line.end_point_id)

    changed = True
    while changed:
        changed = False
        for arc in props.sketch_arcs:
            arc_points = {arc.start_point_id, arc.end_point_id, arc.mid_point_id, arc.center_point_id}
            if arc_points.intersection(selected_points) and not arc_points.issubset(selected_points):
                selected_points.update(arc_points)
                changed = True
        for circle in props.sketch_circles:
            circle_points = {circle.center_point_id, circle.radius_point_id}
            if circle_points.intersection(selected_points) and not circle_points.issubset(selected_points):
                selected_points.update(circle_points)
                changed = True

    selected_arcs = {
        arc.id for arc in props.sketch_arcs
        if {arc.start_point_id, arc.end_point_id, arc.mid_point_id, arc.center_point_id}.issubset(selected_points)
    }
    selected_circles = {
        circle.id for circle in props.sketch_circles
        if {circle.center_point_id, circle.radius_point_id}.issubset(selected_points)
    }

    return selected_points, selected_lines, selected_arcs, selected_circles


def _serialize_sketch_selection(props, selected_points, selected_lines, selected_arcs, selected_circles):
    point_lookup = {pt.id: pt for pt in props.sketch_points}
    line_lookup = {line.id: line for line in props.sketch_lines}
    arc_lookup = {arc.id: arc for arc in props.sketch_arcs}
    circle_lookup = {circle.id: circle for circle in props.sketch_circles}

    points_payload = []
    selected_point_cos = []
    for pid in sorted(selected_points):
        pt = point_lookup.get(pid)
        if not pt:
            continue
        points_payload.append({
            "id": pid,
            "co": [float(pt.co[0]), float(pt.co[1])],
            "is_segment": bool(pt.is_segment),
        })
        selected_point_cos.append(mathutils.Vector((pt.co[0], pt.co[1], 0.0)))

    lines_payload = []
    for lid in sorted(selected_lines):
        line = line_lookup.get(lid)
        if not line:
            continue
        if line.start_point_id not in selected_points or line.end_point_id not in selected_points:
            continue
        lines_payload.append({
            "id": lid,
            "start_point_id": line.start_point_id,
            "end_point_id": line.end_point_id,
            "is_construction": bool(getattr(line, "is_construction", False)),
        })

    arcs_payload = []
    for aid in sorted(selected_arcs):
        arc = arc_lookup.get(aid)
        if not arc:
            continue
        arcs_payload.append({
            "id": aid,
            "center_point_id": arc.center_point_id,
            "start_point_id": arc.start_point_id,
            "end_point_id": arc.end_point_id,
            "mid_point_id": arc.mid_point_id,
            "is_construction": bool(getattr(arc, "is_construction", False)),
        })

    circles_payload = []
    for cid in sorted(selected_circles):
        circle = circle_lookup.get(cid)
        if not circle:
            continue
        circles_payload.append({
            "id": cid,
            "center_point_id": circle.center_point_id,
            "radius_point_id": circle.radius_point_id,
            "is_construction": bool(getattr(circle, "is_construction", False)),
        })

    constraints_payload = []
    for const in props.sketch_constraints:
        try:
            target_ids = [int(x.strip()) for x in const.target_ids_str.split(",") if x.strip()]
        except ValueError:
            continue
        if target_ids and all(tid in selected_points for tid in target_ids):
            constraints_payload.append({
                "type": const.type,
                "target_ids": target_ids,
                "value": float(const.value),
            })

    anchor = [0.0, 0.0]
    if selected_point_cos:
        center = mathutils.Vector((0.0, 0.0, 0.0))
        for co in selected_point_cos:
            center += co
        center /= len(selected_point_cos)
        anchor = [center.x, center.y]

    return {
        "points": points_payload,
        "lines": lines_payload,
        "arcs": arcs_payload,
        "circles": circles_payload,
        "constraints": constraints_payload,
        "anchor": anchor,
    }


def action_copy_selection(op, context, props):
    selected_points, selected_lines, selected_arcs, selected_circles = _collect_sketch_selection(props)
    if not selected_points:
        op.report({'WARNING'}, "Select sketch geometry to copy.")
        return

    payload = _serialize_sketch_selection(props, selected_points, selected_lines, selected_arcs, selected_circles)
    props.sketch_clipboard_json = json.dumps(payload)
    props.sketch_clipboard_has_data = True
    op.report(
        {'INFO'},
        f"Copied {len(payload['points'])} points, {len(payload['lines'])} lines, {len(payload['arcs'])} arcs, {len(payload['circles'])} circles."
    )


def action_paste_selection(op, context, props):
    if not props.sketch_clipboard_json:
        props.sketch_clipboard_has_data = False
        op.report({'WARNING'}, "Sketch clipboard is empty.")
        return

    try:
        payload = json.loads(props.sketch_clipboard_json)
    except Exception:
        props.sketch_clipboard_json = ""
        props.sketch_clipboard_has_data = False
        op.report({'ERROR'}, "Sketch clipboard data is invalid.")
        return

    points_payload = payload.get("points", [])
    if not points_payload:
        op.report({'WARNING'}, "Sketch clipboard has no point data.")
        return

    anchor = payload.get("anchor", [0.0, 0.0])
    if sketch_globals._mouse_pos is not None:
        target_anchor = mathutils.Vector((float(sketch_globals._mouse_pos.x), float(sketch_globals._mouse_pos.y), 0.0))
    else:
        target_anchor = mathutils.Vector((float(anchor[0]) + 1.0, float(anchor[1]) - 1.0, 0.0))
    source_anchor = mathutils.Vector((float(anchor[0]), float(anchor[1]), 0.0))
    delta = target_anchor - source_anchor

    push_history(props)

    max_point_id = max([p.id for p in props.sketch_points] + [0])
    max_line_id = max([l.id for l in props.sketch_lines] + [0])
    max_arc_id = max([a.id for a in props.sketch_arcs] + [0])
    max_circle_id = max([c.id for c in props.sketch_circles] + [0])
    max_constraint_id = max([c.id for c in props.sketch_constraints] + [0])

    point_id_map = {}
    new_point_ids = []
    for point_data in points_payload:
        max_point_id += 1
        point_id_map[int(point_data["id"])] = max_point_id
        new_pt = props.sketch_points.add()
        new_pt.id = max_point_id
        new_pt.co = (
            float(point_data["co"][0]) + delta.x,
            float(point_data["co"][1]) + delta.y,
        )
        new_pt.is_segment = bool(point_data.get("is_segment", False))
        new_point_ids.append(str(max_point_id))

    new_line_ids = []
    for line_data in payload.get("lines", []):
        start_id = point_id_map.get(int(line_data["start_point_id"]))
        end_id = point_id_map.get(int(line_data["end_point_id"]))
        if start_id is None or end_id is None:
            continue
        max_line_id += 1
        new_line = props.sketch_lines.add()
        new_line.id = max_line_id
        new_line.start_point_id = start_id
        new_line.end_point_id = end_id
        new_line.is_construction = bool(line_data.get("is_construction", False))
        new_line_ids.append(str(max_line_id))

    for arc_data in payload.get("arcs", []):
        mapped_ids = {
            "center_point_id": point_id_map.get(int(arc_data["center_point_id"])),
            "start_point_id": point_id_map.get(int(arc_data["start_point_id"])),
            "end_point_id": point_id_map.get(int(arc_data["end_point_id"])),
            "mid_point_id": point_id_map.get(int(arc_data["mid_point_id"])),
        }
        if any(value is None for value in mapped_ids.values()):
            continue
        max_arc_id += 1
        new_arc = props.sketch_arcs.add()
        new_arc.id = max_arc_id
        new_arc.center_point_id = mapped_ids["center_point_id"]
        new_arc.start_point_id = mapped_ids["start_point_id"]
        new_arc.end_point_id = mapped_ids["end_point_id"]
        new_arc.mid_point_id = mapped_ids["mid_point_id"]
        new_arc.is_construction = bool(arc_data.get("is_construction", False))

    for circle_data in payload.get("circles", []):
        center_id = point_id_map.get(int(circle_data["center_point_id"]))
        radius_id = point_id_map.get(int(circle_data["radius_point_id"]))
        if center_id is None or radius_id is None:
            continue
        max_circle_id += 1
        new_circle = props.sketch_circles.add()
        new_circle.id = max_circle_id
        new_circle.center_point_id = center_id
        new_circle.radius_point_id = radius_id
        new_circle.is_construction = bool(circle_data.get("is_construction", False))

    for const_data in payload.get("constraints", []):
        target_ids = [point_id_map.get(int(pid)) for pid in const_data.get("target_ids", [])]
        if any(pid is None for pid in target_ids):
            continue
        max_constraint_id += 1
        new_const = props.sketch_constraints.add()
        new_const.id = max_constraint_id
        new_const.type = const_data.get("type", "FIXED")
        new_const.target_ids_str = ",".join(str(pid) for pid in target_ids)
        new_const.value = float(const_data.get("value", 0.0))

    props.sketch_selected_points_str = ",".join(new_point_ids)
    props.sketch_selected_lines_str = ",".join(new_line_ids)
    props.sketch_selected_point_id = int(new_point_ids[0]) if new_point_ids else -1
    props.sketch_selected_point_id_2 = int(new_point_ids[1]) if len(new_point_ids) > 1 else -1
    props.sketch_selected_line_id = int(new_line_ids[0]) if new_line_ids else -1
    props.sketch_selected_line_id_2 = int(new_line_ids[1]) if len(new_line_ids) > 1 else -1
    props.sketch_clipboard_has_data = True

    solve_gcs_external(props, context)
    update_cad_preview(None, context)
    op.report({'INFO'}, f"Pasted sketch selection at ({target_anchor.x:.3f}, {target_anchor.y:.3f}).")


