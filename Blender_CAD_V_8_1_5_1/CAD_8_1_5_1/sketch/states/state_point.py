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
from ..sketch_history import push_history
from ..sketch_solver import solve_gcs_external
from ...core_bridge import update_cad_preview

class StatePoint(SketchState):
    def handle_left_click_press(self, event, mouse_pos_3d):
        props = self.props
        x, y = mouse_pos_3d.x, mouse_pos_3d.y
        
        push_history(props)
        new_pt = props.sketch_points.add()
        new_id = max([p.id for p in props.sketch_points] + [0]) + 1
        new_pt.id = new_id
        new_pt.co = (x, y)
        props.sketch_selected_point_id = new_id
        props.sketch_selected_point_x = x
        props.sketch_selected_point_y = y
        solve_gcs_external(props, self.context)
        update_cad_preview(None, self.context)
        return None
