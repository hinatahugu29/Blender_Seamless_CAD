import bpy
import mathutils
import math
from ... import utils
from ..sketch_history import push_history, perform_undo
from ..sketch_solver import solve_gcs_external, find_arc_by_line_id
from ..sketch_finalize import finalize_sketch, calculate_arc_points, calculate_circle_points, is_point_in_polygon

from ...core_bridge import update_cad_preview


def action_delete_constraint(op, context, props):
    if op.constraint_id >= 0:
        push_history(props)
        found_idx = -1
        for idx, c in enumerate(props.sketch_constraints):
            if c.id == op.constraint_id:
                found_idx = idx
                break
        if found_idx >= 0:
            props.sketch_constraints.remove(found_idx)
            solve_gcs_external(props, context)
            update_cad_preview(None, context)
            op.report({'INFO'}, f"Constraint ID:{op.constraint_id} removed.")
        else:
            op.report({'WARNING'}, f"Constraint ID:{op.constraint_id} not found.")
        

def action_constraint_fixed(op, context, props):
    pt_id = props.sketch_selected_point_id
    pt_id2 = props.sketch_selected_point_id_2
    targets = [x for x in (pt_id, pt_id2) if x >= 0]
    if targets:
        push_history(props)
        for tid in targets:
            dup = any(c.type == 'FIXED' and c.target_ids_str == str(tid) for c in props.sketch_constraints)
            if not dup:
                const = props.sketch_constraints.add()
                const.id = len(props.sketch_constraints) + 1
                const.type = 'FIXED'
                const.target_ids_str = str(tid)
                const.value = 0.0
        solve_gcs_external(props, context)
        update_cad_preview(None, context)
        op.report({'INFO'}, f"Point(s) {targets} Fixed!")
            

def action_constraint_horizontal_vertical(op, context, props):
    p1_id = props.sketch_selected_point_id
    p2_id = props.sketch_selected_point_id_2
    const_type = 'HORIZONTAL' if op.action == 'CONSTRAINT_HORIZONTAL' else 'VERTICAL'
    
    # 1. 2つのVertexが選択されている場合（Vertex揃え）
    if p1_id >= 0 and p2_id >= 0:
        push_history(props)
        target_str = f"{p1_id},{p2_id}"
        target_str_rev = f"{p2_id},{p1_id}"
        dup = any(c.type == const_type and (c.target_ids_str == target_str or c.target_ids_str == target_str_rev) for c in props.sketch_constraints)
        if not dup:
            const = props.sketch_constraints.add()
            const.id = len(props.sketch_constraints) + 1
            const.type = const_type
            const.target_ids_str = target_str
            const.value = 0.0
            solve_gcs_external(props, context)
            update_cad_preview(None, context)
            op.report({'INFO'}, f"Points {p1_id} and {p2_id} aligned {const_type}!")
            
    # 2. それ以外（辺または1Vertex経由での辺揃え）
    else:
        line_id = props.sketch_selected_line_id
        if line_id < 0:
            line_id = props.sketch_hover_line_id
        if line_id < 0 and p1_id >= 0:
            for l in props.sketch_lines:
                if l.start_point_id == p1_id or l.end_point_id == p1_id:
                    line_id = l.id
                    break
        
        if line_id >= 0:
            line = next((l for l in props.sketch_lines if l.id == line_id), None)
            if line:
                push_history(props)
                target_str = f"{line.start_point_id},{line.end_point_id}"
                dup = any(c.type == const_type and c.target_ids_str == target_str for c in props.sketch_constraints)
                if not dup:
                    const = props.sketch_constraints.add()
                    const.id = len(props.sketch_constraints) + 1
                    const.type = const_type
                    const.target_ids_str = target_str
                    const.value = 0.0
                    solve_gcs_external(props, context)
                    update_cad_preview(None, context)
                    op.report({'INFO'}, f"Line {line_id} Constrained {const_type}!")
        else:
            op.report({'WARNING'}, "Select two points or one line to apply horizontal/vertical constraint.")
                

def action_constraint_parallel_perpendicular(op, context, props):
    l1_id = props.sketch_selected_line_id
    l2_id = props.sketch_selected_line_id_2
    const_type = 'PARALLEL' if op.action == 'CONSTRAINT_PARALLEL' else 'PERPENDICULAR'
    
    if l1_id >= 0 and l2_id >= 0:
        line1 = next((l for l in props.sketch_lines if l.id == l1_id), None)
        line2 = next((l for l in props.sketch_lines if l.id == l2_id), None)
        if line1 and line2:
            push_history(props)
            # 端点4点
            s1, e1 = line1.start_point_id, line1.end_point_id
            s2, e2 = line2.start_point_id, line2.end_point_id
            
            target_str = f"{s1},{e1},{s2},{e2}"
            # 順序が入れ替わったパターンも考慮した重複チェック
            dup = False
            for c in props.sketch_constraints:
                if c.type == const_type:
                    parts = [int(x.strip()) for x in c.target_ids_str.split(",") if x.strip()]
                    if len(parts) == 4:
                        if ((parts[0] == s1 and parts[1] == e1) or (parts[0] == e1 and parts[1] == s1)) and \
                           ((parts[2] == s2 and parts[3] == e2) or (parts[2] == e2 and parts[3] == s2)):
                            dup = True
                            break
                        if ((parts[0] == s2 and parts[1] == e2) or (parts[0] == e2 and parts[1] == s2)) and \
                           ((parts[2] == s1 and parts[3] == e1) or (parts[2] == e1 and parts[3] == s1)):
                            dup = True
                            break
            
            if not dup:
                const = props.sketch_constraints.add()
                const.id = len(props.sketch_constraints) + 1
                const.type = const_type
                const.target_ids_str = target_str
                const.value = 0.0
                solve_gcs_external(props, context)
                update_cad_preview(None, context)
                op.report({'INFO'}, f"Lines {l1_id} and {l2_id} constrained {const_type}!")
    else:
        op.report({'WARNING'}, "Select two lines to apply parallel or perpendicular constraint.")
                

def action_constraint_tangent(op, context, props):
    line_id = props.sketch_selected_line_id
    pt_id = props.sketch_selected_point_id
    
    # --- 直感的な選択解釈の試み ---
    selected_pts = []
    if props.sketch_selected_point_id >= 0:
        selected_pts.append(props.sketch_selected_point_id)
    if props.sketch_selected_point_id_2 >= 0:
        selected_pts.append(props.sketch_selected_point_id_2)
        
    selected_lines = []
    if props.sketch_selected_line_id >= 0:
        selected_lines.append(props.sketch_selected_line_id)
    if props.sketch_selected_line_id_2 >= 0:
        selected_lines.append(props.sketch_selected_line_id_2)
        
    pivot_pt_id = -1
    
    # パターン1: 2つの点を選択（直線の端点 + 円・円弧の制御点）
    if len(selected_pts) == 2:
        p1, p2 = selected_pts[0], selected_pts[1]
        
        # p1, p2 に接続する直線を検索
        l1 = next((l for l in props.sketch_lines if (l.start_point_id == p1 or l.end_point_id == p1) and l.id not in selected_lines), None)
        l2 = next((l for l in props.sketch_lines if (l.start_point_id == p2 or l.end_point_id == p2) and l.id not in selected_lines), None)
        
        # p1, p2 が円または円弧の制御点か検索
        c1 = next((c for c in props.sketch_circles if c.center_point_id == p1 or c.radius_point_id == p1), None)
        a1 = next((a for a in props.sketch_arcs if a.start_point_id == p1 or a.end_point_id == p1 or a.mid_point_id == p1), None)
        c2 = next((c for c in props.sketch_circles if c.center_point_id == p2 or c.radius_point_id == p2), None)
        a2 = next((a for a in props.sketch_arcs if a.start_point_id == p2 or a.end_point_id == p2 or a.mid_point_id == p2), None)
        
        if l1 and (c2 or a2):
            line_id = l1.id
            pt_id = p2
            pivot_pt_id = l1.end_point_id if l1.start_point_id == p1 else l1.start_point_id
        elif l2 and (c1 or a1):
            line_id = l2.id
            pt_id = p1
            pivot_pt_id = l2.end_point_id if l2.start_point_id == p2 else l2.start_point_id
            
    # パターン2: 1つの点と1つの線を選択（直線の端点 + 円弧のセグメント線）
    elif len(selected_pts) == 1 and len(selected_lines) == 1:
        p1 = selected_pts[0]
        l1_id = selected_lines[0]
        
        l_obj = next((l for l in props.sketch_lines if l.start_point_id == p1 or l.end_point_id == p1), None)
        arc_obj = find_arc_by_line_id(props, l1_id)
        
        if l_obj and arc_obj:
            line_id = l_obj.id
            pt_id = arc_obj.mid_point_id
            pivot_pt_id = l_obj.end_point_id if l_obj.start_point_id == p1 else l_obj.start_point_id
            
    # パターン3: フォールバック（2つの線を選択）
    elif line_id >= 0 and props.sketch_selected_line_id_2 >= 0:
        l1_id = line_id
        l2_id = props.sketch_selected_line_id_2
        
        arc1 = find_arc_by_line_id(props, l1_id)
        arc2 = find_arc_by_line_id(props, l2_id)
        
        if arc1 and not arc2:
            line_id = l2_id
            pt_id = arc1.mid_point_id
        elif arc2 and not arc1:
            line_id = l1_id
            pt_id = arc2.mid_point_id
    
    # ピボット点の自動固定（FIXED）を適用
    if pivot_pt_id >= 0:
        has_fixed = False
        for const in props.sketch_constraints:
            if const.type == 'FIXED' and const.target_ids_str.strip() == str(pivot_pt_id):
                has_fixed = True
                break
        if not has_fixed:
            f_const = props.sketch_constraints.add()
            f_const.id = max([c.id for c in props.sketch_constraints] + [0]) + 1
            f_const.type = 'FIXED'
            f_const.target_ids_str = str(pivot_pt_id)
            f_const.value = 0.0
    
    if line_id >= 0 and pt_id >= 0:
        line = next((l for l in props.sketch_lines if l.id == line_id), None)
        if line:
            target_circle = None
            for circ in props.sketch_circles:
                if circ.center_point_id == pt_id or circ.radius_point_id == pt_id:
                    target_circle = circ
                    break
                    
            target_arc = None
            if not target_circle:
                for arc in props.sketch_arcs:
                    if arc.start_point_id == pt_id or arc.end_point_id == pt_id or arc.mid_point_id == pt_id:
                        target_arc = arc
                        break
                        
            if target_circle:
                push_history(props)
                target_str = f"{line.start_point_id},{line.end_point_id},{target_circle.center_point_id},{target_circle.radius_point_id}"
                
                dup = False
                for c in props.sketch_constraints:
                    if c.type == 'TANGENT':
                        parts = [int(x.strip()) for x in c.target_ids_str.split(",") if x.strip()]
                        if len(parts) == 4:
                            s1, e1 = line.start_point_id, line.end_point_id
                            cc, cr = target_circle.center_point_id, target_circle.radius_point_id
                            if ((parts[0] == s1 and parts[1] == e1) or (parts[0] == e1 and parts[1] == s1)) and \
                               parts[2] == cc and parts[3] == cr:
                                dup = True
                                break
                                
                if not dup:
                    const = props.sketch_constraints.add()
                    const.id = max([c.id for c in props.sketch_constraints] + [0]) + 1
                    const.type = 'TANGENT'
                    const.target_ids_str = target_str
                    const.value = 0.0
                    solve_gcs_external(props, context)
                    update_cad_preview(None, context)
                    op.report({'INFO'}, f"Line {line_id} and Circle {target_circle.id} constrained TANGENT!")
                else:
                    op.report({'WARNING'}, "Tangent constraint already exists.")
                    
            elif target_arc:
                push_history(props)
                target_str = f"{line.start_point_id},{line.end_point_id},{target_arc.start_point_id},{target_arc.end_point_id},{target_arc.mid_point_id}"
                
                dup = False
                for c in props.sketch_constraints:
                    if c.type == 'TANGENT':
                        parts = [int(x.strip()) for x in c.target_ids_str.split(",") if x.strip()]
                        if len(parts) == 5:
                            s1, e1 = line.start_point_id, line.end_point_id
                            as_, ae, am = target_arc.start_point_id, target_arc.end_point_id, target_arc.mid_point_id
                            if ((parts[0] == s1 and parts[1] == e1) or (parts[0] == e1 and parts[1] == s1)) and \
                               parts[2] == as_ and parts[3] == ae and parts[4] == am:
                                dup = True
                                break
                                
                if not dup:
                    const = props.sketch_constraints.add()
                    const.id = max([c.id for c in props.sketch_constraints] + [0]) + 1
                    const.type = 'TANGENT'
                    const.target_ids_str = target_str
                    const.value = 0.0
                    solve_gcs_external(props, context)
                    update_cad_preview(None, context)
                    op.report({'INFO'}, f"Line {line_id} and Arc {target_arc.id} constrained TANGENT!")
                else:
                    op.report({'WARNING'}, "Tangent constraint already exists.")
            else:
                op.report({'WARNING'}, "Selected point is not part of any Circle or Arc.")
        else:
            op.report({'WARNING'}, "Selected line is not valid.")
    else:
        op.report({'WARNING'}, "Select one Line and one Point belonging to a Circle or Arc to apply Tangent constraint.")
        

def action_constraint_distance(op, context, props):
    p1_id = props.sketch_selected_point_id
    p2_id = props.sketch_selected_point_id_2
    line_id = props.sketch_selected_line_id
    
    targets = []
    if p1_id >= 0 and p2_id >= 0:
        targets = [p1_id, p2_id]
    elif line_id >= 0:
        line = next((l for l in props.sketch_lines if l.id == line_id), None)
        if line:
            targets = [line.start_point_id, line.end_point_id]
    
    if len(targets) == 2:
        push_history(props)
        target_str = f"{targets[0]},{targets[1]}"
        target_str_rev = f"{targets[1]},{targets[0]}"
        dup = any(c.type == 'DISTANCE' and (c.target_ids_str == target_str or c.target_ids_str == target_str_rev) for c in props.sketch_constraints)
        if not dup:
            pt1 = next((p for p in props.sketch_points if p.id == targets[0]), None)
            pt2 = next((p for p in props.sketch_points if p.id == targets[1]), None)
            if pt1 and pt2:
                dx = pt1.co[0] - pt2.co[0]
                dy = pt1.co[1] - pt2.co[1]
                current_dist = math.sqrt(dx*dx + dy*dy)
                
                const = props.sketch_constraints.add()
                const.id = len(props.sketch_constraints) + 1
                const.type = 'DISTANCE'
                const.target_ids_str = target_str
                const.value = current_dist
                solve_gcs_external(props, context)
                update_cad_preview(None, context)
                op.report({'INFO'}, f"Distance constraint ({current_dist:.3f}) added between point {targets[0]} and {targets[1]}!")
    else:
        op.report({'WARNING'}, "Select two points or one line to apply distance constraint.")


def _two_selected_lines(props):
    """選択中の2本の線を (線1, 線2, "s1,e1,s2,e2") で返す。無ければ None。

    ANGLE / EQUAL は PARALLEL / PERPENDICULAR と同じ「線2本」の選択で、
    Rust 側へ渡す並びも同じ4点。
    """
    l1_id = props.sketch_selected_line_id
    l2_id = props.sketch_selected_line_id_2
    if l1_id < 0 or l2_id < 0:
        return None
    line1 = next((l for l in props.sketch_lines if l.id == l1_id), None)
    line2 = next((l for l in props.sketch_lines if l.id == l2_id), None)
    if not line1 or not line2:
        return None
    target_str = (f"{line1.start_point_id},{line1.end_point_id},"
                  f"{line2.start_point_id},{line2.end_point_id}")
    return (line1, line2, target_str)


def _has_two_line_constraint(props, const_type, line1, line2):
    """同じ2本の線に、同じ種類の拘束が既にあるか。

    どちらの線を先に選んだかで target_ids_str の並びが変わるので、
    線の組み合わせとして一致するかを見る。ここを素通しすると同じ拘束が
    二重に積まれ、過拘束でソルバが解を返さなくなる。
    """
    pair = {(line1.start_point_id, line1.end_point_id),
            (line2.start_point_id, line2.end_point_id)}
    for c in props.sketch_constraints:
        if c.type != const_type:
            continue
        parts = [int(x.strip()) for x in c.target_ids_str.split(",") if x.strip()]
        if len(parts) != 4:
            continue
        if {(parts[0], parts[1]), (parts[2], parts[3])} == pair:
            return True
    return False


def _line_direction(props, line):
    p_start = next((p for p in props.sketch_points if p.id == line.start_point_id), None)
    p_end = next((p for p in props.sketch_points if p.id == line.end_point_id), None)
    if not p_start or not p_end:
        return None
    return (p_end.co[0] - p_start.co[0], p_end.co[1] - p_start.co[1])


def action_constraint_angle(op, context, props):
    """2本の線がなす角を現在値で固定する。あとは数値欄で編集できる。

    角度の測り方は ezpz の LinesAtAngle に合わせる必要がある。あちらの残差は
    `u × rot(θ)⁻¹ · v` で、**線1の向きから線2の向きへ反時計回り**に測った角が θ。
    ここで符号や向きを取り違えると、拘束を付けた瞬間に図形が跳ねる。
    """
    found = _two_selected_lines(props)
    if not found:
        op.report({'WARNING'}, "Select two lines to apply an angle constraint.")
        return
    line1, line2, target_str = found

    if _has_two_line_constraint(props, 'ANGLE', line1, line2):
        op.report({'WARNING'}, "An angle constraint already exists on these two lines.")
        return

    u = _line_direction(props, line1)
    v = _line_direction(props, line2)
    if not u or not v:
        op.report({'WARNING'}, "Could not resolve the lines' points.")
        return
    if math.hypot(*u) < 1e-9 or math.hypot(*v) < 1e-9:
        op.report({'WARNING'}, "A zero-length line has no direction to measure.")
        return

    angle_deg = math.degrees(math.atan2(v[1], v[0]) - math.atan2(u[1], u[0]))
    # (-180, 180] に畳む。畳まないと 350 度のような値が入り、数値欄が読みにくい
    while angle_deg <= -180.0:
        angle_deg += 360.0
    while angle_deg > 180.0:
        angle_deg -= 360.0

    push_history(props)
    const = props.sketch_constraints.add()
    const.id = len(props.sketch_constraints) + 1
    const.type = 'ANGLE'
    const.target_ids_str = target_str
    const.value = angle_deg

    solve_gcs_external(props, context)
    update_cad_preview(None, context)
    op.report({'INFO'}, f"Angle constraint ({angle_deg:.2f} deg) added between lines {line1.id} and {line2.id}!")


def action_constraint_equal(op, context, props):
    """2本の線の長さを揃える。値は取らない。"""
    found = _two_selected_lines(props)
    if not found:
        op.report({'WARNING'}, "Select two lines to make them equal in length.")
        return
    line1, line2, target_str = found

    if _has_two_line_constraint(props, 'EQUAL', line1, line2):
        op.report({'WARNING'}, "These two lines are already constrained equal.")
        return

    push_history(props)
    const = props.sketch_constraints.add()
    const.id = len(props.sketch_constraints) + 1
    const.type = 'EQUAL'
    const.target_ids_str = target_str
    const.value = 0.0

    solve_gcs_external(props, context)
    update_cad_preview(None, context)
    op.report({'INFO'}, f"Lines {line1.id} and {line2.id} constrained to equal length!")


def _circular_centre_of(props, point_id):
    """その点が属する円/円弧の中心点IDを返す。属していなければ None。

    中心点そのものを選んだ場合も、円周上の点を選んだ場合も同じ中心を返す。
    """
    for c in props.sketch_circles:
        if point_id in (c.center_point_id, c.radius_point_id):
            return c.center_point_id
    for a in props.sketch_arcs:
        if point_id in (a.center_point_id, a.start_point_id, a.end_point_id, a.mid_point_id):
            return a.center_point_id
    return None


def action_constraint_concentric(op, context, props):
    """2つの円/円弧の中心を一致させる。

    Coincident(点の統合)とは別物。あちらは点IDを付け替えて片方を消してしまう
    ので、円を2つとも残したまま中心だけ揃えることができない。こちらは点を
    2つとも残す拘束なので、後から解除すれば元の自由度に戻る。
    """
    selected_pts = [int(x) for x in props.sketch_selected_points_str.split(",") if x]
    for pid in (props.sketch_selected_point_id, props.sketch_selected_point_id_2):
        if pid >= 0 and pid not in selected_pts:
            selected_pts.append(pid)

    centres = []
    for pid in selected_pts:
        c = _circular_centre_of(props, pid)
        if c is not None and c not in centres:
            centres.append(c)

    if len(centres) < 2:
        op.report({'WARNING'}, "Select points on two different circles or arcs.")
        return

    c1, c2 = centres[0], centres[1]
    pair = {c1, c2}
    for c in props.sketch_constraints:
        if c.type != 'CONCENTRIC':
            continue
        parts = [int(x.strip()) for x in c.target_ids_str.split(",") if x.strip()]
        if len(parts) == 2 and set(parts) == pair:
            op.report({'WARNING'}, "These two are already concentric.")
            return

    push_history(props)
    const = props.sketch_constraints.add()
    const.id = len(props.sketch_constraints) + 1
    const.type = 'CONCENTRIC'
    const.target_ids_str = f"{c1},{c2}"
    const.value = 0.0

    solve_gcs_external(props, context)
    update_cad_preview(None, context)
    op.report({'INFO'}, f"Centres {c1} and {c2} constrained concentric!")


def action_constraint_symmetric(op, context, props):
    """2点を1本の線について対称にする。

    選択は「線1本 + 点2つ」。Rust へは [軸始点, 軸終点, 点1, 点2] の順で渡す
    (ezpz の Symmetric は (線, 点, 点) の順だが、targets の並びは軸を先頭に
    そろえてある --- ANGLE などと同じく線の端点が先という規則)。
    """
    line_id = props.sketch_selected_line_id
    if line_id < 0:
        op.report({'WARNING'}, "Select a line to mirror across, plus the two points.")
        return
    axis = next((l for l in props.sketch_lines if l.id == line_id), None)
    if not axis:
        op.report({'WARNING'}, "The selected line was not found.")
        return

    axis_pts = {axis.start_point_id, axis.end_point_id}
    selected_pts = [int(x) for x in props.sketch_selected_points_str.split(",") if x]
    for pid in (props.sketch_selected_point_id, props.sketch_selected_point_id_2):
        if pid >= 0 and pid not in selected_pts:
            selected_pts.append(pid)
    # 軸の端点そのものを対称対象にはできない(自明に解けてしまう)
    selected_pts = [p for p in selected_pts if p not in axis_pts]

    if len(selected_pts) < 2:
        op.report({'WARNING'}, "Select two points that are not on the mirror line.")
        return

    p1, p2 = selected_pts[0], selected_pts[1]
    pair = {p1, p2}
    for c in props.sketch_constraints:
        if c.type != 'SYMMETRIC':
            continue
        parts = [int(x.strip()) for x in c.target_ids_str.split(",") if x.strip()]
        if len(parts) == 4 and set(parts[2:]) == pair:
            op.report({'WARNING'}, "These two points are already constrained symmetric.")
            return

    push_history(props)
    const = props.sketch_constraints.add()
    const.id = len(props.sketch_constraints) + 1
    const.type = 'SYMMETRIC'
    const.target_ids_str = f"{axis.start_point_id},{axis.end_point_id},{p1},{p2}"
    const.value = 0.0

    solve_gcs_external(props, context)
    update_cad_preview(None, context)
    op.report({'INFO'}, f"Points {p1} and {p2} constrained symmetric about line {line_id}!")


def _find_radius_target(props, selected_pts):
    """選択された点から、半径を拘束できる円/円弧を1つ選ぶ。

    返すのは (中心点ID, 円周上の点ID, 表示名)。見つからなければ None。

    円は中心と円周上の点の2点で持っている(SeamlessSketchCircle)ので、
    そのどちらか一方が選ばれていればその円を指したと解釈してよい。
    円弧は始点・終点・中点のどれでも同じ扱いにする。中心点だけは特別で、
    円と円弧の両方が同じ中心を共有しうるため最後に見る。
    """
    for p in selected_pts:
        c = next((c for c in props.sketch_circles if c.radius_point_id == p), None)
        if c:
            return (c.center_point_id, c.radius_point_id, f"circle {c.id}")
        a = next((a for a in props.sketch_arcs
                  if p in (a.start_point_id, a.end_point_id, a.mid_point_id)), None)
        if a:
            return (a.center_point_id, p, f"arc {a.id}")

    for p in selected_pts:
        c = next((c for c in props.sketch_circles if c.center_point_id == p), None)
        if c:
            return (c.center_point_id, c.radius_point_id, f"circle {c.id}")
        a = next((a for a in props.sketch_arcs if a.center_point_id == p), None)
        if a:
            return (a.center_point_id, a.start_point_id, f"arc {a.id}")

    return None


def action_constraint_radius(op, context, props):
    """円・円弧の半径を現在値で固定する。あとは数値欄で編集できる。

    RADIUS は Rust 側で CircleRadius + DistanceVar に展開される
    (src_rust/src/api/sketch.rs の "RADIUS" を参照)。Python からは
    targets = [中心点, 円周上の点] の順で渡す約束になっている。
    """
    selected_pts = [int(x) for x in props.sketch_selected_points_str.split(",") if x]
    for pid in (props.sketch_selected_point_id, props.sketch_selected_point_id_2):
        if pid >= 0 and pid not in selected_pts:
            selected_pts.append(pid)

    if not selected_pts:
        op.report({'WARNING'}, "Select a circle or an arc to apply a radius constraint.")
        return

    target = _find_radius_target(props, selected_pts)
    if not target:
        op.report({'WARNING'}, "The selection does not belong to a circle or an arc.")
        return

    center_id, rim_id, label = target
    target_str = f"{center_id},{rim_id}"

    # 同じ円に二重に付けると過拘束になる。中心が同じなら円周上のどの点を
    # 拾ったかに関わらず同じ半径を指しているので、中心IDだけで重複を見る。
    for c in props.sketch_constraints:
        if c.type != 'RADIUS':
            continue
        existing = [x.strip() for x in c.target_ids_str.split(",") if x.strip()]
        if existing and existing[0] == str(center_id):
            op.report({'WARNING'}, f"A radius constraint already exists on {label}.")
            return

    pt_c = next((p for p in props.sketch_points if p.id == center_id), None)
    pt_r = next((p for p in props.sketch_points if p.id == rim_id), None)
    if not pt_c or not pt_r:
        op.report({'WARNING'}, "Could not resolve the circle's points.")
        return

    dx = pt_r.co[0] - pt_c.co[0]
    dy = pt_r.co[1] - pt_c.co[1]
    current_radius = math.sqrt(dx * dx + dy * dy)

    # 半径0は解けない(ヤコビ行列が特異になる)。付ける前に弾く。
    if current_radius < 1e-6:
        op.report({'WARNING'}, "Radius is zero; nothing to constrain.")
        return

    push_history(props)

    const = props.sketch_constraints.add()
    const.id = len(props.sketch_constraints) + 1
    const.type = 'RADIUS'
    const.target_ids_str = target_str
    const.value = current_radius

    solve_gcs_external(props, context)
    update_cad_preview(None, context)
    op.report({'INFO'}, f"Radius constraint ({current_radius:.3f}) added to {label}!")


def action_constraint_midpoint(op, context, props):
    sel_pts = [int(x) for x in props.sketch_selected_points_str.split(",") if x]
    sel_lines = [int(x) for x in props.sketch_selected_lines_str.split(",") if x]

    targets = []
    if len(sel_pts) >= 3:
        targets = [sel_pts[0], sel_pts[1], sel_pts[2]]
    elif len(sel_pts) >= 1 and len(sel_lines) >= 1:
        line = next((l for l in props.sketch_lines if l.id == sel_lines[0]), None)
        if line:
            targets = [line.start_point_id, line.end_point_id, sel_pts[0]]
    elif props.sketch_selected_point_id >= 0 and props.sketch_selected_point_id_2 >= 0:
        third_id = next(
            (
                pt.id for pt in props.sketch_points
                if pt.id not in {props.sketch_selected_point_id, props.sketch_selected_point_id_2}
                and pt.id in sel_pts
            ),
            -1
        )
        if third_id >= 0:
            targets = [props.sketch_selected_point_id, props.sketch_selected_point_id_2, third_id]

    if len(targets) != 3:
        op.report({'WARNING'}, "Select two end points and one midpoint, or one line and one point.")
        return

    p1_id, p2_id, pm_id = targets
    if pm_id in {p1_id, p2_id}:
        op.report({'WARNING'}, "Midpoint must be different from the two end points.")
        return

    target_str = f"{p1_id},{p2_id},{pm_id}"
    target_str_rev = f"{p2_id},{p1_id},{pm_id}"
    dup = any(
        c.type == 'MIDPOINT' and c.target_ids_str in {target_str, target_str_rev}
        for c in props.sketch_constraints
    )
    if dup:
        op.report({'WARNING'}, "Midpoint constraint already exists.")
        return

    push_history(props)
    const = props.sketch_constraints.add()
    const.id = max([c.id for c in props.sketch_constraints] + [0]) + 1
    const.type = 'MIDPOINT'
    const.target_ids_str = target_str
    const.value = 0.0
    solve_gcs_external(props, context)
    update_cad_preview(None, context)
    op.report({'INFO'}, f"Midpoint constraint added to {pm_id}.")


def action_constraint_coincident_merge(op, context, props):
    selected_point_ids = [int(x) for x in props.sketch_selected_points_str.split(",") if x]
    selected_point_ids = [pid for pid in selected_point_ids if pid >= 0]
    if len(selected_point_ids) < 2:
        op.report({'WARNING'}, "Select two or more points to merge coincident.")
        return

    keeper_id = props.sketch_selected_point_id if props.sketch_selected_point_id in selected_point_ids else selected_point_ids[0]
    merged_ids = [pid for pid in selected_point_ids if pid != keeper_id]
    if not merged_ids:
        op.report({'WARNING'}, "Select two or more distinct points to merge coincident.")
        return

    keeper_pt = next((pt for pt in props.sketch_points if pt.id == keeper_id), None)
    if not keeper_pt:
        op.report({'WARNING'}, "Primary point for coincident merge was not found.")
        return

    push_history(props)

    def remap_point_id(point_id):
        return keeper_id if point_id in merged_ids else point_id

    for line in props.sketch_lines:
        line.start_point_id = remap_point_id(line.start_point_id)
        line.end_point_id = remap_point_id(line.end_point_id)

    for circle in props.sketch_circles:
        circle.center_point_id = remap_point_id(circle.center_point_id)
        circle.radius_point_id = remap_point_id(circle.radius_point_id)

    for arc in props.sketch_arcs:
        arc.center_point_id = remap_point_id(arc.center_point_id)
        arc.start_point_id = remap_point_id(arc.start_point_id)
        arc.end_point_id = remap_point_id(arc.end_point_id)
        arc.mid_point_id = remap_point_id(arc.mid_point_id)

    constraint_payloads = []
    seen_constraints = set()
    for const in props.sketch_constraints:
        try:
            target_ids = [int(x.strip()) for x in const.target_ids_str.split(",") if x.strip()]
        except ValueError:
            continue
        remapped_targets = [remap_point_id(point_id) for point_id in target_ids]

        if const.type in {'DISTANCE', 'HORIZONTAL', 'VERTICAL'} and len(set(remapped_targets)) < 2:
            continue
        if const.type == 'MIDPOINT' and len(set(remapped_targets)) < 3:
            continue

        key = (const.type, tuple(remapped_targets), round(float(const.value), 9))
        if key in seen_constraints:
            continue
        seen_constraints.add(key)
        constraint_payloads.append((const.id, const.type, remapped_targets, float(const.value)))

    points_to_keep = [pt for pt in props.sketch_points if pt.id not in merged_ids]
    props.sketch_points.clear()
    for pt in points_to_keep:
        new_pt = props.sketch_points.add()
        new_pt.id = pt.id
        new_pt.co = pt.co[:]
        new_pt.is_segment = pt.is_segment

    deduped_lines = []
    seen_line_pairs = set()
    for line in props.sketch_lines:
        if line.start_point_id == line.end_point_id:
            continue
        pair = tuple(sorted((line.start_point_id, line.end_point_id)))
        if pair in seen_line_pairs:
            continue
        seen_line_pairs.add(pair)
        deduped_lines.append((line.id, line.start_point_id, line.end_point_id, getattr(line, "is_construction", False)))

    props.sketch_lines.clear()
    for line_id, start_id, end_id, is_construction in deduped_lines:
        new_line = props.sketch_lines.add()
        new_line.id = line_id
        new_line.start_point_id = start_id
        new_line.end_point_id = end_id
        new_line.is_construction = is_construction

    valid_circles = []
    for circle in props.sketch_circles:
        if circle.center_point_id == circle.radius_point_id:
            continue
        valid_circles.append((circle.id, circle.center_point_id, circle.radius_point_id, getattr(circle, "is_construction", False)))

    props.sketch_circles.clear()
    for circle_id, center_id, radius_id, is_construction in valid_circles:
        new_circle = props.sketch_circles.add()
        new_circle.id = circle_id
        new_circle.center_point_id = center_id
        new_circle.radius_point_id = radius_id
        new_circle.is_construction = is_construction

    valid_arcs = []
    for arc in props.sketch_arcs:
        unique_ids = {arc.center_point_id, arc.start_point_id, arc.end_point_id, arc.mid_point_id}
        if len(unique_ids) < 4:
            continue
        valid_arcs.append((
            arc.id,
            arc.center_point_id,
            arc.start_point_id,
            arc.end_point_id,
            arc.mid_point_id,
            getattr(arc, "is_construction", False),
        ))

    props.sketch_arcs.clear()
    for arc_id, center_id, start_id, end_id, mid_id, is_construction in valid_arcs:
        new_arc = props.sketch_arcs.add()
        new_arc.id = arc_id
        new_arc.center_point_id = center_id
        new_arc.start_point_id = start_id
        new_arc.end_point_id = end_id
        new_arc.mid_point_id = mid_id
        new_arc.is_construction = is_construction

    props.sketch_constraints.clear()
    for const_id, const_type, target_ids, value in constraint_payloads:
        new_const = props.sketch_constraints.add()
        new_const.id = const_id
        new_const.type = const_type
        new_const.target_ids_str = ",".join(str(point_id) for point_id in target_ids)
        new_const.value = value

    connected_line_ids = [
        line.id for line in props.sketch_lines
        if keeper_id in {line.start_point_id, line.end_point_id}
    ]
    props.sketch_selected_points_str = str(keeper_id)
    props.sketch_selected_lines_str = ",".join(str(line_id) for line_id in connected_line_ids[:2])
    props.sketch_selected_point_id = keeper_id
    props.sketch_selected_point_id_2 = -1
    props.sketch_selected_line_id = connected_line_ids[0] if connected_line_ids else -1
    props.sketch_selected_line_id_2 = connected_line_ids[1] if len(connected_line_ids) > 1 else -1
    props.sketch_selected_point_x = keeper_pt.co[0]
    props.sketch_selected_point_y = keeper_pt.co[1]

    solve_gcs_external(props, context)
    update_cad_preview(None, context)
    op.report({'INFO'}, f"Merged {len(merged_ids) + 1} points into point {keeper_id}.")
    
