import mathutils
from .state_base import SketchState
from .. import sketch_globals
from ..sketch_history import push_history
from ..sketch_solver import solve_gcs_external
from ..sketch_finalize import calculate_arc_points
from ...core_bridge import update_cad_preview
import math

class StateSemicircle(SketchState):
    def handle_left_click_press(self, event, mouse_pos_3d):
        props = self.props
        x, y = mouse_pos_3d.x, mouse_pos_3d.y
        
        push_history(props)
        current_click_pos = mathutils.Vector((x, y, 0.0))
        hover_id = props.sketch_hover_point_id if props.sketch_hover_point_id >= 0 else None
        sketch_globals._semicircle_points.append((current_click_pos, hover_id))
        
        # 3-click flow:
        # 1st: diameter start, 2nd: diameter end, 3rd: arc side/direction
        if len(sketch_globals._semicircle_points) == 3:
            (p1, id1), (p2, id2), (p3_click, _) = sketch_globals._semicircle_points
            point_dict = {p.id: p.co[:] for p in props.sketch_points}
            if id1 is not None and id1 in point_dict:
                p1 = mathutils.Vector((point_dict[id1][0], point_dict[id1][1], 0.0))
            if id2 is not None and id2 in point_dict:
                p2 = mathutils.Vector((point_dict[id2][0], point_dict[id2][1], 0.0))
                
            c_pos = (p1 + p2) * 0.5

            d_vec = p2 - p1
            d_len = d_vec.length
            if d_len <= 1e-6:
                sketch_globals._semicircle_points = []
                return None

            # Decide arc side from third click.
            n_vec = mathutils.Vector((-d_vec.y, d_vec.x, 0.0)).normalized()
            side = n_vec.dot(p3_click - c_pos)
            sign = 1.0 if side >= 0.0 else -1.0
            p3 = c_pos + n_vec * (d_len * 0.5 * sign)
            
            arc_cos = calculate_arc_points(p1, p3, p2, num_segments=16)
            
            # ID assignment
            start_id = id1 if id1 is not None else self._add_pt(p1)
            end_id = id2 if id2 is not None else self._add_pt(p2)
            mid_id = self._add_pt(p3)
            center_id = self._add_pt(c_pos)
            
            new_arc = props.sketch_arcs.add()
            new_arc.id = max([a.id for a in props.sketch_arcs] + [0]) + 1
            new_arc.center_point_id = center_id
            new_arc.start_point_id = start_id
            new_arc.end_point_id = end_id
            new_arc.mid_point_id = mid_id
            
            const_arc = props.sketch_constraints.add()
            const_arc.id = max([c.id for c in props.sketch_constraints] + [0]) + 1
            const_arc.type = 'ARC'
            const_arc.target_ids_str = f"{start_id},{end_id},{mid_id},{center_id}"
            
            last_pt_id = start_id
            for pt_co in arc_cos[1:-1]:
                new_id = self._add_pt(pt_co, is_seg=True)
                self._add_line(last_pt_id, new_id)
                last_pt_id = new_id
            self._add_line(last_pt_id, end_id)
                
            sketch_globals._semicircle_points = []
            solve_gcs_external(props, self.context)
            update_cad_preview(None, self.context)
            
        return None

    def _add_pt(self, co, is_seg=False):
        new_pt = self.props.sketch_points.add()
        new_id = max([p.id for p in self.props.sketch_points] + [0]) + 1
        new_pt.id = new_id
        new_pt.co = (co.x, co.y)
        new_pt.is_segment = is_seg
        return new_id
        
    def _add_line(self, s, e):
        line = self.props.sketch_lines.add()
        line.id = max([l.id for l in self.props.sketch_lines] + [0]) + 1
        line.start_point_id = s
        line.end_point_id = e
