import bpy
import bmesh
import math
import mathutils
import json
import collections
from . import sketch_globals
from ..core_bridge import update_cad_preview
from .. import utils

def is_point_in_polygon(x, y, poly_pts):
    n = len(poly_pts)
    inside = False
    if n < 3:
        return False
    p1x, p1y = poly_pts[0][0], poly_pts[0][1]
    for i in range(n + 1):
        p2x, p2y = poly_pts[i % n][0], poly_pts[i % n][1]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xints = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xints:
                        inside = not inside
        p1x, p1y = p2x, p2y
    return inside


def transform_point(mat, co):
    v = mat @ mathutils.Vector(co)
    return (v.x, v.y, v.z)


def transform_direction(mat, direction):
    v = mat.to_3x3() @ mathutils.Vector(direction)
    if v.length > 1e-8:
        v.normalize()
    return (v.x, v.y, v.z)


def transform_segments(mat, segments):
    transformed = []
    for seg in segments:
        out = dict(seg)
        for key in ("start", "end", "mid", "center"):
            if seg.get(key) is not None:
                out[key] = list(transform_point(mat, seg[key]))
        if seg.get("normal") is not None:
                out["normal"] = list(transform_direction(mat, seg["normal"]))
        transformed.append(out)
    return transformed


def add_standalone_arc_primitive(props, pt_dict, mat, ref_rot, arc, sketch_uuid=""):
    if (
        arc.center_point_id not in pt_dict
        or arc.start_point_id not in pt_dict
        or arc.end_point_id not in pt_dict
        or arc.mid_point_id not in pt_dict
    ):
        return

    s_co = pt_dict[arc.start_point_id]
    e_co = pt_dict[arc.end_point_id]
    m_co = pt_dict[arc.mid_point_id]

    p1 = mathutils.Vector(s_co)
    p2 = mathutils.Vector(m_co)
    p3 = mathutils.Vector(e_co)
    d = 2.0 * (p1.x * (p2.y - p3.y) + p2.x * (p3.y - p1.y) + p3.x * (p1.y - p2.y))
    if abs(d) > 1e-6:
        ox = ((p1.x**2 + p1.y**2) * (p2.y - p3.y) + (p2.x**2 + p2.y**2) * (p3.y - p1.y) + (p3.x**2 + p3.y**2) * (p1.y - p2.y)) / d
        oy = ((p1.x**2 + p1.y**2) * (p3.x - p2.x) + (p2.x**2 + p2.y**2) * (p1.x - p3.x) + (p3.x**2 + p3.y**2) * (p2.x - p1.x)) / d
        c_co = (ox, oy, 0.0)
    else:
        c_co = pt_dict[arc.center_point_id]

    dx = s_co[0] - c_co[0]
    dy = s_co[1] - c_co[1]
    radius = math.sqrt(dx * dx + dy * dy)

    v_start = mathutils.Vector((s_co[0] - c_co[0], s_co[1] - c_co[1]))
    v_mid = mathutils.Vector((m_co[0] - c_co[0], m_co[1] - c_co[1]))
    v_end = mathutils.Vector((e_co[0] - c_co[0], e_co[1] - c_co[1]))

    deg_start = math.degrees(math.atan2(v_start.y, v_start.x)) % 360
    deg_mid = math.degrees(math.atan2(v_mid.y, v_mid.x)) % 360
    deg_end = math.degrees(math.atan2(v_end.y, v_end.x)) % 360

    cross = (m_co[0] - s_co[0]) * (e_co[1] - s_co[1]) - (m_co[1] - s_co[1]) * (e_co[0] - s_co[0])

    if cross > 0:
        angle_start = deg_start
        angle_end = deg_end
        if angle_end < angle_start:
            angle_end += 360.0
    else:
        angle_start = deg_end
        angle_end = deg_start
        if angle_end < angle_start:
            angle_end += 360.0

    prim = props.primitives.add()
    prim.name = "Sketch Arc"
    prim.type = 'ARC'
    prim.operation = 'ADD'
    prim.location = transform_point(mat, c_co)
    prim.rotation = ref_rot.to_euler('XYZ')
    prim.radius = radius
    prim.angle_start = angle_start
    prim.angle_end = angle_end
    prim.fill_closed = False
    prim.sketch_source_uuid = sketch_uuid

def finalize_sketch(context, props, sketch_uuid=None):
    import json
    if len(props.sketch_points) == 0:
        return

    # V8.1.5: スケッチ編集履歴 - このfinalizeで生成される全primitiveに同じsketch_uuidを
    # タグ付けする(Edit Sketchでの再finalize時は既存のuuidを渡して in-place 更新に使う)。
    if not sketch_uuid:
        import uuid as _uuid_mod
        sketch_uuid = str(_uuid_mod.uuid4())[:8]

    mat = sketch_globals._reference_matrix if sketch_globals._reference_matrix else mathutils.Matrix.Identity(4)
    ref_loc, ref_rot, _ = mat.decompose()

    pt_dict = {pt.id: (pt.co[0], pt.co[1], 0.0) for pt in props.sketch_points}
    loops = []

    # 1. 円(sketch_circles)を閉ループとして追加
    for circ in props.sketch_circles:
        if getattr(circ, "is_construction", False):
            continue
        if circ.center_point_id in pt_dict and circ.radius_point_id in pt_dict:
            c_co = pt_dict[circ.center_point_id]
            r_co = pt_dict[circ.radius_point_id]
            
            dx = r_co[0] - c_co[0]
            dy = r_co[1] - c_co[1]
            radius = math.sqrt(dx*dx + dy*dy)
            
            num_segs = 32
            circ_pts = []
            for j in range(num_segs):
                theta = 2.0 * math.pi * j / num_segs
                circ_pts.append((c_co[0] + radius * math.cos(theta), c_co[1] + radius * math.sin(theta), 0.0))
            circ_pts.append(circ_pts[0])
            
            segments = [{
                "type": "CIRCLE",
                "center": list(c_co),
                "radius": radius,
                "normal": [0.0, 0.0, 1.0]
            }]
            
            loops.append({
                'points': circ_pts,
                'segments': segments,
                'area': math.pi * radius * radius,
                'rep': (c_co[0], c_co[1])
            })

    # 1.5 独立した円弧の実体化と、論理エッジ的抽出
    pt_is_segment = {pt.id: pt.is_segment for pt in props.sketch_points}
    arc_segment_lines = set()
    arc_segment_line_ids_by_arc = {}
    standalone_arc_ids = set()
    
    import collections
    line_adj = collections.defaultdict(list)
    for line in props.sketch_lines:
        if getattr(line, "is_construction", False):
            continue
        line_adj[line.start_point_id].append((line.end_point_id, line.id))
        line_adj[line.end_point_id].append((line.start_point_id, line.id))
        
    arc_adj = collections.defaultdict(list)
    for arc in props.sketch_arcs:
        if getattr(arc, "is_construction", False):
            continue
        arc_adj[arc.start_point_id].append(arc.id)
        arc_adj[arc.end_point_id].append(arc.id)

    def collect_arc_segment_line_ids(arc):
        s_id = arc.start_point_id
        e_id = arc.end_point_id
        if s_id == e_id:
            return []

        stack = [(s_id, [], {s_id})]
        while stack:
            node, curr_lines, visited = stack.pop()
            if node == e_id:
                return curr_lines

            segment_neighbors = []
            direct_end_neighbors = []
            for next_id, line_id in line_adj[node]:
                if line_id in curr_lines:
                    continue
                if next_id == e_id:
                    direct_end_neighbors.append((next_id, line_id))
                elif pt_is_segment.get(next_id, False):
                    segment_neighbors.append((next_id, line_id))

            for next_id, line_id in direct_end_neighbors:
                if next_id not in visited:
                    stack.append((next_id, curr_lines + [line_id], visited | {next_id}))
            for next_id, line_id in reversed(segment_neighbors):
                if next_id not in visited:
                    stack.append((next_id, curr_lines + [line_id], visited | {next_id}))

        return []

    for arc in props.sketch_arcs:
        if getattr(arc, "is_construction", False):
            continue
        s_id = arc.start_point_id
        e_id = arc.end_point_id
        
        path_lines = collect_arc_segment_line_ids(arc)
        arc_segment_line_ids_by_arc[arc.id] = set(path_lines)
        arc_segment_lines.update(path_lines)

        stack = []
        visited = {s_id}
        while stack:
            node, curr_lines = stack.pop()
            if node == e_id:
                path_lines = curr_lines
                break
            for n, l_id in line_adj[node]:
                if l_id in arc_segment_lines:
                    continue
                if n not in visited:
                    if n != e_id and not pt_is_segment.get(n, False):
                        continue
                    visited.add(n)
                    stack.append((n, curr_lines + [l_id]))
                    
        if path_lines:
            for l_id in path_lines:
                arc_segment_lines.add(l_id)
                
        # 独立円弧判定 (両端が普通の線と繋がっていない)
        start_connected = False
        end_connected = False
        for n, l_id in line_adj[s_id]:
            if not pt_is_segment.get(n, False) and l_id not in path_lines:
                start_connected = True
        if len(arc_adj.get(s_id, [])) > 1:
            start_connected = True
        for n, l_id in line_adj[e_id]:
            if not pt_is_segment.get(n, False) and l_id not in path_lines:
                end_connected = True
        if len(arc_adj.get(e_id, [])) > 1:
            end_connected = True

        start_connected = any(
            line_id not in arc_segment_line_ids_by_arc[arc.id]
            for _, line_id in line_adj[s_id]
        )
        end_connected = any(
            line_id not in arc_segment_line_ids_by_arc[arc.id]
            for _, line_id in line_adj[e_id]
        )
        if len(arc_adj.get(s_id, [])) > 1:
            start_connected = True
        if len(arc_adj.get(e_id, [])) > 1:
            end_connected = True
                
        if not start_connected and not end_connected:
            standalone_arc_ids.add(arc.id)
            # 独立円弧はARCプリミティブとする
            if False and arc.center_point_id in pt_dict and arc.start_point_id in pt_dict and arc.end_point_id in pt_dict and arc.mid_point_id in pt_dict:
                s_co = pt_dict[arc.start_point_id]
                e_co = pt_dict[arc.end_point_id]
                m_co = pt_dict[arc.mid_point_id]
                
                # グリッドスナップ等で座標が変更されている可能性を考慮し、中心と半径を再計算
                p1 = mathutils.Vector(s_co)
                p2 = mathutils.Vector(m_co)
                p3 = mathutils.Vector(e_co)
                d = 2.0 * (p1.x * (p2.y - p3.y) + p2.x * (p3.y - p1.y) + p3.x * (p1.y - p2.y))
                if abs(d) > 1e-6:
                    ox = ((p1.x**2 + p1.y**2) * (p2.y - p3.y) + (p2.x**2 + p2.y**2) * (p3.y - p1.y) + (p3.x**2 + p3.y**2) * (p1.y - p2.y)) / d
                    oy = ((p1.x**2 + p1.y**2) * (p3.x - p2.x) + (p2.x**2 + p2.y**2) * (p1.x - p3.x) + (p3.x**2 + p3.y**2) * (p2.x - p1.x)) / d
                    c_co = (ox, oy, 0.0)
                else:
                    c_co = pt_dict[arc.center_point_id]
                
                dx = s_co[0] - c_co[0]
                dy = s_co[1] - c_co[1]
                radius = math.sqrt(dx*dx + dy*dy)
                
                v_start = mathutils.Vector((s_co[0] - c_co[0], s_co[1] - c_co[1]))
                v_mid   = mathutils.Vector((m_co[0] - c_co[0], m_co[1] - c_co[1]))
                v_end   = mathutils.Vector((e_co[0] - c_co[0], e_co[1] - c_co[1]))
                
                deg_start = math.degrees(math.atan2(v_start.y, v_start.x)) % 360
                deg_mid   = math.degrees(math.atan2(v_mid.y, v_mid.x)) % 360
                deg_end   = math.degrees(math.atan2(v_end.y, v_end.x)) % 360
                
                cross = (m_co[0] - s_co[0]) * (e_co[1] - s_co[1]) - (m_co[1] - s_co[1]) * (e_co[0] - s_co[0])
                
                if cross > 0:
                    angle_start = deg_start
                    angle_end = deg_end
                    if angle_end < angle_start:
                        angle_end += 360.0
                else:
                    angle_start = deg_end
                    angle_end = deg_start
                    if angle_end < angle_start:
                        angle_end += 360.0
                
                prim = props.primitives.add()
                prim.name = "Sketch Arc"
                prim.type = 'ARC'
                prim.operation = 'ADD'
                prim.location = transform_point(mat, c_co)
                prim.rotation = ref_rot.to_euler('XYZ')
                prim.radius = radius
                prim.angle_start = angle_start
                prim.angle_end = angle_end
                prim.fill_closed = False

    # 2. 論理エッジ(直線・接続円弧)をたどってポリライン/面を構築
    edges = []
    for line in props.sketch_lines:
        if getattr(line, "is_construction", False):
            continue
        if line.id in arc_segment_lines:
            continue
        if line.start_point_id in pt_dict and line.end_point_id in pt_dict:
            edges.append((line.start_point_id, line.end_point_id, 'LINE', line))
            
    for arc in props.sketch_arcs:
        if getattr(arc, "is_construction", False):
            continue
        s_id = arc.start_point_id
        e_id = arc.end_point_id
        
        # 独立円弧でないか確認
        start_connected = False
        end_connected = False
        for n, l_id in line_adj[s_id]:
            if not pt_is_segment.get(n, False):
                start_connected = True
        if len(arc_adj.get(s_id, [])) > 1:
            start_connected = True
        for n, l_id in line_adj[e_id]:
            if not pt_is_segment.get(n, False):
                end_connected = True
        if len(arc_adj.get(e_id, [])) > 1:
            end_connected = True
                
        if arc.id in standalone_arc_ids:
            continue
        if start_connected or end_connected:
            if s_id in pt_dict and e_id in pt_dict:
                edges.append((s_id, e_id, 'ARC', arc))

    open_curves = []
    if edges:
        adj = collections.defaultdict(list)
        for u, v, etype, obj in edges:
            adj[u].append((v, etype, obj))
            adj[v].append((u, etype, obj))
            
        visited_edges = set()
        polylines = []
        
        for u, v, etype, obj in edges:
            edge_key = (tuple(sorted((u, v))), etype, getattr(obj, "id", 0))
            if edge_key in visited_edges:
                continue
                
            current_path = [u, v]
            current_edges = [(u, v, etype, obj)]
            visited_edges.add(edge_key)
            current_node = v
            while True:
                neighbors = adj[current_node]
                next_node = None
                next_edge_info = None
                for n, n_etype, n_obj in neighbors:
                    e_key = (tuple(sorted((current_node, n))), n_etype, getattr(n_obj, "id", 0))
                    if e_key not in visited_edges:
                        next_node = n
                        next_edge_info = (current_node, n, n_etype, n_obj)
                        visited_edges.add(e_key)
                        break
                if next_node is not None:
                    current_path.append(next_node)
                    current_edges.append(next_edge_info)
                    current_node = next_node
                else:
                    break
            polylines.append((current_path, current_edges))

        for path, path_edges in polylines:
            utils.debug_print(f"[DEBUG Finalize] Evaluating polyline: path={path}, length={len(path)}")
            if len(path) < 2:
                continue
            
            is_closed = False
            if path[0] == path[-1]:
                utils.debug_print("[DEBUG Finalize] Polyline is naturally closed.")
                is_closed = True
            else:
                for n, et, ob in adj[path[-1]]:
                    if n == path[0]:
                        e_key = (tuple(sorted((path[-1], path[0]))), et, getattr(ob, "id", 0))
                        if e_key not in visited_edges:
                            utils.debug_print(f"[DEBUG Finalize] Force closing loop with edge {e_key}")
                            is_closed = True
                            path.append(path[0])
                            path_edges.append((path[-2], path[-1], et, ob))
                            visited_edges.add(e_key)
                        break
            utils.debug_print(f"[DEBUG Finalize] Final is_closed={is_closed}, path={path}")

            path_pts = []
            segments_json = []
            
            for (u, v, etype, obj) in path_edges:
                u_co = pt_dict[u]
                v_co = pt_dict[v]
                
                if etype == 'LINE':
                    segments_json.append({
                        "type": "LINE",
                        "start": list(u_co),
                        "end": list(v_co)
                    })
                    path_pts.append(u_co)
                elif etype == 'ARC':
                    m_co = pt_dict[obj.mid_point_id]
                    # 進行方向に合わせて ARC の start, mid, end を調整
                    # u_co が ARCのstartかendか確認し、進行方向と一致させる
                    is_reversed = False
                    if list(v_co) == list(pt_dict[obj.start_point_id]):
                        is_reversed = True
                        
                    start_pt = u_co
                    end_pt = v_co
                    
                    segments_json.append({
                        "type": "ARC",
                        "start": list(start_pt),
                        "mid": list(m_co),
                        "end": list(end_pt)
                    })
                    
                    # 面積計算などのPython側処理用にpath_ptsを近似ポリゴンで追加
                    arc_pts = calculate_arc_points(
                        mathutils.Vector(start_pt), 
                        mathutils.Vector(m_co), 
                        mathutils.Vector(end_pt), 
                        num_segments=16
                    )
                    path_pts.extend([(p.x, p.y, p.z) for p in arc_pts[:-1]])
            
            if is_closed:
                path_pts.append(path_pts[0])
                area = 0.0
                n_pts = len(path_pts)
                for k in range(n_pts - 1):
                    area += path_pts[k][0] * path_pts[k+1][1] - path_pts[k+1][0] * path_pts[k][1]
                area = abs(area) * 0.5
                utils.debug_print(f"[DEBUG Finalize] Closed loop area: {area}")
                
                avg_x = sum(p[0] for p in path_pts[:-1]) / (n_pts - 1)
                avg_y = sum(p[1] for p in path_pts[:-1]) / (n_pts - 1)
                
                loops.append({
                    'points': path_pts,
                    'segments': segments_json,
                    'area': area,
                    'rep': (avg_x, avg_y)
                })
            else:
                path_pts.append(pt_dict[path[-1]])
                open_curves.append({
                    'points': path_pts,
                    'segments': segments_json
                })

    # 3. 包含判定による自動島・穴分類
    loops.sort(key=lambda x: x['area'], reverse=True)
    
    islands = []
    for loop in loops:
        parent_island = None
        for island in islands:
            if is_point_in_polygon(loop['rep'][0], loop['rep'][1], island['outer']['points']):
                parent_island = island
                break
        if parent_island:
            parent_island['inners'].append(loop)
        else:
            islands.append({
                'outer': loop,
                'inners': []
            })

    # 4. SURFACE プリミティブの実体化
    log_msg = (
        f"[DEBUG BLENDER FINALIZE]\n"
        f"  Reference Matrix:\n{mat}\n"
        f"  ref_loc = {ref_loc}\n"
        f"  ref_rot (Quat) = {ref_rot}\n"
        f"  ref_rot (Euler XYZ) = {ref_rot.to_euler('XYZ')}\n"
        f"  ref_rot (Euler XZY) = {ref_rot.to_euler('XZY')}\n"
        f"  ref_rot (Euler YXZ) = {ref_rot.to_euler('YXZ')}\n"
        f"  ref_rot (Euler YZX) = {ref_rot.to_euler('YZX')}\n"
        f"  ref_rot (Euler ZXY) = {ref_rot.to_euler('ZXY')}\n"
        f"  ref_rot (Euler ZYX) = {ref_rot.to_euler('ZYX')}\n"
    )
    # デバッグ出力は必ず debug_print 経由にする(設定でON/OFFでき、失敗しない)。
    # ここは以前 open("cad_server_debug.log", "a") を直接呼んでいた。相対パスなので
    # 書き込み先は「Blender を起動した時のカレントディレクトリ」になり、開発機では
    # たまたま書けるが、スタートメニューから起動した利用者では Program Files 等の
    # 書けない場所を指す。try/except も無かったため PermissionError がそのまま
    # 伝播し、スケッチの確定そのものが失敗していた(2026-08-05 利用者報告)。
    utils.debug_print(log_msg)


    for island in islands:
        prim = props.primitives.add()
        prim.location = (0.0, 0.0, 0.0)
        prim.rotation = (0.0, 0.0, 0.0)
        prim.name = "Sketch Surface"
        prim.type = 'SURFACE'
        prim.operation = 'ADD'
        prim.fill_closed = True
        prim.sketch_source_uuid = sketch_uuid
        
        island_segments = transform_segments(mat, island['outer']['segments'])
        
        for co in island['outer']['points']:
            p = prim.points.add()
            p.co = transform_point(mat, co)
             
        for inner in island['inners']:
            dp = prim.points.add()
            dp.co = (1e10, 1e10, 1e10)
             
            island_segments.append({"type": "DELIMITER"})
            island_segments.extend(transform_segments(mat, inner['segments']))
             
            for co in inner['points']:
                p = prim.points.add()
                p.co = transform_point(mat, co)
                 
        prim.segments_json = json.dumps(island_segments)

    # 5. 開いたポリラインは CURVE として実体化
    for curve_data in open_curves:
        prim = props.primitives.add()
        prim.location = (0.0, 0.0, 0.0)
        prim.rotation = (0.0, 0.0, 0.0)
        prim.name = "Sketch Curve"
        prim.type = 'CURVE'
        prim.operation = 'ADD'
        prim.fill_closed = False
        prim.sketch_source_uuid = sketch_uuid
        prim.segments_json = json.dumps(transform_segments(mat, curve_data['segments']))
        for co in curve_data['points']:
            p = prim.points.add()
            p.co = transform_point(mat, co)

    for arc in props.sketch_arcs:
        if getattr(arc, "is_construction", False):
            continue
        if arc.id not in standalone_arc_ids:
            continue
        add_standalone_arc_primitive(props, pt_dict, mat, ref_rot, arc, sketch_uuid=sketch_uuid)

    # V8.1.5: スケッチ編集履歴 - スクラッチデータを破棄する直前に、元のパラメトリック
    # データ(拘束込み)をsketch_snapshotsへ退避する。これにより後からEdit Sketchで
    # 再編集できるようになる(このスナップショット保存自体は既存のfinalize挙動を
    # 一切変更しない、副作用のない追加処理)。
    from .sketch_snapshot import save_sketch_snapshot
    save_sketch_snapshot(props, sketch_uuid)

    props.sketch_points.clear()
    props.sketch_lines.clear()
    props.sketch_circles.clear()
    props.sketch_arcs.clear()
    props.sketch_constraints.clear()
    props.sketch_selected_point_id = -1
    props.sketch_selected_point_id_2 = -1
    props.sketch_selected_line_id = -1
    props.sketch_selected_line_id_2 = -1
    sketch_globals._reference_matrix = None
    update_cad_preview(None, context)

def calculate_circle_points(center, radius, num_segments=32):
    """中心と半径から円周上の点列を計算して返す (すべてVector)"""
    points = []
    for i in range(num_segments + 1):
        theta = 2 * math.pi * i / num_segments
        points.append(mathutils.Vector((center.x + radius * math.cos(theta), center.y + radius * math.sin(theta), 0.0)))
    return points

def calculate_arc_points(p1, p2, p3, num_segments=16):
    """始点p1、中間点p2、終点p3を通る円弧上の点列を計算して返す (すべてVector)"""
    d = 2 * (p1.x * (p2.y - p3.y) + p2.x * (p3.y - p1.y) + p3.x * (p1.y - p2.y))
    if abs(d) < 1e-6:
        # 同一直線上の場合は直線を返す
        utils.debug_print(f"DEBUG: calculate_arc_points collinear! d={d:.10f}, p1={p1[:2]}, p2={p2[:2]}, p3={p3[:2]}")
        return [p1, p2, p3]
        
    ox = ((p1.x**2 + p1.y**2) * (p2.y - p3.y) + (p2.x**2 + p2.y**2) * (p3.y - p1.y) + (p3.x**2 + p3.y**2) * (p1.y - p2.y)) / d
    oy = ((p1.x**2 + p1.y**2) * (p3.x - p2.x) + (p2.x**2 + p2.y**2) * (p1.x - p3.x) + (p3.x**2 + p3.y**2) * (p2.x - p1.x)) / d
    center = mathutils.Vector((ox, oy, 0.0))
    radius = (p1 - center).length
    
    t1 = math.atan2(p1.y - oy, p1.x - ox)
    t2 = math.atan2(p2.y - oy, p2.x - ox)
    t3 = math.atan2(p3.y - oy, p3.x - ox)
    
    diff = (t3 - t1) % (2 * math.pi)
    c_diff = (t2 - t1) % (2 * math.pi)
    
    points = []
    if c_diff < diff:
        # 反時計回り
        for i in range(num_segments + 1):
            theta = t1 + (diff * i / num_segments)
            points.append(mathutils.Vector((ox + radius * math.cos(theta), oy + radius * math.sin(theta), 0.0)))
    else:
        # 時計回り
        diff_rev = (2 * math.pi) - diff
        for i in range(num_segments + 1):
            theta = t1 - (diff_rev * i / num_segments)
            points.append(mathutils.Vector((ox + radius * math.cos(theta), oy + radius * math.sin(theta), 0.0)))
            
    return points

