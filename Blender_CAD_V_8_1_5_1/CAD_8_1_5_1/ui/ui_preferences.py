import bpy
from .. import utils
from .. import core_bridge

# このモジュールは "<アドオンルート>.ui" なので、末尾の ".ui" を落とすとルートになる。
#
# 以前は `__package__.split('.')[0]` を使っていた。レガシーアドオン
# ("CAD_8_1_5_1.ui") では偶然正しいが、Blender 4.2+ の Extensions として
# インストールすると "bl_ext.user_default.CAD_8_1_5_1.ui" になるため
# "bl_ext" になってしまい、アドオン設定が一切引けなくなる
# (= ログ設定が既定値のまま固定される)。
ADDON_PACKAGE = __package__.rsplit('.', 1)[0]


def _get_addon_prefs(context=None):
    for ctx in (context, bpy.context):
        try:
            prefs_root = getattr(ctx, "preferences", None) if ctx else None
            if not prefs_root:
                continue
            addon = prefs_root.addons.get(ADDON_PACKAGE)
            if addon:
                return addon.preferences
        except Exception:
            continue
    return None


def _apply_log_preferences(context=None):
    prefs = _get_addon_prefs(context)

    if prefs is None:
        # 黙って既定値のままにすると原因が分からないので必ず知らせる。
        # WARN_LOGS は既定 False なので error_print を使う。
        utils.error_print(
            f"Seamless CAD: addon preferences not found for package '{ADDON_PACKAGE}'; "
            "keeping module-level logging defaults"
        )
        return

    utils.DEBUG_LOGS = bool(getattr(prefs, "log_debug", False))
    utils.INFO_LOGS = bool(getattr(prefs, "log_info", False))
    utils.WARN_LOGS = bool(getattr(prefs, "log_warn", False))
    utils.ERROR_LOGS = bool(getattr(prefs, "log_error", True))
    utils.ENABLE_PERF_LOGGING = bool(getattr(prefs, "enable_perf_logging", False))

    try:
        core = core_bridge.get_core()
        if core and hasattr(core, "set_cad_debug_logging"):
            core.set_cad_debug_logging(bool(getattr(prefs, "log_debug", False)))
    except Exception:
        pass

def _on_log_pref_updated(self, context):
    _apply_log_preferences(context)

class SEAMLESS_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = ADDON_PACKAGE

    log_debug: bpy.props.BoolProperty(
        name="Enable DEBUG Logs",
        description="Verbose debug logs (can affect performance)",
        default=False,
        update=_on_log_pref_updated
    )
    log_info: bpy.props.BoolProperty(
        name="Enable INFO Logs",
        description="General information logs",
        default=False,
        update=_on_log_pref_updated
    )
    log_warn: bpy.props.BoolProperty(
        name="Enable WARN Logs",
        description="Warning logs",
        default=False,
        update=_on_log_pref_updated
    )
    log_error: bpy.props.BoolProperty(
        name="Enable ERROR Logs",
        description="Error logs",
        default=True,
        update=_on_log_pref_updated
    )
    enable_perf_logging: bpy.props.BoolProperty(
        name="Perf Logging",
        description="Write timing logs to seamless_cad_profile.log (in the OS temp dir) for the CAD preview pipeline",
        default=False,
        update=_on_log_pref_updated
    )

    def draw(self, context):
        layout = self.layout
        
        box_eng = layout.box()
        row = box_eng.row()
        # CORE_AVAILABLE は常に True の定数なので、以前このアイコンは
        # サーバーが落ちていても「有効」を表示していた。実状を出す。
        engine_up = core_bridge.is_server_running()
        row.label(
            text="CAD Engine: " + ("Running" if engine_up else "Not running"),
            icon='GHOST_ENABLED' if engine_up else 'GHOST_DISABLED',
        )
        row.operator("seamless.get_version", text="Version")
        layout.separator()
        
        layout.label(text="Seamless CAD Logging")
        col = layout.column(align=True)
        col.prop(self, "enable_perf_logging")
        col.separator()
        col.prop(self, "log_error")
        col.prop(self, "log_warn")
        col.prop(self, "log_info")
        col.prop(self, "log_debug")
