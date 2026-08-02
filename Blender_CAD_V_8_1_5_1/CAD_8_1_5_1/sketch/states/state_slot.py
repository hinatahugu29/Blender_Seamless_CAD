import math
import mathutils
from .state_base import SketchState
from .. import sketch_globals
from ..sketch_history import push_history
from ..sketch_solver import solve_gcs_external
from ...core_bridge import update_cad_preview

class StateSlot(SketchState):
    def handle_mouse_move(self, event, mouse_pos_3d):
        super().handle_mouse_move(event, mouse_pos_3d)
        
        # プレビュー表示用のダミー描画データなどをセットする
        # (sketch_globals に一時プレビュー用データを格納しても良いが、
        #  シンプルにするためにクリック時のステップ管理を行う)
        return False

    def handle_left_click_press(self, event, mouse_pos_3d):
        props = self.props
        m_pos = mathutils.Vector((mouse_pos_3d.x, mouse_pos_3d.y, 0.0))
        
        # _circle_points をテンポラリの点保持用として流用する
        # 1点目: C1
        if not sketch_globals._circle_points:
            sketch_globals._circle_points = [(m_pos, -1)]
            sketch_globals._axis_lock_start_co = m_pos
            return None
            
        # 2点目: C2
        elif len(sketch_globals._circle_points) == 1:
            c1_pos = sketch_globals._circle_points[0][0]
            if (m_pos - c1_pos).length < 1e-3:
                return None
            sketch_globals._circle_points.append((m_pos, -1))
            sketch_globals._axis_lock_start_co = m_pos
            return None
            
        # 3点目: 半径決定とスロット生成
        elif len(sketch_globals._circle_points) == 2:
            c1 = sketch_globals._circle_points[0][0]
            c2 = sketch_globals._circle_points[1][0]
            
            # C1-C2ベクトルに対するマウスの垂線距離を半径 R とする
            v_dir = c2 - c1
            v_len = v_dir.length
            if v_len > 1e-4:
                proj = c1 + v_dir * ((m_pos - c1).dot(v_dir) / (v_len * v_len))
                r = (m_pos - proj).length
            else:
                r = (m_pos - c1).length
                
            if r < 1e-3:
                r = 0.2 # 最小フォールバック値
                
            # スロット要素のコミット
            self._commit_slot(c1, c2, r)
            
            sketch_globals._circle_points.clear()
            sketch_globals._axis_lock_start_co = None
            return None
            
        return None

    def handle_right_click(self, event):
        if sketch_globals._circle_points:
            sketch_globals._circle_points.clear()
            sketch_globals._axis_lock_start_co = None
            update_cad_preview(None, self.context)
            return None
        return 'SELECT'

    def _create_point(self, co):
        new_pt = self.props.sketch_points.add()
        new_id = max([p.id for p in self.props.sketch_points] + [0]) + 1
        new_pt.id = new_id
        new_pt.co = (co.x, co.y)
        new_pt.is_segment = False
        return new_id

    def _create_segment_point(self, co):
        new_pt = self.props.sketch_points.add()
        new_id = max([p.id for p in self.props.sketch_points] + [0]) + 1
        new_pt.id = new_id
        new_pt.co = (co.x, co.y)
        new_pt.is_segment = True
        return new_id

    def _add_line(self, start_id, end_id, is_const=False):
        line = self.props.sketch_lines.add()
        line.id = max([l.id for l in self.props.sketch_lines] + [0]) + 1
        line.start_point_id = start_id
        line.end_point_id = end_id
        line.is_construction = is_const
        return line.id

    def _add_constraint(self, c_type, targets, value=0.0):
        const = self.props.sketch_constraints.add()
        const.id = max([c.id for c in self.props.sketch_constraints] + [0]) + 1
        const.type = c_type
        const.target_ids_str = ",".join(map(str, targets))
        const.value = value
        return const.id

    def _commit_slot(self, c1, c2, r):
        props = self.props
        push_history(props)
        
        # 向きベクトルの計算
        v_dir = (c2 - c1).normalized()
        v_perp = mathutils.Vector((-v_dir.y, v_dir.x, 0.0))
        
        # ジオメトリの点座標
        p1_pos = c2 + v_perp * r
        p2_pos = c2 - v_perp * r
        p3_pos = c1 - v_perp * r
        p4_pos = c1 + v_perp * r
        
        m1_pos = c1 - v_dir * r # 左円弧の中点
        m2_pos = c2 + v_dir * r # 右円弧の中点
        
        # 点の生成
        c1_id = self._create_point(c1)
        c2_id = self._create_point(c2)
        p1_id = self._create_point(p1_pos)
        p2_id = self._create_point(p2_pos)
        p3_id = self._create_point(p3_pos)
        p4_id = self._create_point(p4_pos)
        
        m1_id = self._create_segment_point(m1_pos)
        m2_id = self._create_segment_point(m2_pos)
        
        # 線の生成
        l1_id = self._add_line(p4_id, p1_id) # 上の平行線
        l2_id = self._add_line(p2_id, p3_id) # 下の平行線
        
        # 中心線の生成 (Construction)
        self._add_line(c1_id, c2_id, is_const=True)
        
        # 円弧の生成
        # Arc1 (左): 始点 P3, 終点 P4, 中点 M1, 中心 C1
        arc1 = props.sketch_arcs.add()
        arc1.id = max([a.id for a in props.sketch_arcs] + [0]) + 1
        arc1.start_point_id = p3_id
        arc1.end_point_id = p4_id
        arc1.mid_point_id = m1_id
        arc1.center_point_id = c1_id
        
        # Arc2 (右): 始点 P1, 終点 P2, 中点 M2, 中心 C2
        arc2 = props.sketch_arcs.add()
        arc2.id = max([a.id for a in props.sketch_arcs] + [0]) + 1
        arc2.start_point_id = p1_id
        arc2.end_point_id = p2_id
        arc2.mid_point_id = m2_id
        arc2.center_point_id = c2_id
        
        # --- 幾何拘束の自動生成 ---
        # 1. 円弧形状拘束 (ARC)
        self._add_constraint('ARC', [p3_id, p4_id, m1_id, c1_id])
        self._add_constraint('ARC', [p1_id, p2_id, m2_id, c2_id])
        
        # 2. 接線拘束 (TANGENT)
        # 上の直線 l1 (p4-p1) は Arc1, Arc2 に接する
        self._add_constraint('TANGENT', [p4_id, p1_id, c1_id, m1_id])
        self._add_constraint('TANGENT', [p4_id, p1_id, c2_id, m2_id])
        # 下の直線 l2 (p2-p3) は Arc1, Arc2 に接する
        self._add_constraint('TANGENT', [p2_id, p3_id, c1_id, m1_id])
        self._add_constraint('TANGENT', [p2_id, p3_id, c2_id, m2_id])
        
        # 3. 半径・距離拘束の追加 (C1-P4 距離 = r, C1-C2 距離 = 中心間距離)
        self._add_constraint('DISTANCE', [c1_id, p4_id], r)
        self._add_constraint('DISTANCE', [c1_id, c2_id], (c2 - c1).length)
        
        # CADプレビューとソルバーの解決
        solve_gcs_external(props, self.context)
        update_cad_preview(None, self.context)
