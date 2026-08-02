import mathutils
from .state_base import SketchState
from .. import sketch_globals
from ..sketch_history import push_history
from ..sketch_solver import solve_gcs_external
from ...core_bridge import update_cad_preview

class StateLine(SketchState):
    def handle_left_click_press(self, event, mouse_pos_3d):
        props = self.props
        x, y = mouse_pos_3d.x, mouse_pos_3d.y
        
        push_history(props)
        if props.sketch_is_drawing_line:
            if props.sketch_hover_point_id >= 0:
                target_id = props.sketch_hover_point_id
            else:
                new_pt = props.sketch_points.add()
                target_id = max([p.id for p in props.sketch_points] + [0]) + 1
                new_pt.id = target_id
                new_pt.co = (x, y)
                
            if props.sketch_draw_start_pt_id != target_id:
                dup = any(
                    (l.start_point_id == props.sketch_draw_start_pt_id and l.end_point_id == target_id) or
                    (l.start_point_id == target_id and l.end_point_id == props.sketch_draw_start_pt_id)
                    for l in props.sketch_lines
                )
                if not dup:
                    line = props.sketch_lines.add()
                    line.id = max([l.id for l in props.sketch_lines] + [0]) + 1
                    line.start_point_id = props.sketch_draw_start_pt_id
                    line.end_point_id = target_id
                    
                    # --- 4. 自動水平/垂直拘束 (Auto-Constraint) ---
                    pt1 = next((p for p in props.sketch_points if p.id == props.sketch_draw_start_pt_id), None)
                    pt2 = next((p for p in props.sketch_points if p.id == target_id), None)
                    if pt1 and pt2:
                        dx = abs(pt1.co[0] - pt2.co[0])
                        dy = abs(pt1.co[1] - pt2.co[1])
                        import math
                        angle = math.atan2(dy, dx)
                        
                        if angle < 0.087: # 約5度
                            const = props.sketch_constraints.add()
                            const.id = max([c.id for c in props.sketch_constraints] + [0]) + 1
                            const.type = 'HORIZONTAL'
                            const.target_ids_str = f"{pt1.id},{pt2.id}"
                            const.value = 0.0
                        elif angle > 1.483: # 90度 - 5度
                            const = props.sketch_constraints.add()
                            const.id = max([c.id for c in props.sketch_constraints] + [0]) + 1
                            const.type = 'VERTICAL'
                            const.target_ids_str = f"{pt1.id},{pt2.id}"
                            const.value = 0.0
                            
                    solve_gcs_external(props, self.context)
                    
            props.sketch_draw_start_pt_id = target_id
            sketch_globals._axis_lock_start_co = mathutils.Vector((x, y, 0.0))
        else:
            if props.sketch_hover_point_id >= 0:
                props.sketch_draw_start_pt_id = props.sketch_hover_point_id
            else:
                new_pt = props.sketch_points.add()
                new_id = max([p.id for p in props.sketch_points] + [0]) + 1
                new_pt.id = new_id
                new_pt.co = (x, y)
                props.sketch_draw_start_pt_id = new_id
            props.sketch_is_drawing_line = True
            sketch_globals._axis_lock_start_co = mathutils.Vector((x, y, 0.0))
        update_cad_preview(None, self.context)
        return None
        
    def handle_right_click(self, event):
        if self.props.sketch_is_drawing_line:
            self.props.sketch_is_drawing_line = False
            self.props.sketch_draw_start_pt_id = -1
            sketch_globals._axis_lock_start_co = None
            return None # 連続描画をキャンセルするだけでSELECTには戻らない
        sketch_globals._axis_lock_start_co = None
        return 'SELECT'
