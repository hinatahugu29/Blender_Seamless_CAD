import bpy
from . import utils

_handle_3d_post = None
_handle_2d_post = None
_handle_3d_pre = None

def register_handlers():
    global _handle_3d_post, _handle_2d_post, _handle_3d_pre
    
    if "seamless_cad_draw_handler_3d_post" in bpy.app.driver_namespace:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(bpy.app.driver_namespace["seamless_cad_draw_handler_3d_post"], 'WINDOW')
        except Exception:
            pass
    if "seamless_cad_draw_handler_2d_post" in bpy.app.driver_namespace:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(bpy.app.driver_namespace["seamless_cad_draw_handler_2d_post"], 'WINDOW')
        except Exception:
            pass
            
    _handle_3d_post = bpy.types.SpaceView3D.draw_handler_add(_draw_3d_post, (None, None), 'WINDOW', 'POST_VIEW')
    _handle_2d_post = bpy.types.SpaceView3D.draw_handler_add(_draw_2d_post, (None, None), 'WINDOW', 'POST_PIXEL')
    
    bpy.app.driver_namespace["seamless_cad_draw_handler_3d_post"] = _handle_3d_post
    bpy.app.driver_namespace["seamless_cad_draw_handler_2d_post"] = _handle_2d_post

def unregister_handlers():
    global _handle_3d_post, _handle_2d_post, _handle_3d_pre
    
    if _handle_3d_post:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_handle_3d_post, 'WINDOW')
        except Exception:
            pass
        _handle_3d_post = None
        
    if _handle_2d_post:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_handle_2d_post, 'WINDOW')
        except Exception:
            pass
        _handle_2d_post = None
        
    if "seamless_cad_draw_handler_3d_post" in bpy.app.driver_namespace:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(bpy.app.driver_namespace["seamless_cad_draw_handler_3d_post"], 'WINDOW')
        except Exception:
            pass
        del bpy.app.driver_namespace["seamless_cad_draw_handler_3d_post"]
        
    if "seamless_cad_draw_handler_2d_post" in bpy.app.driver_namespace:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(bpy.app.driver_namespace["seamless_cad_draw_handler_2d_post"], 'WINDOW')
        except Exception:
            pass
        del bpy.app.driver_namespace["seamless_cad_draw_handler_2d_post"]

def _find_3d_view_context(fallback_context):
    """画面上のアクティブな3Dビューポートを探して、描画に必要な最小限の属性を備えたコンテキストを返す"""
    if fallback_context and hasattr(fallback_context, "space_data") and fallback_context.space_data and fallback_context.space_data.type == 'VIEW_3D':
        return fallback_context
        
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                for region in area.regions:
                    if region.type == 'WINDOW':
                        class DummyContext:
                            def __init__(self, w, a, r):
                                self.window = w
                                self.area = a
                                self.region = r
                                self.space_data = a.spaces.active
                                self.region_data = r.data if hasattr(r, "data") else None
                                self.scene = bpy.context.scene
                                self.view_layer = w.view_layer
                        return DummyContext(window, area, region)
    return fallback_context

def _draw_3d_post(self, context):
    context = _find_3d_view_context(context or bpy.context)
    try:
        props = utils.get_active_props(context)
        if not props:
            return
            
        # Draw CAD (Wireframe & Faces)
        from . import drawing
        drawing.draw_cad_3d(self, context, props)
        
        # Draw Sketch
        if props.is_sketch_active:
            from .sketch import sketch_draw
            sketch_draw.draw_sketch_3d(context, props)
            
    except Exception as e:
        utils.error_print(f"GPU Manager 3D Error: {e}")

def _draw_2d_post(self, context):
    context = _find_3d_view_context(context or bpy.context)
    try:
        props = utils.get_active_props(context)
        if not props:
            return
            
        # Draw Sketch 2D HUD
        if props.is_sketch_active:
            from .sketch import sketch_draw
            sketch_draw.draw_sketch_2d(context, props)
            
        # Draw Drag Snap HUD
        from .drawing import get_gizmo_engine
        gizmo = get_gizmo_engine()
        if gizmo:
            gizmo.draw_hud(context)
            
    except Exception as e:
        utils.error_print(f"GPU Manager 2D Error: {e}")
