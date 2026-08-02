import bpy
import mathutils
import math
from ... import utils
from ..sketch_history import push_history, perform_undo
from ..sketch_solver import solve_gcs_external, find_arc_by_line_id
from ..sketch_finalize import finalize_sketch, calculate_arc_points, calculate_circle_points, is_point_in_polygon

from ...core_bridge import update_cad_preview


def _find_corner_lines(props, corner_pt_id):
    """corner_pt_idに接続するちょうど2本の線を返す(見つからなければNone, None)。"""
    connected = [l for l in props.sketch_lines if l.start_point_id == corner_pt_id or l.end_point_id == corner_pt_id]
    if len(connected) == 2:
        return connected[0], connected[1]
    return None, None


def _is_corner_eligible(props, corner_pt_id, line1, line2):
    """円弧・円・円弧分割セグメントに接する角にはフィレット/面取りを適用させないための安全ガード。"""
    for arc in props.sketch_arcs:
        if corner_pt_id in {arc.start_point_id, arc.end_point_id, arc.mid_point_id, arc.center_point_id}:
            return False
    for circ in props.sketch_circles:
        if corner_pt_id in {circ.center_point_id, circ.radius_point_id}:
            return False
    point_dict = {p.id: p for p in props.sketch_points}
    corner_pt = point_dict.get(corner_pt_id)
    if corner_pt and corner_pt.is_segment:
        return False
    for l in {line1, line2}:
        other_id = l.end_point_id if l.start_point_id == corner_pt_id else l.start_point_id
        other_pt = point_dict.get(other_id)
        if other_pt and other_pt.is_segment:
            return False
    return True


def _fillet_single_corner(props, corner_pt_id, line1, line2):
    """1つの角にフィレットを適用する(ジオメトリ構築のみ。solve_gcs_external/update_cad_preview
    は呼び出し側でバッチ全体の完了後に一度だけ呼ぶこと)。成功時は(True, R)、失敗時は(False, 理由)を返す。"""
    line1_id = line1.id
    line2_id = line2.id

    pt_a = next((p for p in props.sketch_points if p.id == corner_pt_id), None)
    p1_id = line1.end_point_id if line1.start_point_id == corner_pt_id else line1.start_point_id
    p2_id = line2.end_point_id if line2.start_point_id == corner_pt_id else line2.start_point_id
    pt_b = next((p for p in props.sketch_points if p.id == p1_id), None)
    pt_c = next((p for p in props.sketch_points if p.id == p2_id), None)
    
    if not pt_a or not pt_b or not pt_c:
        return False, "Vertex data not found."

    a_co = mathutils.Vector(pt_a.co)
    b_co = mathutils.Vector(pt_b.co)
    c_co = mathutils.Vector(pt_c.co)

    vec_ab = b_co - a_co
    vec_ac = c_co - a_co
    len_ab = vec_ab.length
    len_ac = vec_ac.length

    if len_ab < 1e-4 or len_ac < 1e-4:
        return False, "Line is too short."

    u = vec_ab.normalized()
    v = vec_ac.normalized()
    dot_val = u.dot(v)
    if abs(dot_val) > 0.999:
        return False, "Lines are nearly colinear, cannot apply fillet."

    theta = math.acos(max(-1.0, min(1.0, dot_val)))
    max_r = min(len_ab, len_ac) * 0.45
    R = min(props.sketch_fillet_radius, max_r)
    if R < 0.001:
        return False, "Fillet radius is too small."

    t_offset = R / math.tan(theta / 2.0)
    d_center = R / math.sin(theta / 2.0)
    w_dir = (u + v).normalized()

    o_co = a_co + d_center * w_dir
    t1_co = a_co + t_offset * u
    t2_co = a_co + t_offset * v
    m_co = o_co - R * w_dir

    max_pt_id = max([p.id for p in props.sketch_points] + [0])
    
    pt_t1 = props.sketch_points.add()
    pt_t1.id = max_pt_id + 1
    pt_t1.co = (t1_co.x, t1_co.y)
    
    pt_t2 = props.sketch_points.add()
    pt_t2.id = max_pt_id + 2
    pt_t2.co = (t2_co.x, t2_co.y)
    
    pt_m = props.sketch_points.add()
    pt_m.id = max_pt_id + 3
    pt_m.co = (m_co.x, m_co.y)
    
    pt_o = props.sketch_points.add()
    pt_o.id = max_pt_id + 4
    pt_o.co = (o_co.x, o_co.y)
    
    # 円弧を構成する16分割直線セグメントの生成
    t1_3d = mathutils.Vector((t1_co.x, t1_co.y, 0.0))
    m_3d = mathutils.Vector((m_co.x, m_co.y, 0.0))
    t2_3d = mathutils.Vector((t2_co.x, t2_co.y, 0.0))
    arc_cos = calculate_arc_points(t1_3d, m_3d, t2_3d, num_segments=16)
    last_pt_id = pt_t1.id
    for pt_co in arc_cos[1:-1]:
        new_pt = props.sketch_points.add()
        new_id = max([p.id for p in props.sketch_points] + [0]) + 1
        new_pt.id = new_id
        new_pt.co = (pt_co.x, pt_co.y)
        new_pt.is_segment = True
        
        line = props.sketch_lines.add()
        line.id = max([l.id for l in props.sketch_lines] + [0]) + 1
        line.start_point_id = last_pt_id
        line.end_point_id = new_id
        
        last_pt_id = new_id
        
    # 終点との接続
    line = props.sketch_lines.add()
    line.id = max([l.id for l in props.sketch_lines] + [0]) + 1
    line.start_point_id = last_pt_id
    line.end_point_id = pt_t2.id
    
    # オブジェクトの再取得 (CollectionProperty追加による参照崩壊防止)
    line1 = next((l for l in props.sketch_lines if l.id == line1_id), None)
    line2 = next((l for l in props.sketch_lines if l.id == line2_id), None)
    
    if line1.start_point_id == corner_pt_id:
        line1.start_point_id = pt_t1.id
    else:
        line1.end_point_id = pt_t1.id
        
    if line2.start_point_id == corner_pt_id:
        line2.start_point_id = pt_t2.id
    else:
        line2.end_point_id = pt_t2.id
        
    id_t1 = pt_t1.id
    id_t2 = pt_t2.id
    id_m = pt_m.id
    id_o = pt_o.id

    new_arc = props.sketch_arcs.add()
    new_arc.id = max([a.id for a in props.sketch_arcs] + [0]) + 1
    new_arc.start_point_id = id_t1
    new_arc.end_point_id = id_t2
    new_arc.mid_point_id = id_m
    new_arc.center_point_id = id_o
    # コーナーフィレット由来の円弧は常に劣弧(内側)を維持する(sketch_solver.py参照)
    new_arc.is_fillet = True
    
    points_to_keep = [{"id": p.id, "co": p.co[:], "is_segment": p.is_segment} for p in props.sketch_points if p.id != corner_pt_id]
    props.sketch_points.clear()
    for p in points_to_keep:
        np = props.sketch_points.add()
        np.id = p["id"]
        np.co = p["co"]
        np.is_segment = p["is_segment"]
        
    constraints_to_keep = []
    for c in props.sketch_constraints:
        keep = True
        try:
            parts = [int(x.strip()) for x in c.target_ids_str.split(",") if x.strip()]
            if corner_pt_id in parts:
                keep = False
        except ValueError:
            pass
        if keep:
            constraints_to_keep.append({
                "id": c.id,
                "type": c.type,
                "target_ids_str": c.target_ids_str,
                "value": c.value
            })
    props.sketch_constraints.clear()
    for c in constraints_to_keep:
        nc = props.sketch_constraints.add()
        nc.id = c["id"]
        nc.type = c["type"]
        nc.target_ids_str = c["target_ids_str"]
        nc.value = c["value"]
        
    c_max_id = max([c.id for c in props.sketch_constraints] + [0])
    
    const_arc = props.sketch_constraints.add()
    const_arc.id = c_max_id + 1
    const_arc.type = 'ARC'
    const_arc.target_ids_str = f"{id_t1},{id_t2},{id_m},{id_o}"
    const_arc.value = 0.0
    
    # オブジェクトの再取得 (CollectionProperty追加による参照崩壊防止)
    line1 = next((l for l in props.sketch_lines if l.id == line1_id), None)
    line2 = next((l for l in props.sketch_lines if l.id == line2_id), None)
    
    const_tang1 = props.sketch_constraints.add()
    const_tang1.id = c_max_id + 2
    const_tang1.type = 'PERPENDICULAR'
    const_tang1.target_ids_str = f"{line1.start_point_id},{line1.end_point_id},{id_o},{id_t1}"
    const_tang1.value = 0.0
    
    const_tang2 = props.sketch_constraints.add()
    const_tang2.id = c_max_id + 3
    const_tang2.type = 'PERPENDICULAR'
    const_tang2.target_ids_str = f"{line2.start_point_id},{line2.end_point_id},{id_o},{id_t2}"
    const_tang2.value = 0.0
    
    const_rad = props.sketch_constraints.add()
    const_rad.id = c_max_id + 4
    const_rad.type = 'DISTANCE'
    const_rad.target_ids_str = f"{id_o},{id_m}"
    const_rad.value = R

    return True, R


def action_corner_fillet(op, context, props):
    """単一コーナー選択時は従来通り1角のみに、複数コーナー選択時
    (sketch_selected_points_str に2件以上)はまとめて全コーナーに適用する。
    バッチ全体で solve_gcs_external / update_cad_preview は最後に1回だけ呼ぶ
    (角ごとに再ソルブしないことで、付与順序によるジオメトリの手順依存を減らす)。"""
    try:
        multi_ids = sorted({int(x.strip()) for x in props.sketch_selected_points_str.split(",") if x.strip()})
    except ValueError:
        multi_ids = []

    push_history(props)

    if len(multi_ids) >= 2:
        # バッチモード: 選択された各点のうち「角」として有効なものだけに適用する
        succeeded = 0
        skipped = 0
        last_r = None
        for pid in multi_ids:
            line1, line2 = _find_corner_lines(props, pid)
            if not line1 or not line2 or not _is_corner_eligible(props, pid, line1, line2):
                skipped += 1
                continue
            ok, result = _fillet_single_corner(props, pid, line1, line2)
            if ok:
                succeeded += 1
                last_r = result
            else:
                skipped += 1

        props.sketch_selected_point_id = -1
        props.sketch_selected_point_id_2 = -1
        props.sketch_selected_line_id = -1
        props.sketch_selected_line_id_2 = -1
        props.sketch_selected_points_str = ""

        if succeeded == 0:
            op.report({'WARNING'}, f"No eligible corners among {len(multi_ids)} selected points.")
            return {'CANCELLED'}

        solve_gcs_external(props, context)
        update_cad_preview(None, context)
        if skipped:
            op.report({'INFO'}, f"Fillet applied to {succeeded} corner(s), skipped {skipped} ineligible.")
        else:
            op.report({'INFO'}, f"Fillet applied to {succeeded} corner(s) (R={last_r:.3f}).")
        return {'FINISHED'}

    # 単一コーナー(従来の挙動): 選択された1点、または共有点を持つ2本の線から角を特定する
    corner_pt_id = -1
    line1 = None
    line2 = None

    if props.sketch_selected_point_id >= 0:
        p_id = props.sketch_selected_point_id
        line1, line2 = _find_corner_lines(props, p_id)
        if line1 and line2:
            corner_pt_id = p_id
    elif props.sketch_selected_line_id >= 0 and props.sketch_selected_line_id_2 >= 0:
        l1 = next((l for l in props.sketch_lines if l.id == props.sketch_selected_line_id), None)
        l2 = next((l for l in props.sketch_lines if l.id == props.sketch_selected_line_id_2), None)
        if l1 and l2:
            l1_ends = {l1.start_point_id, l1.end_point_id}
            l2_ends = {l2.start_point_id, l2.end_point_id}
            shared = l1_ends.intersection(l2_ends)
            if len(shared) == 1:
                corner_pt_id = list(shared)[0]
                line1 = l1
                line2 = l2

    if corner_pt_id < 0 or not line1 or not line2:
        op.report({'WARNING'}, "Select a corner vertex or two sharing lines to apply fillet.")
        return {'CANCELLED'}

    if not _is_corner_eligible(props, corner_pt_id, line1, line2):
        op.report({'WARNING'}, "Fillet cannot be applied to corners with arcs or circles.")
        return {'CANCELLED'}

    ok, result = _fillet_single_corner(props, corner_pt_id, line1, line2)

    props.sketch_selected_point_id = -1
    props.sketch_selected_point_id_2 = -1
    props.sketch_selected_line_id = -1
    props.sketch_selected_line_id_2 = -1

    if not ok:
        op.report({'WARNING'}, result)
        return {'CANCELLED'}

    solve_gcs_external(props, context)
    update_cad_preview(None, context)
    op.report({'INFO'}, f"Fillet (R={result:.3f}) applied to corner!")
    return {'FINISHED'}


def action_corner_chamfer(op, context, props):
    corner_pt_id = -1
    line1 = None
    line2 = None
    
    if props.sketch_selected_point_id >= 0:
        p_id = props.sketch_selected_point_id
        connected = [l for l in props.sketch_lines if l.start_point_id == p_id or l.end_point_id == p_id]
        if len(connected) == 2:
            corner_pt_id = p_id
            line1 = connected[0]
            line2 = connected[1]
    elif props.sketch_selected_line_id >= 0 and props.sketch_selected_line_id_2 >= 0:
        l1 = next((l for l in props.sketch_lines if l.id == props.sketch_selected_line_id), None)
        l2 = next((l for l in props.sketch_lines if l.id == props.sketch_selected_line_id_2), None)
        if l1 and l2:
            l1_ends = {l1.start_point_id, l1.end_point_id}
            l2_ends = {l2.start_point_id, l2.end_point_id}
            shared = l1_ends.intersection(l2_ends)
            if len(shared) == 1:
                corner_pt_id = list(shared)[0]
                line1 = l1
                line2 = l2
    
    if corner_pt_id < 0 or not line1 or not line2:
        op.report({'WARNING'}, "Select a corner vertex or two sharing lines to apply chamfer.")
        return {'CANCELLED'}
        
    # 円弧または円を含む角には面取りを適用させないための安全ガード
    is_arc_or_circle = False
    for arc in props.sketch_arcs:
        if corner_pt_id in {arc.start_point_id, arc.end_point_id, arc.mid_point_id, arc.center_point_id}:
            is_arc_or_circle = True
            break
    if not is_arc_or_circle:
        for circ in props.sketch_circles:
            if corner_pt_id in {circ.center_point_id, circ.radius_point_id}:
                is_arc_or_circle = True
                break
    if not is_arc_or_circle:
        point_dict = {p.id: p for p in props.sketch_points}
        corner_pt = point_dict.get(corner_pt_id)
        if corner_pt and corner_pt.is_segment:
            is_arc_or_circle = True
        else:
            for l in {line1, line2}:
                other_id = l.end_point_id if l.start_point_id == corner_pt_id else l.start_point_id
                other_pt = point_dict.get(other_id)
                if other_pt and other_pt.is_segment:
                    is_arc_or_circle = True
                    break
                    
    if is_arc_or_circle:
        op.report({'WARNING'}, "Chamfer cannot be applied to corners with arcs or circles.")
        return {'CANCELLED'}
        
    pt_a = next((p for p in props.sketch_points if p.id == corner_pt_id), None)
    p1_id = line1.end_point_id if line1.start_point_id == corner_pt_id else line1.start_point_id
    p2_id = line2.end_point_id if line2.start_point_id == corner_pt_id else line2.start_point_id
    pt_b = next((p for p in props.sketch_points if p.id == p1_id), None)
    pt_c = next((p for p in props.sketch_points if p.id == p2_id), None)
    
    if not pt_a or not pt_b or not pt_c:
        op.report({'WARNING'}, "Vertex data not found.")
        return {'CANCELLED'}
        
    a_co = mathutils.Vector(pt_a.co)
    b_co = mathutils.Vector(pt_b.co)
    c_co = mathutils.Vector(pt_c.co)
    
    vec_ab = b_co - a_co
    vec_ac = c_co - a_co
    len_ab = vec_ab.length
    len_ac = vec_ac.length
    
    if len_ab < 1e-4 or len_ac < 1e-4:
        op.report({'WARNING'}, "Line is too short.")
        return {'CANCELLED'}
        
    u = vec_ab.normalized()
    v = vec_ac.normalized()
    dot_val = u.dot(v)
    if abs(dot_val) > 0.999:
        op.report({'WARNING'}, "Lines are nearly colinear, cannot apply chamfer.")
        return {'CANCELLED'}
        
    max_c = min(len_ab, len_ac) * 0.45
    C = min(props.sketch_chamfer_distance, max_c)
    if C < 0.001:
        op.report({'WARNING'}, "Chamfer distance is too small.")
        return {'CANCELLED'}
        
    t1_co = a_co + C * u
    t2_co = a_co + C * v
    
    push_history(props)
    max_pt_id = max([p.id for p in props.sketch_points] + [0])
    
    pt_t1 = props.sketch_points.add()
    pt_t1.id = max_pt_id + 1
    pt_t1.co = (t1_co.x, t1_co.y)
    
    pt_t2 = props.sketch_points.add()
    pt_t2.id = max_pt_id + 2
    pt_t2.co = (t2_co.x, t2_co.y)
    
    if line1.start_point_id == corner_pt_id:
        line1.start_point_id = pt_t1.id
    else:
        line1.end_point_id = pt_t1.id
        
    if line2.start_point_id == corner_pt_id:
        line2.start_point_id = pt_t2.id
    else:
        line2.end_point_id = pt_t2.id
        
    new_line = props.sketch_lines.add()
    new_line.id = max([l.id for l in props.sketch_lines] + [0]) + 1
    new_line.start_point_id = pt_t1.id
    new_line.end_point_id = pt_t2.id
    
    points_to_keep = [{"id": p.id, "co": p.co[:], "is_segment": p.is_segment} for p in props.sketch_points if p.id != corner_pt_id]
    props.sketch_points.clear()
    for p in points_to_keep:
        np = props.sketch_points.add()
        np.id = p["id"]
        np.co = p["co"]
        np.is_segment = p["is_segment"]
        
    constraints_to_keep = []
    for c in props.sketch_constraints:
        keep = True
        try:
            parts = [int(x.strip()) for x in c.target_ids_str.split(",") if x.strip()]
            if corner_pt_id in parts:
                keep = False
        except ValueError:
            pass
        if keep:
            constraints_to_keep.append({
                "id": c.id,
                "type": c.type,
                "target_ids_str": c.target_ids_str,
                "value": c.value
            })
    props.sketch_constraints.clear()
    for c in constraints_to_keep:
        nc = props.sketch_constraints.add()
        nc.id = c["id"]
        nc.type = c["type"]
        nc.target_ids_str = c["target_ids_str"]
        nc.value = c["value"]
    
    c_max_id = max([c.id for c in props.sketch_constraints] + [0])
    const_len = props.sketch_constraints.add()
    const_len.id = c_max_id + 1
    const_len.type = 'DISTANCE'
    const_len.target_ids_str = f"{pt_t1.id},{pt_t2.id}"
    const_len.value = (t1_co - t2_co).length
    
    props.sketch_selected_point_id = -1
    props.sketch_selected_point_id_2 = -1
    props.sketch_selected_line_id = -1
    props.sketch_selected_line_id_2 = -1
    
    solve_gcs_external(props, context)
    update_cad_preview(None, context)
    op.report({'INFO'}, f"Chamfer (C={C:.3f}) applied to corner!")
    
