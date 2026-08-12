import bpy
import math
import mathutils
from ..core_bridge import get_core
from .sketch_finalize import calculate_arc_points
from .. import utils

_in_solve = False


def run_dof_simulation_delayed():
    import bpy
    from . import sketch_globals
    from .. import utils
    from ...core_bridge import get_core
    
    core = get_core()
    props = sketch_globals._pending_dof_props
    data = sketch_globals._pending_dof_data
    if not props or not data or not core:
        sketch_globals._dof_timer_handle = None
        return None
        
    points_list, constraints_list = data
    
    try:
        fully_constrained_pts = set()
        for pt in props.sketch_points:
            # 円弧などの補間用分割頂点(is_segment)はDoFテストから除外して高速化
            if getattr(pt, "is_segment", False):
                continue
            
            # X方向の移動テスト
            pts_test_x = []
            for p in props.sketch_points:
                if p.id == pt.id:
                    pts_test_x.append((p.id, float(p.co[0] + 0.05), float(p.co[1])))
                else:
                    pts_test_x.append((p.id, float(p.co[0]), float(p.co[1])))
            
            consts_test_x = constraints_list + [('FIXED', [pt.id], 0.0)]
            try:
                res_x = core.solve_sketch(pts_test_x, consts_test_x)
                solved_x = res_x is not None and len(res_x) > 0
            except:
                solved_x = False
            
            # Y方向の移動テスト
            pts_test_y = []
            for p in props.sketch_points:
                if p.id == pt.id:
                    pts_test_y.append((p.id, float(p.co[0]), float(p.co[1] + 0.05)))
                else:
                    pts_test_y.append((p.id, float(p.co[0]), float(p.co[1])))
            
            consts_test_y = constraints_list + [('FIXED', [pt.id], 0.0)]
            try:
                res_y = core.solve_sketch(pts_test_y, consts_test_y)
                solved_y = res_y is not None and len(res_y) > 0
            except:
                solved_y = False
            
            # 両方向ともに「動かせない（解決失敗する）」なら完全拘束
            if not solved_x and not solved_y:
                fully_constrained_pts.add(pt.id)
        
        sketch_globals._fully_constrained_pts = fully_constrained_pts
        
        # 直線の完全拘束判定
        fully_constrained_lines = set()
        for line in props.sketch_lines:
            if line.start_point_id in fully_constrained_pts and line.end_point_id in fully_constrained_pts:
                fully_constrained_lines.add(line.id)
        sketch_globals._fully_constrained_lines = fully_constrained_lines
        
        # 円の完全拘束判定
        fully_constrained_circles = set()
        for circ in props.sketch_circles:
            if circ.center_point_id in fully_constrained_pts and circ.radius_point_id in fully_constrained_pts:
                fully_constrained_circles.add(circ.id)
        sketch_globals._fully_constrained_circles = fully_constrained_circles
        
        # 円弧の完全拘束判定
        fully_constrained_arcs = set()
        for arc in props.sketch_arcs:
            if (arc.start_point_id in fully_constrained_pts and 
                arc.end_point_id in fully_constrained_pts and 
                arc.mid_point_id in fully_constrained_pts and 
                arc.center_point_id in fully_constrained_pts):
                fully_constrained_arcs.add(arc.id)
        sketch_globals._fully_constrained_arcs = fully_constrained_arcs
        
        # 再描画要求
        for area in bpy.context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
                
    except Exception as e_dof:
        utils.error_print(f"DoF simulation failed: {e_dof}")
        
    sketch_globals._dof_timer_handle = None
    return None

def solve_gcs_external(props, context, drag_pt_id=None, mouse_pos=None):
    global _in_solve
    if _in_solve:
        return True
        
    core = get_core()
    if not core:
        return False
        
    _in_solve = True
    try:
        return _solve_gcs_external_impl(props, context, drag_pt_id, mouse_pos, core)
    finally:
        _in_solve = False

def _solve_gcs_external_impl(props, context, drag_pt_id, mouse_pos, core):
    # 1. 座標と拘束値のバックアップ (ロールバック用)
    backup_cos = {pt.id: pt.co[:] for pt in props.sketch_points}
    backup_constraints = {c.id: c.value for c in props.sketch_constraints}

    # 2. ソルバー実行前の初期値補正:
    # ドラッグによる変位を仮反映させつつ、全円弧の中間点(pt_mid)を数学的に正しい「劣弧の真ん中」へ事前配置する。
    # これにより、ソルバーの初期状態矛盾による不収束・反転を根絶する。
    point_dict = {p.id: p for p in props.sketch_points}

    # V8.1.5バグ修正: フィレット円弧(is_fillet)の目標半径をDISTANCE拘束から事前に引けるようにする。
    # T1/T2(接続辺の端点でもある)がドラッグで動いた際、中心Oの初期値が古いままだと
    # ソルバーが不整合な局所解(半径がO-M間だけ正しくO-T1/O-T2は大きく外れる歪んだ円弧)に
    # 収束しやすい。ソルブ前にOを「T1・T2から半径Rで作図した正しい位置」へ再計算しておくことで、
    # ソルバーはほぼ解けた状態から始められる。
    fillet_radius_by_arc = {}
    for arc in props.sketch_arcs:
        if not getattr(arc, "is_fillet", False):
            continue
        target_set = {arc.center_point_id, arc.mid_point_id}
        for c in props.sketch_constraints:
            if c.type == 'DISTANCE':
                try:
                    ids = {int(x.strip()) for x in c.target_ids_str.split(",") if x.strip()}
                except ValueError:
                    continue
                if ids == target_set:
                    fillet_radius_by_arc[arc.id] = c.value
                    break

    for arc in props.sketch_arcs:
        s_id = arc.start_point_id
        e_id = arc.end_point_id
        m_id = arc.mid_point_id
        c_id = arc.center_point_id

        pt_start = point_dict.get(s_id)
        pt_end = point_dict.get(e_id)
        pt_mid = point_dict.get(m_id)
        pt_center = point_dict.get(c_id)

        if pt_start and pt_end and pt_mid and pt_center:
            p1 = mathutils.Vector((pt_start.co[0], pt_start.co[1], 0.0))
            p3 = mathutils.Vector((pt_end.co[0], pt_end.co[1], 0.0))
            o = mathutils.Vector((pt_center.co[0], pt_center.co[1], 0.0))

            if drag_pt_id is not None and mouse_pos is not None:
                if s_id == drag_pt_id:
                    p1 = mathutils.Vector((mouse_pos.x, mouse_pos.y, 0.0))
                elif e_id == drag_pt_id:
                    p3 = mathutils.Vector((mouse_pos.x, mouse_pos.y, 0.0))
                elif c_id == drag_pt_id:
                    o = mathutils.Vector((mouse_pos.x, mouse_pos.y, 0.0))

            r_target = fillet_radius_by_arc.get(arc.id)
            if r_target and r_target > 1e-6 and c_id != drag_pt_id:
                # T1-T2間距離 d が 2R以下なら、半径Rの円がT1・T2両方を通る中心を作図できる。
                # 2解のうち、現在のOに近い側(=角の内側)を採用して反転を防ぐ。
                d = (p3 - p1).length
                if 1e-6 < d <= 2.0 * r_target:
                    mid_t = (p1 + p3) * 0.5
                    h = math.sqrt(max(0.0, r_target * r_target - (d * 0.5) * (d * 0.5)))
                    edge_dir = (p3 - p1).normalized()
                    perp_dir = mathutils.Vector((-edge_dir.y, edge_dir.x, 0.0))
                    cand1 = mid_t + perp_dir * h
                    cand2 = mid_t - perp_dir * h
                    o = cand1 if (cand1 - o).length <= (cand2 - o).length else cand2
                    pt_center.co = (o.x, o.y)

            R = (p1 - o).length
            mid_c = (p1 + p3) * 0.5
            v_dir = mid_c - o
            if v_dir.length > 1e-6:
                current_mid_dir = mathutils.Vector((pt_mid.co[0], pt_mid.co[1], 0.0)) - o
                if current_mid_dir.length > 1e-6 and v_dir.dot(current_mid_dir) < 0:
                    v_dir = -v_dir
                m_co = o + v_dir.normalized() * R
                pt_mid.co = (m_co.x, m_co.y)

    points_list = []
    for pt in props.sketch_points:
        points_list.append((pt.id, float(pt.co[0]), float(pt.co[1])))

    # 円の寸法は、保存上は DISTANCE でもソルバーには RADIUS として渡す。
    #
    # Distance(中心, 円周点) は式が1本に対して自由な座標が4つあるので、ソルバーは
    # 補正を両方の点に分配する。つまり半径を変えると**中心が半分ぶん動いて円が
    # 横にずれる**。ユーザーから上がってきたのがこの症状で、期待は当然
    # 「中心はそのまま、外周が変わる」。RADIUS 側は中心を優先度1で留めてあるので、
    # 振り替えるだけで期待どおりになる。
    #
    # 振り替えるのは**ソルバーへ送るペイロードだけ**で、保存されている拘束は
    # DISTANCE のまま触らない。パネルの寸法ラベル(_find_distance_constraint)は
    # DISTANCE を探して編集欄を出しているので、型を書き換えると寸法が編集できなく
    # なる。ここが振り替えを「保存側でやらない」理由。
    #
    # **フィレット円弧は除外する。** あちらは中心 O を「T1・T2 から半径 R で
    # 作図した正しい位置」へソルブ前に置き直す専用処理があり(上の
    # fillet_radius_by_arc)、中心が動くことが前提になっている。留めると
    # その処理と正面から衝突する。
    radius_pairs = {}
    for c in props.sketch_circles:
        radius_pairs[frozenset((c.center_point_id, c.radius_point_id))] = c.center_point_id
    for a in props.sketch_arcs:
        if getattr(a, "is_fillet", False):
            continue
        for rim in (a.start_point_id, a.end_point_id, a.mid_point_id):
            radius_pairs[frozenset((a.center_point_id, rim))] = a.center_point_id

    constraints_list = []
    for const in props.sketch_constraints:
        try:
            target_ids = [int(x.strip()) for x in const.target_ids_str.split(",") if x.strip()]
        except ValueError:
            continue

        c_type = const.type
        if c_type == 'DISTANCE' and len(target_ids) == 2:
            centre = radius_pairs.get(frozenset(target_ids))
            # frozenset は中心と円周点が同一IDだと1要素になる(退化した円)。
            # その場合は振り替えず、これまでどおり DISTANCE として送る。
            if centre is not None and target_ids[0] != target_ids[1]:
                rim = target_ids[1] if target_ids[0] == centre else target_ids[0]
                c_type = 'RADIUS'
                target_ids = [centre, rim]   # RADIUS は [中心, 円周点] の順

        constraints_list.append((c_type, target_ids, float(const.value)))

    if drag_pt_id is not None and mouse_pos is not None:
        constraints_list = [c for c in constraints_list if not (c[0] == 'FIXED' and c[1] == [drag_pt_id])]
        for idx, pt in enumerate(points_list):
            if pt[0] == drag_pt_id:
                points_list[idx] = (drag_pt_id, float(mouse_pos.x), float(mouse_pos.y))
                break
        constraints_list.append(('FIXED', [drag_pt_id], 0.0))

    try:
        # デバッグ出力は debug_print で。error_print は ERROR_LOGS(既定 True)で
        # 常に出るため、ここに置くとスケッチのドラッグ中に毎フレーム
        # 全点・全拘束を文字列化してコンソールへ書き込むことになる。
        # 「デバッグログを沈黙させてメインスレッドの引っ掛かりを消す」という
        # V1.3.5 の作業を、この経路だけ打ち消していた。
        utils.debug_print(f"DEBUG SOLVE: points_list={points_list}")
        utils.debug_print(f"DEBUG SOLVE: constraints_list={constraints_list}")
        resolved = core.solve_sketch(points_list, constraints_list)
        if not resolved or len(resolved) == 0:
            # ここは本物の失敗なので error_print のままでよい
            utils.error_print(f"GCS solve returned nothing: {resolved}")
            raise ValueError("GCS solver returned empty result (failed to converge)")
            
        resolved_dict = {p_id: (x, y) for p_id, x, y in resolved}
        
        # 解決後の幾何整合性バリデーション:
        invalid_solve = False
        
        # 1) 爆発的な異常変位チェック (不収束の妥協点検出)
        if drag_pt_id is not None and mouse_pos is not None:
            if drag_pt_id in backup_cos:
                drag_pt_old = mathutils.Vector((backup_cos[drag_pt_id][0], backup_cos[drag_pt_id][1]))
                drag_pt_new = mathutils.Vector((mouse_pos.x, mouse_pos.y))
                drag_dist = (drag_pt_new - drag_pt_old).length
                
                max_allowed_drift = max(3.0, drag_dist * 5.0)
                for pt_id, new_co in resolved_dict.items():
                    if pt_id != drag_pt_id and pt_id in backup_cos:
                        old_co = mathutils.Vector((backup_cos[pt_id][0], backup_cos[pt_id][1]))
                        new_co_v = mathutils.Vector((new_co[0], new_co[1]))
                        if (new_co_v - old_co).length > max_allowed_drift:
                            invalid_solve = True
                            break
                            
        # 2) 直線の極端な縮小・潰れチェック (フィレット同士のオーバーラップ衝突検出)
        if not invalid_solve:
            pt_is_segment = {pt.id: pt.is_segment for pt in props.sketch_points}
            for line in props.sketch_lines:
                # 円弧セグメントを構成するVertexを持つ直線は、極小サイズになり得るため、崩壊チェックから除外する
                is_seg_s = pt_is_segment.get(line.start_point_id, False)
                is_seg_e = pt_is_segment.get(line.end_point_id, False)
                if is_seg_s or is_seg_e:
                    continue
                
                co_s = resolved_dict.get(line.start_point_id, None)
                co_e = resolved_dict.get(line.end_point_id, None)
                if co_s and co_e:
                    p_s = mathutils.Vector((co_s[0], co_s[1]))
                    p_e = mathutils.Vector((co_e[0], co_e[1]))
                    if (p_s - p_e).length < 0.005:
                        invalid_solve = True
                        break
                        
        # 3) フィレット円弧の飛び出し（交差オーバーラン）チェック
        if not invalid_solve:
            pt_is_segment = {pt.id: pt.is_segment for pt in props.sketch_points}
            res_co = {pt_id: mathutils.Vector((co[0], co[1], 0.0)) for pt_id, co in resolved_dict.items()}
            
            for arc in props.sketch_arcs:
                s_id = arc.start_point_id
                e_id = arc.end_point_id
                
                if s_id not in res_co or e_id not in res_co:
                    continue
                co_t1 = res_co[s_id]
                co_t2 = res_co[e_id]
                
                # s_id, e_id に接続している通常直線（相手が is_segment == False）を検索
                pt_a_id = None
                pt_b_id = None
                
                for line in props.sketch_lines:
                    if line.start_point_id == s_id:
                        other = line.end_point_id
                        if other in pt_is_segment and not pt_is_segment[other]:
                            pt_a_id = other
                    elif line.end_point_id == s_id:
                        other = line.start_point_id
                        if other in pt_is_segment and not pt_is_segment[other]:
                            pt_a_id = other
                            
                    if line.start_point_id == e_id:
                        other = line.end_point_id
                        if other in pt_is_segment and not pt_is_segment[other]:
                            pt_b_id = other
                    elif line.end_point_id == e_id:
                        other = line.start_point_id
                        if other in pt_is_segment and not pt_is_segment[other]:
                            pt_b_id = other
                
                if pt_a_id is not None and pt_b_id is not None:
                    if pt_a_id in res_co and pt_b_id in res_co:
                        co_a = res_co[pt_a_id]
                        co_b = res_co[pt_b_id]
                        
                        u = co_t1 - co_a
                        v = co_t2 - co_b
                        len_u = u.length
                        len_v = v.length
                        
                        if len_u > 1e-4 and len_v > 1e-4:
                            u_dir = u / len_u
                            v_dir = v / len_v
                            
                            # 2直線の交差パラメータ s, t を算出
                            D = -u_dir.x * v_dir.y + u_dir.y * v_dir.x
                            if abs(D) > 1e-4:
                                s = ((co_b.x - co_a.x) * -v_dir.y - (co_b.y - co_a.y) * -v_dir.x) / D
                                t = (u_dir.x * (co_b.y - co_a.y) - u_dir.y * (co_b.x - co_a.x)) / D
                                
                                # 交点が T1, T2 よりも前方にある（s > len_u かつ t > len_v）ことを検証する
                                if s < len_u - 1e-3 or t < len_v - 1e-3:
                                    invalid_solve = True
                                    utils.debug_print(f"DEBUG: Fillet overrun/overlap validation failed! s={s:.4f}, len_u={len_u:.4f}, t={t:.4f}, len_v={len_v:.4f}")
                                    break
                                    
        # 4) フィレット円弧の半径整合性チェック (V8.1.5バグ修正)
        # ARC拘束(t1,t2,m,oが同一円周上)とDISTANCE拘束(o-m間=R)は、遠くへドラッグされた
        # t1/t2に対してソルバーが数値的に妥協解へ収束すると、o-t1やo-t2がo-mから大きく
        # 乖離した「歪んだ円弧」を許してしまうことがある。半径が一致しない解は却下し、
        # ドラッグ前の座標へロールバックする(チェック1の「異常変位」しきい値は固定3.0単位の
        # 下限があり、小さいスケッチではこの種の破綻を検出できないため、別途チェックする)。
        if not invalid_solve:
            res_co_all = {pt_id: mathutils.Vector((co[0], co[1])) for pt_id, co in resolved_dict.items()}
            for arc in props.sketch_arcs:
                if not getattr(arc, "is_fillet", False):
                    continue
                s_id, e_id, m_id, c_id = arc.start_point_id, arc.end_point_id, arc.mid_point_id, arc.center_point_id
                if not all(pid in res_co_all for pid in (s_id, e_id, m_id, c_id)):
                    continue
                o = res_co_all[c_id]
                r_ref = (res_co_all[m_id] - o).length
                if r_ref < 1e-6:
                    invalid_solve = True
                    break
                r_t1 = (res_co_all[s_id] - o).length
                r_t2 = (res_co_all[e_id] - o).length
                tol = max(0.01, r_ref * 0.1)
                if abs(r_t1 - r_ref) > tol or abs(r_t2 - r_ref) > tol:
                    invalid_solve = True
                    utils.debug_print(
                        f"DEBUG: Fillet radius consistency check failed! r_ref={r_ref:.4f} "
                        f"r_t1={r_t1:.4f} r_t2={r_t2:.4f} tol={tol:.4f}"
                    )
                    break

        if invalid_solve:
            raise ValueError("Geometric validation failed (excessive drift or collapsed line)")
            
        for pt in props.sketch_points:
            if pt.id in resolved_dict:
                pt.co = resolved_dict[pt.id]
                
        # GCS解決後に、円弧(sketch_arcs)の中間セグメント点の座標を再計算して追従させる
        for arc in props.sketch_arcs:
            s_id = arc.start_point_id
            e_id = arc.end_point_id
            m_id = arc.mid_point_id
            c_id = arc.center_point_id
            
            pt_start = next((p for p in props.sketch_points if p.id == s_id), None)
            pt_end = next((p for p in props.sketch_points if p.id == e_id), None)
            pt_mid = next((p for p in props.sketch_points if p.id == m_id), None)
            pt_center = next((p for p in props.sketch_points if p.id == c_id), None)
            
            if pt_start and pt_end and pt_mid and pt_center:
                p1 = mathutils.Vector((pt_start.co[0], pt_start.co[1], 0.0))
                p3 = mathutils.Vector((pt_end.co[0], pt_end.co[1], 0.0))
                o = mathutils.Vector((pt_center.co[0], pt_center.co[1], 0.0))
                
                # 半径R
                R = (p1 - o).length
                
                # 中心から始点・終点への方向ベクトルから、角の内側（二等分線）を向く方向ベクトルを計算する
                v1 = p1 - o
                v3 = p3 - o
                if v1.length > 1e-6 and v3.length > 1e-6:
                    u = v1.normalized()
                    v = v3.normalized()
                    # u + v は常に劣弧（カドの内側）の方向を指す二等分線ベクトルになります
                    w_dir = u + v
                    if w_dir.length < 1e-6:
                        w_dir = mathutils.Vector((-u.y, u.x, 0.0))
                        
                    # フィレットの場合は常に劣弧（内側）を維持するため、反転させない。
                    # V8.1.5バグ修正: 以前は実在しない拘束タイプ'FILLET'で判定しており
                    # 常にFalse扱い(=常に反転ヒューリスティック側)になっていたため、
                    # ドラッグで角度が変わると円弧が反対側にめくれる不具合があった。
                    # arc.is_fillet フラグ(コーナーフィレット生成時にセット)で正しく判定する。
                    is_fillet = getattr(arc, "is_fillet", False)

                    if not is_fillet:
                        current_mid_dir = mathutils.Vector((pt_mid.co[0], pt_mid.co[1], 0.0)) - o
                        if current_mid_dir.length > 1e-6 and w_dir.dot(current_mid_dir) < 0:
                            w_dir = -w_dir
                        
                    if w_dir.length > 1e-6:
                        m_co = o + w_dir.normalized() * R
                        pt_mid.co = (m_co.x, m_co.y)

        import collections
        arc_segment_nodes = set()
        for arc in props.sketch_arcs:
            s_id = arc.start_point_id
            e_id = arc.end_point_id
            m_id = arc.mid_point_id
            
            pt_start = next((p for p in props.sketch_points if p.id == s_id), None)
            pt_end = next((p for p in props.sketch_points if p.id == e_id), None)
            pt_mid = next((p for p in props.sketch_points if p.id == m_id), None)
            
            if pt_start and pt_end and pt_mid:
                p1 = mathutils.Vector((pt_start.co[0], pt_start.co[1], 0.0))
                p2 = mathutils.Vector((pt_mid.co[0], pt_mid.co[1], 0.0))
                p3 = mathutils.Vector((pt_end.co[0], pt_end.co[1], 0.0))
                utils.debug_print(f"DEBUG: arc ID start={s_id}, mid={m_id}, end={e_id}")
                utils.debug_print(f"DEBUG: arc p1={p1[:2]}, p2={p2[:2]}, p3={p3[:2]}")
                arc_cos = calculate_arc_points(p1, p2, p3, num_segments=16)
                
                point_objs = {p.id: p for p in props.sketch_points}
                
                # 始点から終点までの接続パスを検索
                adj = collections.defaultdict(list)
                for line in props.sketch_lines:
                    adj[line.start_point_id].append(line.end_point_id)
                    adj[line.end_point_id].append(line.start_point_id)
                    
                path = None
                stack = [(s_id, [s_id])]
                visited = {s_id}
                while stack:
                    node, curr_path = stack.pop()
                    if node == e_id:
                        path = curr_path
                        break
                    for n in adj[node]:
                        if n in arc_segment_nodes:
                            continue
                        if n not in visited:
                            # 途中のノードは必ず円弧のセグメントVertex(is_segment == True)でなければならない
                            if n != e_id:
                                pt_node = point_objs.get(n, None)
                                if not pt_node or not pt_node.is_segment:
                                    continue
                            visited.add(n)
                            stack.append((n, curr_path + [n]))
                            
                utils.debug_print(f"DEBUG: path={path}")
                if path:
                    for p_id in path:
                        if p_id != s_id and p_id != e_id:
                            arc_segment_nodes.add(p_id)
                    utils.debug_print(f"DEBUG: len(path)={len(path)}, len(arc_cos)={len(arc_cos)}")
                if path and len(path) == len(arc_cos):
                    for i, p_id in enumerate(path):
                        if p_id in point_objs:
                            point_objs[p_id].co = (arc_cos[i].x, arc_cos[i].y)
                else:
                    utils.debug_print(f"DEBUG: Sync skipped! path={path is not None}, len_match={(len(path) == len(arc_cos)) if path else False}")
    except Exception as e:
        utils.error_print(f"GCS Solver error / Arc fitting failed: {e}. Rolling back coordinates to maintain sketch topology.")
        for pt_id, co in backup_cos.items():
            pt = next((p for p in props.sketch_points if p.id == pt_id), None)
            if pt:
                pt.co = co
        for c_id, val in backup_constraints.items():
            c = next((x for x in props.sketch_constraints if x.id == c_id), None)
            if c:
                c.value = val
        return False

    # --- 1. 完全拘束の自由度 (DoF) 遅延シミュレーション（デバウンス） ---
    if drag_pt_id is None:
        import bpy
        from . import sketch_globals
        
        # 既存のタイマーをキャンセル
        if sketch_globals._dof_timer_handle is not None:
            try:
                bpy.app.timers.unregister(run_dof_simulation_delayed)
            except Exception:
                pass
            sketch_globals._dof_timer_handle = None
            
        sketch_globals._pending_dof_props = props
        sketch_globals._pending_dof_data = (points_list, constraints_list)
        
        # 0.15秒後に非同期でDoFテストを実行
        sketch_globals._dof_timer_handle = bpy.app.timers.register(run_dof_simulation_delayed, first_interval=0.15)

    return True

def find_arc_by_line_id(props, line_id):
    line = next((l for l in props.sketch_lines if l.id == line_id), None)
    if not line: return None
    s_id = line.start_point_id
    e_id = line.end_point_id
    
    import collections
    for arc in props.sketch_arcs:
        as_id = arc.start_point_id
        ae_id = arc.end_point_id
        
        adj = collections.defaultdict(list)
        for l in props.sketch_lines:
            adj[l.start_point_id].append(l.end_point_id)
            adj[l.end_point_id].append(l.start_point_id)
            
        stack = [(as_id, [as_id])]
        visited = {as_id}
        path = None
        while stack:
            node, curr_path = stack.pop()
            if node == ae_id:
                path = curr_path
                break
            for n in adj[node]:
                if n not in visited:
                    visited.add(n)
                    stack.append((n, curr_path + [n]))
                    
        if path and (s_id in path or e_id in path):
            return arc
    return None

