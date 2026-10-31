"""既存形状をスケッチ平面へ投影して、スケッチのエンティティとして取り込む。

ロードマップ フェーズ2.1 の**第1段階**。取り込みは一度きりで、上流の
フィーチャーが変わっても再投影しない。投影元の lineage も覚えていない。
「編集すると切れる」ことを承知で使う機能で、そこは第2段階の仕事。

カーネル側の計算は occ_sketch.cpp の project_to_sketch_plane。こちらは
返ってきた平坦な数値列をスケッチのコレクションへ流し込むだけ。
"""

import mathutils

from . import sketch_globals
from .. import utils
from .. import core_bridge

# 投影で作った点を既存の点と同一視する距離。辺を1本ずつ投影したとき、
# 隣り合う辺の端点が別々の点として増えるのを防ぐ。スケッチの寸法が
# ミリ前提なので、ここは固定値でよい。
_WELD_TOL = 1e-5


def _next_id(coll):
    return max([item.id for item in coll] + [0]) + 1


def _add_point(props, x, y, weld=True):
    """点を足して id を返す。既に同じ位置に点があればそれを使い回す。"""
    if weld:
        for pt in props.sketch_points:
            if abs(pt.co[0] - x) < _WELD_TOL and abs(pt.co[1] - y) < _WELD_TOL:
                return pt.id
    pt = props.sketch_points.add()
    pt.id = _next_id(props.sketch_points)
    pt.co = (x, y)
    return pt.id


def _add_line(props, x1, y1, x2, y2, construction):
    if abs(x1 - x2) < _WELD_TOL and abs(y1 - y2) < _WELD_TOL:
        return 0
    a = _add_point(props, x1, y1)
    b = _add_point(props, x2, y2)
    for l in props.sketch_lines:
        if (l.start_point_id == a and l.end_point_id == b) or (l.start_point_id == b and l.end_point_id == a):
            return 0
    line = props.sketch_lines.add()
    line.id = _next_id(props.sketch_lines)
    line.start_point_id = a
    line.end_point_id = b
    line.is_construction = construction
    return 1


def _add_circle(props, cx, cy, r, construction):
    if r <= _WELD_TOL:
        return 0
    center = _add_point(props, cx, cy)
    # 半径点は円周上の +X 側に置く。StateCircle と同じ持ち方。
    radius_pt = _add_point(props, cx + r, cy, weld=False)
    circ = props.sketch_circles.add()
    circ.id = _next_id(props.sketch_circles)
    circ.center_point_id = center
    circ.radius_point_id = radius_pt
    circ.is_construction = construction
    return 1


def _add_arc(props, cx, cy, sx, sy, ex, ey, mx, my, construction):
    arc = props.sketch_arcs.add()
    arc.id = _next_id(props.sketch_arcs)
    arc.center_point_id = _add_point(props, cx, cy)
    arc.start_point_id = _add_point(props, sx, sy)
    arc.end_point_id = _add_point(props, ex, ey)
    arc.mid_point_id = _add_point(props, mx, my, weld=False)
    arc.is_construction = construction
    return 1


def _decode(props, flat, construction):
    """カーネルが返した平坦な数値列を読んでエンティティを足す。作った数を返す。

    書式は core_bridge.project_to_sketch_plane の docstring と同じ。
    長さが足りない列は**途中で打ち切る**。黙って 0 で埋めると、原点に
    張り付いた線が湧いて原因が分からなくなる。
    """
    made = 0
    i = 0
    n = len(flat)
    while i < n:
        kind = int(round(flat[i]))
        if kind == 0:
            if i + 4 >= n:
                break
            made += _add_line(props, flat[i + 1], flat[i + 2], flat[i + 3], flat[i + 4], construction)
            i += 5
        elif kind == 1:
            if i + 3 >= n:
                break
            made += _add_circle(props, flat[i + 1], flat[i + 2], flat[i + 3], construction)
            i += 4
        elif kind == 2:
            if i + 8 >= n:
                break
            made += _add_arc(props, flat[i + 1], flat[i + 2], flat[i + 3], flat[i + 4],
                             flat[i + 5], flat[i + 6], flat[i + 7], flat[i + 8], construction)
            i += 9
        elif kind == 3:
            if i + 1 >= n:
                break
            count = int(round(flat[i + 1]))
            if count < 2 or i + 2 + count * 2 > n:
                break
            base = i + 2
            for k in range(count - 1):
                made += _add_line(props,
                                  flat[base + k * 2], flat[base + k * 2 + 1],
                                  flat[base + (k + 1) * 2], flat[base + (k + 1) * 2 + 1],
                                  construction)
            i = base + count * 2
        else:
            # 未知の種別。ここから先は読み方が分からないので止める。
            break
    return made


def project_entity(context, props, lineage, is_face, construction=False):
    """lineage で指す辺/面をスケッチ平面へ投影して取り込む。

    (作ったエンティティ数, エラー文字列) を返す。エラーは呼び出し側が
    そのまま report に出せる形。
    """
    col = utils.get_active_collection(context)
    if not col or getattr(col, "seamless_cad_stack_ptr", "0") == "0":
        return 0, "No CAD part to project from"

    mat = sketch_globals._reference_matrix if sketch_globals._reference_matrix else mathutils.Matrix.Identity(4)
    origin = mat.translation
    rot = mat.to_3x3()
    plane_x = rot.col[0]
    plane_z = rot.col[2]

    try:
        stack_ptr = int(col.seamless_cad_stack_ptr)
    except (TypeError, ValueError):
        return 0, "The CAD stack pointer is not usable"

    flat = core_bridge.project_to_sketch_plane(
        stack_ptr, lineage, is_face,
        [origin.x, origin.y, origin.z],
        [plane_x.x, plane_x.y, plane_x.z],
        [plane_z.x, plane_z.y, plane_z.z],
    )
    if not flat:
        return 0, "The kernel returned nothing to project"

    made = _decode(props, list(flat), construction)
    if made == 0:
        return 0, "Nothing was projected onto this plane"
    return made, ""
