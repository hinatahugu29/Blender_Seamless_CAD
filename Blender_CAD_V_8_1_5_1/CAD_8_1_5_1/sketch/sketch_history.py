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
from . import sketch_globals
from ..core_bridge import update_cad_preview
from .sketch_solver import solve_gcs_external

def clear_sketch_temp_states(props=None):
    
    sketch_globals._arc_points.clear()
    sketch_globals._circle_points.clear()
    sketch_globals._semicircle_points.clear()
    sketch_globals._rectangle_points.clear()
    sketch_globals._axis_lock = None
    sketch_globals._axis_lock_start_co = None
    sketch_globals._box_select_start = None
    sketch_globals._box_select_end = None
    sketch_globals._is_box_selecting = False
    
    if props:
        props.sketch_is_drawing_line = False
        props.sketch_draw_start_pt_id = -1
        props.sketch_hover_point_id = -1
        props.sketch_hover_line_id = -1

def push_history(props):
    snapshot = {
        'points': [(pt.id, pt.co[0], pt.co[1], pt.is_segment) for pt in props.sketch_points],
        'lines': [(line.id, line.start_point_id, line.end_point_id) for line in props.sketch_lines],
        'circles': [(c.id, c.center_point_id, c.radius_point_id) for c in props.sketch_circles],
        'arcs': [(a.id, a.center_point_id, a.start_point_id, a.end_point_id, a.mid_point_id) for a in props.sketch_arcs],
        'constraints': [(c.id, c.type, c.target_ids_str, c.value) for c in props.sketch_constraints]
    }
    sketch_globals._history_stack.append(snapshot)
    if len(sketch_globals._history_stack) > 50:
        sketch_globals._history_stack.pop(0)

def perform_undo(context, props):
    if not sketch_globals._history_stack:
        return False
        
    snapshot = sketch_globals._history_stack.pop()
    
    props.sketch_points.clear()
    for p_info in snapshot['points']:
        if len(p_info) == 4:
            p_id, px, py, is_seg = p_info
        else:
            p_id, px, py = p_info
            is_seg = False
        pt = props.sketch_points.add()
        pt.id = p_id
        pt.co = (px, py)
        pt.is_segment = is_seg
        
    props.sketch_lines.clear()
    for l_id, sp, ep in snapshot['lines']:
        line = props.sketch_lines.add()
        line.id = l_id
        line.start_point_id = sp
        line.end_point_id = ep
        
    props.sketch_circles.clear()
    if 'circles' in snapshot:
        for c_id, cp, rp in snapshot['circles']:
            c = props.sketch_circles.add()
            c.id = c_id
            c.center_point_id = cp
            c.radius_point_id = rp

    props.sketch_arcs.clear()
    if 'arcs' in snapshot:
        for a_id, cp, sp_id, ep_id, mp_id in snapshot['arcs']:
            a = props.sketch_arcs.add()
            a.id = a_id
            a.center_point_id = cp
            a.start_point_id = sp_id
            a.end_point_id = ep_id
            a.mid_point_id = mp_id
        
    props.sketch_constraints.clear()
    for c_id, c_type, targets, val in snapshot['constraints']:
        c = props.sketch_constraints.add()
        c.id = c_id
        c.type = c_type
        c.target_ids_str = targets
        c.value = val
        
    props.sketch_selected_point_id = -1
    props.sketch_selected_point_id_2 = -1
    props.sketch_selected_line_id = -1
    props.sketch_selected_line_id_2 = -1
    solve_gcs_external(props, context)
    update_cad_preview(None, context)
    return True

