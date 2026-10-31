from bpy_extras import view3d_utils

from .state_base import SketchState
from .. import sketch_globals
from ..sketch_history import push_history
from ..sketch_project import project_entity
from ...core_bridge import update_cad_preview, pick_edge, pick_face
from ... import utils


class StateProject(SketchState):
    """既存形状の辺(Shift で面の輪郭)をスケッチ平面へ投影して取り込む。

    取り込みは一度きり。上流が変わっても追従しない(フェーズ2.1 第1段階)。
    """

    def handle_left_click_press(self, event, mouse_pos_3d):
        context = self.context
        props = self.props

        col = utils.get_active_collection(context)
        if not col or getattr(col, "seamless_cad_stack_ptr", "0") == "0":
            return None

        region = context.region
        rv3d = context.region_data
        if not region or not rv3d:
            return None

        coord = (event.mouse_region_x, event.mouse_region_y)
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)

        try:
            stack_ptr = int(col.seamless_cad_stack_ptr)
        except (TypeError, ValueError):
            return None

        # Shift を押していれば面の輪郭を丸ごと、既定では辺を1本。
        is_face = bool(event.shift)
        if is_face:
            res = pick_face(stack_ptr, list(origin), list(direction), 0.1)
        else:
            res = pick_edge(stack_ptr, list(origin), list(direction), 0.5)
        if not res:
            return None

        lineage = res[0]
        push_history(props)
        made, err = project_entity(context, props, lineage, is_face,
                                   construction=getattr(props, "sketch_project_as_construction", False))
        if err:
            self.sketch_op.report({'WARNING'}, err)
            return None

        self.sketch_op.report({'INFO'}, f"Projected {made} element(s)")
        update_cad_preview(None, context)
        if context.area:
            context.area.tag_redraw()
        return None

    def handle_right_click(self, event):
        sketch_globals._axis_lock_start_co = None
        return 'SELECT'
