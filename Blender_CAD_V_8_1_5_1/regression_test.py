"""Blender をヘッドレスで起動して回す回帰テスト。

    "C:\\Program Files\\Blender Foundation\\Blender 5.1\\blender.exe" ^
        --background --factory-startup --python regression_test.py

DEPSGRAPH_STATE_MACHINE.md §5 の手動チェックリストのうち、GUI が無くても
検証できる項目を機械化したもの。全部が置き換わるわけではない:

  自動化した : A(アクティブ同期) B(Feature Tree→ビューポート) E(単発編集)
               F(削除同期) G相当(ハイライト文字列) + 確定フェーズの契約
               + 出品前チェック(パネル登録/ベイク/STEP書き出し/保存再読込)
               + FILLET / CHAMFER が実際に形状を変えること
               + 2D スケッチ(拘束ソルバと確定)
               + I の一部(Undo 1回で1つ戻ること)
  手動のまま : C(ドラッグ追従) D(確定後に固まらない) H(WGPU Overlay OFF)
               Redo、および Ctrl+Z 後にビューポートが更新されるか(§4-6)

C/D/H はネイティブの変形モーダルと GPU 描画が要るため、ここでは原理的に
再現できない。**変形まわりを触ったら実機確認は依然として必要。**
代わりに、確定フェーズ(_handle_settle)の「フラグを確実に下ろす」という契約は
関数を直接叩いて検証している。2026-07-28 のフェーズ抽出で可能になった。

終了コード 0 = 全パス、1 = 失敗あり。
"""

import math
import os
import sys
import traceback

ADDON_PARENT = os.path.dirname(os.path.abspath(__file__))
if ADDON_PARENT not in sys.path:
    sys.path.insert(0, ADDON_PARENT)

import bpy  # noqa: E402
import mathutils  # noqa: E402

_results = []


class Skip(Exception):
    """この環境では安全に実行できない検査。失敗ではなく SKIP として記録する。"""


def check(name, fn):
    """fn() を走らせ、送出された AssertionError を失敗として記録する。

    開始時に名前を flush 付きで出すのは、テストが Blender ごと落とした場合に
    「どれが落としたか」を特定できるようにするため(§4-6 の Undo 調査で必要になった)。
    """
    print(f"[run] {name}", flush=True)
    try:
        fn()
    except Skip as e:
        _results.append((name, None, str(e)))
    except Exception as e:
        _results.append((name, False, f"{type(e).__name__}: {e}"))
        traceback.print_exc()
    else:
        _results.append((name, True, ""))


def _fresh_part():
    """まっさらな .blend から CAD コレクションを1つ作り、(col, props) を返す。

    シーンを毎回リセットしないと、前のテストが作ったプリミティブが同じ
    Part_1 に積み上がって後続の断言が壊れる(テストどうしが汚染し合う)。

    掃除は手作業で行う。`bpy.ops.wm.read_factory_settings()` を使うと
    depsgraph_update_handler が **@persistent でないため外れてしまい**、
    以降のテストで同期が一切走らなくなる(§4-5 参照)。
    """
    from CAD_8_1_5_1 import utils
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for col in list(bpy.data.collections):
        bpy.data.collections.remove(col)
    utils._registered_cad_collections.clear()
    utils._proxy_initial_matrices.clear()
    utils._last_change_time = 0.0
    bpy.ops.seamless.start_cad()
    col = utils.get_active_collection(bpy.context)
    props = utils.get_active_props(bpy.context)
    assert col is not None, "start_cad did not produce an active collection"
    assert props is not None, "collection has no seamless_props"
    assert getattr(col, "seamless_cad_stack_ptr", "0") != "0", \
        "no stack_ptr -- the geometry kernel (cad_server.exe) did not answer"
    return col, props


def _proxies(col):
    return [o for o in col.objects if o.get("is_seamless_proxy")]


def _proxy_for(col, prim):
    for o in _proxies(col):
        if o.get("primitive_uuid") == prim.uuid:
            return o
    raise AssertionError(f"no proxy object for primitive {prim.name} ({prim.uuid})")


# --------------------------------------------------------------------------
# テスト本体
# --------------------------------------------------------------------------

def t_register():
    """アドオンが import / register できる。

    8.1.5.1 で「キャッシュ済みサブモジュールのせいで有効化に失敗する」事故が
    あったので、まずここを固定する。
    """
    import CAD_8_1_5_1 as addon
    addon.register()
    assert hasattr(bpy.types.Collection, "seamless_props"), \
        "register() did not attach seamless_props to Collection"
    assert hasattr(bpy.ops, "seamless"), "no seamless operator namespace after register()"


def t_add_primitives():
    """プリミティブを追加すると prim とプロキシが1対1で生える。"""
    col, props = _fresh_part()
    bpy.ops.seamless.add_primitive(type='BOX')
    bpy.ops.seamless.add_primitive(type='CYLINDER')
    types = [p.type for p in props.primitives]
    assert types == ['BOX', 'CYLINDER'], f"expected [BOX, CYLINDER], got {types}"
    for prim in props.primitives:
        assert prim.uuid, f"primitive {prim.name} has no uuid"
        _proxy_for(col, prim)


def t_b_feature_tree_to_viewport():
    """B: Feature Tree の行を選ぶと、対応するプロキシがアクティブになる。

    ⚠️ これは弱い検査。active_primitive_index は背景実行だと1操作ぶん遅れて
    観測される: オペレータ内の `select_all(DESELECT)` が depsgraph を回し、
    まだ古いオブジェクトがアクティブなまま
    sync_active_primitive_from_active_object() が走って index を上書きするため。
    GUI では次の depsgraph 更新で正しい値に落ち着く(実機で確認済み)。
    view_layer.update() を挟んでも解消しないので、ここでは断言しない。

    結果として本テストは「どのプロキシがアクティブになったか」しか見ておらず、
    そこは self.index から直に決まるので index の取り違えは捕まえられない。
    index の正しさは A(sync_active_primitive_from_active_object)が担保する。
    """
    col, props = _fresh_part()
    bpy.ops.seamless.add_primitive(type='BOX')
    bpy.ops.seamless.add_primitive(type='CYLINDER')
    target = props.primitives[0]
    expected = _proxy_for(col, target)
    bpy.ops.seamless.set_active_primitive(index=0)
    active = bpy.context.view_layer.objects.active
    assert active == expected, \
        f"clicking row 0 should activate {expected.name}, got {active.name if active else None}"


def t_a_viewport_to_feature_tree():
    """A: プロキシをアクティブにすると Feature Tree の選択が追従する。"""
    from CAD_8_1_5_1 import utils
    col, props = _fresh_part()
    bpy.ops.seamless.add_primitive(type='BOX')
    bpy.ops.seamless.add_primitive(type='CYLINDER')
    target = props.primitives[0]
    proxy = _proxy_for(col, target)

    props.active_primitive_index = 1              # わざとずらす
    bpy.context.view_layer.objects.active = proxy
    utils.sync_active_primitive_from_active_object()
    assert props.active_primitive_index == 0, \
        f"selecting the row-0 proxy should move the marker to 0, got {props.active_primitive_index}"


def t_f_delete_sync():
    """F: プロキシを消すと Feature Tree から該当行が消え、index が範囲内に収まる。"""
    col, props = _fresh_part()
    bpy.ops.seamless.add_primitive(type='BOX')
    bpy.ops.seamless.add_primitive(type='CYLINDER')
    doomed = _proxy_for(col, props.primitives[1])

    bpy.data.objects.remove(doomed, do_unlink=True)
    bpy.context.view_layer.update()

    types = [p.type for p in props.primitives]
    assert types == ['BOX'], f"expected the CYLINDER row to disappear, got {types}"
    assert 0 <= props.active_primitive_index < len(props.primitives), \
        f"active index {props.active_primitive_index} out of range after delete"


def t_e_single_edit_is_not_a_drag():
    """E: 数値の直接編集はドラッグ扱いにならない(is_dragging が立ちっぱなしにならない)。"""
    col, props = _fresh_part()
    bpy.ops.seamless.add_primitive(type='BOX')
    prim = props.primitives[0]

    prim.size = (2.0, 2.0, 2.0)
    bpy.context.view_layer.update()
    assert not props.is_dragging, \
        "a direct numeric edit must not latch is_dragging (checklist E / §4-1)"


def t_settle_contract():
    """確定フェーズの契約: 呼べば必ず is_dragging が下り、初期行列が捨てられる。

    C/D/H は GUI 無しでは再現できないが、その裏で効いている
    _handle_settle() の約束事だけはここで固定できる。フェーズ抽出
    (2026-07-28)で関数として叩けるようになった部分。
    """
    from CAD_8_1_5_1 import utils
    col, props = _fresh_part()
    bpy.ops.seamless.add_primitive(type='BOX')

    # ドラッグ中の状態を人工的に作る
    props.is_dragging = True
    utils._proxy_initial_matrices["pre-drag-marker"] = mathutils.Matrix.Identity(4)
    utils._last_change_time = 1.0

    utils._handle_settle([col], modal_ended=True, activity_ended=False,
                         is_fast_mode=False, is_transform_modal=False)

    assert not props.is_dragging, "_handle_settle must drop is_dragging (checklist D)"
    # 「空になること」ではなく「ドラッグ前のスナップショットが捨てられること」を見る。
    # _handle_settle 内の高品質再計算が depsgraph を回すため、背景実行だと同じ
    # フレームのうちに新しい行列が入り直すことがある(GUI では確定後 is_transform_modal が
    # False なので起きない)。契約はあくまで「古い基準を残さない」。
    assert "pre-drag-marker" not in utils._proxy_initial_matrices, \
        "_handle_settle must drop the pre-drag matrices when a modal drag ended"
    assert utils._last_change_time == 0, \
        "_handle_settle must reset _last_change_time so fast-mode does not stick"


def t_settle_is_a_noop_when_nothing_ended():
    """何も終わっていないフレームで確定処理が誤爆しない。"""
    from CAD_8_1_5_1 import utils
    col, props = _fresh_part()
    bpy.ops.seamless.add_primitive(type='BOX')

    props.is_dragging = True
    utils._handle_settle([col], modal_ended=False, activity_ended=False,
                         is_fast_mode=True, is_transform_modal=True)
    assert props.is_dragging, \
        "_handle_settle must leave a drag in progress alone"
    props.is_dragging = False


def t_g_fillet_highlight_data():
    """G(データ層): FILLET を選ぶと選択エッジの文字列が入る。

    実際のハイライト描画は GPU 依存なので見られない。ここで見るのは
    「描画側に渡すデータが両経路で同じように用意されるか」。
    """
    col, props = _fresh_part()
    bpy.ops.seamless.add_primitive(type='BOX')
    bpy.ops.seamless.add_primitive(type='FILLET')
    idx = len(props.primitives) - 1
    assert props.primitives[idx].type == 'FILLET', "FILLET row was not added"

    bpy.ops.seamless.set_active_primitive(index=idx)
    assert props.selection_type == 'EDGE', \
        f"selecting a FILLET row should switch selection_type to EDGE, got {props.selection_type}"


def t_save_reload_keeps_cad_live():
    """保存した .blend を開き直しても CAD が生きている(§4-5)。

    2026-07-30 まで壊れていた: depsgraph_update_handler に @persistent が無く
    ロードで捨てられ、さらに stack_ptr が 0 に潰されてコレクションが
    「生きた CAD」と見なされなくなるため、開き直すとドラッグが無反応だった。
    片方だけ直しても駄目なので、両方が効いていることをここで固定する。
    """
    import tempfile
    from CAD_8_1_5_1 import utils

    col, props = _fresh_part()
    bpy.ops.seamless.add_primitive(type='BOX')
    blend = os.path.join(tempfile.gettempdir(), "seamless_cad_regression.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend)
    bpy.ops.wm.open_mainfile(filepath=blend)

    assert utils.depsgraph_update_handler in bpy.app.handlers.depsgraph_update_post, \
        "depsgraph_update_handler must survive a file load (needs @persistent)"

    # 同じ「ロードで捨てられる」問題がタイマー側にも残っていた(2026-08-05)。
    # ハンドラだけ直してタイマーを見落としていたため、ファイルを開いた瞬間に
    # 非同期結果を取り出す者が居なくなり、cad_server が返した結果は
    # _async_results に溜まったまま描画されない。同期経路の Bake Mesh だけが
    # 効くので「表示の不具合」に見えるが、実体は止まったポンプ。
    from CAD_8_1_5_1 import core_bridge
    assert bpy.app.timers.is_registered(core_bridge.poll_async_results), \
        ("the async result pump must survive a file load (needs persistent=True); "
         "without it every async preview silently stops being applied")

    col2 = utils.get_active_collection(bpy.context)
    props2 = utils.get_active_props(bpy.context)
    assert props2 and len(props2.primitives) == 1, "the saved feature tree did not come back"
    assert getattr(col2, "seamless_cad_stack_ptr", "0") != "0", \
        "the CAD stack was not recreated on load -- the collection is not live"

    # 開いた直後にプロキシを動かして、prim へ反映されるか(=利用者が最初にやること)
    proxy = _proxy_for(col2, props2.primitives[0])
    proxy.location = (5.0, 0.0, 0.0)
    bpy.context.view_layer.update()
    assert abs(props2.primitives[0].location[0] - 5.0) < 1e-3, \
        ("dragging a proxy right after opening a saved file must sync to the primitive; "
         f"got {list(props2.primitives[0].location)}")


def t_dispatch_signature_precision():
    """重複リクエスト除去のシグネチャが、利用者の入力値を潰さない。

    _quantize_for_sig は「動かしていないのにプロキシ行列の分解で毎回わずかに
    変わる」ドリフトを畳むための仕組みで、それ自体は必要。ただし丸めてよいのは
    行列由来の location / rotation / size だけ。

    以前は stack_data 全体を無差別に 1e-3 で丸めていたため、数値欄に直接
    打ち込む radius / extrude_height などまで潰れていた。Blender の内部単位は
    メートルなので実質 1mm 刻みで、半径 0.2000 -> 0.2003 の変更が
    「前回と同一」と判定されて再計算がスキップされる。プロパティ側は更新
    済みなので、パネルは 0.2003・形状は 0.2000 のまま食い違い、後で force 付き
    再計算が走った瞬間に形状が飛ぶ。
    """
    from CAD_8_1_5_1.core_bridge import _quantize_for_sig as q

    def prim(**over):
        p = {
            "type": "FILLET", "operation": "ADD", "uuid": "abc",
            "location": [0.0, 0.0, 0.0],
            "rotation": [0.0, 0.0, 0.0],
            "size": [1.0, 1.0, 1.0],
            "radius": 0.2,
            "extrude_height": 0.5,
            "pipe_radius": 0.05,
            "radius2": 0.3,
            "minor_radius": 0.1,
            "edge_radii": [("Edge:1", 0.25)],
        }
        p.update(over)
        return [p]

    base = q(prim())

    # 丸めが存在する理由。ここが崩れると重複除去そのものが効かなくなる。
    for key in ("location", "rotation", "size"):
        drifted = prim(**{key: [v + 4.0e-4 for v in prim()[0][key]]})
        assert q(drifted) == base, \
            f"matrix-derived drift in {key} must still collapse (that is why rounding exists)"

    assert q(prim(location=[0.01, 0.0, 0.0])) != base, \
        "a real move must still change the signature"

    # 本題。利用者が打ち込む値は 1mm 未満でも別物として扱う。
    for key in ("radius", "extrude_height", "pipe_radius", "radius2", "minor_radius"):
        changed = prim(**{key: prim()[0][key] + 3.0e-4})
        assert q(changed) != base, \
            (f"a {key} change of 3e-4 must reach the kernel; rounding user-typed "
             "scalars makes sub-millimetre edits silently do nothing")

    assert q(prim(edge_radii=[("Edge:1", 0.2503)])) != base, \
        "per-edge variable fillet radii must not be collapsed either"

    hash(base)  # シグネチャは辞書キーになるのでハッシュ可能でなければならない


# --------------------------------------------------------------------------
# 出品前チェック(LISTING_PREP.md の「最低限の検証チェックリスト」由来)
# --------------------------------------------------------------------------

def _capture_edge_lineages(col):
    """今の結果形状のエッジ識別子(lineage)を集める。

    通常は利用者がビューポートでエッジをクリックして選ぶ値。GUI が無いので、
    カーネルが描画エンジンへ渡す lineage を横取りして同じものを手に入れる。
    これが無いと FILLET/CHAMFER は「対象が空だから何もしない」状態しか試せない。
    """
    from CAD_8_1_5_1 import core_bridge, drawing
    captured = []
    engine = drawing.get_wireframe_engine()
    original = engine.update_data

    def spy(stack_ptr, points, counts, lineages):
        if lineages:
            captured[:] = list(lineages)
        return original(stack_ptr, points, counts, lineages)

    engine.update_data = spy
    try:
        core_bridge.update_cad_preview_forced(bpy.context)
    finally:
        engine.update_data = original
    return captured


def _face_centroid(col, target_lineage):
    """結果形状のうち、指定 lineage の面の重心。無ければ None。"""
    import math
    from CAD_8_1_5_1 import core_bridge
    core = core_bridge.get_core()
    res = core.generate_mesh(int(col.seamless_cad_stack_ptr), 0.03, math.radians(6.0))
    if not res:
        return None
    verts, tris, fids, counts = res
    prefix = str(target_lineage).split("@")[0]
    off = 0
    for i, lid in enumerate(fids):
        n = counts[i]
        if str(lid).split("@")[0] == prefix:
            idxs = list(tris[off:off + n])
            if not idxs:
                return None
            xs = [verts[k * 3] for k in idxs]
            ys = [verts[k * 3 + 1] for k in idxs]
            zs = [verts[k * 3 + 2] for k in idxs]
            return (sum(xs) / len(xs), sum(ys) / len(ys), sum(zs) / len(zs))
        off += n
    return None


def _capture_face_lineages(col):
    """今の結果形状の面識別子(lineage)を集める。

    エッジ側と違い、面の lineage は generate_mesh の応答に face_ids として
    そのまま入っている。三角形ごとに1つなので重複を落として返す。
    """
    import math
    from CAD_8_1_5_1 import core_bridge
    core_bridge.update_cad_preview_forced(bpy.context)
    core = core_bridge.get_core()
    res = core.generate_mesh(int(col.seamless_cad_stack_ptr), 0.03, math.radians(6.0))
    if not res:
        return []
    seen = []
    for fid in res[2]:
        if fid and fid not in seen:
            seen.append(fid)
    return seen


def _result_vertex_count(col):
    import math
    from CAD_8_1_5_1 import core_bridge
    core_bridge.update_cad_preview_forced(bpy.context)
    core = core_bridge.get_core()
    res = core.generate_mesh(int(col.seamless_cad_stack_ptr), 0.03, math.radians(6.0))
    if not res or len(res[0]) == 0:
        return 0
    return len(res[0]) // 3


def t_fillet_rounds_edges():
    """FILLET が実際に角を丸める。

    CAD アドオンの看板機能。対象エッジを与えないと何もしないのが正しい挙動なので、
    エッジ識別子を取ってから適用する(_capture_edge_lineages 参照)。
    """
    col, props = _fresh_part()
    bpy.ops.seamless.add_primitive(type='BOX')
    base = _result_vertex_count(col)
    assert base == 8, f"a plain box should have 8 vertices, got {base}"

    lineages = _capture_edge_lineages(col)
    assert len(lineages) >= 4, f"expected the box to report its edges, got {lineages}"

    bpy.ops.seamless.add_primitive(type='FILLET')
    props = utils_props()
    fillet = props.primitives[-1]
    fillet.target_lineages = "|".join(lineages[:4])
    fillet.radius = 0.1

    after = _result_vertex_count(col)
    assert after > base, \
        f"filleting 4 edges must add geometry; stayed at {after} vertices"


def t_chamfer_cuts_edges():
    """CHAMFER が実際に角を落とす。"""
    col, props = _fresh_part()
    bpy.ops.seamless.add_primitive(type='BOX')
    base = _result_vertex_count(col)

    lineages = _capture_edge_lineages(col)
    assert len(lineages) >= 4, f"expected the box to report its edges, got {lineages}"

    bpy.ops.seamless.add_primitive(type='CHAMFER')
    props = utils_props()
    chamfer = props.primitives[-1]
    chamfer.target_lineages = "|".join(lineages[:4])
    chamfer.radius = 0.1

    after = _result_vertex_count(col)
    assert after > base, \
        f"chamfering 4 edges must add geometry; stayed at {after} vertices"


def _result_bounds(col):
    """結果メッシュの軸ごとの (min, max) を返す。

    頂点数だけを見ると「増えたが向きが逆」を取り逃がす(§4 の罠: 対称な値だけの
    テスト)。REVOLVE は回転方向と軸位置の誤りが症状に出にくいので範囲で見る。
    """
    import math
    from CAD_8_1_5_1 import core_bridge
    core_bridge.update_cad_preview_forced(bpy.context)
    core = core_bridge.get_core()
    res = core.generate_mesh(int(col.seamless_cad_stack_ptr), 0.03, math.radians(6.0))
    if not res or len(res[0]) == 0:
        return None
    flat = list(res[0])
    xs = flat[0::3]
    ys = flat[1::3]
    zs = flat[2::3]
    return (min(xs), max(xs)), (min(ys), max(ys)), (min(zs), max(zs))


def t_revolve_sweeps_a_profile():
    """REVOLVE が閉じたプロファイルから回転体を作る。

    ここが空回りしていた。REVOLVE のターゲットは uuid_to_shape 経由で渡るため、
    POLYGON / SLOT / SURFACE が occ_core.cpp で厚み 1e-4 に強制押し出しされた
    「薄いソリッド」が来る。BRepPrimAPI_MakeRevol はソリッドを回せないので結果が
    空になり、UUID を入れても何も起きなかった(2026-08-18 利用者報告)。
    occ_arrays.cpp の extract_revolvable_profile がこれを吸収する。

    値は非対称にすること。プロファイルを XZ 平面へ倒して X=3 に置き、Z 軸まわりに
    210 度回す。軸を取り違えたり 360 度に丸めたりすると Y の広がりが合わなくなる。
    """
    col, props = _fresh_part()

    bpy.ops.seamless.add_primitive(type='POLYGON')
    profile = utils_props().primitives[-1]
    profile.sides = 5
    profile.radius = 0.5
    # XY 平面のプロファイルを XZ 平面へ倒す。倒さないと回転軸(Z)が
    # プロファイル平面に含まれず、掃引しても体積が出ない
    profile.rotation = (math.radians(90.0), 0.0, 0.0)
    profile.location = (3.0, 0.0, 0.0)
    profile_uuid = profile.uuid

    base_bounds = _result_bounds(col)
    assert base_bounds is not None, "the profile itself should produce a mesh"
    assert base_bounds[1][1] - base_bounds[1][0] < 0.5, \
        f"the flat profile must be thin along Y before revolving, got {base_bounds[1]}"

    bpy.ops.seamless.add_primitive(type='REVOLVE')
    rev = utils_props().primitives[-1]
    rev.target_uuid = profile_uuid
    rev.pattern_axis = 'Z'
    rev.distance = 210.0
    rev.location = (0.0, 0.0, 0.0)

    bounds = _result_bounds(col)
    assert bounds is not None, "REVOLVE produced no geometry at all"

    _, (y_min, y_max), _ = bounds
    # 掃引角は Y の範囲で見る。cad_server 直叩きでの実測 (2026-08-18):
    #   プロファイル単体      y = (-0.000,  0.000)
    #   210 度回した後        y = (-1.750,  3.500)
    # 210 度は 90 度を通過するので +Y は半径いっぱい(3.5)まで届き、
    # 180 度を越えた分だけ -Y へ回り込んで -1.75 で止まる。
    assert y_max > 2.0, \
        f"revolving 210 deg must sweep into +Y; got y_max={y_max:.3f} (bounds={bounds})"
    assert y_min < -1.0, \
        f"revolving past 180 deg must reach -Y; got y_min={y_min:.3f} (bounds={bounds})"
    # 一周させると y_min は -3.5 まで落ちる。360 度に丸められていないことの確認。
    # X で見てはいけない: 210 度でも 180 度を通過するので -X は半径まで届く
    assert y_min > -2.5, \
        f"210 deg is not a full turn; y_min should stop short of -3.5, got y_min={y_min:.3f}"


def t_revolve_ignores_a_missing_target():
    """ターゲット未設定の REVOLVE が形状を壊さない。

    extract_revolvable_profile で null を返す経路。ここで例外が漏れると
    stack_results が空になり、無関係な形状まで消える。
    """
    col, props = _fresh_part()
    bpy.ops.seamless.add_primitive(type='BOX')
    base = _result_vertex_count(col)
    assert base == 8, f"a plain box should have 8 vertices, got {base}"

    bpy.ops.seamless.add_primitive(type='REVOLVE')
    rev = utils_props().primitives[-1]
    rev.target_uuid = ""
    rev.pattern_axis = 'Y'
    rev.distance = 130.0

    after = _result_vertex_count(col)
    assert after == base, \
        f"a REVOLVE with no target must leave the box alone; {base} -> {after}"


def t_no_import_shadowing():
    """関数内 import が、その関数の前半で使っている同名モジュールを隠していないか。

    Python は関数内に代入(import も代入)があると、その名前を**関数全体で**
    ローカル扱いにする。モジュール先頭で import 済みの名前を関数の途中で
    import し直すと、それより前の行での参照が UnboundLocalError になる。

    ops_visual_snap.py が実際にこれで壊れた(2026-08-18 利用者報告)。
    modal() 末尾の `from .. import utils` は初回コミットからあったが無害で、
    8.1.5.8 で modal() の冒頭に utils.is_viewport_nav_event() を足した瞬間に
    「Visual Snap がどのイベントでも例外」になった。追加したコードは正しく、
    離れた場所にある無害だったはずの import が牙を剥く形。

    grep では見つけにくい(両方とも普通の import 文にしか見えない)ので
    構文木で見る。実行は要らないのでヘッドレスで完全に検証できる。
    """
    import ast

    addon_dir = os.path.join(ADDON_PARENT, "CAD_8_1_5_1")
    hits = []

    for root, dirs, files in os.walk(addon_dir):
        # libs/ は同梱サードパーティ。こちらの責任ではないので見ない
        dirs[:] = [d for d in dirs if d not in {"__pycache__", "libs"}]
        for fn in files:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(root, fn)
            with open(path, encoding="utf-8") as fh:
                src = fh.read()
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue

            module_names = set()
            for node in tree.body:
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    for a in node.names:
                        module_names.add(a.asname or a.name.split(".")[0])
            if not module_names:
                continue

            for fnode in ast.walk(tree):
                if not isinstance(fnode, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                # ネストした関数は別スコープなので、この関数の分だけを集める
                local_imports = {}
                for n in ast.walk(fnode):
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n is not fnode:
                        continue
                    if isinstance(n, (ast.Import, ast.ImportFrom)):
                        for a in n.names:
                            nm = a.asname or a.name.split(".")[0]
                            if nm in module_names:
                                local_imports.setdefault(nm, n.lineno)
                if not local_imports:
                    continue
                for n in ast.walk(fnode):
                    if not (isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)):
                        continue
                    shadowed_at = local_imports.get(n.id)
                    if shadowed_at is not None and n.lineno < shadowed_at:
                        rel = os.path.relpath(path, ADDON_PARENT)
                        hits.append(
                            f"{rel}:{n.lineno} reads '{n.id}' in {fnode.name}(), "
                            f"but line {shadowed_at} re-imports it into the same scope"
                        )
                        break

    assert not hits, (
        "a function-level import shadows a module-level one it reads earlier; "
        "delete the inner import:" + "".join("\n  " + h for h in sorted(hits))
    )


def utils_props():
    from CAD_8_1_5_1 import utils
    return utils.get_active_props(bpy.context)


def _sketch_reset(props):
    # 円と円弧も消すこと。ここに入れ忘れると、前のテストで作った円が次の
    # テストに残り、RADIUS のように「選択から円を探す」処理が別の円を掴む。
    for coll in (props.sketch_points, props.sketch_lines, props.sketch_constraints,
                 props.sketch_circles, props.sketch_arcs):
        while len(coll):
            coll.remove(0)


def _sk_point(props, pid, x, y):
    p = props.sketch_points.add()
    p.id = pid
    p.co = (x, y)


def _sk_line(props, lid, a, b):
    l = props.sketch_lines.add()
    l.id = lid
    l.start_point_id = a
    l.end_point_id = b


def _sk_circle(props, cid, center_id, rim_id):
    c = props.sketch_circles.add()
    c.id = cid
    c.center_point_id = center_id
    c.radius_point_id = rim_id


def _sk_constraint(props, cid, ctype, point_ids, value=0.0):
    """拘束を1つ足す。

    対象は **点の id** をカンマ区切りで `target_ids_str` に入れる(線 id ではない)。
    引数の順序は種類ごとに決まっていて、MIDPOINT は (端点1, 端点2, 中点)。
    ここを取り違えると解は出るが答えが合わないので注意。
    """
    c = props.sketch_constraints.add()
    c.id = cid
    c.type = ctype
    c.target_ids_str = ",".join(str(x) for x in point_ids)
    c.value = value


def _sk_co(props, pid):
    for p in props.sketch_points:
        if p.id == pid:
            return (round(p.co[0], 4), round(p.co[1], 4))
    raise AssertionError(f"sketch point {pid} not found")


class _FakeEvent:
    """モーダルへ渡す event の最小の代役。

    StateSelect の release 処理が読むのは shift / ctrl とマウス座標だけ。
    背景実行では region が無いので、画面基準のしきい値計算は従来の
    固定値へ落ちる。そのぶん距離の数字は素直に比較できる。
    """

    def __init__(self, shift=False, ctrl=False, x=0, y=0):
        self.shift = shift
        self.ctrl = ctrl
        self.mouse_region_x = x
        self.mouse_region_y = y
        self.type = 'LEFTMOUSE'
        self.value = 'RELEASE'


class _FakeSketchOp:
    """StateSelect が触るモーダル側の属性だけを持つ代役。"""

    def __init__(self, drag_point_id):
        self._is_dragging = True
        self._drag_point_id = drag_point_id
        self._drag_point_ids = [drag_point_id]
        self._last_solve_time = 0.0


def _release_drag(props, drag_pt_id, ctrl=False):
    """頂点をドラッグして離した瞬間の処理を1回走らせる。"""
    from CAD_8_1_5_1.sketch.states.state_select import StateSelect
    from CAD_8_1_5_1.sketch import sketch_globals

    sketch_globals._is_box_selecting = False
    sketch_globals._last_mouse_pos = None
    op = _FakeSketchOp(drag_pt_id)
    state = StateSelect(bpy.context, props, op)
    state.handle_left_click_release(_FakeEvent(ctrl=ctrl), mathutils.Vector((0.0, 0.0, 0.0)))


def t_measure_part():
    """計測が実際の形状を測っている。

    2x2x2 の箱なら体積 8、表面積 24、重心は原点。数字が既知なので、
    「何か返ってきた」ではなく「正しい値か」を見られる。
    """
    from CAD_8_1_5_1 import core_bridge

    col, props = _fresh_part()
    bpy.ops.seamless.add_primitive(type='BOX')
    props = utils_props()
    prim = props.primitives[-1]
    prim.size = (2.0, 2.0, 2.0)
    core_bridge.update_cad_preview_forced(bpy.context)

    stack_ptr = int(col.seamless_cad_stack_ptr)
    assert stack_ptr, "the part has no stack to measure"

    m = core_bridge.measure_stack(stack_ptr)
    assert m is not None, "measure_stack returned nothing"

    assert abs(m["volume"] - 8.0) < 1e-3, f"a 2x2x2 box should have volume 8, got {m['volume']}"
    assert abs(m["area"] - 24.0) < 1e-3, f"a 2x2x2 box should have area 24, got {m['area']}"
    for axis, v in zip("xyz", m["size"]):
        assert abs(v - 2.0) < 1e-3, f"size {axis} should be 2.0, got {v}"
    for axis, v in zip("xyz", m["centre_of_mass"]):
        assert abs(v) < 1e-3, f"centre of mass {axis} should be 0, got {v}"

    # 寸法を変えたら測り直しに追従する。同じ値を返し続けるキャッシュを検出する
    prim.size = (4.0, 2.0, 2.0)
    core_bridge.update_cad_preview_forced(bpy.context)
    m2 = core_bridge.measure_stack(stack_ptr)
    assert m2 is not None, "measure_stack returned nothing after the edit"
    assert abs(m2["volume"] - 16.0) < 1e-3, \
        f"after widening the box the volume should be 16, got {m2['volume']}"

    # 存在しないスタックはエラーであって、ゼロ埋めの成功ではない
    assert core_bridge.measure_stack(0) is None, \
        "measuring a null stack must fail rather than report zeroes"

    # オペレータ経由でも同じ値がプロパティに載る
    bpy.ops.seamless.measure_part()
    assert props.measure_valid, "the measure operator did not mark the result valid"
    assert abs(props.measure_volume - 16.0) < 1e-3, \
        f"the operator stored {props.measure_volume}, expected 16"

    # **曲面でも寸法が正確であること。** 箱は全面が平面なので、バウンディング
    # ボックスの求め方を間違えていても正解が出てしまう。実際 BRepBndLib::Add と
    # AddOptimal(useTriangulation=true) では、半径2の球が 4.109/4.094/4.123 と
    # 3軸バラバラかつ 3% 大きい値になっていた。箱だけで測っていたので通っていた。
    col, props = _fresh_part()
    bpy.ops.seamless.add_primitive(type='SPHERE')
    props = utils_props()
    props.primitives[-1].size = (2.0, 2.0, 2.0)
    core_bridge.update_cad_preview_forced(bpy.context)
    m = core_bridge.measure_stack(int(col.seamless_cad_stack_ptr))
    assert m is not None, "measure_stack returned nothing for a sphere"

    # 体積から半径を逆算する: V = 4/3 pi r^3
    r = (m["volume"] * 3.0 / (4.0 * math.pi)) ** (1.0 / 3.0)
    for axis, v in zip("xyz", m["size"]):
        assert abs(v - 2.0 * r) < 1e-3,             f"a sphere of radius {r:.4f} should measure {2*r:.4f} on {axis}, got {v:.4f}"
    # 対称な形なので3軸は一致していなければならない。ここがずれるのは
    # バウンディングボックスがテセレーション由来になっている印
    assert max(m["size"]) - min(m["size"]) < 1e-3, \
        f"a sphere must measure the same on every axis, got {tuple(round(v,4) for v in m['size'])}"


def t_measure_entity():
    """選択した辺/面の寸法。既知の箱で値が合うこと。

    2x2x2 の箱なら、辺はどれも長さ 2、面はどれも面積 4、面種は Plane。
    「何か返ってきた」ではなく「正しい」を見られる数字を選んでいる。
    """
    from CAD_8_1_5_1 import core_bridge

    col, props = _fresh_part()
    bpy.ops.seamless.add_primitive(type='BOX')
    props = utils_props()
    props.primitives[-1].size = (2.0, 2.0, 2.0)
    core_bridge.update_cad_preview_forced(bpy.context)
    stack_ptr = int(col.seamless_cad_stack_ptr)

    lineages = _capture_edge_lineages(col)
    assert lineages, "the box reported no edges to measure"

    m = core_bridge.measure_entity(stack_ptr, lineages[0], False)
    assert m is not None, "measure_entity returned nothing"
    assert m["resolved"], f"the edge lineage should resolve: {lineages[0]}"
    assert not m["is_face"], "an edge lineage must report as an edge"
    assert abs(m["amount"] - 2.0) < 1e-3, \
        f"every edge of a 2x2x2 box is 2.0 long, got {m['amount']}"
    assert m["shape"] == "Line", f"a box edge is a straight line, got {m['shape']}"
    assert m["radius"] is None, "a straight edge has no radius"

    # **解決できない lineage は黙ること。** ここが一番大事な検査で、
    # 近い別の辺を返して数字を埋めてしまうと、間違いを自信満々に表示する。
    bogus = core_bridge.measure_entity(stack_ptr, "Edge:doesnotexist:99", False)
    assert bogus is not None, "an unresolvable lineage is not a transport error"
    assert bogus["resolved"] is False,         "an unresolvable lineage must report unresolved, not invent a measurement"

    # 円柱の側面は円柱面として認識され、半径が取れる。フィレット面の半径を
    # 読むのと同じ経路(面の種類を見て半径を返す)なので、ここで固定しておく
    col, props = _fresh_part()
    bpy.ops.seamless.add_primitive(type='CYLINDER')
    props = utils_props()
    core_bridge.update_cad_preview_forced(bpy.context)
    stack_ptr = int(col.seamless_cad_stack_ptr)

    found_cylinder = None
    for lid in _capture_face_lineages(col):
        r = core_bridge.measure_entity(stack_ptr, lid, True)
        if r and r.get("resolved") and r.get("shape") == "Cylinder":
            found_cylinder = r
            break
    assert found_cylinder is not None,         "a cylinder must expose at least one cylindrical face"
    assert found_cylinder["radius"] is not None and found_cylinder["radius"] > 0.0, \
        f"a cylindrical face must report its radius, got {found_cylinder['radius']}"
    assert found_cylinder["amount"] > 0.0, "a face must report a positive area"


def t_measure_during_retargeting():
    """モディファイアの対象を選び直している最中の計測は、適用前の形を測る。

    これは不具合ではなく仕様。core_bridge は選択途中の中途半端な対象で
    モディファイアが適用されないよう、ターゲットを空で送っている
    (_is_modifier_retargeting)。対象ゼロのフィレットは何もしないので、
    カーネルの current_shape は本当にフィレット前の形になる。

    **問題は数字ではなく、それを黙って出すこと。** パネルはこの状態を検出して
    「適用前を測っている」と明示する。ここではその検出条件を固定する ---
    条件が壊れると、警告が出ないまま間違った体積が表示される。
    """
    from CAD_8_1_5_1 import core_bridge

    col, props = _fresh_part()
    bpy.ops.seamless.add_primitive(type='BOX')
    props = utils_props()
    props.primitives[-1].size = (2.0, 2.0, 2.0)

    lineages = _capture_edge_lineages(col)
    assert len(lineages) >= 4, "the box did not report its edges"

    bpy.ops.seamless.add_primitive(type='FILLET')
    props = utils_props()
    fillet = props.primitives[-1]
    fillet.target_lineages = "|".join(lineages[:4])
    fillet.radius = 0.2
    core_bridge.update_cad_preview_forced(bpy.context)

    stack_ptr = int(col.seamless_cad_stack_ptr)
    filleted = core_bridge.measure_stack(stack_ptr)
    assert filleted is not None
    # 角を丸めたぶん体積は 8 より小さい
    assert filleted["volume"] < 8.0 - 1e-4, \
        f"the fillet should remove material; volume is {filleted['volume']}"

    # 選択モードに入る = 対象の選び直し
    props.active_primitive_index = len(props.primitives) - 1
    props.is_selection_mode = True
    active = core_bridge._get_active_preview_primitive(props)
    assert core_bridge._is_modifier_retargeting(props, active),         "entering Selection Mode on a FILLET must count as retargeting (the panel warns on this)"

    core_bridge.update_cad_preview_forced(bpy.context)
    during = core_bridge.measure_stack(stack_ptr)
    assert during is not None
    assert abs(during["volume"] - 8.0) < 1e-3,         (f"while re-picking targets the fillet is sent with none, so the shape is the "
         f"plain 2x2x2 box; volume should be 8.0, got {during['volume']}")

    # 抜ければ元に戻る
    props.is_selection_mode = False
    assert not core_bridge._is_modifier_retargeting(props, active),         "leaving Selection Mode must clear the retargeting state"
    core_bridge.update_cad_preview_forced(bpy.context)
    after = core_bridge.measure_stack(stack_ptr)
    assert abs(after["volume"] - filleted["volume"]) < 1e-3, \
        f"the fillet should come back; {after['volume']} vs {filleted['volume']}"


def t_modifier_proxy_is_not_drawn():
    """対象に効くだけのモディファイアは、ビューポートに形を描かない。

    プロキシは全型が「箱」として作られていたので、FILLET を足すと原点に
    1x1x1 のワイヤーフレーム立方体が生まれ、モデルと無関係な場所に浮いていた。
    追加直後は自動でアクティブ選択されてハイライトが付き、選択が移ると
    地味な線に戻るため「一瞬出て消える」ように見えていた。

    **オブジェクト自体は残すこと。** Feature Tree の行とビューポート選択を
    結ぶのがプロキシの役目で(チェックリスト A/B)、消すと同期が壊れる。
    """
    from CAD_8_1_5_1 import core_bridge, utils

    col, props = _fresh_part()
    bpy.ops.seamless.add_primitive(type='BOX')
    props = utils_props()
    props.primitives[0].size = (2.0, 2.0, 2.0)
    lineages = _capture_edge_lineages(col)

    bpy.ops.seamless.add_primitive(type='FILLET')
    props = utils_props()
    fillet = props.primitives[-1]
    fillet.target_lineages = "|".join(lineages[:4])
    fillet.radius = 0.2
    core_bridge.update_cad_preview_forced(bpy.context)

    proxy = _proxy_for(col, fillet)
    assert len(proxy.data.vertices) == 0, \
        f"a FILLET proxy must have nothing to draw, got {len(proxy.data.vertices)} vertices"
    assert not proxy.show_name,         "with an empty mesh the name label would be the only thing left floating at the origin"

    # 箱のプロキシはこれまでどおり形を持つ
    box_proxy = _proxy_for(col, props.primitives[0])
    assert len(box_proxy.data.vertices) == 8, \
        f"a BOX proxy still needs its shape, got {len(box_proxy.data.vertices)} vertices"

    # 描かなくなっても、行を選べばプロキシがアクティブになる(チェックリスト B)
    bpy.ops.seamless.set_active_primitive(index=len(props.primitives) - 1)
    assert bpy.context.view_layer.objects.active == proxy,         "the modifier proxy must still be selectable from the Feature Tree"

    # そしてフィレット自体は効いたまま
    m = core_bridge.measure_stack(int(col.seamless_cad_stack_ptr))
    assert m["volume"] < 8.0 - 1e-4, \
        f"blanking the proxy must not stop the fillet working; volume is {m['volume']}"


def t_modifier_transform_is_ignored():
    """空メッシュ化した型が、本当に自分の transform を使っていないこと。

    これが前提。もしどれかが location / rotation を読むようになったら、
    ユーザーは「動かせるはずのものが見えない」状態になる。集合を広げる前にも
    ここで同じ確認をすること。
    """
    from CAD_8_1_5_1 import core_bridge, utils

    col, props = _fresh_part()
    bpy.ops.seamless.add_primitive(type='BOX')
    props = utils_props()
    props.primitives[0].size = (2.0, 2.0, 2.0)
    lineages = _capture_edge_lineages(col)

    bpy.ops.seamless.add_primitive(type='FILLET')
    props = utils_props()
    fillet = props.primitives[-1]
    fillet.target_lineages = "|".join(lineages[:4])
    fillet.radius = 0.2
    core_bridge.update_cad_preview_forced(bpy.context)
    before = core_bridge.measure_stack(int(col.seamless_cad_stack_ptr))["volume"]

    fillet.location = (17.0, -9.0, 5.0)
    fillet.rotation = (0.7, 0.3, 1.1)
    core_bridge.update_cad_preview_forced(bpy.context)
    after = core_bridge.measure_stack(int(col.seamless_cad_stack_ptr))["volume"]

    assert abs(before - after) < 1e-9,         (f"a FILLET must ignore its own transform, but moving it changed the volume "
         f"{before} -> {after}; the proxy cannot be blanked if this is false")


def t_offset_pick_writes_the_visible_field():
    """Offset のスポイトが、パネルに出ているプロパティへ書くこと。

    FACE_OFFSET の深さは radius ただ1つで、パネルもそれしか描かない。
    それなのに Offset のボタンだけ depth_attr を渡しておらず、
    StringProperty の既定値に頼っていた。このオペレータは
    bl_options に REGISTER/UNDO を持つので前回値が残りうる。先に Inset の
    スポイト(こちらは extrude_height を明示的に渡す)を使っていると、
    次の Offset が extrude_height へ書き、**拾った数値がどこにも出ない**。

    型から決め直すようにしたので、何が渡ってきても FACE_OFFSET は radius。
    """
    from CAD_8_1_5_1.operators.ops_offset_pick import resolve_depth_attr

    # Inset を先に使った後の持ち越しを再現する
    assert resolve_depth_attr('FACE_OFFSET', 'extrude_height') == 'radius',         "FACE_OFFSET must always write radius, whatever the operator remembered"
    assert resolve_depth_attr('FACE_OFFSET', 'radius') == 'radius'

    # FACE_INSET は radius と extrude_height の2つを持つので、指定を尊重する
    assert resolve_depth_attr('FACE_INSET', 'extrude_height') == 'extrude_height',         "FACE_INSET's Depth eyedropper must still drive extrude_height"
    assert resolve_depth_attr('FACE_INSET', 'radius') == 'radius',         "FACE_INSET's inset amount is radius; the caller's choice stands"

    # 空文字が来ても radius に落ちる(既定値が消えた場合の保険)
    assert resolve_depth_attr('FACE_INSET', '') == 'radius'


def t_offset_pick_reference_face():
    """スポイトが基準にする面の選び方。

    実機のログから取った本物の lineage で確かめる:

        Face:12@0.000;1.587;-1.500#N:0.0000;0.0000;1.0000

    **座標の後ろに法線が付く。** 最初の修正はこれを外さずに `@` 以降を `;` で
    割っていたので、3個目が "-1.500#N:0.0000" になって float() が例外を投げ、
    「手がかり無し」と判定して番号一致の旧経路へ落ちていた。つまり一度も
    発動していなかった。ログの cache_ref_pt=(0.5, 1.5866, -2.0) /
    ref_norm=(1,0,0) が、法線 (0,0,1) の面とは別物を掴んでいた証拠。
    """
    from CAD_8_1_5_1.operators.ops_offset_pick import (
        choose_reference_face, lineage_hint_point, lineage_hint_normal,
    )
    import mathutils

    V = mathutils.Vector
    real = "Face:12@0.000;1.587;-1.500#N:0.0000;0.0000;1.0000"

    hint = lineage_hint_point(real)
    assert hint is not None, "the #N: suffix must not stop the coordinates parsing"
    assert (hint - V((0.0, 1.587, -1.5))).length < 1e-6, f"got {hint}"

    n = lineage_hint_normal(real)
    assert n is not None and (n - V((0.0, 0.0, 1.0))).length < 1e-6, f"got {n}"

    # 報告された状況: 番号が一致する面は法線の違う別物(ログの (1,0,0))。
    # 本当の対象は番号が変わっており、法線が揃っている。
    candidates = [
        ("Face:12@0.500;1.587;-2.000#N:1.0000;0.0000;0.0000", V((0.5, 1.5866, -2.0)), V((1.0, 0.0, 0.0))),
        ("Face:31@0.000;1.587;-1.000#N:0.0000;0.0000;1.0000", V((0.0, 1.587, -1.0)),  V((0.0, 0.0, 1.0))),
    ]
    pick = choose_reference_face(candidates, real)
    assert pick == 1,         (f"the reference must be the face whose normal agrees with the lineage, "
         f"not the one that merely kept the number; picked {candidates[pick][0]}")

    # 法線が揃う面が複数あるときは、座標が近いほう
    candidates = [
        ("Face:5@0.000;1.587;-9.000#N:0.0000;0.0000;1.0000", V((0.0, 1.587, -9.0)), V((0.0, 0.0, 1.0))),
        ("Face:6@0.000;1.587;-1.400#N:0.0000;0.0000;1.0000", V((0.0, 1.587, -1.4)), V((0.0, 0.0, 1.0))),
    ]
    assert choose_reference_face(candidates, real) == 1

    # 裏返った法線も同じ面として扱う(|dot| で見るため)
    candidates = [
        ("Face:9@0.000;1.587;-1.400#N:0.0000;0.0000;-1.0000", V((0.0, 1.587, -1.4)), V((0.0, 0.0, -1.0))),
        ("Face:12@5.000;0.000;0.000#N:1.0000;0.0000;0.0000",  V((5.0, 0.0, 0.0)),    V((1.0, 0.0, 0.0))),
    ]
    assert choose_reference_face(candidates, real) == 0,         "a face pointing the opposite way is still the same face"

    # 完全一致は無条件で勝つ
    same = ("Face:12@0.000;1.587;-1.500#N:0.0000;0.0000;1.0000", V((0.0, 1.587, -1.5)), V((0.0, 0.0, 1.0)))
    assert choose_reference_face([("Face:1@0;0;0#N:0;0;1", V((0.0, 0.0, 0.0)), V((0.0, 0.0, 1.0))), same], real) == 1

    # 法線も座標も無い古い lineage は番号で
    plain = "Face:12"
    assert lineage_hint_point(plain) is None and lineage_hint_normal(plain) is None
    old = [("Face:3@0;0;0", V((0.0, 0.0, 0.0)), None), ("Face:12@9;9;9", V((9.0, 9.0, 9.0)), None)]
    assert choose_reference_face(old, plain) == 1

    assert choose_reference_face([], real) is None


def t_offset_face_becomes_unidentifiable():
    """オフセットした面は、動くほど身元が分からなくなる。

    **面は指定量ぶんきちんと動く。** radius=1.0 なら移動もちょうど 1.0。
    (このテストを最初に書いたときは「動かない」と書いていたが、それは
    面をプレフィックス一致で探していたための誤りだった --- 別の面を測っていた。)

    壊れるのはその手前、動いた後の面を lineage から見つける部分。手がかりは
    選んだ時点の座標しかないので、面が離れるほど当てにならなくなる。
    2 ユニットの箱では radius=2.0 で本物と反対側の面が手がかりから等距離になり、
    法線でゲートしても平行な面は両方通るので選び分けられない。

    **これがスポイトが測る前に深さを 0 に戻す理由。** 0 なら面は手がかりの
    座標そのものに居るので、特定が曖昧になりようがない。
    """
    from CAD_8_1_5_1 import core_bridge
    from CAD_8_1_5_1.operators.ops_offset_pick import choose_reference_face, _triangle_normal

    col, props = _fresh_part()
    bpy.ops.seamless.add_primitive(type='BOX')
    props = utils_props()
    props.primitives[0].size = (2.0, 2.0, 2.0)
    core_bridge.update_cad_preview_forced(bpy.context)

    def faces():
        import math as _m
        core = core_bridge.get_core()
        v, t, fids, counts = core.generate_mesh(int(col.seamless_cad_stack_ptr), 0.03, _m.radians(6.0))
        out, off = [], 0
        for i, lid in enumerate(fids):
            n = counts[i]
            idxs = list(t[off:off + n]); off += n
            if not idxs:
                continue
            vs = [mathutils.Vector((float(v[k*3]), float(v[k*3+1]), float(v[k*3+2]))) for k in idxs]
            c = mathutils.Vector((0.0, 0.0, 0.0))
            for q in vs:
                c += q
            c /= len(vs)
            out.append((lid, c, _triangle_normal(vs)))
        return out

    base = faces()[0]
    # 実際のピックが作るトークンと同じ形(法線付き)にする
    n = base[2]
    target = f"{base[0]}#N:{n.x:.4f};{n.y:.4f};{n.z:.4f}"

    bpy.ops.seamless.add_primitive(type='FACE_OFFSET')
    props = utils_props()
    ofs = props.primitives[-1]
    ofs.target_lineages = target

    # 小さいオフセットなら、まだ正しく見つかり、移動量は指定どおり
    ofs.radius = 1.0
    core_bridge.update_cad_preview_forced(bpy.context)
    cs = faces()
    i = choose_reference_face(cs, target)
    assert i is not None, "the face should still be found at a small offset"
    travelled = (cs[i][1] - base[1]).dot(base[2])
    assert abs(travelled - 1.0) < 1e-3, \
        f"the face does move by the requested amount; got {travelled} for 1.0"

    # 大きくすると、反対側の平行面のほうが手がかりに近くなり、選び分けられない
    ofs.radius = 3.0
    core_bridge.update_cad_preview_forced(bpy.context)
    cs = faces()
    i = choose_reference_face(cs, target)
    assert i is not None
    travelled = (cs[i][1] - base[1]).dot(base[2])
    assert abs(travelled - 3.0) > 1e-3,         ("identification survived a large offset. If that is now reliable the "
         "zeroing could be revisited, but verify on more than a box first")


def t_offset_pick_zero_reference():
    """深さ 0 のとき、対象面は lineage が記録した座標にいること。

    スポイトが深さを 0 に戻してから測る、その拠り所。ここが崩れると
    基準面の選択(座標の近さで選ぶ)も外れる。
    """
    from CAD_8_1_5_1 import core_bridge
    from CAD_8_1_5_1.operators.ops_offset_pick import lineage_hint_point

    col, props = _fresh_part()
    bpy.ops.seamless.add_primitive(type='BOX')
    props = utils_props()
    props.primitives[0].size = (2.0, 2.0, 2.0)
    faces = _capture_face_lineages(col)
    target = faces[0]

    hint = lineage_hint_point(target)
    assert hint is not None, f"the lineage should carry coordinates: {target}"

    bpy.ops.seamless.add_primitive(type='FACE_OFFSET')
    props = utils_props()
    ofs = props.primitives[-1]
    ofs.target_lineages = target
    ofs.radius = 0.0
    core_bridge.update_cad_preview_forced(bpy.context)

    c = _face_centroid(col, target)
    assert c is not None, "the target face must exist at depth 0"
    assert (mathutils.Vector(c) - hint).length < 1e-2, \
        f"at depth 0 the face should sit where the lineage says: {c} vs {tuple(hint)}"


def t_step_export_scale():
    """STEP 書き出しのスケール。1 Blender 単位を何 mm にするか選べること。

    以前は 1 単位 = 1 mm 固定で、ミリ単位で作ることを強制していた
    (docs/en/limitations.md の "STEP export scale is fixed")。

    検証は往復で行う。倍率 s で書き出したものを倍率 1 で読み戻すと、
    体積は s^3 倍になっていなければならない。ファイルの中身を読むより、
    「相手が受け取る寸法」を直接見るほうが意味がある。
    """
    import tempfile, os
    from CAD_8_1_5_1 import core_bridge

    col, props = _fresh_part()
    bpy.ops.seamless.add_primitive(type='BOX')
    props = utils_props()
    props.primitives[0].size = (2.0, 2.0, 2.0)
    core_bridge.update_cad_preview_forced(bpy.context)
    stack_ptr = int(col.seamless_cad_stack_ptr)

    src = core_bridge.measure_stack(stack_ptr)
    assert src and abs(src["volume"] - 8.0) < 1e-3, f"expected a volume of 8, got {src}"

    def roundtrip(scale):
        path = os.path.join(tempfile.gettempdir(), f"seamless_scale_{scale:g}.stp")
        assert core_bridge.export_stack_to_step(stack_ptr, path, scale),             f"export at scale {scale} failed"
        assert os.path.exists(path), f"no file written for scale {scale}"

        # 読み戻しはオペレータ経由。プリミティブの組み立て方(target_uuid /
        # step_scale / size)を検証側で真似すると、そこがズレたときに
        # 「スケールの不具合」に見えてしまう。
        col2, props2 = _fresh_part()
        res = bpy.ops.seamless.import_step(filepath=path, import_scale=1.0)
        assert 'FINISHED' in res, f"the file written at scale {scale} could not be read back"
        core_bridge.update_cad_preview_forced(bpy.context)
        got = core_bridge.measure_stack(int(col2.seamless_cad_stack_ptr))
        os.remove(path)
        return got

    # 既定(1.0)は従来どおり。ここが変わると既存ユーザーのファイルが崩れる
    same = roundtrip(1.0)
    assert same and abs(same["volume"] - 8.0) < 1e-2, \
        f"scale 1.0 must keep the previous behaviour; got {same}"

    # 2 倍で出すと、受け取り側では体積が 8 倍(2^3)
    bigger = roundtrip(2.0)
    assert bigger and abs(bigger["volume"] - 64.0) < 1e-1, \
        f"exporting at 2.0 should give a volume of 64 on the other side; got {bigger}"


def t_delete_updates_the_shape_at_once():
    """削除したら、その場で形状が消えること。

    利用者報告(2026-08-14, macOS): Feature Tree を全部消しても最後の1つが
    画面に残り、Workspace を移動すると消える。

    削除には2つの経路がある。ひとつは hidden_primitive_uuids へ入れて
    ワイヤーを見た目から即座に消すもの(management.py)。もうひとつが本物の
    再計算で、面のキャッシュを更新できるのはこちらだけ。後者が
    core_bridge の throttle(直前の更新から 60ms 以内なら debounce へ回して
    return)に捨てられると、ワイヤーだけ消えてシェーディングされた面が残る。

    throttle が force を見ていなかったのが原因。削除は連続した更新の直後に
    走るので、この間隔に収まりやすい。

    ここでは**連続して**消す。1つずつ間を空けると throttle に掛からず、
    修正の有無に関わらず通ってしまう。
    """
    from CAD_8_1_5_1 import core_bridge

    col, props = _fresh_part()
    for t in ('BOX', 'CYLINDER', 'SPHERE'):
        bpy.ops.seamless.add_primitive(type=t)
    core_bridge.update_cad_preview_forced(bpy.context)
    assert _result_vertex_count(col) > 0, "the three primitives produced no geometry"

    # 間を空けずに全部消す
    while len(utils_props().primitives):
        props = utils_props()
        bpy.ops.seamless.remove_primitive(index=len(props.primitives) - 1)

    assert len(utils_props().primitives) == 0, "the tree should be empty"

    # 見るのは**描画エンジンに渡ったデータ**。利用者が見ているのはそれ。
    # generate_mesh はカーネルの current_shape を読むので別物で、そちらは
    # ツリーが空でも直前の形を保持したままになる(下の注記を参照)。
    from CAD_8_1_5_1 import drawing
    stack = drawing.get_wireframe_engine().get_stack(int(col.seamless_cad_stack_ptr))
    verts = len(stack._cache_verts) if getattr(stack, "_cache_verts", None) is not None else 0
    edges = len(stack.coords) if getattr(stack, "coords", None) is not None else 0
    assert verts == 0 and edges == 0,         (f"deleting every row must leave nothing to draw, but the engine still holds "
         f"{verts} face vertices and {edges} edge coords — that is the shape staying "
         f"on screen until something else forces a recompute")

    # 既知の別件: ツリーが空になってもカーネルの current_shape は直前の形を
    # 保持する。画面には出ないが、その状態で測ると消したはずの体積が返る。
    # 表示の不具合とは別なので、ここでは固定しない。


def t_inset_needs_a_flat_face():
    """Inset が曲面で効かないことを、既知の制限として固定する。

    利用者報告(2026-08-14, macOS): 「Inset が cylinder や円錐で動作しません」。
    正確には「円柱・円錐だから」ではなく**曲面だから**で、平らな上面・底面や
    箱の6面では動く。内側オフセットに平面ワイヤーの処理を使っているため
    (occ_modifiers.cpp の BRepOffsetAPI_MakeOffset)。

    これは「こうあるべき」ではなく「今こうである」を書き留めるテスト。
    曲面に対応したらここが赤くなるので、そのとき制限の記述(limitations.md)と
    パネルの注記も一緒に消すこと。
    """
    from CAD_8_1_5_1 import core_bridge

    col, props = _fresh_part()
    bpy.ops.seamless.add_primitive(type='CYLINDER')
    core_bridge.update_cad_preview_forced(bpy.context)
    stack_ptr = int(col.seamless_cad_stack_ptr)
    base = core_bridge.measure_stack(stack_ptr)["volume"]

    curved = None
    flat = None
    for lid in _capture_face_lineages(col):
        info = core_bridge.measure_entity(stack_ptr, lid, True)
        if not info or not info.get("resolved"):
            continue
        if info["shape"] == "Cylinder" and curved is None:
            curved = lid
        elif info["shape"] == "Plane" and flat is None:
            flat = lid
    assert curved and flat, "a cylinder should expose both a curved side and flat ends"

    def inset_on(target):
        bpy.ops.seamless.add_primitive(type='FACE_INSET')
        p = utils_props().primitives[-1]
        p.target_lineages = target
        p.radius = 0.15
        p.extrude_height = 0.2
        core_bridge.update_cad_preview_forced(bpy.context)
        v = core_bridge.measure_stack(stack_ptr)["volume"]
        props_now = utils_props()
        props_now.primitives.remove(len(props_now.primitives) - 1)
        core_bridge.update_cad_preview_forced(bpy.context)
        return v

    assert abs(inset_on(flat) - base) > 1e-6,         "Inset must work on the flat end of a cylinder"
    assert abs(inset_on(curved) - base) < 1e-9,         ("Inset now changes a curved face. If that is intended, remove this test, "
         "the note in the Inset panel and the entry in limitations.md")


def t_offset_pick_reference_is_exact():
    """スポイトの基準が、テセレーションではなくカーネルの厳密な幾何から来ること。

    利用者報告(2026-08-14): スポイトで面を揃えてから CLEANUP しても、統合される
    ときとされないときがある。保存ファイルを開いて測ると、全体高さが 1.0 に対し
    1.9864e-6 高く、上下の offset 2本も絶対値が 9.5e-7 食い違っていた。

    基準点をテセレーション結果(numpy float32)の頂点平均から取っていたのが原因で、
    精度の床が 1e-6 前後。CLEANUP の SetLinearTolerance も 1e-6 なので、誤差が
    ちょうど境界に乗り、条件次第で統合されたりされなかったりしていた。

    許容値を緩めるのではなく、床のほうを消してある。
    """
    from CAD_8_1_5_1 import core_bridge
    from CAD_8_1_5_1.operators.ops_offset_pick import SEAMLESS_OT_InteractiveOffsetPick as OP
    import types

    col, props = _fresh_part()
    bpy.ops.seamless.add_primitive(type='BOX')
    props = utils_props()
    props.primitives[0].size = (1.0, 1.0, 1.0)
    # 半端な位置に置く。きりの良い座標だと float32 でも誤差が出ず、検査にならない
    props.primitives[0].location = (0.0, 0.0, 0.3172819)
    core_bridge.update_cad_preview_forced(bpy.context)
    stack_ptr = int(col.seamless_cad_stack_ptr)

    class _Shim:
        pass
    op = _Shim()
    op._get_face_center_and_normal = types.MethodType(OP._get_face_center_and_normal, op)

    checked = 0
    for lid in _capture_face_lineages(col):
        info = core_bridge.measure_entity(stack_ptr, lid, True)
        if not info or not info.get("resolved") or not info.get("normal"):
            continue
        pt, nrm = op._get_face_center_and_normal(stack_ptr, lid)
        assert pt is not None, f"the reference for {lid} could not be resolved"
        gap = (mathutils.Vector(info["centre"]) - pt).length
        assert gap < 1e-12,             (f"the eyedropper reference must be the kernel's exact face centre, "
             f"but it is {gap:.3e} away for {lid}. A float32 tessellation average "
             f"lands around 1e-6, which is exactly CLEANUP's linear tolerance")
        n_gap = (mathutils.Vector(info["normal"]).normalized() - nrm).length
        assert n_gap < 1e-12, f"the normal should be the exact plane normal; off by {n_gap:.3e}"
        checked += 1

    assert checked >= 6, f"a box should offer six planar faces to check, got {checked}"


def t_offset_pick_then_cleanup_merges():
    """スポイトで揃えた面が CLEANUP で本当に統合されること。

    t_offset_pick_reference_is_exact が基準点の精度を見るのに対し、こちらは
    結果側を見る。統合が丸ごと壊れたら気づけるようにするためのもので、
    **精度の改善を証明するものではない**。破壊試験で確かめたところ、基準を
    float32 のテセレーションキャッシュに戻してもこの規模では通ってしまう
    (残差 3e-8、CLEANUP の許容 1e-6 に対して十分小さい)。

    座標を 40 倍にすると、基準を厳密にしても統合されなくなる。これは
    テセレーションではなく `radius` が Blender の FloatProperty = float32 で
    あることの床で、値が 32 付近だと 1ulp が 2e-6、許容 1e-6 を超えるため。
    別の問題として残っている。
    """
    from CAD_8_1_5_1 import core_bridge
    from CAD_8_1_5_1.operators.ops_offset_pick import SEAMLESS_OT_InteractiveOffsetPick as OP
    import types

    col, props = _fresh_part()
    bpy.ops.seamless.add_primitive(type='BOX')
    props = utils_props()
    props.primitives[0].size = (1.0, 1.0, 1.0)
    props.primitives[0].location = (0.0, 0.0, 0.0)
    bpy.ops.seamless.add_primitive(type='BOX')
    props = utils_props()
    # 隣に置き、天面だけ半端な高さにずらす。ここを揃えて統合させる
    props.primitives[1].size = (1.0, 1.0, 0.6172819)
    props.primitives[1].location = (1.0, 0.0, -0.1913590)
    props.primitives[1].operation = 'ADD'
    core_bridge.update_cad_preview_forced(bpy.context)
    stack_ptr = int(col.seamless_cad_stack_ptr)

    class _Shim:
        pass
    op = _Shim()
    op._get_face_center_and_normal = types.MethodType(OP._get_face_center_and_normal, op)

    # 天面(+Z)を2つ拾い、低いほうを高いほうへ揃える距離を、スポイトと同じ式で出す
    tops = []
    for lid in _capture_face_lineages(col):
        info = core_bridge.measure_entity(stack_ptr, lid, True)
        if not info or not info.get("normal"):
            continue
        if abs(info["normal"][2] - 1.0) > 1e-6:
            continue
        tops.append((lid, info["centre"]))
    assert len(tops) == 2, f"two upward faces expected, got {len(tops)}"
    tops.sort(key=lambda t: t[1][2])
    low_lid, _ = tops[0]
    _, high_c = tops[1]

    ref_pt, ref_n = op._get_face_center_and_normal(stack_ptr, low_lid)
    assert ref_pt is not None
    d = (mathutils.Vector(high_c) - ref_pt).dot(ref_n)

    bpy.ops.seamless.add_primitive(type='FACE_OFFSET')
    props = utils_props()
    mod = props.primitives[-1]
    mod.target_lineage = low_lid
    mod.radius = d
    core_bridge.update_cad_preview_forced(bpy.context)

    before = len(_capture_face_lineages(col))
    bpy.ops.seamless.add_primitive(type='CLEANUP')
    core_bridge.update_cad_preview_forced(bpy.context)
    after = len(_capture_face_lineages(col))

    assert after < before,         (f"CLEANUP left {after} faces from {before}: the two top faces are meant to be "
         f"coplanar after the pick and should merge. If the reference came from the "
         f"float32 tessellation cache the residual is ~1e-6, which is exactly "
         f"CLEANUP's SetLinearTolerance, so merging becomes a coin toss")


def t_grid_lines_pass_through_the_origin():
    """描いたグリッドの線が、吸着位置と同じ場所に来る。

    吸着は modal_sketch が round(x/step)*step、つまり原点基準で丸める。
    グリッド描画がそれと違う基準で線を並べると、**見た目と吸着先がずれる**。
    以前は -max(10.0, step*20.0) から step 刻みで並べていたため、
    step が 10.0 を割り切らない値(0.064 / 0.128 / 0.256)のとき 0.016 ずれた
    (2026-08-18 のユーザー報告。X=-0.768 は 0.064 の12倍で、
    吸着自体は正しくグリッドだけがずれていた)。

    刻みが 2 の冪乗から外れる経路も塞いだが、ここでは**どんな刻みでも**
    原点を通ることを確かめる。片方だけ直して安心しないため。
    """
    from CAD_8_1_5_1.sketch import sketch_globals
    from CAD_8_1_5_1.sketch.modal_sketch import MIN_GRID_STEP, MAX_GRID_STEP

    def grid_x_lines(step):
        """sketch_draw のグリッド生成と同じ式で X 座標だけ作る。"""
        half = max(10.0, step * 20.0)
        n = int(math.ceil(half / step))
        return [i * step for i in range(-n, n + 1)]

    # 2 の冪乗だけでなく、列から外れた値も混ぜる。対称な値だけで確かめると
    # まさに今回の不具合が素通りする。
    for step in (1.0, 0.5, 0.25, 0.125, 0.064, 0.128, 0.256, 0.512, 1.024, 0.3, 0.001):
        xs = grid_x_lines(step)
        nearest = min(xs, key=abs)
        assert abs(nearest) < 1e-9, \
            f"grid step {step} puts no line on the origin; nearest is {nearest}"

        # 吸着先(原点基準の丸め)が、必ずグリッド線の上に乗ること
        for probe in (0.0, step * 0.4, -step * 0.4, step * 3.2, -step * 7.7):
            snapped = round(probe / step) * step
            assert any(abs(snapped - x) < step * 1e-6 for x in xs), \
                f"grid step {step}: snap target {snapped} is not on any drawn grid line"

    # 刻みの上下限が、1.0 を起点にした 2 の冪乗の列の上にあること。
    # ここが列から外れると、下げ切って戻したときに変な刻みが残る。
    for limit in (MIN_GRID_STEP, MAX_GRID_STEP):
        exponent = math.log2(limit)
        assert abs(exponent - round(exponent)) < 1e-12, \
            f"grid step limit {limit} is not a power of two, so halving and doubling cannot round-trip"

    # 下げ切ってから戻すと元の刻みに帰ってくること(クランプで列を外れない)
    step = 1.0
    for _ in range(30):
        finer = step / 2.0
        if finer >= MIN_GRID_STEP:
            step = finer
    assert abs(step - MIN_GRID_STEP) < 1e-12, f"halving should stop at the limit, got {step}"
    for _ in range(30):
        coarser = step * 2.0
        if coarser <= MAX_GRID_STEP:
            step = coarser
    assert abs(step - MAX_GRID_STEP) < 1e-12, f"doubling should stop at the limit, got {step}"

    sketch_globals._grid_step = 1.0


def t_vertex_snap_off_stops_merge_on_release():
    """Vertex Snap を切ったら、離した頂点が隣の頂点に吸収されない。

    releasing a drag は state_base のホバー判定とは **別経路** で近くの点を
    探し、見つかると参照を書き換えて点を削除する破壊的マージを行う。
    ホバー側だけ止めても効かず、トグルを OFF にしても勝手に繋がる、という
    報告(2026-08-18)がここから出た。長方形の頂点が1点にまとまる症状も同じ経路。

    背景実行では region が無いのでしきい値は従来の固定値 0.15 に落ちる。
    0.1 離した2点はその中に入るので、ON なら必ず吸収される距離になる。
    """
    col, props = _fresh_part()

    def build():
        _sketch_reset(props)
        _sk_point(props, 1, 0.0, 0.0)
        _sk_point(props, 2, 0.1, 0.0)   # しきい値 0.15 の内側
        _sk_point(props, 3, 2.0, 0.0)
        _sk_line(props, 1, 1, 3)
        _sk_line(props, 2, 2, 3)

    def ids():
        return sorted(p.id for p in props.sketch_points)

    # ON(既定): 従来どおり吸収される。これが壊れると「繋げたいのに繋がらない」
    build()
    props.sketch_snap_vertex = True
    _release_drag(props, 2)
    assert ids() == [1, 3], \
        f"with Vertex Snap on, releasing point 2 next to point 1 should merge it away; points are {ids()}"

    # OFF: 3点そのまま残る
    build()
    props.sketch_snap_vertex = False
    _release_drag(props, 2)
    assert ids() == [1, 2, 3], \
        f"with Vertex Snap off, no point may be absorbed; points are {ids()}"
    assert _sk_co(props, 2) == (0.1, 0.0), \
        f"point 2 must keep the position it was dropped at, got {_sk_co(props, 2)}"

    # ON でも Ctrl を押していれば、そのリリースだけ吸収しない
    build()
    props.sketch_snap_vertex = True
    _release_drag(props, 2, ctrl=True)
    assert ids() == [1, 2, 3], \
        f"holding Ctrl must skip the merge even with the toggle on; points are {ids()}"


def t_sketch_solver_constraints():
    """2D スケッチの拘束ソルバ(GCS)が実際に解いている。

    拘束を足した時点で自動的に解かれるので、明示的に solve を呼ぶ必要はない。
    ソルバ本体は Rust 側の ezpz。ここが壊れるとスケッチ機能全体が無言で
    「拘束を付けても形が変わらない」状態になる。
    """
    col, props = _fresh_part()

    # HORIZONTAL: 2点の Y が揃う
    _sketch_reset(props)
    _sk_point(props, 1, 0.0, 0.0)
    _sk_point(props, 2, 2.0, 0.37)
    _sk_line(props, 1, 1, 2)
    _sk_constraint(props, 1, 'FIXED', [1])
    _sk_constraint(props, 2, 'HORIZONTAL', [1, 2])
    assert _sk_co(props, 2) == (2.0, 0.0), \
        f"HORIZONTAL should level the two points, got {_sk_co(props, 2)}"

    # DISTANCE: 指定した距離ちょうどになる
    _sketch_reset(props)
    _sk_point(props, 1, 0.0, 0.0)
    _sk_point(props, 2, 2.0, 0.0)
    _sk_line(props, 1, 1, 2)
    _sk_constraint(props, 1, 'FIXED', [1])
    _sk_constraint(props, 2, 'DISTANCE', [1, 2], 5.0)
    x, y = _sk_co(props, 2)
    dist = math.hypot(x - 0.0, y - 0.0)
    assert abs(dist - 5.0) < 1e-3, f"DISTANCE 5.0 was not honoured; got {dist}"

    # MIDPOINT: (端点1, 端点2, 中点) の順
    _sketch_reset(props)
    _sk_point(props, 1, 0.0, 0.0)
    _sk_point(props, 2, 4.0, 0.0)
    _sk_point(props, 3, 3.0, 0.8)
    _sk_line(props, 1, 1, 2)
    _sk_constraint(props, 1, 'FIXED', [1])
    _sk_constraint(props, 2, 'FIXED', [2])
    _sk_constraint(props, 3, 'MIDPOINT', [1, 2, 3])
    assert _sk_co(props, 3) == (2.0, 0.0), \
        f"MIDPOINT should land halfway, got {_sk_co(props, 3)}"

    # RADIUS: 円の半径が指定値になる。Rust 側では CircleRadius + DistanceVar
    # の2本に展開される。DistanceVar を落とすと半径変数がどの点にも繋がらず、
    # 「拘束は受理されるのに円が動かない」という無言の壊れ方をする。
    _sketch_reset(props)
    _sk_point(props, 1, 0.0, 0.0)   # 中心
    _sk_point(props, 2, 2.0, 0.0)   # 円周上
    _sk_circle(props, 1, 1, 2)
    _sk_constraint(props, 1, 'FIXED', [1])
    _sk_constraint(props, 2, 'RADIUS', [1, 2], 5.0)
    x, y = _sk_co(props, 2)
    r = math.hypot(x, y)
    assert abs(r - 5.0) < 1e-3, f"RADIUS 5.0 was not honoured; radius is {r}"

    # 縮める方向も効くこと。増やす側だけ見ていると、初期推定値をそのまま
    # 返しているだけの実装を見逃す。value の update コールバックが解き直す
    props.sketch_constraints[1].value = 1.5
    x, y = _sk_co(props, 2)
    r = math.hypot(x, y)
    assert abs(r - 1.5) < 1e-3, f"RADIUS should shrink the circle too; radius is {r}"

    # **中心が動かないこと。** 半径を変えたときに中心まで動くと、円が横へ
    # ずれる。ソルバは「今の配置から移動量が最小の解」を返すので、中心も
    # 円周点も自由なら両方が半分ずつ動く。中心を低優先で留めて防いでいる。
    # ここでは中心に FIXED を付けずに確かめる --- FIXED があると、この保持が
    # 効いていなくても中心が動かず、検査が意味を失う。
    _sketch_reset(props)
    _sk_point(props, 1, 3.0, 1.0)   # 中心 (原点から離しておく)
    _sk_point(props, 2, 5.0, 1.0)   # 円周上 (半径 2)
    _sk_circle(props, 1, 1, 2)
    _sk_constraint(props, 1, 'RADIUS', [1, 2], 6.0)
    cx, cy = _sk_co(props, 1)
    assert abs(cx - 3.0) < 1e-3 and abs(cy - 1.0) < 1e-3, \
        f"the centre must stay at (3.0, 1.0) when the radius changes; it moved to ({cx}, {cy})"
    x, y = _sk_co(props, 2)
    assert abs(math.hypot(x - cx, y - cy) - 6.0) < 1e-3, \
        f"the rim should be 6.0 from the centre, got {math.hypot(x - cx, y - cy)}"


def t_sketch_angle_and_equal():
    """ANGLE と EQUAL が解けている。

    ANGLE の角度は ezpz の LinesAtAngle に合わせて **線1から線2へ反時計回り**。
    向きを取り違えると符号が反転し、90度を指定したのに -90 度に落ち着く。
    """
    col, props = _fresh_part()

    # ANGLE: 水平な線1に対して、線2を 90 度(反時計回り)にする
    _sketch_reset(props)
    _sk_point(props, 1, 0.0, 0.0)
    _sk_point(props, 2, 3.0, 0.0)   # 線1: +X 向き
    _sk_point(props, 3, 0.0, 0.0)
    _sk_point(props, 4, 3.0, 0.4)   # 線2: ほぼ +X 向き(まだ寝ている)
    _sk_line(props, 1, 1, 2)
    _sk_line(props, 2, 3, 4)
    _sk_constraint(props, 1, 'FIXED', [1])
    _sk_constraint(props, 2, 'FIXED', [2])
    _sk_constraint(props, 3, 'FIXED', [3])
    _sk_constraint(props, 4, 'ANGLE', [1, 2, 3, 4], 90.0)

    x, y = _sk_co(props, 4)
    got = math.degrees(math.atan2(y - 0.0, x - 0.0))
    assert abs(got - 90.0) < 0.5, \
        f"ANGLE 90 should stand line 2 up (CCW from line 1); line 2 points at {got:.2f} deg"

    # 別の角度でも効く。90度は対称なので、これを外すと符号の誤りを見逃す
    _sketch_reset(props)
    _sk_point(props, 1, 0.0, 0.0)
    _sk_point(props, 2, 3.0, 0.0)
    _sk_point(props, 3, 0.0, 0.0)
    _sk_point(props, 4, 3.0, 0.4)
    _sk_line(props, 1, 1, 2)
    _sk_line(props, 2, 3, 4)
    _sk_constraint(props, 1, 'FIXED', [1])
    _sk_constraint(props, 2, 'FIXED', [2])
    _sk_constraint(props, 3, 'FIXED', [3])
    _sk_constraint(props, 4, 'ANGLE', [1, 2, 3, 4], 30.0)
    x, y = _sk_co(props, 4)
    got = math.degrees(math.atan2(y, x))
    assert abs(got - 30.0) < 0.5, f"ANGLE 30 was not honoured; line 2 points at {got:.2f} deg"

    # EQUAL: 短い線が長い線に揃う(あるいはその逆)。長さが一致すればよい
    _sketch_reset(props)
    _sk_point(props, 1, 0.0, 0.0)
    _sk_point(props, 2, 4.0, 0.0)   # 長さ 4
    _sk_point(props, 3, 0.0, 2.0)
    _sk_point(props, 4, 1.0, 2.0)   # 長さ 1
    _sk_line(props, 1, 1, 2)
    _sk_line(props, 2, 3, 4)
    _sk_constraint(props, 1, 'FIXED', [1])
    _sk_constraint(props, 2, 'FIXED', [2])
    _sk_constraint(props, 3, 'FIXED', [3])
    _sk_constraint(props, 4, 'EQUAL', [1, 2, 3, 4])

    x1, y1 = _sk_co(props, 1)
    x2, y2 = _sk_co(props, 2)
    x3, y3 = _sk_co(props, 3)
    x4, y4 = _sk_co(props, 4)
    len1 = math.hypot(x2 - x1, y2 - y1)
    len2 = math.hypot(x4 - x3, y4 - y3)
    assert abs(len1 - len2) < 1e-3, \
        f"EQUAL should match the two lengths; got {len1:.4f} and {len2:.4f}"
    # 線1は両端を固定してあるので、動いたのは線2でなければならない
    assert abs(len1 - 4.0) < 1e-3, f"the pinned line should not have moved; it is {len1:.4f}"


def t_sketch_concentric_and_symmetric():
    """CONCENTRIC と SYMMETRIC が解けている。"""
    col, props = _fresh_part()

    # CONCENTRIC: 2つ目の円の中心が1つ目に寄る。中心点は2つとも残る
    # (Coincident の統合と違い、点を消す拘束ではない)
    _sketch_reset(props)
    _sk_point(props, 1, 0.0, 0.0)   # 円1 中心
    _sk_point(props, 2, 2.0, 0.0)   # 円1 円周
    _sk_circle(props, 1, 1, 2)
    _sk_point(props, 3, 5.0, 3.0)   # 円2 中心
    _sk_point(props, 4, 6.0, 3.0)   # 円2 円周
    _sk_circle(props, 2, 3, 4)
    _sk_constraint(props, 1, 'FIXED', [1])
    _sk_constraint(props, 2, 'CONCENTRIC', [1, 3])

    assert _sk_co(props, 3) == (0.0, 0.0), \
        f"CONCENTRIC should pull the second centre onto the first, got {_sk_co(props, 3)}"
    assert len(props.sketch_points) == 4, \
        "CONCENTRIC must not merge or delete points; that is what Coincident does"
    assert len(props.sketch_circles) == 2, "both circles must survive"

    # SYMMETRIC: Y軸を鏡にして2点が対称になる。非対称な初期配置から始める
    _sketch_reset(props)
    _sk_point(props, 1, 0.0, 0.0)   # 軸 始点
    _sk_point(props, 2, 0.0, 5.0)   # 軸 終点 (Y軸)
    _sk_line(props, 1, 1, 2)
    _sk_point(props, 3, -3.0, 2.0)  # 点1
    _sk_point(props, 4, 1.0, 0.5)   # 点2 (まだ対称ではない)
    _sk_constraint(props, 1, 'FIXED', [1])
    _sk_constraint(props, 2, 'FIXED', [2])
    _sk_constraint(props, 3, 'FIXED', [3])
    _sk_constraint(props, 4, 'SYMMETRIC', [1, 2, 3, 4])

    x3, y3 = _sk_co(props, 3)
    x4, y4 = _sk_co(props, 4)
    assert abs(x4 - (-x3)) < 1e-3 and abs(y4 - y3) < 1e-3, \
        f"SYMMETRIC about the Y axis should mirror ({x3}, {y3}) to ({-x3}, {y3}); got ({x4}, {y4})"

    # 斜めの軸でも効くこと。Y軸だけで確かめると、単に X を反転しているだけの
    # 実装や、軸の向きを無視した実装を見逃す
    _sketch_reset(props)
    _sk_point(props, 1, 0.0, 0.0)
    _sk_point(props, 2, 4.0, 4.0)   # 45度の軸
    _sk_line(props, 1, 1, 2)
    _sk_point(props, 3, 3.0, 0.0)
    _sk_point(props, 4, 1.0, 1.5)
    _sk_constraint(props, 1, 'FIXED', [1])
    _sk_constraint(props, 2, 'FIXED', [2])
    _sk_constraint(props, 3, 'FIXED', [3])
    _sk_constraint(props, 4, 'SYMMETRIC', [1, 2, 3, 4])

    # 45度線について (3, 0) の鏡像は (0, 3)
    x4, y4 = _sk_co(props, 4)
    assert abs(x4 - 0.0) < 1e-2 and abs(y4 - 3.0) < 1e-2, \
        f"mirroring (3, 0) across the 45-degree axis should give (0, 3); got ({x4}, {y4})"


def t_sketch_two_line_constraint_actions():
    """Angle / Equal ボタンの経路。重複拒否と、選択なしの扱い。"""
    from CAD_8_1_5_1.sketch.actions import constraints as sk_constraints

    col, props = _fresh_part()
    _sketch_reset(props)
    _sk_point(props, 1, 0.0, 0.0)
    _sk_point(props, 2, 3.0, 0.0)
    _sk_point(props, 3, 0.0, 1.0)
    _sk_point(props, 4, 3.0, 1.4)
    _sk_line(props, 1, 1, 2)
    _sk_line(props, 2, 3, 4)

    # 線が選ばれていなければ何も起きない
    props.sketch_selected_line_id = -1
    props.sketch_selected_line_id_2 = -1
    assert sk_constraints._two_selected_lines(props) is None, \
        "no lines selected must not resolve to a pair"
    before = len(props.sketch_constraints)
    bpy.ops.seamless.sketch_action(action='CONSTRAINT_ANGLE')
    assert len(props.sketch_constraints) == before, \
        "ANGLE was added without a selection"

    props.sketch_selected_line_id = 1
    props.sketch_selected_line_id_2 = 2
    bpy.ops.seamless.sketch_action(action='CONSTRAINT_ANGLE')
    added = props.sketch_constraints[-1]
    assert added.type == 'ANGLE', f"wrong type: {added.type}"
    assert added.target_ids_str == "1,2,3,4", f"wrong targets: {added.target_ids_str}"
    # 現在の角度が入っていること。線2は (3,0.4) 方向なので atan2(0.4,3)
    expected = math.degrees(math.atan2(0.4, 3.0))
    assert abs(added.value - expected) < 0.5, \
        f"value should be the current angle {expected:.2f}, got {added.value:.2f}"

    # 二重付けは拒否
    bpy.ops.seamless.sketch_action(action='CONSTRAINT_ANGLE')
    assert sum(1 for c in props.sketch_constraints if c.type == 'ANGLE') == 1, \
        "a second angle constraint was added on the same pair"

    # 線を選ぶ順を入れ替えても同じ組と見なす
    props.sketch_selected_line_id = 2
    props.sketch_selected_line_id_2 = 1
    bpy.ops.seamless.sketch_action(action='CONSTRAINT_ANGLE')
    assert sum(1 for c in props.sketch_constraints if c.type == 'ANGLE') == 1, \
        "swapping the selection order let a duplicate angle constraint through"

    # EQUAL は別種なので、同じ組でも足せる
    bpy.ops.seamless.sketch_action(action='CONSTRAINT_EQUAL')
    assert sum(1 for c in props.sketch_constraints if c.type == 'EQUAL') == 1, \
        "EQUAL should be addable alongside ANGLE"
    assert props.sketch_constraints[-1].target_ids_str == "3,4,1,2", \
        f"EQUAL should record the current selection order, got {props.sketch_constraints[-1].target_ids_str}"


def t_sketch_circle_distance_holds_centre():
    """円の寸法を DISTANCE で編集しても中心が動かない。

    ユーザー報告そのもの: 円の寸法ラベル(パネルの Edit Dimension)は DISTANCE
    拘束を編集する経路で、Distance(中心, 円周点) は補正を両方の点に分配する
    ため中心が横へ流れていた。ソルバーへ送る段で RADIUS に振り替えて直した。

    保存されている拘束は DISTANCE のままであることも併せて確かめる。型ごと
    書き換えてしまうと、パネルが寸法ラベルを見つけられなくなり編集できなくなる。
    """
    col, props = _fresh_part()
    _sketch_reset(props)
    _sk_point(props, 1, 4.0, 2.0)   # 中心
    _sk_point(props, 2, 6.0, 2.0)   # 円周上 (半径 2)
    _sk_circle(props, 1, 1, 2)
    _sk_constraint(props, 1, 'DISTANCE', [1, 2], 5.0)

    cx, cy = _sk_co(props, 1)
    assert abs(cx - 4.0) < 1e-3 and abs(cy - 2.0) < 1e-3, \
        f"editing a circle's dimension must not move its centre; it went to ({cx}, {cy})"
    x, y = _sk_co(props, 2)
    assert abs(math.hypot(x - cx, y - cy) - 5.0) < 1e-3, \
        f"the rim should end up 5.0 from the centre, got {math.hypot(x - cx, y - cy)}"

    assert props.sketch_constraints[0].type == 'DISTANCE',         "the stored constraint must stay DISTANCE or the dimension label cannot find it"

    # 円周点を先に書いた順序でも同じこと(振り替えで並べ替えている)
    _sketch_reset(props)
    _sk_point(props, 1, 4.0, 2.0)
    _sk_point(props, 2, 6.0, 2.0)
    _sk_circle(props, 1, 1, 2)
    _sk_constraint(props, 1, 'DISTANCE', [2, 1], 5.0)
    cx, cy = _sk_co(props, 1)
    assert abs(cx - 4.0) < 1e-3 and abs(cy - 2.0) < 1e-3, \
        f"reversed target order must also hold the centre; it went to ({cx}, {cy})"

    # 円に属さない2点なら従来どおり両方が動いてよい(線の寸法はこの経路)
    _sketch_reset(props)
    _sk_point(props, 1, 0.0, 0.0)
    _sk_point(props, 2, 2.0, 0.0)
    _sk_line(props, 1, 1, 2)
    _sk_constraint(props, 1, 'DISTANCE', [1, 2], 6.0)
    a = _sk_co(props, 1)
    b = _sk_co(props, 2)
    assert abs(math.hypot(b[0] - a[0], b[1] - a[1]) - 6.0) < 1e-3,         "a plain distance between two loose points must still be honoured"


def t_sketch_radius_constraint_action():
    """Radius ボタンの経路。選択から円を見つけて拘束を作れている。

    ソルバ本体は t_sketch_solver_constraints が見ているので、ここが守るのは
    その手前 --- 「どの点が選ばれていたら、どの円の、どの2点を対象にするか」。
    ここを間違えると、解は正しく出るのに違う円が縮む。
    """
    from CAD_8_1_5_1.sketch.actions import constraints as sk_constraints

    col, props = _fresh_part()
    _sketch_reset(props)
    _sk_point(props, 1, 0.0, 0.0)
    _sk_point(props, 2, 2.0, 0.0)
    _sk_circle(props, 1, 1, 2)
    # 別の円を混ぜておく。選択と無関係な円を掴んでいないことを確かめるため
    _sk_point(props, 3, 10.0, 10.0)
    _sk_point(props, 4, 13.0, 10.0)
    _sk_circle(props, 2, 3, 4)

    # 円周上の点を選ぶ
    found = sk_constraints._find_radius_target(props, [2])
    assert found == (1, 2, "circle 1"), f"rim point should resolve to its own circle, got {found}"

    # 中心点を選んでも同じ円に解決する
    found = sk_constraints._find_radius_target(props, [1])
    assert found == (1, 2, "circle 1"), f"center point should resolve to its own circle, got {found}"

    # 2つ目の円の点は2つ目の円に解決する(1つ目に吸われない)
    found = sk_constraints._find_radius_target(props, [4])
    assert found == (3, 4, "circle 2"), f"second circle must not resolve to the first, got {found}"

    # 円弧は中心と始点を返す
    _sk_point(props, 5, 0.0, 5.0)
    _sk_point(props, 6, 1.0, 5.0)
    _sk_point(props, 7, 0.5, 5.5)
    a = props.sketch_arcs.add()
    a.id = 1
    a.center_point_id = 5
    a.start_point_id = 6
    a.end_point_id = 7
    a.mid_point_id = 7
    found = sk_constraints._find_radius_target(props, [6])
    assert found == (5, 6, "arc 1"), f"arc point should resolve to its arc, got {found}"

    # 円にも円弧にも属さない点は None
    _sk_point(props, 8, -4.0, -4.0)
    assert sk_constraints._find_radius_target(props, [8]) is None, \
        "a loose point must not resolve to any circle"

    # 実際にボタンを押す経路。選択状態を作ってオペレータを呼ぶ
    props.sketch_selected_points_str = "2"
    props.sketch_selected_point_id = -1
    props.sketch_selected_point_id_2 = -1
    before = len(props.sketch_constraints)
    bpy.ops.seamless.sketch_action(action='CONSTRAINT_RADIUS')
    assert len(props.sketch_constraints) == before + 1, \
        "CONSTRAINT_RADIUS did not add a constraint"
    added = props.sketch_constraints[-1]
    assert added.type == 'RADIUS', f"wrong constraint type: {added.type}"
    assert added.target_ids_str == "1,2", f"wrong targets: {added.target_ids_str}"
    assert abs(added.value - 2.0) < 1e-6, f"value should be the current radius, got {added.value}"

    # 二重付けは過拘束になるので拒否される
    bpy.ops.seamless.sketch_action(action='CONSTRAINT_RADIUS')
    radius_count = sum(1 for c in props.sketch_constraints if c.type == 'RADIUS')
    assert radius_count == 1, f"a second radius constraint was added on the same circle ({radius_count})"


def t_sketch_finalize_makes_geometry():
    """スケッチを確定すると CAD のプリミティブになる。

    ここが通らないと、描いた線が形状にならない = スケッチ機能が成立しない。
    """
    col, props = _fresh_part()
    _sketch_reset(props)
    for pid, (x, y) in enumerate([(0, 0), (2, 0), (2, 2), (0, 2)], start=1):
        _sk_point(props, pid, float(x), float(y))
    for lid, (a, b) in enumerate([(1, 2), (2, 3), (3, 4), (4, 1)], start=1):
        _sk_line(props, lid, a, b)

    before = len(props.primitives)
    from CAD_8_1_5_1.sketch.sketch_finalize import finalize_sketch
    finalize_sketch(bpy.context, props)

    props = utils_props()
    assert len(props.primitives) > before, \
        "finalizing a closed 4-line sketch must produce a primitive"
    types = [p.type for p in props.primitives]
    assert 'SURFACE' in types, f"expected a SURFACE from the closed loop, got {types}"


def t_panels_registered():
    """基本パネルが登録されている。

    描画そのものは GUI が要るので、クラスが登録され poll が呼べることまでを見る。
    パネルが丸ごと消える種類の壊れ方(register 漏れ、poll の例外)はこれで捕まる。
    """
    wanted = [
        "SEAMLESS_PT_WorkspacePanel",
        "SEAMLESS_PT_DisplayPanel",
        "SEAMLESS_PT_QualityBakePanel",
    ]
    for name in wanted:
        cls = getattr(bpy.types, name, None)
        assert cls is not None, f"panel {name} is not registered"
        # poll が例外を投げないこと(投げるとパネルが出ない)
        cls.poll(bpy.context)


def t_bake_to_mesh():
    """ベイクできる。

    CAD の結果を実 Blender メッシュに焼く導線。ジオメトリカーネルから
    実際に頂点が返ってきているかまで見るので、コアとの往復が壊れたら落ちる。
    """
    col, props = _fresh_part()
    bpy.ops.seamless.add_primitive(type='BOX')

    before = set(bpy.data.objects.keys())
    res = bpy.ops.seamless.bake_mesh()
    assert res == {'FINISHED'}, f"bake_mesh returned {res}"

    new_objs = [bpy.data.objects[n] for n in set(bpy.data.objects.keys()) - before]
    baked = [o for o in new_objs if o.type == 'MESH' and o.data and len(o.data.vertices) > 0]
    assert baked, f"bake produced no mesh with vertices (new objects: {[o.name for o in new_objs]})"
    # BOX なので最低でも8頂点は出るはず。0 や極端に少ない値はコア側の異常。
    v = len(baked[0].data.vertices)
    assert v >= 8, f"baked mesh has only {v} vertices; the kernel likely returned garbage"


def t_step_export():
    """STEP を書き出せる。

    出品ページで CAD を名乗る以上ここは通っている必要がある。
    ファイルが出来ただけでなく、STEP らしい中身かどうかまで確かめる。
    """
    import tempfile
    col, props = _fresh_part()
    bpy.ops.seamless.add_primitive(type='BOX')

    out = os.path.join(tempfile.gettempdir(), "seamless_cad_regression.stp")
    if os.path.exists(out):
        os.remove(out)

    res = bpy.ops.seamless.export_step(filepath=out)
    assert res == {'FINISHED'}, f"export_step returned {res}"
    assert os.path.exists(out), "export_step reported success but wrote no file"
    assert os.path.getsize(out) > 0, "exported STEP file is empty"

    with open(out, encoding="utf-8", errors="replace") as f:
        head = f.read(200)
    assert "ISO-10303" in head, f"file does not look like STEP; starts with: {head[:60]!r}"


def t_step_export_carries_part_name():
    """書き出した STEP に Part 名が入っている。

    ここが通らないと、受け取った側では**名前の無い塊がひとつ**見えるだけになる。
    listing で「STEP 相互運用」を看板にしている以上、形が出るだけでは足りない。

    STEP はテキストなので PRODUCT の中身を直接見る。読み戻しに XCAF リーダを
    足すより、ファイルに何が書かれたかを見るほうが確実。
    """
    import tempfile
    col, props = _fresh_part()
    bpy.ops.seamless.add_primitive(type='BOX')

    # 既定名 (Seamless_CAD.001 など) は他と紛れるので、確実に判別できる名前にする
    col.name = "RegressionWidget"

    out = os.path.join(tempfile.gettempdir(), "seamless_cad_regression_named.stp")
    if os.path.exists(out):
        os.remove(out)

    res = bpy.ops.seamless.export_step(filepath=out)
    assert res == {'FINISHED'}, f"export_step returned {res}"
    assert os.path.exists(out), "export_step reported success but wrote no file"

    with open(out, encoding="utf-8", errors="replace") as f:
        text = f.read()
    assert "ISO-10303" in text, "file does not look like STEP"
    assert "RegressionWidget" in text, \
        "the Part name is missing from the STEP file; it was written without XCAF"


def t_step_export_all_parts_is_an_assembly():
    """複数 Part を1つの STEP にアセンブリとして書き出せる。

    見るのは3つ: 両方の Part 名があること、アセンブリ名があること、そして
    **NEXT_ASSEMBLY_USAGE_OCCURRENCE があること**。3つ目が無いと、名前は
    付いていても構造としては並べただけになる。

    空の Part はサーバー側が読み飛ばす仕様なので、両方に形状を入れておく。

    **2つ目は `add_part` で作ること。** `_fresh_part()` は全コレクションを
    消してから作り直すので、2回呼ぶと1つ目が消え、Part がひとつの
    ファイルしか出ない (最初にこれで失敗させた)。
    """
    from CAD_8_1_5_1 import utils
    import tempfile
    col_a, props_a = _fresh_part()
    col_a.name = "RegressionPartA"
    bpy.ops.seamless.add_primitive(type='BOX')

    bpy.ops.seamless.add_part()
    col_b = utils.get_active_collection(bpy.context)
    assert col_b is not None and col_b != col_a, "add_part did not switch to a new collection"
    col_b.name = "RegressionPartB"
    bpy.ops.seamless.add_primitive(type='SPHERE')
    assert getattr(col_b, "seamless_cad_stack_ptr", "0") != "0", \
        "the second part never got a stack; the kernel did not answer"

    out = os.path.join(tempfile.gettempdir(), "seamless_cad_regression_asm.stp")
    if os.path.exists(out):
        os.remove(out)

    res = bpy.ops.seamless.export_step(filepath=out, all_parts=True,
                                       assembly_name="RegressionAssembly")
    assert res == {'FINISHED'}, f"export_step(all_parts=True) returned {res}"

    with open(out, encoding="utf-8", errors="replace") as f:
        text = f.read()
    for expected in ("RegressionPartA", "RegressionPartB", "RegressionAssembly"):
        assert expected in text, f"{expected!r} is missing from the assembly STEP"
    assert "NEXT_ASSEMBLY_USAGE_OCCURRENCE" in text, \
        "no assembly relationship in the file; the parts were written side by side"

    # スタックの結果はコンパウンドで返ることがあり、そのまま入れると
    # PRODUCT('PartA') の下に無名の PRODUCT('SOLID') がもう一段生える。
    # このテストの部品はどちらもソリッド1個なので、剥がれていれば出ない。
    # (中身が複数ソリッドの Part では正当に出るので、一般の断言ではない)
    assert "PRODUCT('SOLID'" not in text, \
        "an unnamed SOLID product is nested under the part; the lone-solid compound was not unwrapped"


def t_iges_export():
    """IGES を書き出せる。

    IGES は幾何のみ (名前もアセンブリ構造も入らない) なので、見るのは
    「IGES として成立しているか」まで。

    **このテストは `IGESControl_Controller::Init()` の番人ではない。**
    2026-08-17 にその行を外して通したところ書き出しは成功した (OCCT 8.0.1)。
    同一プロセスで先に STEP を扱っているためと思われる。
    番人だと思って安心しないこと。

    IGES は固定長80桁のレコードで、各行の73桁目が区分文字 (S/G/D/P/T)。
    先頭は必ず S、末尾は T。拡張子だけ見て通すより、この形を見るほうが確実。
    """
    import tempfile
    col, props = _fresh_part()
    bpy.ops.seamless.add_primitive(type='BOX')

    out = os.path.join(tempfile.gettempdir(), "seamless_cad_regression.igs")
    if os.path.exists(out):
        os.remove(out)

    res = bpy.ops.seamless.export_iges(filepath=out)
    assert res == {'FINISHED'}, f"export_iges returned {res}"
    assert os.path.exists(out), "export_iges reported success but wrote no file"
    assert os.path.getsize(out) > 0, "exported IGES file is empty"

    with open(out, encoding="ascii", errors="replace") as f:
        lines = [ln.rstrip("\n").rstrip("\r") for ln in f if ln.strip()]
    assert lines, "IGES file has no records"
    assert lines[0][72:73] == "S", \
        f"first record is not a Start record; column 73 is {lines[0][72:73]!r}"
    assert lines[-1][72:73] == "T", \
        f"last record is not a Terminate record; column 73 is {lines[-1][72:73]!r}"

    sections = {ln[72:73] for ln in lines if len(ln) > 72}
    for needed in ("S", "G", "D", "P", "T"):
        assert needed in sections, f"IGES file is missing the {needed} section"


def t_stl_export():
    """STL を書き出せる。カーネルから直接で、Bake を経由しない。

    見るのは「ファイルが出来たか」ではなく **三角形が入っているか**。
    StlAPI_Writer は自分でメッシュを切らないので、テセレーションを忘れると
    ヘッダだけの 84 バイトが出来る。**開けるが中身が空**という一番たちの悪い
    壊れ方をするため、三角形数まで数える。
    """
    import struct
    import tempfile
    col, props = _fresh_part()
    bpy.ops.seamless.add_primitive(type='BOX')

    out = os.path.join(tempfile.gettempdir(), "seamless_cad_regression.stl")
    if os.path.exists(out):
        os.remove(out)

    res = bpy.ops.seamless.export_stl(filepath=out)
    assert res == {'FINISHED'}, f"export_stl returned {res}"
    assert os.path.exists(out), "export_stl reported success but wrote no file"

    # バイナリ STL: 80 バイトのヘッダ + 三角形数 (uint32) + 50 バイト x N
    size = os.path.getsize(out)
    assert size > 84, f"STL is header-only ({size} bytes); tessellation produced nothing"
    with open(out, "rb") as f:
        f.seek(80)
        n_tri = struct.unpack("<I", f.read(4))[0]
    assert n_tri > 0, "STL header claims 0 triangles"
    assert size == 84 + n_tri * 50, \
        f"STL size {size} does not match {n_tri} triangles (expected {84 + n_tri * 50})"

    # 箱は 6 面 x 2 = 12 三角形。これを下回るなら面が落ちている。
    assert n_tri >= 12, f"a box should be at least 12 triangles, got {n_tri}"


def t_stl_export_scale():
    """STL の scale が実際に大きさを変える。

    STEP と同じ意味の引数なので、同じように効かないと片方だけ嘘になる。
    三角形の座標を読んで、10倍で出したら 10 倍になっていることを見る。
    **三角形数は変わってはいけない** — 倍率に合わせてたわみ量も掛けているので、
    メッシュの粗さは相対的に同じになる、という設計をここで固定する。
    """
    import struct
    import tempfile
    col, props = _fresh_part()
    bpy.ops.seamless.add_primitive(type='BOX')

    def _write_and_read(scale):
        path = os.path.join(tempfile.gettempdir(), f"seamless_cad_regression_s{scale:g}.stl")
        if os.path.exists(path):
            os.remove(path)
        res = bpy.ops.seamless.export_stl(filepath=path, scale=scale)
        assert res == {'FINISHED'}, f"export_stl at scale {scale} returned {res}"
        with open(path, "rb") as f:
            f.seek(80)
            n_tri = struct.unpack("<I", f.read(4))[0]
            extent = 0.0
            for _ in range(n_tri):
                data = f.read(50)
                # 12 バイトの法線を飛ばし、頂点 9 個の float を読む
                coords = struct.unpack("<9f", data[12:48])
                extent = max(extent, max(abs(c) for c in coords))
        return n_tri, extent

    n1, e1 = _write_and_read(1.0)
    n10, e10 = _write_and_read(10.0)

    assert e1 > 0.0, "unit-scale STL has all-zero coordinates"
    ratio = e10 / e1
    assert 9.9 < ratio < 10.1, f"scale=10 should be 10x larger, got {ratio:.3f}x"
    assert n1 == n10, \
        f"scale must not change mesh density: {n1} triangles at 1.0 vs {n10} at 10.0"


def t_stl_export_honours_quality():
    """STL のテセレーションが品質設定に従う。

    **これが効かないと STL を直接書き出す意味そのものが消える** (画面用の
    粗いメッシュがそのまま出るだけになり、Bake 経由と変わらない)。

    2026-08-17 に実際に壊れていた: current_shape にはプレビューが作った
    三角形分割が載っており、BRepMesh_IncrementalMesh は要求精度を満たす面を
    作り直さないため、指定した品質が黙って無視されていた。
    書き出し用のコピーに対して BRepTools::Clean してから切り直すことで解決。

    球で見る。箱は精度をいくら上げても12三角形のままなので**この誤りを
    検出できない** — 曲面が要る。
    """
    import struct
    import tempfile
    col, props = _fresh_part()
    bpy.ops.seamless.add_primitive(type='SPHERE')

    def _tri_count(deflection, tag):
        props.use_high_quality_bake = False
        props.mesh_quality = deflection
        path = os.path.join(tempfile.gettempdir(), f"seamless_cad_regression_q{tag}.stl")
        if os.path.exists(path):
            os.remove(path)
        res = bpy.ops.seamless.export_stl(filepath=path)
        assert res == {'FINISHED'}, f"export_stl at deflection {deflection} returned {res}"
        with open(path, "rb") as f:
            f.seek(80)
            return struct.unpack("<I", f.read(4))[0]

    coarse = _tri_count(0.5, "coarse")
    fine = _tri_count(0.01, "fine")

    assert fine > coarse, (
        f"tightening the deflection did not add triangles ({coarse} -> {fine}); "
        "the quality setting is being ignored, probably because an existing "
        "triangulation was reused"
    )


def t_one_undo_is_one_step():
    """Ctrl+Z 1回で1つ戻る(2回押さないと戻らない、が起きない)。

    2026-07-30 まで壊れていた: undo_redo_post_handler が undo_post の中で
    sync_proxies と再計算を行いデータを書き換えていたため、その書き換え自体が
    新しい undo ステップになり、1回目の Ctrl+Z が実質無効化されていた
    (実測: ハンドラを外すと1回で正しく戻る)。再同期はタイマーへ逃がして解決。

    背景実行ではタイマーが回らないので、ここで確認できるのは
    「undo_post がもうデータを書かない」ことまで。**GUI で Ctrl+Z 後に
    ビューポートがちゃんと更新されるかは実機確認が必要。**
    """
    from CAD_8_1_5_1 import utils

    # Blender 4.x の背景実行で ed.undo() を呼ぶと Blender ごと落ちる(4.2.7 で確認)。
    # 5.x では起きない。アドオン側の問題ではなく背景モードの undo まわりの差と見て
    # いるが、落ちると残りの検査を道連れにするので安全な環境でだけ走らせる。
    # **4.2 の GUI で Ctrl+Z が安全かは、この検査では分からない。実機で確認すること。**
    if bpy.app.version < (5, 0, 0):
        raise Skip(f"background undo crashes Blender {bpy.app.version_string}; check Ctrl+Z by hand")

    col, props = _fresh_part()
    bpy.ops.seamless.add_primitive(type='BOX')
    for i in range(3):
        # 背景実行の undo スタックは眠っている。数回 push しないと poll が通らない。
        bpy.ops.ed.undo_push(message=f"regression baseline {i}")
    bpy.ops.seamless.add_primitive(type='CYLINDER')

    props = utils.get_active_props(bpy.context)
    assert len(props.primitives) == 2, f"setup failed: {[p.type for p in props.primitives]}"

    # poll が False のまま ed.undo() を呼ぶと Blender ごと落ちる(§4-6)。必ず確認する。
    if not bpy.ops.ed.undo.poll():
        raise AssertionError("undo is not available; refusing to call it (would crash Blender)")

    bpy.ops.ed.undo()
    props = utils.get_active_props(bpy.context)
    assert props is not None, "the CAD collection vanished after undo"
    types = [p.type for p in props.primitives]
    assert types == ['BOX'], \
        f"one undo must roll back exactly one step; expected ['BOX'], got {types}"


# Redo は自動化していない。

#
# 背景実行で ed.undo() を呼ぶと、アドオンを register した状態では Blender ごと
# EXCEPTION_ACCESS_VIOLATION で落ちることがある(2026-07-30、5回中5回再現した
# スクリプト形状がある一方、ほぼ同じ手順でも落ちないものがあり、条件は未特定)。
# undo_post ハンドラを外すと落ちず、Undo 自体は正しく 2 -> 1 に戻る。
# 4秒待ってから undo しても落ちるので、単純な非同期処理のレースではない。
#
# 落ちるテストは「失敗を報告する」のではなく「残り全部を道連れにして終了コード11で
# 死ぬ」ため、安全網としては有害。原因が分かるまでスイートには入れない。
# 詳細は DEPSGRAPH_STATE_MACHINE.md §4-6。**Ctrl+Z は実機で確認すること。**


def main():
    check("register / enable", t_register)
    check("add primitives -> proxies", t_add_primitives)
    # 背景実行の undo は不安定(§4-6)。**実行位置に敏感**で、他の検査を
    # ひととおり済ませた後(スイート末尾)に置くと Blender ごと落ちた。
    # 操作をあまり積んでいない早い段階なら安定して通る。動かすときは注意。
    check("one undo = one step", t_one_undo_is_one_step)
    check("B: feature tree -> viewport", t_b_feature_tree_to_viewport)
    check("A: viewport -> feature tree", t_a_viewport_to_feature_tree)
    check("F: delete sync", t_f_delete_sync)
    check("delete updates the shape at once", t_delete_updates_the_shape_at_once)
    check("inset needs a flat face", t_inset_needs_a_flat_face)
    check("E: numeric edit is not a drag", t_e_single_edit_is_not_a_drag)
    check("settle drops the drag flags", t_settle_contract)
    check("settle is a no-op mid-drag", t_settle_is_a_noop_when_nothing_ended)
    check("G: fillet highlight data", t_g_fillet_highlight_data)
    check("dispatch signature keeps user precision", t_dispatch_signature_precision)
    check("FILLET rounds edges", t_fillet_rounds_edges)
    check("CHAMFER cuts edges", t_chamfer_cuts_edges)
    check("REVOLVE sweeps a profile", t_revolve_sweeps_a_profile)
    check("REVOLVE without a target is inert", t_revolve_ignores_a_missing_target)
    check("no function-level import shadowing", t_no_import_shadowing)
    check("measure part", t_measure_part)
    check("measure selected entity", t_measure_entity)
    check("measure while retargeting", t_measure_during_retargeting)
    check("modifier proxy draws nothing", t_modifier_proxy_is_not_drawn)
    check("modifier ignores its transform", t_modifier_transform_is_ignored)
    check("offset pick targets the shown field", t_offset_pick_writes_the_visible_field)
    check("offset pick reference face", t_offset_pick_reference_face)
    check("offset pick reference is exact", t_offset_pick_reference_is_exact)
    check("offset pick then cleanup merges", t_offset_pick_then_cleanup_merges)
    check("offset face gets hard to identify", t_offset_face_becomes_unidentifiable)
    check("offset pick zero reference", t_offset_pick_zero_reference)
    check("grid lines hit the origin", t_grid_lines_pass_through_the_origin)
    check("vertex snap off stops merge", t_vertex_snap_off_stops_merge_on_release)
    check("sketch solver constraints", t_sketch_solver_constraints)
    check("sketch radius constraint", t_sketch_radius_constraint_action)
    check("circle dimension holds centre", t_sketch_circle_distance_holds_centre)
    check("sketch angle + equal solve", t_sketch_angle_and_equal)
    check("sketch angle/equal actions", t_sketch_two_line_constraint_actions)
    check("sketch concentric + symmetric", t_sketch_concentric_and_symmetric)
    check("sketch finalize makes geometry", t_sketch_finalize_makes_geometry)
    check("panels registered", t_panels_registered)
    check("bake to mesh", t_bake_to_mesh)
    check("STEP export", t_step_export)
    check("STEP export scale", t_step_export_scale)
    check("STEP carries part name", t_step_export_carries_part_name)
    check("STEP all parts is an assembly", t_step_export_all_parts_is_an_assembly)
    check("IGES export", t_iges_export)
    check("STL export", t_stl_export)
    check("STL export scale", t_stl_export_scale)
    check("STL export honours quality", t_stl_export_honours_quality)
    # シーンを丸ごと開き直すので、他のテストを汚さないよう最後に回す
    check("save + reload keeps CAD live", t_save_reload_keeps_cad_live)


    print("\n" + "=" * 60)
    failed = skipped = 0
    for name, ok, detail in _results:
        label = "PASS" if ok else ("SKIP" if ok is None else "FAIL")
        print(f"  {label}  {name}")
        if ok is None:
            print(f"        {detail}")
            skipped += 1
        elif not ok:
            print(f"        {detail}")
            failed += 1
    print("=" * 60)
    passed = len(_results) - failed - skipped
    print(f"{passed} passed, {failed} failed, {skipped} skipped")
    print("\nNOT covered here -- still needs real Blender:")
    print("  C  drag follows in real time")
    print("  D  no freeze after releasing a drag")
    print("  H  edges survive with WGPU Overlay OFF")
    print("  I  undo / redo")

    sys.stdout.flush()
    # Blender は --python の例外だけでは終了コードを立てないので明示する
    os._exit(1 if failed else 0)


if __name__ == "__main__":
    main()
