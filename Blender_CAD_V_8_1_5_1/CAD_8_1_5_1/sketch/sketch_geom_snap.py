"""スケッチ平面の外にある「既存の立体」へ吸着するためのスナップ。

スケッチ内部の点・中点・グリッドへの吸着は従来どおり modal_sketch 側が持つ。
こちらが相手にするのは履歴が組み上げた B-Rep の頂点で、ワイヤーフレーム
エンジンが保持している `stack.coords` をそのまま使う。カーネルへの問い合わせは
発生しない(ops_visual_snap.py の `_get_nearest_vertex` と同じ出どころ)。

吸着先はスケッチ平面へ**投影**した位置。平面の外にある頂点でも、真上/真下に
あれば掴める。これは他社 CAD の「ジオメトリ投影」と同じ振る舞い。
"""

import mathutils
from bpy_extras import view3d_utils

from . import sketch_globals
from .. import utils

# マウスから何ピクセル以内なら吸着するか。グリッド吸着より強いので、
# 広げすぎると平面上を自由に打てなくなる。
SNAP_PIXEL_RADIUS = 14.0

# (stack_ptr, 頂点数, 基準行列) -> [(x, y), ...]
_cache_key = None
_cache_points_2d = []


def invalidate():
    """キャッシュを捨てる。スケッチの開始と終了で呼ぶこと。"""
    global _cache_key, _cache_points_2d
    _cache_key = None
    _cache_points_2d = []
    sketch_globals._geom_snap_co = None


def _collect_points_2d(context, mat):
    """立体の頂点をスケッチ平面のローカル2Dへ落とした一覧を返す(キャッシュ付き)。"""
    global _cache_key, _cache_points_2d

    col = utils.get_active_collection(context)
    if not col or getattr(col, "seamless_cad_stack_ptr", "0") == "0":
        return []

    try:
        stack_ptr = int(col.seamless_cad_stack_ptr)
    except (TypeError, ValueError):
        return []

    from ..drawing import get_wireframe_engine
    stack = get_wireframe_engine().get_stack(stack_ptr)
    coords = getattr(stack, "coords", None)
    if not coords:
        return []

    key = (stack_ptr, len(coords), tuple(v for row in mat for v in row))
    if key == _cache_key:
        return _cache_points_2d

    mat_inv = mat.inverted()
    # stack.coords はスタックのローカル空間。描画時と同じ matrix を掛けて
    # ワールドへ出してから、スケッチ平面のローカルへ落とす。
    stack_mat = getattr(stack, "matrix", None)
    has_transform = stack_mat is not None and not stack_mat.is_identity

    pts = []
    for co in coords:
        v = mathutils.Vector(co)
        if has_transform:
            v = stack_mat @ v
        local = mat_inv @ v
        pts.append((local.x, local.y))

    _cache_key = key
    _cache_points_2d = pts
    return pts


def find_snap(context, mat, hit_pos, mouse_coord):
    """吸着先があればスケッチ平面ローカルの Vector を、無ければ None を返す。

    平面2Dでの最近傍を1つだけ選び、それが画面上でマウスから
    SNAP_PIXEL_RADIUS 以内にある時だけ採用する。射影は1回で済むので、
    頂点数が増えてもマウス移動あたりの重さはほぼ変わらない。
    """
    pts = _collect_points_2d(context, mat)
    if not pts:
        return None

    best = None
    best_d2 = None
    for x, y in pts:
        dx = x - hit_pos.x
        dy = y - hit_pos.y
        d2 = dx * dx + dy * dy
        if best_d2 is None or d2 < best_d2:
            best_d2 = d2
            best = (x, y)

    if best is None:
        return None

    region = context.region
    rv3d = context.region_data
    if not region or not rv3d:
        return None

    world = mat @ mathutils.Vector((best[0], best[1], 0.0))
    screen = view3d_utils.location_3d_to_region_2d(region, rv3d, world)
    if screen is None:
        return None

    if (screen - mathutils.Vector(mouse_coord)).length > SNAP_PIXEL_RADIUS:
        return None

    return mathutils.Vector((best[0], best[1], 0.0))
