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

import mathutils
from .state_base import SketchState
from .. import sketch_globals
from ..sketch_history import push_history
from ..sketch_solver import solve_gcs_external
from ...core_bridge import update_cad_preview


class StateRectangle(SketchState):
    def _find_existing_point(self, co, tolerance=1e-6):
        for pt in self.props.sketch_points:
            if pt.is_segment:
                continue
            if abs(pt.co[0] - co.x) <= tolerance and abs(pt.co[1] - co.y) <= tolerance:
                return pt.id
        return None

    def _create_point(self, co):
        existing_id = self._find_existing_point(co)
        if existing_id is not None:
            return existing_id

        new_pt = self.props.sketch_points.add()
        new_id = max([p.id for p in self.props.sketch_points] + [0]) + 1
        new_pt.id = new_id
        new_pt.co = (co.x, co.y)
        return new_id

    def _add_line(self, start_id, end_id, new_line_ids):
        if start_id == end_id:
            return
        dup = any(
            (line.start_point_id == start_id and line.end_point_id == end_id)
            or (line.start_point_id == end_id and line.end_point_id == start_id)
            for line in self.props.sketch_lines
        )
        if dup:
            return
        line = self.props.sketch_lines.add()
        line.id = max([l.id for l in self.props.sketch_lines] + [0]) + 1
        line.start_point_id = start_id
        line.end_point_id = end_id
        new_line_ids.append(line.id)

    def _add_axis_constraint(self, const_type, start_id, end_id):
        target_str = f"{start_id},{end_id}"
        target_str_rev = f"{end_id},{start_id}"
        dup = any(
            c.type == const_type and c.target_ids_str in {target_str, target_str_rev}
            for c in self.props.sketch_constraints
        )
        if dup:
            return
        const = self.props.sketch_constraints.add()
        const.id = max([c.id for c in self.props.sketch_constraints] + [0]) + 1
        const.type = const_type
        const.target_ids_str = target_str
        const.value = 0.0

    def _commit_rectangle(self, p1, p2, center_mode=False):
        if center_mode:
            center = p1
            dx = abs(p2.x - center.x)
            dy = abs(p2.y - center.y)
            if dx <= 1e-6 or dy <= 1e-6:
                return False
            corners = [
                mathutils.Vector((center.x - dx, center.y - dy, 0.0)),
                mathutils.Vector((center.x + dx, center.y - dy, 0.0)),
                mathutils.Vector((center.x + dx, center.y + dy, 0.0)),
                mathutils.Vector((center.x - dx, center.y + dy, 0.0)),
            ]
        else:
            if abs(p2.x - p1.x) <= 1e-6 or abs(p2.y - p1.y) <= 1e-6:
                return False
            corners = [
                mathutils.Vector((p1.x, p1.y, 0.0)),
                mathutils.Vector((p2.x, p1.y, 0.0)),
                mathutils.Vector((p2.x, p2.y, 0.0)),
                mathutils.Vector((p1.x, p2.y, 0.0)),
            ]

        push_history(self.props)

        point_ids = [self._create_point(corner) for corner in corners]
        new_line_ids = []
        for idx in range(4):
            self._add_line(point_ids[idx], point_ids[(idx + 1) % 4], new_line_ids)

        self._add_axis_constraint('HORIZONTAL', point_ids[0], point_ids[1])
        self._add_axis_constraint('VERTICAL', point_ids[1], point_ids[2])
        self._add_axis_constraint('HORIZONTAL', point_ids[2], point_ids[3])
        self._add_axis_constraint('VERTICAL', point_ids[3], point_ids[0])

        self.props.sketch_selected_points_str = ",".join(str(pid) for pid in point_ids)
        self.props.sketch_selected_lines_str = ",".join(str(lid) for lid in new_line_ids)
        self.props.sketch_selected_point_id = point_ids[0] if point_ids else -1
        self.props.sketch_selected_point_id_2 = point_ids[1] if len(point_ids) > 1 else -1
        self.props.sketch_selected_line_id = new_line_ids[0] if new_line_ids else -1
        self.props.sketch_selected_line_id_2 = new_line_ids[1] if len(new_line_ids) > 1 else -1
        self.props.sketch_selected_point_x = corners[0].x
        self.props.sketch_selected_point_y = corners[0].y

        solve_gcs_external(self.props, self.context)
        update_cad_preview(None, self.context)
        return True

    def handle_left_click_press(self, event, mouse_pos_3d):
        if not sketch_globals._rectangle_points:
            sketch_globals._rectangle_points = [mathutils.Vector((mouse_pos_3d.x, mouse_pos_3d.y, 0.0))]
            sketch_globals._axis_lock_start_co = sketch_globals._rectangle_points[0].copy()
            update_cad_preview(None, self.context)
            return None

        start = sketch_globals._rectangle_points[0]
        end = mathutils.Vector((mouse_pos_3d.x, mouse_pos_3d.y, 0.0))
        center_mode = self.props.sketch_pen_mode == 'CENTER_RECT'
        created = self._commit_rectangle(start, end, center_mode=center_mode)
        sketch_globals._rectangle_points.clear()
        sketch_globals._axis_lock_start_co = None
        if not created:
            return None
        return None

    def handle_right_click(self, event):
        if sketch_globals._rectangle_points:
            sketch_globals._rectangle_points.clear()
            sketch_globals._axis_lock_start_co = None
            update_cad_preview(None, self.context)
            return None
        return 'SELECT'
