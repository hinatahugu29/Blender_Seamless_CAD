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

class SketchState:
    def __init__(self, context, props, sketch_op):
        self.context = context
        self.props = props
        self.sketch_op = sketch_op

    def handle_mouse_move(self, event, mouse_pos_3d):
        hit_pos = mouse_pos_3d
        props = self.props
        p_2d = mathutils.Vector((hit_pos.x, hit_pos.y, 0.0))
        
        # --- HOVER LOGIC INJECTED FROM V5 ---
        from bpy_extras import view3d_utils
        from .. import sketch_globals
        
        region = self.context.region
        rv3d = self.context.region_data
        
        mat = sketch_globals._reference_matrix if sketch_globals._reference_matrix else mathutils.Matrix.Identity(4)
        world_hit = mat @ mathutils.Vector((hit_pos.x, hit_pos.y, 0.0))
        
        # 画面上の15ピクセルが3D空間上で何メートルになるか計算
        pos2_3d = view3d_utils.region_2d_to_location_3d(region, rv3d, (event.mouse_region_x + 15, event.mouse_region_y), world_hit)
        
        if pos2_3d:
            dynamic_threshold = (world_hit - pos2_3d).length
        else:
            dynamic_threshold = 0.25
            
        # ホバー判定 (Vertex)
        props.sketch_hover_point_id = -1
        hover_dist_threshold = dynamic_threshold  # ピクセルベースの動的スナップ範囲
        for pt in props.sketch_points:
            if pt.is_segment:
                continue
            pt_3d = mathutils.Vector((pt.co[0], pt.co[1], 0.0))
            if (p_2d - pt_3d).length < hover_dist_threshold:
                props.sketch_hover_point_id = pt.id
                break
                
        # ホバー判定 (円周)
        if props.sketch_hover_point_id < 0:
            min_circle_dist = dynamic_threshold * 0.8 # スナップ距離を動的に
            best_circle_pt_id = -1
            for circ in props.sketch_circles:
                center_pt = next((p for p in props.sketch_points if p.id == circ.center_point_id), None)
                radius_pt = next((p for p in props.sketch_points if p.id == circ.radius_point_id), None)
                if center_pt and radius_pt:
                    cp = mathutils.Vector((center_pt.co[0], center_pt.co[1], 0.0))
                    rp = mathutils.Vector((radius_pt.co[0], radius_pt.co[1], 0.0))
                    radius = (rp - cp).length
                    dist_to_center = (p_2d - cp).length
                    dist_to_circumference = abs(dist_to_center - radius)
                    if dist_to_circumference < min_circle_dist:
                        min_circle_dist = dist_to_circumference
                        best_circle_pt_id = circ.radius_point_id
                        
            if best_circle_pt_id >= 0:
                props.sketch_hover_point_id = best_circle_pt_id
                
        # ホバー判定 (辺)
        props.sketch_hover_line_id = -1
        if props.sketch_hover_point_id < 0:
            min_line_dist = dynamic_threshold * 0.6
            for line in props.sketch_lines:
                pt1 = next((p for p in props.sketch_points if p.id == line.start_point_id), None)
                pt2 = next((p for p in props.sketch_points if p.id == line.end_point_id), None)
                if pt1 and pt2:
                    if pt1.is_segment or pt2.is_segment:
                        continue
                    a = mathutils.Vector((pt1.co[0], pt1.co[1], 0.0))
                    b = mathutils.Vector((pt2.co[0], pt2.co[1], 0.0))
                    ab = b - a
                    if ab.length_squared > 1e-6:
                        ap = p_2d - a
                        t_val = ap.dot(ab) / ab.length_squared
                        t_val = max(0.0, min(1.0, t_val))
                        closest = a + t_val * ab
                        dist = (p_2d - closest).length
                        if dist < min_line_dist:
                            min_line_dist = dist
                            props.sketch_hover_line_id = line.id
        
        # インファレンススナップ（一時ガイドライン）
        sketch_globals._inference_lines = []
        if props.sketch_pen_mode != 'SELECT' and props.sketch_hover_point_id < 0:
            snap_dist_threshold = dynamic_threshold * 0.6
            snap_x_co = None
            snap_y_co = None
            ref_pt_x = None
            ref_pt_y = None
            
            for pt in props.sketch_points:
                if pt.is_segment:
                    continue
                # X方向が揃っているか
                dx = abs(p_2d.x - pt.co[0])
                if dx < snap_dist_threshold:
                    snap_x_co = pt.co[0]
                    ref_pt_x = pt
                    
                # Y方向が揃っているか
                dy = abs(p_2d.y - pt.co[1])
                if dy < snap_dist_threshold:
                    snap_y_co = pt.co[1]
                    ref_pt_y = pt
            
            if snap_x_co is not None:
                sketch_globals._mouse_pos.x = snap_x_co
                p_start = mathutils.Vector((snap_x_co, ref_pt_x.co[1], 0.0))
                p_end = mathutils.Vector((snap_x_co, sketch_globals._mouse_pos.y, 0.0))
                sketch_globals._inference_lines.append((p_start, p_end))
                
            if snap_y_co is not None:
                sketch_globals._mouse_pos.y = snap_y_co
                p_start = mathutils.Vector((ref_pt_y.co[0], snap_y_co, 0.0))
                p_end = mathutils.Vector((sketch_globals._mouse_pos.x, snap_y_co, 0.0))
                sketch_globals._inference_lines.append((p_start, p_end))

        # 中点スナップ判定 (Midpoint Snap)
        sketch_globals._midpoint_snap_co = None
        if props.sketch_hover_point_id < 0:
            min_midpoint_dist = dynamic_threshold * 0.8
            best_mid_co = None
            for line in props.sketch_lines:
                pt1 = next((p for p in props.sketch_points if p.id == line.start_point_id), None)
                pt2 = next((p for p in props.sketch_points if p.id == line.end_point_id), None)
                if pt1 and pt2:
                    if pt1.is_segment or pt2.is_segment:
                        continue
                    a = mathutils.Vector((pt1.co[0], pt1.co[1], 0.0))
                    b = mathutils.Vector((pt2.co[0], pt2.co[1], 0.0))
                    mid = (a + b) * 0.5
                    dist = (p_2d - mid).length
                    if dist < min_midpoint_dist:
                        min_midpoint_dist = dist
                        best_mid_co = mid
            
            if best_mid_co is not None:
                sketch_globals._midpoint_snap_co = best_mid_co
                sketch_globals._mouse_pos = best_mid_co

        # --- END HOVER LOGIC ---
        return False
        
    def handle_left_click_press(self, event, mouse_pos_3d):
        return None
        
    def handle_left_click_release(self, event, mouse_pos_3d):
        return None
        
    def handle_right_click(self, event):
        if self.props.sketch_pen_mode != 'SELECT':
            return 'SELECT'
        return None
