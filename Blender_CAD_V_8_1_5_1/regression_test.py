"""Blender をヘッドレスで起動して回す回帰テスト。

    "C:\\Program Files\\Blender Foundation\\Blender 5.1\\blender.exe" ^
        --background --factory-startup --python regression_test.py

DEPSGRAPH_STATE_MACHINE.md §5 の手動チェックリストのうち、GUI が無くても
検証できる項目を機械化したもの。全部が置き換わるわけではない:

  自動化した : A(アクティブ同期) B(Feature Tree→ビューポート) E(単発編集)
               F(削除同期) G相当(ハイライト文字列) + 確定フェーズの契約
               + 出品前チェック(パネル登録/ベイク/STEP書き出し/保存再読込)
  手動のまま : C(ドラッグ追従) D(確定後に固まらない) H(WGPU Overlay OFF)
               I(Undo/Redo … 自動化を試みたが背景実行だと Blender ごと落ちる。
                 理由は下の該当箇所のコメントと §4-6 を参照)

C/D/H はネイティブの変形モーダルと GPU 描画が要るため、ここでは原理的に
再現できない。**変形まわりを触ったら実機確認は依然として必要。**
代わりに、確定フェーズ(_handle_settle)の「フラグを確実に下ろす」という契約は
関数を直接叩いて検証している。2026-07-28 のフェーズ抽出で可能になった。

終了コード 0 = 全パス、1 = 失敗あり。
"""

import os
import sys
import traceback

ADDON_PARENT = os.path.dirname(os.path.abspath(__file__))
if ADDON_PARENT not in sys.path:
    sys.path.insert(0, ADDON_PARENT)

import bpy  # noqa: E402
import mathutils  # noqa: E402

_results = []


def check(name, fn):
    """fn() を走らせ、送出された AssertionError を失敗として記録する。"""
    try:
        fn()
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


# --------------------------------------------------------------------------
# 出品前チェック(LISTING_PREP.md の「最低限の検証チェックリスト」由来)
# --------------------------------------------------------------------------

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


# Undo / Redo は意図的に自動化していない。
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
    check("B: feature tree -> viewport", t_b_feature_tree_to_viewport)
    check("A: viewport -> feature tree", t_a_viewport_to_feature_tree)
    check("F: delete sync", t_f_delete_sync)
    check("E: numeric edit is not a drag", t_e_single_edit_is_not_a_drag)
    check("settle drops the drag flags", t_settle_contract)
    check("settle is a no-op mid-drag", t_settle_is_a_noop_when_nothing_ended)
    check("G: fillet highlight data", t_g_fillet_highlight_data)
    check("panels registered", t_panels_registered)
    check("bake to mesh", t_bake_to_mesh)
    check("STEP export", t_step_export)
    # シーンを丸ごと開き直すので、他のテストを汚さないよう最後に回す
    check("save + reload keeps CAD live", t_save_reload_keeps_cad_live)

    print("\n" + "=" * 60)
    failed = 0
    for name, ok, detail in _results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        if not ok:
            print(f"        {detail}")
            failed += 1
    print("=" * 60)
    print(f"{len(_results) - failed} passed, {failed} failed")
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
