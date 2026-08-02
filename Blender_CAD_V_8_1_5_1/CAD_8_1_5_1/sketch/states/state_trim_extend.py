import mathutils
from .state_base import SketchState
from .. import sketch_globals
from ..sketch_history import push_history
from ..sketch_solver import solve_gcs_external
from ...core_bridge import update_cad_preview
from ..actions.geometry import _line_intersection_with_params, _visible_line_data, _apply_endpoint_to_point

class StateTrimExtend(SketchState):
    def handle_mouse_move(self, event, mouse_pos_3d):
        super().handle_mouse_move(event, mouse_pos_3d)
        
        props = self.props
        sketch_globals._trim_preview_coords = None
        sketch_globals._extend_preview_coords = None
        
        if props.sketch_hover_line_id >= 0:
            target_data = _visible_line_data(props, props.sketch_hover_line_id)
            if target_data:
                target_line, start_pt, end_pt, p1, p2 = target_data
                
                t_trims = []
                t_extends_left = []
                t_extends_right = []
                
                for line in props.sketch_lines:
                    if line.id == target_line.id:
                        continue
                    ref_data = _visible_line_data(props, line.id)
                    if ref_data:
                        _, _, _, p3, p4 = ref_data
                        intersection, t, u = _line_intersection_with_params(p1, p2, p3, p4)
                        if intersection is not None and (-1e-5 <= u <= 1.0 + 1e-5):
                            if 1e-5 < t < 1.0 - 1e-5:
                                t_trims.append((t, intersection))
                            elif t <= 1e-5:
                                t_extends_left.append((t, intersection))
                            elif t >= 1.0 - 1e-5:
                                t_extends_right.append((t, intersection))
                
                v_dir = p2 - p1
                len_sq = v_dir.length_squared
                if len_sq > 1e-6:
                    ap = mouse_pos_3d - p1
                    t_mouse = ap.dot(v_dir) / len_sq
                    t_mouse = max(0.0, min(1.0, t_mouse))
                    
                    if t_trims:
                        t_points = sorted([t for t, _ in t_trims])
                        intervals = [0.0] + t_points + [1.0]
                        for i in range(len(intervals) - 1):
                            t_start = intervals[i]
                            t_end = intervals[i+1]
                            if t_start <= t_mouse <= t_end:
                                cut_p1 = p1 + v_dir * t_start
                                cut_p2 = p1 + v_dir * t_end
                                sketch_globals._trim_preview_coords = (cut_p1, cut_p2)
                                return False
                                
                    dist_to_p1 = (mouse_pos_3d - p1).length
                    dist_to_p2 = (mouse_pos_3d - p2).length
                    
                    if dist_to_p1 <= dist_to_p2:
                        if t_extends_left:
                            best_t, best_inter = max(t_extends_left, key=lambda item: item[0])
                            sketch_globals._extend_preview_coords = (p1, best_inter, "start", best_inter)
                    else:
                        if t_extends_right:
                            best_t, best_inter = min(t_extends_right, key=lambda item: item[0])
                            sketch_globals._extend_preview_coords = (p2, best_inter, "end", best_inter)
                            
        return False

    def handle_left_click_press(self, event, mouse_pos_3d):
        props = self.props
        if props.sketch_hover_line_id >= 0:
            target_data = _visible_line_data(props, props.sketch_hover_line_id)
            if not target_data:
                return None
                
            target_line, start_pt, end_pt, p1, p2 = target_data
            
            if getattr(sketch_globals, "_trim_preview_coords", None) is not None:
                push_history(props)
                
                t_points = []
                for line in props.sketch_lines:
                    if line.id == target_line.id:
                        continue
                    ref_data = _visible_line_data(props, line.id)
                    if ref_data:
                        _, _, _, p3, p4 = ref_data
                        intersection, t, u = _line_intersection_with_params(p1, p2, p3, p4)
                        if intersection is not None and (1e-5 < t < 1.0 - 1e-5) and (-1e-5 <= u <= 1.0 + 1e-5):
                            t_points.append(t)
                
                t_points = sorted(list(set(t_points)))
                intervals = [0.0] + t_points + [1.0]
                
                v_dir = p2 - p1
                len_sq = v_dir.length_squared
                if len_sq > 1e-6:
                    ap = mouse_pos_3d - p1
                    t_mouse = ap.dot(v_dir) / len_sq
                    t_mouse = max(0.0, min(1.0, t_mouse))
                    
                    for i in range(len(intervals) - 1):
                        t_start = intervals[i]
                        t_end = intervals[i+1]
                        if t_start <= t_mouse <= t_end:
                            if t_start == 0.0 and t_end == 1.0:
                                self._delete_line(target_line)
                            elif t_start == 0.0:
                                intersection = p1 + v_dir * t_end
                                _apply_endpoint_to_point(props, target_line, "start_point_id", start_pt, intersection)
                            elif t_end == 1.0:
                                intersection = p1 + v_dir * t_start
                                _apply_endpoint_to_point(props, target_line, "end_point_id", end_pt, intersection)
                            else:
                                inter_start = p1 + v_dir * t_start
                                _apply_endpoint_to_point(props, target_line, "end_point_id", end_pt, inter_start)
                                
                                inter_end = p1 + v_dir * t_end
                                new_line = props.sketch_lines.add()
                                new_line.id = max([l.id for l in props.sketch_lines] + [0]) + 1
                                
                                new_pt = props.sketch_points.add()
                                new_pt.id = max([pt.id for pt in props.sketch_points] + [0]) + 1
                                new_pt.co = (inter_end.x, inter_end.y)
                                new_pt.is_segment = False
                                
                                new_line.start_point_id = new_pt.id
                                new_line.end_point_id = end_pt.id
                            
                            sketch_globals._trim_preview_coords = None
                            solve_gcs_external(props, self.context)
                            update_cad_preview(None, self.context)
                            break
                            
            elif getattr(sketch_globals, "_extend_preview_coords", None) is not None:
                push_history(props)
                _, _, end_type, intersection = sketch_globals._extend_preview_coords
                
                if end_type == "start":
                    _apply_endpoint_to_point(props, target_line, "start_point_id", start_pt, intersection)
                else:
                    _apply_endpoint_to_point(props, target_line, "end_point_id", end_pt, intersection)
                    
                sketch_globals._extend_preview_coords = None
                solve_gcs_external(props, self.context)
                update_cad_preview(None, self.context)
                
        return None

    def _delete_line(self, line):
        props = self.props
        from ..actions.geometry import _is_point_used_elsewhere
        start_id = line.start_point_id
        end_id = line.end_point_id
        
        idx = next((i for i, ln in enumerate(props.sketch_lines) if ln.id == line.id), None)
        if idx is not None:
            props.sketch_lines.remove(idx)
            
        if not _is_point_used_elsewhere(props, start_id, -1):
            p_idx = next((i for i, pt in enumerate(props.sketch_points) if pt.id == start_id), None)
            if p_idx is not None:
                props.sketch_points.remove(p_idx)
        if not _is_point_used_elsewhere(props, end_id, -1):
            p_idx = next((i for i, pt in enumerate(props.sketch_points) if pt.id == end_id), None)
            if p_idx is not None:
                props.sketch_points.remove(p_idx)
