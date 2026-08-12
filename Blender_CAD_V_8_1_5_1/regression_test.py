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
    check("E: numeric edit is not a drag", t_e_single_edit_is_not_a_drag)
    check("settle drops the drag flags", t_settle_contract)
    check("settle is a no-op mid-drag", t_settle_is_a_noop_when_nothing_ended)
    check("G: fillet highlight data", t_g_fillet_highlight_data)
    check("dispatch signature keeps user precision", t_dispatch_signature_precision)
    check("FILLET rounds edges", t_fillet_rounds_edges)
    check("CHAMFER cuts edges", t_chamfer_cuts_edges)
    check("sketch solver constraints", t_sketch_solver_constraints)
    check("sketch radius constraint", t_sketch_radius_constraint_action)
    check("sketch angle + equal solve", t_sketch_angle_and_equal)
    check("sketch angle/equal actions", t_sketch_two_line_constraint_actions)
    check("sketch finalize makes geometry", t_sketch_finalize_makes_geometry)
    check("panels registered", t_panels_registered)
    check("bake to mesh", t_bake_to_mesh)
    check("STEP export", t_step_export)
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
