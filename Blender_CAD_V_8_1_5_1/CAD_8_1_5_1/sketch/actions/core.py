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
import math
from ... import utils
from ..sketch_history import push_history, perform_undo
from ..sketch_solver import solve_gcs_external, find_arc_by_line_id
from ..sketch_finalize import finalize_sketch, calculate_arc_points, calculate_circle_points, is_point_in_polygon

from ...core_bridge import update_cad_preview


def action_undo(op, context, props):
    if perform_undo(context, props):
        op.report({'INFO'}, "Undo completed.")
    else:
        op.report({'INFO'}, "No undo history available.")
        

def action_apply(op, context, props):
    editing_uuid = getattr(props, "sketch_editing_uuid", "")
    if editing_uuid:
        # V8.1.5: Edit Sketchで再編集中 -> in-place更新(既存primitiveのuuidを維持し、
        # 下流のREVOLVE/EXTRUDE等のtarget_uuid参照を壊さない)
        from ..sketch_snapshot import finalize_sketch_edit_inplace
        finalize_sketch_edit_inplace(op, context, props, editing_uuid)
        props.sketch_editing_uuid = ""
    else:
        finalize_sketch(context, props)
        op.report({'INFO'}, "2D Sketch finalized and mesh created.")
    props.is_sketch_active = False
    pass # Handlers are managed by gpu_manager.py


def action_cancel(op, context, props):
    props.sketch_points.clear()
    props.sketch_lines.clear()
    props.sketch_arcs.clear()
    props.sketch_circles.clear()
    props.sketch_constraints.clear()
    props.is_sketch_active = False
    # V8.1.5: 編集セッションをキャンセルした場合、元のprimitive/スナップショットは
    # 一切変更していないので、編集状態フラグを外すだけで安全に元に戻る。
    props.sketch_editing_uuid = ""
    pass # Handlers are managed by gpu_manager.py
    update_cad_preview(None, context)
    op.report({'INFO'}, "2D Sketch cancelled.")
    

def action_clear_selection(op, context, props):
    props.sketch_selected_points_str = ""
    props.sketch_selected_lines_str = ""
    props.sketch_selected_point_id = -1
    props.sketch_selected_point_id_2 = -1
    props.sketch_selected_line_id = -1
    props.sketch_selected_line_id_2 = -1
    op.report({'INFO'}, "Selection cleared.")
    
