bl_info = {
    "name": "Project Seamless CAD",
    "author": "hinata_hugu",
    "version": (8, 1, 5, 1),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > Seamless",
    "description": "Native CAD for Blender (DAG V8.1.5.1 GPU preview)",
    "warning": "Beta",
    "category": "Mesh",
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

@persistent
def load_post_handler(dummy):
    """Blenderファイルロード時や新規ファイル作成時に呼び出されます"""
    for col in bpy.data.collections:
        safe_delete_stack(col)
    _clear_all_gpu_draw()
    utils.subscribe_active_object_msgbus()

@persistent
def unload_post_handler(dummy):
    """ファイルがクローズされる際などに、現在メモリ上に残っている CADStack を解放します"""
    for col in bpy.data.collections:
        safe_delete_stack(col)
    _clear_all_gpu_draw()

@persistent
def undo_redo_post_handler(dummy):
    """アンドゥ・リドゥ完了時に、Blender内のプロパティ状態とC++コアおよび描画レイヤーを完全再同期します"""
    import bpy
    from .drawing import get_wireframe_engine
    from .core_bridge import update_cad_preview_high_quality_for_col
    from .utils import sync_proxies
    
    engine = get_wireframe_engine()
    if engine:
        engine.hidden_primitive_uuids.clear()
        
    for col in bpy.data.collections:
        if hasattr(col, "seamless_props") and getattr(col, "seamless_cad_stack_ptr", "0") != "0":
            try:
                sync_proxies(bpy.context, props=col.seamless_props)
                update_cad_preview_high_quality_for_col(col, bpy.context)
            except Exception as e:
                utils.error_print(f"Seamless CAD: Undo/Redo sync error: {e}")

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
    if not bpy.app.timers.is_registered(core_bridge.poll_async_results):
        bpy.app.timers.register(core_bridge.poll_async_results, first_interval=0.05)
    
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
