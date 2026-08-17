import mathutils
import time
from .state_base import SketchState
from .. import sketch_globals
from ..sketch_solver import solve_gcs_external
from ...core_bridge import update_cad_preview

class StateSelect(SketchState):
    def handle_mouse_move(self, event, mouse_pos_3d):
        super().handle_mouse_move(event, mouse_pos_3d)
        hit_pos = mouse_pos_3d
        props = self.props
        context = self.context
        
        # --- DRAG LOGIC INJECTED FROM V5 ---
        # ドラッグ移動
        if self.sketch_op._is_dragging and getattr(self.sketch_op, "_drag_point_ids", None):
            # 解決失敗時のロールバック用に、このドラッグ移動を実行する前の状態をバックアップ
            backup_coords = {pt.id: pt.co[:] for pt in props.sketch_points}
            backup_constraints = {c.id: c.value for c in props.sketch_constraints}
            
            # 前フレームからの変位（delta）を計算する
            last_mouse = getattr(sketch_globals, "_last_mouse_pos", None)
            if last_mouse is None:
                last_mouse = hit_pos.copy()
                sketch_globals._last_mouse_pos = last_mouse
                
            delta = hit_pos - last_mouse
            drag_ids = self.sketch_op._drag_point_ids
            
            is_multi_drag = len(drag_ids) >= 2
            
            if is_multi_drag:
                # 複数移動: 全対象頂点をdelta分平行移動
                for pt_id in drag_ids:
                    pt = next((p for p in props.sketch_points if p.id == pt_id), None)
                    if pt:
                        pt.co[0] += delta.x
                        pt.co[1] += delta.y
            else:
                # 単一移動: マウス位置に直接吸着
                drag_pt_id = drag_ids[0]
                pt = next((p for p in props.sketch_points if p.id == drag_pt_id), None)
                if pt:
                    pt.co = (hit_pos.x, hit_pos.y)
                    
            # 選択中の点の座標プロパティ表示を代表点で更新
            drag_pt = next((p for p in props.sketch_points if p.id == self.sketch_op._drag_point_id), None)
            if drag_pt:
                props.sketch_selected_point_x = drag_pt.co[0]
                props.sketch_selected_point_y = drag_pt.co[1]

            # 連動移動（円の中心を移動したが半径点が未選択の場合、半径点も移動）
            for circ in props.sketch_circles:
                if circ.center_point_id in drag_ids and circ.radius_point_id not in drag_ids:
                    r_pt = next((p for p in props.sketch_points if p.id == circ.radius_point_id), None)
                    if r_pt:
                        r_pt.co[0] += delta.x
                        r_pt.co[1] += delta.y

            # 円弧/半円の中心を移動したが、その構成頂点が未選択の場合、トポロジー共有していないものを連動移動
            for arc in props.sketch_arcs:
                if arc.center_point_id in drag_ids:
                    connected_endpoints = set()
                    for l in props.sketch_lines:
                        connected_endpoints.add(l.start_point_id)
                        connected_endpoints.add(l.end_point_id)
                    for a in props.sketch_arcs:
                        if a.id != arc.id:
                            connected_endpoints.add(a.start_point_id)
                            connected_endpoints.add(a.end_point_id)
                            
                    for sub_id in (arc.start_point_id, arc.end_point_id, arc.mid_point_id):
                        if sub_id not in drag_ids:
                            if sub_id == arc.mid_point_id or sub_id not in connected_endpoints:
                                sub_pt = next((p for p in props.sketch_points if p.id == sub_id), None)
                                if sub_pt:
                                    sub_pt.co[0] += delta.x
                                    sub_pt.co[1] += delta.y

            # 円の半径決定点を単独ドラッグしている場合、距離拘束の値を動的に更新する
            for circ in props.sketch_circles:
                if circ.radius_point_id in drag_ids and circ.center_point_id not in drag_ids:
                    center_pt = next((p for p in props.sketch_points if p.id == circ.center_point_id), None)
                    if center_pt:
                        c_co = mathutils.Vector((center_pt.co[0], center_pt.co[1], 0.0))
                        new_radius = (hit_pos - c_co).length
                        for const in props.sketch_constraints:
                            if const.type == 'DISTANCE':
                                targets = [int(x.strip()) for x in const.target_ids_str.split(",") if x.strip()]
                                if len(targets) == 2 and (
                                    (targets[0] == circ.center_point_id and targets[1] == circ.radius_point_id) or
                                    (targets[0] == circ.radius_point_id and targets[1] == circ.center_point_id)
                                ):
                                    const.value = new_radius
                                    break
                                    
            # フィレット円弧の中間点を単独ドラッグしている場合、半径拘束(DISTANCE)の値を動的に更新する
            for arc in props.sketch_arcs:
                if arc.mid_point_id in drag_ids and arc.center_point_id not in drag_ids:
                    center_pt = next((p for p in props.sketch_points if p.id == arc.center_point_id), None)
                    if center_pt:
                        c_co = mathutils.Vector((center_pt.co[0], center_pt.co[1], 0.0))
                        new_radius = (hit_pos - c_co).length
                        for const in props.sketch_constraints:
                            if const.type == 'DISTANCE':
                                targets = [int(x.strip()) for x in const.target_ids_str.split(",") if x.strip()]
                                if len(targets) == 2 and (
                                    (targets[0] == arc.center_point_id and targets[1] == arc.mid_point_id) or
                                    (targets[0] == arc.mid_point_id and targets[1] == arc.center_point_id)
                                ):
                                    const.value = new_radius
                                    props.sketch_fillet_radius = new_radius
                                    break
            
            # マウス前フレーム座標の更新
            sketch_globals._last_mouse_pos = hit_pos.copy()
            
            # 20ms（約50fps）未満の間隔での高頻度な解決処理をスキップ（スロットリング）
            now = time.time()
            last_time = getattr(self.sketch_op, "_last_solve_time", 0.0)
            if now - last_time >= 0.02:
                self.sketch_op._last_solve_time = now
                if is_multi_drag:
                    # 複数移動時は特定の代表点を強制ワープさせずに解決
                    success = solve_gcs_external(props, context)
                else:
                    # 単一移動時は代表点をマウス位置に固定して解決（吸着力維持）
                    success = solve_gcs_external(props, context, self.sketch_op._drag_point_id, hit_pos)
                    
                if not success:
                    # 解決失敗時は、ドラッグ直前の健全な状態（座標・拘束値）に復元する
                    for pt_id, co in backup_coords.items():
                        pt = next((p for p in props.sketch_points if p.id == pt_id), None)
                        if pt:
                            pt.co = co
                    for c_id, val in backup_constraints.items():
                        const = next((c for c in props.sketch_constraints if c.id == c_id), None)
                        if const:
                            const.value = val
                else:
                    update_cad_preview(None, context)
        
        # --- END DRAG LOGIC ---
        return False

    def _cursor_co(self, x, y):
        """ドラッグ差分の基準にする「実際のカーソル位置」。

        modal_sketch はクリック時、ホバー中の頂点があると渡してくる座標を
        その頂点の座標へ差し替える(スナップ)。それをそのまま
        _last_mouse_pos に入れると、次の MOUSEMOVE で計算する
        delta = 生カーソル - 頂点座標 となり、基準がずれる。
        ホバー判定は画面上15ピクセルまで拾うので、頂点の中心をぴったり
        掴まなかったぶんだけ図形が1フレーム目で飛ぶ。

        _mouse_pos には差し替え前のカーソル位置が入っているのでそれを使う。
        取れなければ渡された座標にそのまま従う。
        """
        cursor = getattr(sketch_globals, "_mouse_pos", None)
        if cursor is None:
            return mathutils.Vector((x, y, 0.0))
        return mathutils.Vector((cursor.x, cursor.y, 0.0))

    def _get_selected(self, props, prop_name):
        s = getattr(props, prop_name)
        return [int(x) for x in s.split(",") if x]

    def _set_selected(self, props, prop_name, ids):
        setattr(props, prop_name, ",".join(map(str, ids)))
        
        # 後方互換性のため、最初の2つを id と id_2 にセット
        if prop_name == 'sketch_selected_points_str':
            props.sketch_selected_point_id = ids[0] if len(ids) > 0 else -1
            props.sketch_selected_point_id_2 = ids[1] if len(ids) > 1 else -1
        elif prop_name == 'sketch_selected_lines_str':
            props.sketch_selected_line_id = ids[0] if len(ids) > 0 else -1
            props.sketch_selected_line_id_2 = ids[1] if len(ids) > 1 else -1

    def handle_left_click_press(self, event, mouse_pos_3d):
        props = self.props
        x, y = mouse_pos_3d.x, mouse_pos_3d.y
        
        sel_pts = self._get_selected(props, 'sketch_selected_points_str')
        sel_lines = self._get_selected(props, 'sketch_selected_lines_str')
        
        # 複数ドラッグ移動用の対象頂点リスト
        drag_point_ids = []
        
        if props.sketch_hover_point_id >= 0:
            pid = props.sketch_hover_point_id
            if event.shift:
                if pid in sel_pts:
                    sel_pts.remove(pid)
                else:
                    sel_pts.append(pid)
                self._set_selected(props, 'sketch_selected_points_str', sel_pts)
                self._set_selected(props, 'sketch_selected_lines_str', sel_lines)
            else:
                self.sketch_op._is_dragging = True
                self.sketch_op._drag_point_id = pid
                
                # すでに選択リストに含まれている頂点をドラッグした場合は選択を維持
                if pid not in sel_pts:
                    sel_pts = [pid]
                    sel_lines = []
                    self._set_selected(props, 'sketch_selected_points_str', sel_pts)
                    self._set_selected(props, 'sketch_selected_lines_str', sel_lines)
                
                # 選択されているすべての点および選択された線の端点をドラッグ対象に収集
                drag_pts_set = set(sel_pts)
                for lid in sel_lines:
                    line = next((l for l in props.sketch_lines if l.id == lid), None)
                    if line:
                        drag_pts_set.add(line.start_point_id)
                        drag_pts_set.add(line.end_point_id)
                self.sketch_op._drag_point_ids = list(drag_pts_set)
                
                for pt in props.sketch_points:
                    if pt.id == pid:
                        props.sketch_selected_point_x = pt.co[0]
                        props.sketch_selected_point_y = pt.co[1]
                        break
                        
                sketch_globals._axis_lock_start_co = mathutils.Vector((x, y, 0.0))
                sketch_globals._last_mouse_pos = self._cursor_co(x, y)

        elif props.sketch_hover_line_id >= 0:
            lid = props.sketch_hover_line_id
            if event.shift:
                if lid in sel_lines:
                    sel_lines.remove(lid)
                else:
                    sel_lines.append(lid)
                self._set_selected(props, 'sketch_selected_points_str', sel_pts)
                self._set_selected(props, 'sketch_selected_lines_str', sel_lines)
            else:
                self.sketch_op._is_dragging = True
                
                # すでに選択リストに含まれている辺をドラッグした場合は選択を維持
                if lid not in sel_lines:
                    sel_lines = [lid]
                    sel_pts = []
                    self._set_selected(props, 'sketch_selected_points_str', sel_pts)
                    self._set_selected(props, 'sketch_selected_lines_str', sel_lines)
                
                # 選択されているすべての点および選択された線の端点をドラッグ対象に収集
                drag_pts_set = set(sel_pts)
                for line_id in sel_lines:
                    line = next((l for l in props.sketch_lines if l.id == line_id), None)
                    if line:
                        drag_pts_set.add(line.start_point_id)
                        drag_pts_set.add(line.end_point_id)
                self.sketch_op._drag_point_ids = list(drag_pts_set)
                
                # 代表ドラッグ点を線の始点等に設定
                first_line = next((l for l in props.sketch_lines if l.id == lid), None)
                if first_line:
                    self.sketch_op._drag_point_id = first_line.start_point_id
                
                sketch_globals._axis_lock_start_co = mathutils.Vector((x, y, 0.0))
                sketch_globals._last_mouse_pos = self._cursor_co(x, y)

        else:
            if not event.shift:
                self._set_selected(props, 'sketch_selected_points_str', [])
                self._set_selected(props, 'sketch_selected_lines_str', [])
            sketch_globals._is_box_selecting = True
            sketch_globals._box_select_start = (event.mouse_region_x, event.mouse_region_y)
            sketch_globals._box_select_end = sketch_globals._box_select_start
            
        return None

    def handle_left_click_release(self, event, mouse_pos_3d):
        import bpy
        from bpy_extras import view3d_utils
        from ..sketch_solver import solve_gcs_external
        from ...core_bridge import update_cad_preview
        props = self.props
        
        if sketch_globals._is_box_selecting:
            x1, y1 = sketch_globals._box_select_start
            x2, y2 = sketch_globals._box_select_end
            
            # ボックスが十分な大きさを持つ場合のみ選択処理
            if abs(x2 - x1) > 2 and abs(y2 - y1) > 2:
                xmin, xmax = min(x1, x2), max(x1, x2)
                ymin, ymax = min(y1, y2), max(y1, y2)
                
                sel_pts = self._get_selected(props, 'sketch_selected_points_str') if event.shift else []
                sel_lines = self._get_selected(props, 'sketch_selected_lines_str') if event.shift else []
                
                region = self.context.region
                rv3d = self.context.region_data
                
                # 行列取得 (3D to 2D 変換用)
                obj_matrix = self.context.active_object.matrix_world if self.context.active_object else mathutils.Matrix()
                
                # Vertexの判定
                for pt in props.sketch_points:
                    if pt.is_segment:
                        continue
                    co_3d = obj_matrix @ mathutils.Vector((pt.co[0], pt.co[1], 0.0))
                    co_2d = view3d_utils.location_3d_to_region_2d(region, rv3d, co_3d)
                    if co_2d:
                        if xmin <= co_2d.x <= xmax and ymin <= co_2d.y <= ymax:
                            if pt.id not in sel_pts:
                                sel_pts.append(pt.id)
                
                # 直線の判定 (両端点がボックス内にあるか、もしくは簡易的な交差判定等。ここでは両端点とする)
                for line in props.sketch_lines:
                    p1 = next((p for p in props.sketch_points if p.id == line.start_point_id), None)
                    p2 = next((p for p in props.sketch_points if p.id == line.end_point_id), None)
                    if p1 and p2:
                        if p1.is_segment or p2.is_segment:
                            continue
                        co1_3d = obj_matrix @ mathutils.Vector((p1.co[0], p1.co[1], 0.0))
                        co2_3d = obj_matrix @ mathutils.Vector((p2.co[0], p2.co[1], 0.0))
                        co1_2d = view3d_utils.location_3d_to_region_2d(region, rv3d, co1_3d)
                        co2_2d = view3d_utils.location_3d_to_region_2d(region, rv3d, co2_3d)
                        if co1_2d and co2_2d:
                            in1 = (xmin <= co1_2d.x <= xmax and ymin <= co1_2d.y <= ymax)
                            in2 = (xmin <= co2_2d.x <= xmax and ymin <= co2_2d.y <= ymax)
                            if in1 and in2: # Window Select (全体が収まっている場合)
                                if line.id not in sel_lines:
                                    sel_lines.append(line.id)
                
                self._set_selected(props, 'sketch_selected_points_str', sel_pts)
                self._set_selected(props, 'sketch_selected_lines_str', sel_lines)
                
        if self.sketch_op._is_dragging and self.sketch_op._drag_point_id is not None:
            drag_id = self.sketch_op._drag_point_id
            drag_pt = next((p for p in props.sketch_points if p.id == drag_id), None)
            if drag_pt:
                drag_co = mathutils.Vector((drag_pt.co[0], drag_pt.co[1], 0.0))
                # 結合のしきい値
                best_dist = 0.15
                target_id = -1
                for pt in props.sketch_points:
                    if pt.id != drag_id and not pt.is_segment:
                        pt_co = mathutils.Vector((pt.co[0], pt.co[1], 0.0))
                        dist = (drag_co - pt_co).length
                        if dist < best_dist:
                            best_dist = dist
                            target_id = pt.id
                            
                if target_id != -1:
                    from ..sketch_history import push_history
                    from ..sketch_solver import solve_gcs_external
                    from ...core_bridge import update_cad_preview
                    push_history(props)
                    
                    # Merge references
                    for line in props.sketch_lines:
                        if line.start_point_id == drag_id: line.start_point_id = target_id
                        if line.end_point_id == drag_id: line.end_point_id = target_id
                    for arc in props.sketch_arcs:
                        if arc.start_point_id == drag_id: arc.start_point_id = target_id
                        if arc.end_point_id == drag_id: arc.end_point_id = target_id
                        if arc.mid_point_id == drag_id: arc.mid_point_id = target_id
                        if arc.center_point_id == drag_id: arc.center_point_id = target_id
                    for circ in props.sketch_circles:
                        if circ.center_point_id == drag_id: circ.center_point_id = target_id
                        if circ.radius_point_id == drag_id: circ.radius_point_id = target_id
                        
                    to_remove = []
                    for i, const in enumerate(props.sketch_constraints):
                        ids = [int(x.strip()) for x in const.target_ids_str.split(",") if x.strip()]
                        if drag_id in ids:
                            new_ids = [target_id if x == drag_id else x for x in ids]
                            if const.type in {'HORIZONTAL', 'VERTICAL', 'DISTANCE', 'COINCIDENT', 'PARALLEL', 'PERPENDICULAR'}:
                                if len(new_ids) >= 2 and new_ids[0] == new_ids[1]:
                                    to_remove.append(i)
                                    continue
                            const.target_ids_str = ",".join(map(str, new_ids))
                            
                    for i in reversed(to_remove):
                        props.sketch_constraints.remove(i)
                        
                    for i, pt in enumerate(props.sketch_points):
                        if pt.id == drag_id:
                            props.sketch_points.remove(i)
                            break
                            
                    sel_pts = self._get_selected(props, 'sketch_selected_points_str')
                    if drag_id in sel_pts:
                        sel_pts = [target_id if x == drag_id else x for x in sel_pts]
                        sel_pts = list(dict.fromkeys(sel_pts))
                        self._set_selected(props, 'sketch_selected_points_str', sel_pts)
                        
            # ドラッグ終了時に確実に最新の座標で最終同期解決を行う
            solve_gcs_external(props, self.context)
            update_cad_preview(None, self.context)
            self.sketch_op._last_solve_time = 0.0
            
        self.sketch_op._is_dragging = False
        self.sketch_op._drag_point_id = None
        self.sketch_op._drag_point_ids = []
        sketch_globals._is_box_selecting = False
        sketch_globals._axis_lock_start_co = None
        sketch_globals._last_mouse_pos = None
        return None
