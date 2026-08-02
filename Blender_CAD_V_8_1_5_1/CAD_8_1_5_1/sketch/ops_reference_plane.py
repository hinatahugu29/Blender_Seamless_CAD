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
from bpy_extras.view3d_utils import region_2d_to_origin_3d, region_2d_to_vector_3d

from . import sketch_globals
from .. import utils


class SEAMLESS_OT_select_reference_plane(bpy.types.Operator):
    """Click on a face to set it as the reference plane and start sketching"""

    bl_idname = "seamless.select_reference_plane"
    bl_label = "Sketch on Face"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def modal(self, context, event):
        if event.type in {'ESC', 'RIGHTMOUSE'}:
            context.workspace.status_text_set(None)
            return {'CANCELLED'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            region = context.region
            rv3d = context.region_data
            coord = (event.mouse_region_x, event.mouse_region_y)

            origin = region_2d_to_origin_3d(region, rv3d, coord)
            direction = region_2d_to_vector_3d(region, rv3d, coord)

            col = utils.get_active_collection(context)
            if col:
                from .. import core_bridge

                stack_ptr = core_bridge.get_or_create_stack_ptr(col)
                res = core_bridge.pick_face(stack_ptr, list(origin), list(direction), 0.1)
                if not res:
                    return {'RUNNING_MODAL'}

                lid, px, py, pz, nx, ny, nz = res
                print(f"DEBUG pick_face returned lid: {lid}")

                local_loc = mathutils.Vector((px, py, pz))
                if "@" in lid:
                    try:
                        coord_part = lid.split("@", 1)[1]
                        if "#" in coord_part:
                            coord_part = coord_part.split("#", 1)[0]
                        parts = coord_part.split(";")
                        if len(parts) >= 3:
                            local_loc = mathutils.Vector((float(parts[0]), float(parts[1]), float(parts[2])))
                    except Exception as e:
                        utils.debug_print(f"DEBUG: Failed to parse face center: {e}")

                local_normal = mathutils.Vector((nx, ny, nz)).normalized()

                z_axis = local_normal
                up = mathutils.Vector((0, 0, 1))
                if abs(z_axis.dot(up)) > 0.99:
                    up = mathutils.Vector((0, 1, 0))
                x_axis = up.cross(z_axis).normalized()
                y_axis = z_axis.cross(x_axis).normalized()

                local_mat = mathutils.Matrix.Identity(4)
                local_mat[0][0], local_mat[1][0], local_mat[2][0] = x_axis[0], x_axis[1], x_axis[2]
                local_mat[0][1], local_mat[1][1], local_mat[2][1] = y_axis[0], y_axis[1], y_axis[2]
                local_mat[0][2], local_mat[1][2], local_mat[2][2] = z_axis[0], z_axis[1], z_axis[2]
                local_mat.translation = local_loc

                sketch_globals._reference_matrix = local_mat

                log_msg = (
                    f"[CAD_DEBUG] ops_reference_plane:\n"
                    f"  local_loc = {local_loc}\n"
                    f"  local_normal = {local_normal}\n"
                    f"  x_axis = {x_axis}\n"
                    f"  y_axis = {y_axis}\n"
                    f"  z_axis = {z_axis}\n"
                    f"  matrix =\n{local_mat}\n"
                )
                print(log_msg)
                utils.debug_print(log_msg)
                with open("cad_server_debug.log", "a", encoding="utf-8") as f:
                    f.write(log_msg + "\n")

                context.workspace.status_text_set(None)
                bpy.ops.seamless.start_sketch('INVOKE_DEFAULT')
                return {'FINISHED'}

        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        context.workspace.status_text_set("Click a face to draw sketch on it. Esc/Right-click to cancel.")
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}
