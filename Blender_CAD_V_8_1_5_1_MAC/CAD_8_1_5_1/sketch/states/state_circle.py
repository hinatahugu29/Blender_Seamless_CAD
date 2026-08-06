import mathutils
from .state_base import SketchState
from .. import sketch_globals
from ..sketch_history import push_history
from ..sketch_solver import solve_gcs_external
from ...core_bridge import update_cad_preview

class StateCircle(SketchState):
    def handle_left_click_press(self, event, mouse_pos_3d):
        props = self.props
        x, y = mouse_pos_3d.x, mouse_pos_3d.y
        
        push_history(props)
        current_click_pos = mathutils.Vector((x, y, 0.0))
        hover_id = props.sketch_hover_point_id if props.sketch_hover_point_id >= 0 else None
        sketch_globals._circle_points.append((current_click_pos, hover_id))
        
        if len(sketch_globals._circle_points) == 2:
            (p_center, id_center), (p_radius, id_radius) = sketch_globals._circle_points
            point_dict = {p.id: p.co[:] for p in props.sketch_points}
            if id_center is not None and id_center in point_dict:
                p_center = mathutils.Vector((point_dict[id_center][0], point_dict[id_center][1], 0.0))
            if id_radius is not None and id_radius in point_dict:
                p_radius = mathutils.Vector((point_dict[id_radius][0], point_dict[id_radius][1], 0.0))
            
            center_id = id_center if id_center is not None else self._add_pt(p_center)
            radius_id = id_radius if id_radius is not None else self._add_pt(p_radius)
                
            new_circle = props.sketch_circles.add()
            new_circle.id = max([c.id for c in props.sketch_circles] + [0]) + 1
            new_circle.center_point_id = center_id
            new_circle.radius_point_id = radius_id
            
            const_dist = props.sketch_constraints.add()
            const_dist.id = max([c.id for c in props.sketch_constraints] + [0]) + 1
            const_dist.type = 'DISTANCE'
            const_dist.target_ids_str = f"{center_id},{radius_id}"
            const_dist.value = (p_center - p_radius).length
            
            sketch_globals._circle_points = []
            solve_gcs_external(props, self.context)
            update_cad_preview(None, self.context)
            
        return None

    def _add_pt(self, co):
        new_pt = self.props.sketch_points.add()
        new_id = max([p.id for p in self.props.sketch_points] + [0]) + 1
        new_pt.id = new_id
        new_pt.co = (co.x, co.y)
        return new_id
