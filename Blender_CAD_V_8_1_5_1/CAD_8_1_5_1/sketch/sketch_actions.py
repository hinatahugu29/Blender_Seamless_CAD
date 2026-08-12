import bpy
import mathutils
import math
from .. import utils
from .sketch_history import push_history, perform_undo
from .sketch_solver import solve_gcs_external, find_arc_by_line_id
from .sketch_finalize import finalize_sketch, calculate_arc_points, calculate_circle_points, is_point_in_polygon

from ..core_bridge import update_cad_preview

from .actions import core, geometry, corner, constraints

import bpy
import mathutils
import math
from .. import utils
from .sketch_history import push_history, perform_undo
from .sketch_solver import solve_gcs_external, find_arc_by_line_id
from .sketch_finalize import finalize_sketch, calculate_arc_points, calculate_circle_points, is_point_in_polygon

from ..core_bridge import update_cad_preview

class SEAMLESS_OT_SketchAction(bpy.types.Operator):
    bl_idname = "seamless.sketch_action"
    bl_label = "Sketch Action"
    bl_description = "Apply action/constraint directly to 2D sketch"
    
    action: bpy.props.StringProperty()
    constraint_id: bpy.props.IntProperty(default=-1)
    
    def execute(self, context):
        props = utils.get_active_props(context)
        if not props: return {'CANCELLED'}
        

        action = self.action
        if action == 'UNDO':
            core.action_undo(self, context, props)
        elif action == 'APPLY':
            core.action_apply(self, context, props)
        elif action == 'CANCEL':
            core.action_cancel(self, context, props)
        elif action == 'CLEAR_SELECTION':
            core.action_clear_selection(self, context, props)
        elif action == 'DELETE_SELECTED':
            geometry.action_delete_selected(self, context, props)
        elif action == 'SELECT_ALL':
            geometry.action_select_all(self, context, props)
        elif action == 'SELECT_CHAIN':
            geometry.action_select_chain(self, context, props)
        elif action == 'COPY_SELECTION':
            geometry.action_copy_selection(self, context, props)
        elif action == 'PASTE_SELECTION':
            geometry.action_paste_selection(self, context, props)
        elif action == 'TOGGLE_CONSTRUCTION':
            geometry.action_toggle_construction(self, context, props)
        elif action == 'MIRROR_X':
            geometry.action_mirror_x(self, context, props)
        elif action == 'MIRROR_Y':
            geometry.action_mirror_y(self, context, props)
        elif action == 'OFFSET_SELECTION':
            geometry.action_offset_selection(self, context, props)
        elif action == 'TRIM_SELECTION':
            geometry.action_trim_selection(self, context, props)
        elif action == 'EXTEND_SELECTION':
            geometry.action_extend_selection(self, context, props)
        elif action == 'CORNER_FILLET':
            corner.action_corner_fillet(self, context, props)
        elif action == 'CORNER_CHAMFER':
            corner.action_corner_chamfer(self, context, props)
        elif action == 'DELETE_CONSTRAINT':
            constraints.action_delete_constraint(self, context, props)
        elif action == 'CONSTRAINT_FIXED':
            constraints.action_constraint_fixed(self, context, props)
        elif action in {'CONSTRAINT_HORIZONTAL', 'CONSTRAINT_VERTICAL'}:
            constraints.action_constraint_horizontal_vertical(self, context, props)
        elif action in {'CONSTRAINT_PARALLEL', 'CONSTRAINT_PERPENDICULAR'}:
            constraints.action_constraint_parallel_perpendicular(self, context, props)
        elif action == 'CONSTRAINT_TANGENT':
            constraints.action_constraint_tangent(self, context, props)
        elif action == 'CONSTRAINT_DISTANCE':
            constraints.action_constraint_distance(self, context, props)
        elif action == 'CONSTRAINT_RADIUS':
            constraints.action_constraint_radius(self, context, props)
        elif action == 'CONSTRAINT_MIDPOINT':
            constraints.action_constraint_midpoint(self, context, props)
        elif action == 'CONSTRAINT_COINCIDENT':
            constraints.action_constraint_coincident_merge(self, context, props)

        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}
