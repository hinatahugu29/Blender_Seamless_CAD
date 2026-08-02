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
import gpu
import blf
import math
import mathutils
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from ..core_bridge import get_core
from . import sketch_globals
from .. import utils
from .sketch_finalize import calculate_arc_points, calculate_circle_points



def _transform_coords(coords):
    mat = sketch_globals._reference_matrix if sketch_globals._reference_matrix else mathutils.Matrix.Identity(4)
    res = []
    for v in coords:
        if hasattr(v, 'x'):
            v3d = mat @ mathutils.Vector((v.x, v.y, 0.0))
        else:
            v3d = mat @ mathutils.Vector((v[0], v[1], 0.0))
        res.append((v3d.x, v3d.y, v3d.z))
    return res

def draw_sketch_3d(context, props):
    if not props.is_sketch_active: return

    try:
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    except Exception:
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        
    shader.bind()
    gpu.state.depth_test_set('ALWAYS')
    gpu.state.blend_set('ALPHA')
    try:

        # グリッドの描画
        if getattr(props, "sketch_show_grid", True):
            grid_coords = []
            step = getattr(sketch_globals, '_grid_step', 1.0)
            size = max(10.0, step * 20.0)
            x = -size
            while x <= size:
                grid_coords.append((x, -size, 0.0))
                grid_coords.append((x, size, 0.0))
                x += step
            y = -size
            while y <= size:
                grid_coords.append((-size, y, 0.0))
                grid_coords.append((size, y, 0.0))
                y += step
            
            gpu.state.line_width_set(1.0)
            # グリッドのアルファ値を少し上げて視認性を高める
            shader.uniform_float("color", (1.0, 1.0, 1.0, 0.25))
            batch = batch_for_shader(shader, 'LINES', {"pos": _transform_coords(grid_coords)})
            batch.draw(shader)

        # 原点（面の中心）を強調表示
        o_size = 0.5
        origin_coords = [
            (-o_size, 0.0, 0.0), (o_size, 0.0, 0.0),
            (0.0, -o_size, 0.0), (0.0, o_size, 0.0)
        ]
        gpu.state.line_width_set(3.0)
        shader.uniform_float("color", (1.0, 0.8, 0.0, 0.8)) # オレンジ・イエロー系
        batch_origin = batch_for_shader(shader, 'LINES', {"pos": _transform_coords(origin_coords)})
        batch_origin.draw(shader)

        point_dict = {pt.id: (pt.co[0], pt.co[1], 0.0) for pt in props.sketch_points}
        pt_is_segment = {pt.id: pt.is_segment for pt in props.sketch_points}

        # ホバー中のスナップ座標を優先して取得
        snap_pos = sketch_globals._mouse_pos.copy()
        if props.sketch_hover_point_id >= 0 and props.sketch_hover_point_id in point_dict:
            snap_pos = mathutils.Vector(point_dict[props.sketch_hover_point_id])

        if sketch_globals._axis_lock is not None and sketch_globals._axis_lock_start_co is not None:
            sx, sy, sz = sketch_globals._axis_lock_start_co
            gpu.state.line_width_set(1.5)
            if sketch_globals._axis_lock == 'X':
                shader.uniform_float("color", (1.0, 0.4, 0.4, 0.5))
                batch = batch_for_shader(shader, 'LINES', {"pos": _transform_coords([(sx - 100.0, sy, sz), (sx + 100.0, sy, sz)])})
                batch.draw(shader)
            else:
                shader.uniform_float("color", (0.4, 1.0, 0.4, 0.5))
                batch = batch_for_shader(shader, 'LINES', {"pos": _transform_coords([(sx, sy - 100.0, sz), (sx, sy + 100.0, sz)])})
                batch.draw(shader)

        solid_line_coords = []
        fully_constrained_line_coords = []
        const_line_coords = []
        
        fully_lines = getattr(sketch_globals, "_fully_constrained_lines", set())
        fully_circles = getattr(sketch_globals, "_fully_constrained_circles", set())
        fully_arcs = getattr(sketch_globals, "_fully_constrained_arcs", set())

        for line in props.sketch_lines:
            if line.id == props.sketch_hover_line_id: continue
            if line.id == props.sketch_selected_line_id: continue
            # 円弧を構成する分割セグメント直線はビューポート上での二重描画を避けるためスキップ
            if pt_is_segment.get(line.start_point_id, False) or pt_is_segment.get(line.end_point_id, False):
                continue
            if line.start_point_id in point_dict and line.end_point_id in point_dict:
                if getattr(line, "is_construction", False):
                    p1 = mathutils.Vector(point_dict[line.start_point_id])
                    p2 = mathutils.Vector(point_dict[line.end_point_id])
                    d = (p2 - p1).length
                    num_dashes = max(1, int(d / 0.15))
                    for i in range(num_dashes):
                        t1 = i / num_dashes
                        t2 = (i + 0.5) / num_dashes
                        const_line_coords.append(p1 + (p2 - p1) * t1)
                        const_line_coords.append(p1 + (p2 - p1) * t2)
                else:
                    if line.id in fully_lines:
                        fully_constrained_line_coords.append(point_dict[line.start_point_id])
                        fully_constrained_line_coords.append(point_dict[line.end_point_id])
                    else:
                        solid_line_coords.append(point_dict[line.start_point_id])
                        solid_line_coords.append(point_dict[line.end_point_id])
            
        if solid_line_coords:
            gpu.state.line_width_set(3.0)
            shader.uniform_float("color", (0.0, 0.7, 0.9, 0.9))
            batch = batch_for_shader(shader, 'LINES', {"pos": _transform_coords(solid_line_coords)})
            batch.draw(shader)
        
        if fully_constrained_line_coords:
            gpu.state.line_width_set(3.0)
            shader.uniform_float("color", (0.1, 0.15, 0.2, 0.95)) # 完全拘束された線（ダークブルー）
            batch = batch_for_shader(shader, 'LINES', {"pos": _transform_coords(fully_constrained_line_coords)})
            batch.draw(shader)
        
        if const_line_coords:
            gpu.state.line_width_set(2.0)
            shader.uniform_float("color", (1.0, 0.5, 0.0, 0.8))
            batch = batch_for_shader(shader, 'LINES', {"pos": _transform_coords(const_line_coords)})
            batch.draw(shader)

        # 直線プレビュー線
        if props.sketch_is_drawing_line and props.sketch_draw_start_pt_id in point_dict:
            start_pos = point_dict[props.sketch_draw_start_pt_id]
            m_pos = (snap_pos.x, snap_pos.y, 0.0)
            gpu.state.line_width_set(1.5)
            shader.uniform_float("color", (1.0, 1.0, 1.0, 0.6))
            batch = batch_for_shader(shader, 'LINES', {"pos": _transform_coords([start_pos, m_pos])})
            batch.draw(shader)

        # 円弧プレビュー線
        if props.sketch_pen_mode == 'ARC' and len(sketch_globals._arc_points) > 0:
            p1 = sketch_globals._arc_points[0][0]
            m_pos = mathutils.Vector((snap_pos.x, snap_pos.y, 0.0))
            gpu.state.line_width_set(1.5)
            shader.uniform_float("color", (1.0, 1.0, 1.0, 0.6))
        
            if len(sketch_globals._arc_points) == 1:
                # 始点とマウス位置を結ぶ直線プレビュー
                batch = batch_for_shader(shader, 'LINES', {"pos": _transform_coords([p1, m_pos])})
                batch.draw(shader)
            elif len(sketch_globals._arc_points) == 2:
                # 始点、終点、マウス位置（中間点）を通るテンポラリ円弧のプレビュー
                p2 = sketch_globals._arc_points[1][0]
                temp_arc = calculate_arc_points(p1, p2, m_pos, num_segments=16)
                arc_lines = []
                for i in range(len(temp_arc) - 1):
                    arc_lines.append(temp_arc[i])
                    arc_lines.append(temp_arc[i+1])
                if arc_lines:
                    batch = batch_for_shader(shader, 'LINES', {"pos": _transform_coords(arc_lines)})
                    batch.draw(shader)

        # 確定された円 (sketch_circles) の描画
        circle_lines = []
        fully_constrained_circle_lines = []
        const_circle_lines = []
        for circ in props.sketch_circles:
            if circ.center_point_id in point_dict and circ.radius_point_id in point_dict:
                cp = mathutils.Vector(point_dict[circ.center_point_id])
                rp = mathutils.Vector(point_dict[circ.radius_point_id])
                radius = (rp - cp).length
            
                is_const = getattr(circ, "is_construction", False)
                segs = 64 if is_const else 32
                c_points = calculate_circle_points(cp, radius, num_segments=segs)
                for i in range(len(c_points) - 1):
                    if is_const:
                        if i % 2 == 0:
                            const_circle_lines.append(c_points[i])
                            const_circle_lines.append(c_points[i+1])
                    else:
                        if circ.id in fully_circles:
                            fully_constrained_circle_lines.append(c_points[i])
                            fully_constrained_circle_lines.append(c_points[i+1])
                        else:
                            circle_lines.append(c_points[i])
                            circle_lines.append(c_points[i+1])
                
        if circle_lines:
            gpu.state.line_width_set(3.0)
            shader.uniform_float("color", (0.0, 0.7, 0.9, 0.9))
            batch = batch_for_shader(shader, 'LINES', {"pos": _transform_coords(circle_lines)})
            batch.draw(shader)
        if fully_constrained_circle_lines:
            gpu.state.line_width_set(3.0)
            shader.uniform_float("color", (0.1, 0.15, 0.2, 0.95))
            batch = batch_for_shader(shader, 'LINES', {"pos": _transform_coords(fully_constrained_circle_lines)})
            batch.draw(shader)
        if const_circle_lines:
            gpu.state.line_width_set(2.0)
            shader.uniform_float("color", (1.0, 0.5, 0.0, 0.8))
            batch = batch_for_shader(shader, 'LINES', {"pos": _transform_coords(const_circle_lines)})
            batch.draw(shader)


        # 確定された円弧 (sketch_arcs) の描画
        arc_lines = []
        fully_constrained_arc_lines = []
        const_arc_lines = []
        for arc in props.sketch_arcs:
            if (arc.start_point_id in point_dict and 
                arc.end_point_id in point_dict and 
                arc.mid_point_id in point_dict):
                p1 = mathutils.Vector(point_dict[arc.start_point_id])
                p2 = mathutils.Vector(point_dict[arc.mid_point_id])
                p3 = mathutils.Vector(point_dict[arc.end_point_id])
            
                is_const = getattr(arc, "is_construction", False)
                segs = 32 if is_const else 16
                a_points = calculate_arc_points(p1, p2, p3, num_segments=segs)
                for i in range(len(a_points) - 1):
                    if is_const:
                        if i % 2 == 0:
                            const_arc_lines.append(a_points[i])
                            const_arc_lines.append(a_points[i+1])
                    else:
                        if arc.id in fully_arcs:
                            fully_constrained_arc_lines.append(a_points[i])
                            fully_constrained_arc_lines.append(a_points[i+1])
                        else:
                            arc_lines.append(a_points[i])
                            arc_lines.append(a_points[i+1])
                
        if arc_lines:
            gpu.state.line_width_set(3.0)
            shader.uniform_float("color", (0.0, 0.7, 0.9, 0.9))
            batch = batch_for_shader(shader, 'LINES', {"pos": _transform_coords(arc_lines)})
            batch.draw(shader)
        if fully_constrained_arc_lines:
            gpu.state.line_width_set(3.0)
            shader.uniform_float("color", (0.1, 0.15, 0.2, 0.95))
            batch = batch_for_shader(shader, 'LINES', {"pos": _transform_coords(fully_constrained_arc_lines)})
            batch.draw(shader)
        if const_arc_lines:
            gpu.state.line_width_set(2.0)
            shader.uniform_float("color", (1.0, 0.5, 0.0, 0.8))
            batch = batch_for_shader(shader, 'LINES', {"pos": _transform_coords(const_arc_lines)})
            batch.draw(shader)

        # 円プレビュー線
        if props.sketch_pen_mode == 'CIRCLE' and len(sketch_globals._circle_points) > 0:
            cp = sketch_globals._circle_points[0][0]
            m_pos = mathutils.Vector((snap_pos.x, snap_pos.y, 0.0))
            gpu.state.line_width_set(1.5)
            shader.uniform_float("color", (1.0, 1.0, 1.0, 0.6))
        
            radius = (m_pos - cp).length
            if radius > 1e-4:
                temp_c_points = calculate_circle_points(cp, radius, num_segments=32)
                temp_c_lines = []
                for i in range(len(temp_c_points) - 1):
                    temp_c_lines.append(temp_c_points[i])
                    temp_c_lines.append(temp_c_points[i+1])
                if temp_c_lines:
                    batch = batch_for_shader(shader, 'LINES', {"pos": _transform_coords(temp_c_lines)})
                    batch.draw(shader)
                
                batch_radius = batch_for_shader(shader, 'LINES', {"pos": _transform_coords([cp, m_pos])})
                batch_radius.draw(shader)

        # 半円プレビュー線
        if props.sketch_pen_mode == 'SEMICIRCLE' and len(sketch_globals._semicircle_points) > 0:
            p1 = sketch_globals._semicircle_points[0][0]
            m_pos = mathutils.Vector((snap_pos.x, snap_pos.y, 0.0))
            gpu.state.line_width_set(1.5)
            shader.uniform_float("color", (1.0, 1.0, 1.0, 0.6))
        
            if len(sketch_globals._semicircle_points) == 1:
                batch = batch_for_shader(shader, 'LINES', {"pos": _transform_coords([p1, m_pos])})
                batch.draw(shader)
            elif len(sketch_globals._semicircle_points) == 2:
                p2 = sketch_globals._semicircle_points[1][0]
                batch_diam = batch_for_shader(shader, 'LINES', {"pos": _transform_coords([p1, p2])})
                batch_diam.draw(shader)
            
                d_vec = p2 - p1
                d_len = d_vec.length
                if d_len > 1e-6:
                    c_pos = (p1 + p2) * 0.5
                    n_vec = mathutils.Vector((-d_vec.y, d_vec.x, 0.0)).normalized()
                    side = n_vec.dot(m_pos - c_pos)
                    sign = 1.0 if side >= 0.0 else -1.0
                    p3_pos = c_pos + n_vec * (d_len * 0.5 * sign)
                
                    temp_arc = calculate_arc_points(p1, p3_pos, p2, num_segments=16)
                    arc_lines = []
                    for i in range(len(temp_arc) - 1):
                        arc_lines.append(temp_arc[i])
                        arc_lines.append(temp_arc[i+1])
                    if arc_lines:
                        batch = batch_for_shader(shader, 'LINES', {"pos": _transform_coords(arc_lines)})
                        batch.draw(shader)

        # スロットプレビュー線
        if props.sketch_pen_mode == 'SLOT' and len(sketch_globals._circle_points) > 0:
            c1 = sketch_globals._circle_points[0][0]
            m_pos = mathutils.Vector((snap_pos.x, snap_pos.y, 0.0))
            gpu.state.line_width_set(1.5)
            shader.uniform_float("color", (1.0, 1.0, 1.0, 0.6))
            
            if len(sketch_globals._circle_points) == 1:
                batch = batch_for_shader(shader, 'LINES', {"pos": _transform_coords([c1, m_pos])})
                batch.draw(shader)
            elif len(sketch_globals._circle_points) == 2:
                c2 = sketch_globals._circle_points[1][0]
                batch_axis = batch_for_shader(shader, 'LINES', {"pos": _transform_coords([c1, c2])})
                batch_axis.draw(shader)
                
                v_dir = c2 - c1
                v_len = v_dir.length
                if v_len > 1e-4:
                    proj = c1 + v_dir * ((m_pos - c1).dot(v_dir) / (v_len * v_len))
                    r = (m_pos - proj).length
                else:
                    r = (m_pos - c1).length
                
                if r > 1e-3:
                    v_dir_n = v_dir.normalized()
                    v_perp = mathutils.Vector((-v_dir_n.y, v_dir_n.x, 0.0))
                    p1 = c2 + v_perp * r
                    p2 = c2 - v_perp * r
                    p3 = c1 - v_perp * r
                    p4 = c1 + v_perp * r
                    
                    slot_lines = [p4, p1, p2, p3]
                    
                    arc_l = calculate_arc_points(p3, c1 - v_dir_n * r, p4, num_segments=8)
                    for idx in range(len(arc_l) - 1):
                        slot_lines.append(arc_l[idx])
                        slot_lines.append(arc_l[idx+1])
                    
                    arc_r = calculate_arc_points(p1, c2 + v_dir_n * r, p2, num_segments=8)
                    for idx in range(len(arc_r) - 1):
                        slot_lines.append(arc_r[idx])
                        slot_lines.append(arc_r[idx+1])
                        
                    batch_slot = batch_for_shader(shader, 'LINES', {"pos": _transform_coords(slot_lines)})
                    batch_slot.draw(shader)

        if props.sketch_pen_mode in {'RECTANGLE', 'CENTER_RECT'} and len(sketch_globals._rectangle_points) > 0:
            p1 = sketch_globals._rectangle_points[0]
            p2 = mathutils.Vector((snap_pos.x, snap_pos.y, 0.0))
            if props.sketch_pen_mode == 'CENTER_RECT':
                dx = abs(p2.x - p1.x)
                dy = abs(p2.y - p1.y)
                corners = [
                    mathutils.Vector((p1.x - dx, p1.y - dy, 0.0)),
                    mathutils.Vector((p1.x + dx, p1.y - dy, 0.0)),
                    mathutils.Vector((p1.x + dx, p1.y + dy, 0.0)),
                    mathutils.Vector((p1.x - dx, p1.y + dy, 0.0)),
                ]
            else:
                corners = [
                    mathutils.Vector((p1.x, p1.y, 0.0)),
                    mathutils.Vector((p2.x, p1.y, 0.0)),
                    mathutils.Vector((p2.x, p2.y, 0.0)),
                    mathutils.Vector((p1.x, p2.y, 0.0)),
                ]

            rect_lines = []
            for idx in range(4):
                rect_lines.append(corners[idx])
                rect_lines.append(corners[(idx + 1) % 4])
            gpu.state.line_width_set(1.5)
            shader.uniform_float("color", (1.0, 1.0, 1.0, 0.6))
            batch = batch_for_shader(shader, 'LINES', {"pos": _transform_coords(rect_lines)})
            batch.draw(shader)

        sel_lines = [int(x) for x in props.sketch_selected_lines_str.split(",") if x]
        for sel_line_id in sel_lines:
            line = next((l for l in props.sketch_lines if l.id == sel_line_id), None)
            if line and line.start_point_id in point_dict and line.end_point_id in point_dict:
                gpu.state.line_width_set(4.0)
                shader.uniform_float("color", (0.0, 0.8, 1.0, 1.0))
                batch = batch_for_shader(shader, 'LINES', {"pos": _transform_coords([point_dict[line.start_point_id], point_dict[line.end_point_id]])})
                batch.draw(shader)

        if props.sketch_hover_line_id >= 0:
            line = next((l for l in props.sketch_lines if l.id == props.sketch_hover_line_id), None)
            if line and line.start_point_id in point_dict and line.end_point_id in point_dict:
                gpu.state.line_width_set(5.0)
                shader.uniform_float("color", (1.0, 0.5, 0.0, 1.0))
                batch = batch_for_shader(shader, 'LINES', {"pos": _transform_coords([point_dict[line.start_point_id], point_dict[line.end_point_id]])})
                batch.draw(shader)

        # is_segment Vertex（円弧セグメントの中間点）は緑色の十字描画から除外する
        point_coords = []
        fully_constrained_point_coords = []
        for pt_id, co in point_dict.items():
            if pt_is_segment.get(pt_id, False):
                continue
            is_fully = pt_id in getattr(sketch_globals, "_fully_constrained_pts", set())
            if is_fully:
                fully_constrained_point_coords.append(co)
            else:
                point_coords.append(co)
                
        if point_coords:
            cross_coords = []
            size = 0.04
            for px, py, pz in point_coords:
                cross_coords.append((px - size, py, pz))
                cross_coords.append((px + size, py, pz))
                cross_coords.append((px, py - size, pz))
                cross_coords.append((px, py + size, pz))
        
            gpu.state.line_width_set(2.0)
            shader.uniform_float("color", (0.0, 0.9, 0.2, 1.0))
            batch = batch_for_shader(shader, 'LINES', {"pos": _transform_coords(cross_coords)})
            batch.draw(shader)

        if fully_constrained_point_coords:
            cross_coords = []
            size = 0.04
            for px, py, pz in fully_constrained_point_coords:
                cross_coords.append((px - size, py, pz))
                cross_coords.append((px + size, py, pz))
                cross_coords.append((px, py - size, pz))
                cross_coords.append((px, py + size, pz))
        
            gpu.state.line_width_set(2.0)
            shader.uniform_float("color", (0.1, 0.15, 0.2, 1.0)) # 完全拘束の点（ダークブルー/黒）
            batch = batch_for_shader(shader, 'LINES', {"pos": _transform_coords(cross_coords)})
            batch.draw(shader)

        target_pt_id = props.sketch_hover_point_id
        if target_pt_id >= 0 and target_pt_id in point_dict:
            hover_pos = point_dict[target_pt_id]
            hx, hy, hz = hover_pos
            h_size = 0.06
            box_coords = [
                (hx - h_size, hy - h_size, hz), (hx + h_size, hy - h_size, hz),
                (hx + h_size, hy - h_size, hz), (hx + h_size, hy + h_size, hz),
                (hx + h_size, hy + h_size, hz), (hx - h_size, hy + h_size, hz),
                (hx - h_size, hy + h_size, hz), (hx - h_size, hy - h_size, hz),
            ]
            gpu.state.line_width_set(2.5)
            shader.uniform_float("color", (1.0, 0.4, 0.0, 1.0))
            batch = batch_for_shader(shader, 'LINES', {"pos": _transform_coords(box_coords)})
            batch.draw(shader)

        sel_pts = [int(x) for x in props.sketch_selected_points_str.split(",") if x]
        for sel_id in sel_pts:
            if sel_id in point_dict:
                sel_pos = point_dict[sel_id]
                sx, sy, sz = sel_pos
                s_size = 0.07
                box_coords = [
                    (sx - s_size, sy - s_size, sz), (sx + s_size, sy - s_size, sz),
                    (sx + s_size, sy - s_size, sz), (sx + s_size, sy + s_size, sz),
                    (sx + s_size, sy + s_size, sz), (sx - s_size, sy + s_size, sz),
                    (sx - s_size, sy + s_size, sz), (sx - s_size, sy - s_size, sz),
                ]
                gpu.state.line_width_set(2.5)
                shader.uniform_float("color", (0.0, 0.8, 1.0, 1.0))
                batch = batch_for_shader(shader, 'LINES', {"pos": _transform_coords(box_coords)})
                batch.draw(shader)

        # インファレンスガイドライン（補助点線）の描画
        inf_lines = getattr(sketch_globals, "_inference_lines", [])
        if inf_lines:
            inf_draw_coords = []
            for p_start, p_end in inf_lines:
                d_vec = p_end - p_start
                d_len = d_vec.length
                if d_len > 1e-4:
                    steps = max(1, int(d_len / 0.1))
                    for i in range(steps):
                        t1 = i / steps
                        t2 = (i + 0.5) / steps
                        inf_draw_coords.append(p_start + d_vec * t1)
                        inf_draw_coords.append(p_start + d_vec * t2)
            if inf_draw_coords:
                gpu.state.line_width_set(1.5)
                shader.uniform_float("color", (1.0, 1.0, 1.0, 0.4))
                batch = batch_for_shader(shader, 'LINES', {"pos": _transform_coords(inf_draw_coords)})
                batch.draw(shader)

        # トリムプレビュー表示
        if props.sketch_pen_mode == 'TRIM_EXTEND' and getattr(sketch_globals, "_trim_preview_coords", None) is not None:
            tp1, tp2 = sketch_globals._trim_preview_coords
            gpu.state.line_width_set(4.0)
            shader.uniform_float("color", (1.0, 0.0, 0.0, 0.9))
            batch = batch_for_shader(shader, 'LINES', {"pos": _transform_coords([tp1, tp2])})
            batch.draw(shader)

        # 延長プレビュー表示
        if props.sketch_pen_mode == 'TRIM_EXTEND' and getattr(sketch_globals, "_extend_preview_coords", None) is not None:
            ep1, ep2, _, _ = sketch_globals._extend_preview_coords
            gpu.state.line_width_set(4.0)
            shader.uniform_float("color", (0.0, 0.9, 0.2, 0.9))
            batch = batch_for_shader(shader, 'LINES', {"pos": _transform_coords([ep1, ep2])})
            batch.draw(shader)

        # 中点スナップ表示
        if getattr(sketch_globals, "_midpoint_snap_co", None) is not None:
            m_snap = sketch_globals._midpoint_snap_co
            mx, my, mz = m_snap.x, m_snap.y, 0.0
            size = 0.05
            v1 = (mx, my + size, mz)
            v2 = (mx - size * 0.866, my - size * 0.5, mz)
            v3 = (mx + size * 0.866, my - size * 0.5, mz)
            tri_coords = [v1, v2, v2, v3, v3, v1]
            gpu.state.line_width_set(3.0)
            shader.uniform_float("color", (0.0, 0.9, 0.2, 1.0))
            batch = batch_for_shader(shader, 'LINES', {"pos": _transform_coords(tri_coords)})
            batch.draw(shader)

    finally:
        gpu.state.line_width_set(1.0)
        gpu.state.depth_test_set('LESS')
        gpu.state.blend_set('NONE')
def draw_sketch_2d(context, props):
    if not props.is_sketch_active: return

    font_id = 0
    blf.size(font_id, 14)
    
    try:
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    except Exception:
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    shader.bind()
    gpu.state.blend_set('ALPHA')
    try:
    
        # HUDの背景枠 (画面上部中央に配置)
        hud_w = 320
        hud_h = 120
        cx = context.region.width // 2
        hud_x1 = cx - hud_w // 2
        hud_x2 = cx + hud_w // 2
        hud_y_top = context.region.height - 10
        hud_y_bot = hud_y_top - hud_h
        hud_bg_coords = [
            (hud_x1, hud_y_top), (hud_x2, hud_y_top),
            (hud_x2, hud_y_bot), (hud_x1, hud_y_bot),
        ]
        shader.uniform_float("color", (0.05, 0.05, 0.05, 0.6))
        batch_bg = batch_for_shader(shader, 'TRI_FAN', {"pos": hud_bg_coords})
        batch_bg.draw(shader)
    
        # 2Dテキスト情報 (HUD内に中央寄せ)
        text_x = hud_x1 + 10
        blf.color(font_id, 0.0, 0.8, 1.0, 1.0)
        blf.position(font_id, text_x, hud_y_top - 20, 0)
        blf.draw(font_id, "SEAMLESS CAD - SKETCH MODE V2.0")
    
        blf.color(font_id, 0.9, 0.9, 0.9, 1.0)
        blf.position(font_id, text_x, hud_y_top - 40, 0)
        blf.draw(font_id, f"Pen Mode: {props.sketch_pen_mode}")
    
        blf.position(font_id, text_x, hud_y_top - 60, 0)
        if props.sketch_selected_point_id >= 0 and props.sketch_selected_point_id_2 >= 0:
            blf.draw(font_id, f"Sel Points: ID={props.sketch_selected_point_id} & ID={props.sketch_selected_point_id_2}")
        elif props.sketch_selected_point_id >= 0:
            blf.draw(font_id, f"Sel Point: ID={props.sketch_selected_point_id} (X: {props.sketch_selected_point_x:.3f}, Y: {props.sketch_selected_point_y:.3f})")
        else:
            blf.draw(font_id, "Sel Point: None")
        
        blf.position(font_id, text_x, hud_y_top - 80, 0)
        if sketch_globals._axis_lock:
            blf.color(font_id, 1.0, 0.5, 0.0, 1.0)
            blf.draw(font_id, f"Axis Lock: {sketch_globals._axis_lock}-Axis locked (Shift)")
        else:
            blf.color(font_id, 0.5, 0.5, 0.5, 1.0)
            blf.draw(font_id, "Axis Lock: None (Hold Shift for Ortho)")

        blf.position(font_id, text_x, hud_y_top - 100, 0)
        if props.sketch_pen_mode == 'ARC' and len(sketch_globals._arc_points) > 0:
            blf.color(font_id, 1.0, 0.8, 0.0, 1.0)
            blf.draw(font_id, f"Arc Points: {len(sketch_globals._arc_points)}/3 (Click to set next)")
        elif props.sketch_pen_mode == 'CIRCLE' and len(sketch_globals._circle_points) > 0:
            blf.color(font_id, 1.0, 0.8, 0.0, 1.0)
            blf.draw(font_id, f"Circle Points: {len(sketch_globals._circle_points)}/2 (Click radius to finish)")
        elif props.sketch_pen_mode == 'SEMICIRCLE' and len(sketch_globals._semicircle_points) > 0:
            blf.color(font_id, 1.0, 0.8, 0.0, 1.0)
            blf.draw(font_id, f"Semicircle Points: {len(sketch_globals._semicircle_points)}/3 (Click direction to finish)")
        elif props.sketch_pen_mode in {'RECTANGLE', 'CENTER_RECT'} and len(sketch_globals._rectangle_points) > 0:
            blf.color(font_id, 1.0, 0.8, 0.0, 1.0)
            if props.sketch_pen_mode == 'CENTER_RECT':
                blf.draw(font_id, "Center Rectangle: 1/2 (Click opposite corner to finish)")
            else:
                blf.draw(font_id, "Rectangle: 1/2 (Click opposite corner to finish)")
        else:
            blf.color(font_id, 0.7, 0.7, 0.7, 1.0)
            blf.draw(font_id, "Operation: Click viewport to draw")

        # 矩形選択枠
        if sketch_globals._is_box_selecting and sketch_globals._box_select_start and sketch_globals._box_select_end:
            x1, y1 = sketch_globals._box_select_start
            x2, y2 = sketch_globals._box_select_end
        
            rect_coords = [
                (x1, y1), (x2, y1),
                (x2, y1), (x2, y2),
                (x2, y2), (x1, y2),
                (x1, y2), (x1, y1)
            ]
            shader.bind()
            gpu.state.line_width_set(1.0)
            shader.uniform_float("color", (1.0, 1.0, 1.0, 0.5))
            batch_rect = batch_for_shader(shader, 'LINES', {"pos": [(v[0], v[1]) for v in rect_coords]})
            batch_rect.draw(shader)

        # 軸コンパス
        region = context.region
        rv3d = context.region_data
        if region and rv3d:
            view_mtx = rv3d.view_matrix.to_3x3()
        
            mat = sketch_globals._reference_matrix if sketch_globals._reference_matrix else mathutils.Matrix.Identity(4)
            local_x = (mat.to_3x3() @ mathutils.Vector((1.0, 0.0, 0.0))).normalized()
            local_y = (mat.to_3x3() @ mathutils.Vector((0.0, 1.0, 0.0))).normalized()
            proj_x = view_mtx @ local_x
            proj_y = view_mtx @ local_y
        
            vec_x = mathutils.Vector((proj_x.x, proj_x.y))
            vec_y = mathutils.Vector((proj_y.x, proj_y.y))
        
            if vec_x.length > 1e-4: vec_x = vec_x.normalized() * 40.0
            if vec_y.length > 1e-4: vec_y = vec_y.normalized() * 40.0
        
            origin = mathutils.Vector((80.0, 80.0))
        
            shader.bind()
            gpu.state.line_width_set(3.0)
        
            shader.uniform_float("color", (1.0, 0.2, 0.2, 1.0))
            batch_x = batch_for_shader(shader, 'LINES', {"pos": [(origin.x, origin.y), (origin.x + vec_x.x, origin.y + vec_x.y)]})
            batch_x.draw(shader)
        
            shader.uniform_float("color", (0.2, 1.0, 0.2, 1.0))
            batch_y = batch_for_shader(shader, 'LINES', {"pos": [(origin.x, origin.y), (origin.x + vec_y.x, origin.y + vec_y.y)]})
            batch_y.draw(shader)
        
            blf.size(font_id, 12)
            blf.color(font_id, 1.0, 0.2, 0.2, 1.0)
            blf.position(font_id, origin.x + vec_x.x + 5, origin.y + vec_x.y - 5, 0)
            blf.draw(font_id, "X")
        
            blf.color(font_id, 0.2, 1.0, 0.2, 1.0)
            blf.position(font_id, origin.x + vec_y.x + 5, origin.y + vec_y.y - 5, 0)
            blf.draw(font_id, "Y")
        
            # DISTANCE（寸法）拘束のオーバーレイ表示
            blf.size(font_id, 12)
            # V8.1.5: 寸法駆動スケッチ - このフレームのラベル位置でヒットボックスを再構築する
            sketch_globals._dimension_label_hitboxes = []
            for const in props.sketch_constraints:
                if const.type == 'DISTANCE':
                    try:
                        targets = [int(x.strip()) for x in const.target_ids_str.split(",") if x.strip()]
                    except ValueError:
                        continue
                    if len(targets) == 2:
                        pt1 = next((p for p in props.sketch_points if p.id == targets[0]), None)
                        pt2 = next((p for p in props.sketch_points if p.id == targets[1]), None)
                        if pt1 and pt2:
                            p1_3d = mathutils.Vector((pt1.co[0], pt1.co[1], 0.0))
                            p2_3d = mathutils.Vector((pt2.co[0], pt2.co[1], 0.0))
                            mid_3d = (p1_3d + p2_3d) * 0.5
                            mat = sketch_globals._reference_matrix if sketch_globals._reference_matrix else mathutils.Matrix.Identity(4)
                            mid_3d = mat @ mid_3d

                            mid_2d = view3d_utils.location_3d_to_region_2d(region, rv3d, mid_3d)
                            if mid_2d:
                                blf.color(font_id, 0.0, 0.8, 1.0, 1.0)
                                label = f"📏 {const.value:.3f}"
                                label_x = mid_2d.x - 20
                                label_y = mid_2d.y + 10
                                blf.position(font_id, label_x, label_y, 0)
                                blf.draw(font_id, label)
                                try:
                                    text_w, text_h = blf.dimensions(font_id, label)
                                except Exception:
                                    text_w, text_h = 60.0, 14.0
                                pad = 4.0
                                sketch_globals._dimension_label_hitboxes.append((
                                    const.id,
                                    label_x - pad, label_y - pad,
                                    label_x + text_w + pad, label_y + text_h + pad,
                                ))

    finally:
        gpu.state.line_width_set(1.0)
        gpu.state.blend_set('NONE')
