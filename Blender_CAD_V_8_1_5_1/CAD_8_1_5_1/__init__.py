# SPDX-License-Identifier: GPL-2.0-or-later
#
# Seamless CAD -- non-destructive CAD modelling inside Blender.
# Copyright (C) 2026 hinata_hugu
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation; either version 2 of the License, or (at your
# option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, see <https://www.gnu.org/licenses/>.
#
# =============================================================================
# DEVELOPMENT NOTES
# =============================================================================
#
# [English]
# This add-on, Seamless CAD, was developed with transparency through a
# collaboration between myself (hinata_hugu), a human developer, and an AI:
#
# - DESIGN INTENT: All design principles, policies, and instructions were
#   entirely driven by me. This add-on exists so that a shape stays editable
#   after you have made it. Every operation is kept as a feature tree you can
#   return to and retype a number in, rather than being baked into a mesh the
#   moment it is created. The geometry is computed by a real B-Rep kernel
#   (OpenCASCADE), driven from Rust in a separate process, so that Blender's
#   interface stays responsive while a lightweight preview follows your drag
#   in real time. The aim is to keep the whole CAD loop inside Blender, with
#   no round trip through external CAD software.
#   Currently in Beta, striving for further evolution.
#
# - ITERATIVE DEVELOPMENT: This is unmistakably an add-on created by me,
#   refined through hundreds of cycles of coding, testing, debugging,
#   and improvement.
#
# - RESPONSIBILITY: All design decisions, release decisions, debugging,
#   user feedback, and support are handled exclusively by the human developer.
#
# - CODE FORMATTING: AI assisted with final code organization and review to
#   improve readability. This benefits GPL users who wish to learn from this
#   codebase. The Rust and C++ sources of the geometry kernel are published
#   alongside the Python add-on at
#   https://github.com/hinatahugu29/Blender_Seamless_CAD
#   honouring the spirit of free software.
#
# [日本語]
# Seamless CAD は hinata_hugu が開発しています。AI にはコードの整理とレビューを
# 手伝わせていますが、設計方針・リリース判断・サポート・そして責任は、すべて
# 開発者本人にあります。目指しているのは、外部の CAD ソフトを往復することなく、
# Blender の中だけで CAD のモデリング — 履歴を残し、後からいつでも数値を
# 編集し直せるやり方 — を完結させることです。幾何演算は実際の B-Rep カーネル
# (OpenCASCADE) が担当し、Blender の操作感を損なわないよう別プロセスで動きます。
# 現在ベータ版です。
#
# -----------------------------------------------------------------------------
#
# Creator's Oath
#
# In the spirit of free software and the GNU GPL:
# May Blender forever remain free under the GPL!
# This addon guarantees all users the freedom to learn from,
# modify, and share this source code forever.
# Keep Blender and Seamless CAD open, inspectable, and modifiable under the GPL.
# =============================================================================

bl_info = {
    "name": "Seamless CAD",
    "author": "hinata_hugu",
    "version": (8, 1, 5, 5),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > Seamless",
    "description": "Non-destructive parametric CAD modelling with a real B-Rep kernel. Edit the feature tree at any time, export STEP",
    "warning": "Beta",
    "category": "Mesh",
    "doc_url": "https://github.com/hinatahugu29/Blender_Seamless_CAD",
    "tracker_url": "https://github.com/hinatahugu29/Blender_Seamless_CAD/issues",
}

import bpy
import sys


def _purge_submodules():
    """このアドオンのサブモジュールを sys.modules から全部落とす。

    以前はトップレベルの10モジュールだけを importlib.reload していたが、
    それでは2つの理由で不十分だった。

    1. サブパッケージの中身(operators.management, sketch.*, ui.*, core.*)は
       一度も reload されない。そのため「新しい operators/__init__.py が、
       古いままキャッシュされた operators.management から import する」状態が
       起きる。実際に、新クラスを追加したビルドを既存セッションへ入れ直すと
       `cannot import name 'SEAMLESS_OT_ForceRecompute' from
       'CAD_8_1_5_1.operators.management'` で有効化に失敗していた。

    2. `from ..core_bridge import get_core` のような from-import は関数
       オブジェクトを束縛するので、後から core_bridge を reload しても
       古い関数を掴んだままになる。

    キャッシュを消してから素の import をやり直すのが唯一確実な方法。
    ここが走るのはアドオン有効化時だけなので、まっさらにして問題ない。
    """
    prefix = (__package__ or "") + "."
    for name in [n for n in sys.modules if n.startswith(prefix)]:
        del sys.modules[name]


_purge_submodules()

# 同梱依存(libs/)のパス設定は他の何よりも先に行う。drawing.py などが
# モジュールロード時に `import numpy` するため、register() まで遅延できない。
from . import vendor_libs  # noqa: E402  (副作用として libs/ を sys.path 末尾へ追加)

from . import utils, core_bridge, properties, operators, modal_selection, drawing, sketch, gpu_manager, ui  # noqa: E402

try:
    from bpy.app.handlers import persistent
    if persistent is None:
        persistent = lambda func: func
except ImportError:
    persistent = lambda func: func

def safe_delete_stack(col):
    if not col or not hasattr(col, "seamless_cad_stack_ptr"):
        return
    ptr_str = getattr(col, "seamless_cad_stack_ptr", "0")
    try:
        ptr = int(ptr_str)
    except ValueError:
        ptr = 0
    if ptr != 0:
        try:
            core_bridge.delete_cad_stack(ptr)
            if utils.DEBUG_LOGS:
                utils.info_print(f"Seamless CAD: Safely deleted CADStack for Collection '{col.name}': {ptr}")
        except Exception as e:
            utils.error_print(f"Seamless CAD: Failed to delete stack for Collection '{col.name}': {e}")
    col.seamless_cad_stack_ptr = "0"
    if hasattr(utils, "_registered_cad_collections") and col.name in utils._registered_cad_collections:
        utils._registered_cad_collections.discard(col.name)

def _clear_all_gpu_draw():
    """GPU描画エンジンに残ったワイヤー/面バッチを全消去する。描画エンジンは
    モジュールグローバルのシングルトンでファイルロードをまたいで生き残るため、
    ここで消さないと『プリミティブが無いのに前ファイルのワイヤーが残る』
    (保存済みの古い stack_ptr が新コレクションと一致して有効扱いになる等)。"""
    try:
        from .drawing import get_wireframe_engine
        engine = get_wireframe_engine()
        if engine:
            engine.clear()
            engine.hidden_primitive_uuids.clear()
    except Exception as e:
        utils.debug_print(f"Seamless CAD: GPU draw clear error: {e}")

def _resume_cad_collections(col_names):
    """ファイルを開いた直後に CAD コレクションを使える状態へ戻す。

    stack_ptr は C++ 側のポインタなので保存された値は無効で、load 時に 0 へ
    潰される。すると `_is_live_cad_collection` が False になり、depsgraph
    ハンドラがそのコレクションを対象外として無視する = ドラッグしても
    何も起きない。ここでスタックを作り直して登録し、形状を1回描き直す。

    プレビューの通信は毎回フル履歴(binary_payload)を送るので、スタックさえ
    作り直せば保存された Feature Tree から完全に復元できる。差分復元は不要。
    """
    for name in col_names:
        col = bpy.data.collections.get(name)
        if not col or not hasattr(col, "seamless_props"):
            continue
        try:
            core_bridge.get_or_create_stack_ptr(col)
            utils._register_cad_collection(col)
        except Exception as e:
            utils.error_print(f"Seamless CAD: failed to resume stack for '{name}': {e}")

    for name in col_names:
        col = bpy.data.collections.get(name)
        if not col or getattr(col, "seamless_cad_stack_ptr", "0") == "0":
            continue
        try:
            core_bridge.update_cad_preview_high_quality_for_col(
                col, bpy.context, force=True, sync=False)
        except Exception as e:
            utils.error_print(f"Seamless CAD: failed to redraw '{name}' after load: {e}")


def _schedule_cad_resume(col_names):
    """復帰をタイマーへ逃がす。

    ファイルを開く処理の中で全パートを OCC 再計算すると、重いモデルほど
    open が固まる。ワンテンポ遅らせて「ファイルは軽く開き、直後にモデルが
    現れる」形にする。背景実行ではタイマーが回らないので即座に走らせる。
    """
    if not col_names:
        return
    if bpy.app.background:
        _resume_cad_collections(col_names)
        return

    def _cb():
        _resume_cad_collections(col_names)
        return None

    try:
        bpy.app.timers.register(_cb, first_interval=0.1)
    except Exception:
        _resume_cad_collections(col_names)


def _ensure_async_poll_timer():
    """非同期結果を取り出すタイマーを、必ず persistent で登録する。

    persistent=True が無いと Blender はファイルを開いた時点でこのタイマーを
    破棄する。すると cad_server が返した結果は _async_results に溜まったまま
    誰にも取り出されず、以後そのセッションでは非同期プレビューが一切反映
    されなくなる(ファイルを開いても形状が出ない、フィレットの数値を変えても
    変わらない、しかし同期経路の Bake Mesh だけは効く)。
    2026-08-05 に実測で確認: ファイルを開いた直後のスナップショットで
    _async_results len=1 / poll timer registered=False / engine stacks=[]。

    register() からも load_post からも呼べるよう冪等にしてある。
    """
    if not bpy.app.timers.is_registered(core_bridge.poll_async_results):
        bpy.app.timers.register(
            core_bridge.poll_async_results, first_interval=0.05, persistent=True
        )


@persistent
def load_post_handler(dummy):
    """Blenderファイルロード時や新規ファイル作成時に呼び出されます"""
    # persistent 登録で破棄されないはずだが、ここでも必ず生きている状態にする。
    # このタイマーが落ちると症状が「アドオンが黙って壊れる」形で出るため。
    _ensure_async_poll_timer()
    # stack_ptr が 0 でないことは「保存した時点で CAD として生きていた」印。
    # safe_delete_stack が潰してしまうので、先に控えておく。
    resumable = [col.name for col in bpy.data.collections
                 if getattr(col, "seamless_cad_stack_ptr", "0") != "0"]
    for col in bpy.data.collections:
        safe_delete_stack(col)
    _clear_all_gpu_draw()
    utils.subscribe_active_object_msgbus()
    _schedule_cad_resume(resumable)

@persistent
def unload_post_handler(dummy):
    """ファイルがクローズされる際などに、現在メモリ上に残っている CADStack を解放します"""
    for col in bpy.data.collections:
        safe_delete_stack(col)
    _clear_all_gpu_draw()

def _resync_after_undo(col_names):
    """Undo/Redo 後のプロパティ・C++コア・描画の再同期(本体)。"""
    from .core_bridge import update_cad_preview_high_quality_for_col
    from .utils import sync_proxies

    for name in col_names:
        col = bpy.data.collections.get(name)
        if not col or not hasattr(col, "seamless_props"):
            continue
        if getattr(col, "seamless_cad_stack_ptr", "0") == "0":
            continue
        try:
            sync_proxies(bpy.context, props=col.seamless_props)
            update_cad_preview_high_quality_for_col(col, bpy.context)
        except Exception as e:
            utils.error_print(f"Seamless CAD: Undo/Redo sync error: {e}")


@persistent
def undo_redo_post_handler(dummy):
    """アンドゥ・リドゥ完了時に、プロパティ・C++コア・描画レイヤーを再同期します。

    再同期は **undo_post の中で直接やってはいけない**。ここでデータを書き換えると
    その書き換え自体が新しい undo ステップになり、次の Ctrl+Z がそこへ戻るため、
    利用者から見ると「1回目の Ctrl+Z が効かず、2回押して初めて1つ戻る」挙動になる。
    2026-07-30 に実測で確認(ハンドラを外すと1回で正しく戻った)。

    そこで書き換えを伴う処理はタイマーへ逃がし、Blender が undo を完全に終えてから
    走らせる。ここで直接触るのは undo スタックに載らない描画エンジン側の状態だけ。
    """
    from .drawing import get_wireframe_engine

    engine = get_wireframe_engine()
    if engine:
        engine.hidden_primitive_uuids.clear()

    col_names = [col.name for col in bpy.data.collections
                 if hasattr(col, "seamless_props")
                 and getattr(col, "seamless_cad_stack_ptr", "0") != "0"]
    if not col_names:
        return

    def _cb():
        _resync_after_undo(col_names)
        return None

    # 背景実行ではスクリプト実行中にタイマーが回らないので、この再同期は走らない。
    # そのぶん undo が Blender 本来の挙動になるため、回帰テストは
    # 「1回の undo で1つ戻る」ことを確認できる(= undo_post がデータを
    # 書かなくなったことの検証)。GUI で再同期が実際に走るかは実機確認が必要。
    bpy.app.timers.register(_cb, first_interval=0.0)

def poll_active_cad_collection(self, col):
    # Seamless_CAD 配下の子コレクションのみを許可
    parent = bpy.data.collections.get("Seamless_CAD")
    if parent:
        return (col.name in parent.children) and (col.name != "Result")
    return hasattr(col, "seamless_props") and col.seamless_cad_stack_ptr != "0"

def update_active_cad_collection(self, context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
    if self.active_cad_collection:
        from . import utils
        from . import core_bridge
        utils.sync_proxies(context)
        core_bridge.update_cad_preview_forced(context)

classes = (
    ui.SEAMLESS_AddonPreferences,
    properties.SeamlessPoint,
    properties.SeamlessFilletEdgeRadius,
    properties.SeamlessPrimitive,
    properties.SeamlessSketchPoint,
    properties.SeamlessSketchLine,
    properties.SeamlessSketchConstraint,
    properties.SeamlessSketchCircle,
    properties.SeamlessSketchArc,
    properties.SeamlessSketchSnapshot,
    properties.SeamlessProperties,
    operators.SEAMLESS_OT_GetVersion,
    operators.SEAMLESS_OT_MeasurePart,
    operators.SEAMLESS_OT_MeasureSelected,
    operators.SEAMLESS_OT_AddPrimitive,
    operators.SEAMLESS_OT_AddDynamicLoftHole,
    operators.SEAMLESS_OT_AddCurvePoint,
    operators.SEAMLESS_OT_AddCurvePointAt,
    operators.SEAMLESS_OT_RemoveCurvePointAt,
    operators.SEAMLESS_OT_RemovePrimitive,
    operators.SEAMLESS_OT_SetActivePrimitive,
    operators.SEAMLESS_OT_DuplicatePrimitive,
    operators.SEAMLESS_OT_PickActiveAsTarget,
    operators.SEAMLESS_OT_PickTargetModal,
    operators.SEAMLESS_OT_ImportStep,
    operators.SEAMLESS_OT_ImportSvg,
    operators.SEAMLESS_OT_ExportStep,
    operators.SEAMLESS_OT_SeparateByBase,
    operators.SEAMLESS_OT_SetRollbackIndex,
    operators.SEAMLESS_OT_ToggleFilletEdgeDefault,
    operators.SEAMLESS_OT_EditSketch,
    operators.SEAMLESS_OT_ForceRecompute,
    operators.SEAMLESS_OT_GroupSelection,
    operators.SEAMLESS_OT_BakeMesh,
    modal_selection.SEAMLESS_OT_SelectionModal,
    sketch.SEAMLESS_OT_StartSketch,
    sketch.SEAMLESS_OT_SketchAction,
    sketch.SEAMLESS_OT_SketchDrawTool,
    sketch.SEAMLESS_OT_EditDimensionValue,
    sketch.ops_reference_plane.SEAMLESS_OT_select_reference_plane,
    operators.SEAMLESS_OT_VariableBoxHole,
    operators.SEAMLESS_OT_InteractivePlacement,
    operators.SEAMLESS_OT_InteractiveTransform,
    operators.CAD_OT_visual_snap,
    operators.SEAMLESS_OT_InteractiveOffsetPick,
    operators.SEAMLESS_OT_StartCAD,
    operators.SEAMLESS_OT_AddPart,
    operators.SEAMLESS_OT_RemovePart,
    ui.SEAMLESS_PT_SketchPanel,
    ui.SEAMLESS_PT_WorkspacePanel,
    ui.SEAMLESS_PT_DisplayPanel,
    ui.SEAMLESS_PT_QualityBakePanel,
    ui.SEAMLESS_PT_MeasurePanel,
    ui.SEAMLESS_PT_SelectionPanel,
    ui.SEAMLESS_PT_PlacementSnapPanel,
    ui.SEAMLESS_PT_CreatePanel,
    ui.SEAMLESS_PT_ModifyPatternPanel,
    ui.SEAMLESS_PT_FeatureTreePanel,
    ui.SEAMLESS_PT_PropertyEditorPanel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    
    bpy.types.Collection.seamless_props = bpy.props.PointerProperty(type=properties.SeamlessProperties)
    bpy.types.Collection.seamless_cad_stack_ptr = bpy.props.StringProperty(name="CAD Stack Pointer", default="0")
    
    # Scene プロパティの追加
    bpy.types.Scene.is_seamless_cad_started = bpy.props.BoolProperty(
        name="Seamless CAD",
        default=False
    )
    bpy.types.Scene.active_cad_collection = bpy.props.PointerProperty(
        type=bpy.types.Collection,
        name="Active CAD Part",
        description="Select active CAD workspace collection",
        poll=poll_active_cad_collection,
        update=update_active_cad_collection
    )
    
    # SDF プレビュー用のプロパティ
    bpy.types.Scene.is_sdf_preview_mode = bpy.props.BoolProperty(
        name="SDF Preview Mode",
        default=False
    )
    bpy.types.Scene.sdf_preview_fillet_radius = bpy.props.FloatProperty(
        name="SDF Preview Fillet Radius",
        default=0.1,
        min=0.0,
        max=10.0
    )
    bpy.types.Scene.sdf_preview_box_size = bpy.props.FloatVectorProperty(
        name="SDF Preview Box Size",
        default=(1.0, 1.0, 1.0),
        size=3
    )
    
    gpu_manager.register_handlers()
    
    bpy.app.handlers.depsgraph_update_post.append(utils.depsgraph_update_handler)
    bpy.app.handlers.load_post.append(load_post_handler)
    bpy.app.handlers.load_pre.append(unload_post_handler)
    bpy.app.handlers.undo_post.append(undo_redo_post_handler)
    bpy.app.handlers.redo_post.append(undo_redo_post_handler)

    utils.subscribe_active_object_msgbus()

    # Register timer for async CAD polling
    _ensure_async_poll_timer()
    
    ui.ui_preferences._apply_log_preferences(bpy.context)
    utils.info_print(
        f"Seamless CAD addon register: bl_info={bl_info['version']}, bridge={core_bridge.get_version()}"
    )


def _unregister_step(label, func):
    """解放処理を1手順ずつ隔離する。

    以前は depsgraph ハンドラの remove だけ存在チェックが無く、register が
    途中で失敗した状態から unregister すると ValueError で関数ごと中断し、
    以降の CADStack 解放・cad_server.exe 停止・クラス解除が
    まとめて実行されないままアドオンが半死状態で残っていた。
    """
    try:
        func()
    except Exception as e:
        utils.error_print(f"Seamless CAD: unregister step '{label}' failed: {e}")


def _remove_handler(handler_list, func):
    if func in handler_list:
        handler_list.remove(func)


def unregister():
    _unregister_step("gpu handlers", gpu_manager.unregister_handlers)
    _unregister_step("msgbus", utils.unsubscribe_active_object_msgbus)

    for label, handler_list, func in (
        ("depsgraph_update_post", bpy.app.handlers.depsgraph_update_post, utils.depsgraph_update_handler),
        ("load_post", bpy.app.handlers.load_post, load_post_handler),
        ("load_pre", bpy.app.handlers.load_pre, unload_post_handler),
        ("undo_post", bpy.app.handlers.undo_post, undo_redo_post_handler),
        ("redo_post", bpy.app.handlers.redo_post, undo_redo_post_handler),
    ):
        _unregister_step(label, lambda hl=handler_list, f=func: _remove_handler(hl, f))

    def _unregister_timer():
        if bpy.app.timers.is_registered(core_bridge.poll_async_results):
            bpy.app.timers.unregister(core_bridge.poll_async_results)
    _unregister_step("async timer", _unregister_timer)

    # すべてのコレクションのポインタを安全に解放する
    def _release_stacks():
        for col in bpy.data.collections:
            safe_delete_stack(col)
    _unregister_step("release CAD stacks", _release_stacks)

    # アドオン無効化時にも cad_server.exe を終了し、次回有効化時に古い描画状態が残らないようにする
    _unregister_step("terminate server", core_bridge.terminate_server)
    # mmap とファイルハンドルを閉じる。閉じないとアドオンのリロードごとにリークする。
    _unregister_step("close shared memory", core_bridge.close_shm)

    for cls in reversed(classes):
        _unregister_step(f"unregister_class {cls.__name__}", lambda c=cls: bpy.utils.unregister_class(c))

    for owner, attr in (
        (bpy.types.Collection, "seamless_props"),
        (bpy.types.Collection, "seamless_cad_stack_ptr"),
        (bpy.types.Scene, "is_seamless_cad_started"),
        (bpy.types.Scene, "active_cad_collection"),
        (bpy.types.Scene, "is_sdf_preview_mode"),
        (bpy.types.Scene, "sdf_preview_fillet_radius"),
        (bpy.types.Scene, "sdf_preview_box_size"),
    ):
        if hasattr(owner, attr):
            _unregister_step(f"del {attr}", lambda o=owner, a=attr: delattr(o, a))

if __name__ == "__main__":
    register()
