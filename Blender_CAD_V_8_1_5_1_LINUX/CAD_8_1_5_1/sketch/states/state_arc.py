import mathutils
from .state_base import SketchState
from .. import sketch_globals
from ..sketch_history import push_history
from ..sketch_solver import solve_gcs_external
from ..sketch_finalize import calculate_arc_points
from ...core_bridge import update_cad_preview

class StateArc(SketchState):
    def handle_left_click_press(self, event, mouse_pos_3d):
        props = self.props
        x, y = mouse_pos_3d.x, mouse_pos_3d.y
        
        push_history(props)
        current_click_pos = mathutils.Vector((x, y, 0.0))
        hover_id = props.sketch_hover_point_id if props.sketch_hover_point_id >= 0 else None
        sketch_globals._arc_points.append((current_click_pos, hover_id))
        
        if len(sketch_globals._arc_points) == 3:
            (p1, id1), (p2, id2), (p3, id3) = sketch_globals._arc_points
            point_dict = {p.id: p.co[:] for p in props.sketch_points}
            if id1 is not None and id1 in point_dict:
                p1 = mathutils.Vector((point_dict[id1][0], point_dict[id1][1], 0.0))
            if id2 is not None and id2 in point_dict:
                p2 = mathutils.Vector((point_dict[id2][0], point_dict[id2][1], 0.0))
            if id3 is not None and id3 in point_dict:
                p3 = mathutils.Vector((point_dict[id3][0], point_dict[id3][1], 0.0))
            arc_cos = calculate_arc_points(p1, p2, p3, num_segments=16)
            
            # 外心中心 C の計算
            x1, y1 = p1.x, p1.y
            x2, y2 = p2.x, p2.y
            x3, y3 = p3.x, p3.y
            d = 2.0 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
            if abs(d) > 1e-6:
                xc = ((x1**2 + y1**2) * (y2 - y3) + (x2**2 + y2**2) * (y3 - y1) + (x3**2 + y3**2) * (y1 - y2)) / d
                yc = ((x1**2 + y1**2) * (x3 - x2) + (x2**2 + y2**2) * (x1 - x3) + (x3**2 + y3**2) * (x2 - x1)) / d
                c_pos = mathutils.Vector((xc, yc, 0.0))
            else:
                c_pos = (p1 + p3) * 0.5
            
            # ID割り当て
            start_id = id1 if id1 is not None else self._add_pt(p1)
            mid_id = id2 if id2 is not None else self._add_pt(p2)
            end_id = id3 if id3 is not None else self._add_pt(p3)
            center_id = self._add_pt(c_pos)
            
            # 円弧データを追加
            new_arc = props.sketch_arcs.add()
            new_arc.id = max([a.id for a in props.sketch_arcs] + [0]) + 1
            new_arc.center_point_id = center_id
            new_arc.start_point_id = start_id
            new_arc.end_point_id = end_id
            new_arc.mid_point_id = mid_id
            
            # 幾何拘束 (ARC) の追加
            const_arc = props.sketch_constraints.add()
            const_arc.id = max([c.id for c in props.sketch_constraints] + [0]) + 1
            const_arc.type = 'ARC'
            const_arc.target_ids_str = f"{start_id},{end_id},{mid_id},{center_id}"
            
            # セグメント直線追加
            last_pt_id = start_id
            for pt_co in arc_cos[1:-1]:
                new_id = self._add_pt(pt_co, is_seg=True)
                self._add_line(last_pt_id, new_id)
                last_pt_id = new_id
            self._add_line(last_pt_id, end_id)
                
            sketch_globals._arc_points = []  # リセット
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
