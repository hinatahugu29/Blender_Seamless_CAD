import mathutils
from .state_base import SketchState
from ..sketch_history import push_history
from ..sketch_solver import solve_gcs_external
from ...core_bridge import update_cad_preview
import bpy

class StateFillet(SketchState):
    def handle_left_click_press(self, event, mouse_pos_3d):
        props = self.props
        
        if props.sketch_hover_point_id >= 0:
            bpy.ops.seamless.sketch_action('INVOKE_DEFAULT', action='CORNER_FILLET')
        elif props.sketch_selected_line_id >= 0 and props.sketch_selected_line_id_2 >= 0:
            bpy.ops.seamless.sketch_action('INVOKE_DEFAULT', action='CORNER_FILLET')
            
        return None
