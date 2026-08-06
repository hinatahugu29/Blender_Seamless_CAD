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
