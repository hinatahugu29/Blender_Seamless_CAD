import mathutils

_handle_3d = None
_handle_2d = None

_mouse_pos = mathutils.Vector((0, 0, 0))
_axis_lock = None
_axis_lock_start_co = None

_box_select_start = None
_box_select_end = None
_is_box_selecting = False

_history_stack = []

_arc_points = []
_circle_points = []
_semicircle_points = []
_rectangle_points = []

_reference_matrix = None
_grid_step = 1.0

# V8.1.5: 寸法駆動スケッチ - ビューポート上の寸法ラベル(📏)のクリック判定用ヒットボックス。
# draw_sketch_2d の描画毎に再構築される。各要素は
# (constraint.id, x0, y0, x1, y1) のタプル。
_dimension_label_hitboxes = []

_midpoint_snap_co = None
_trim_preview_coords = None
_extend_preview_coords = None

_fully_constrained_pts = set()
_fully_constrained_lines = set()
_fully_constrained_circles = set()
_fully_constrained_arcs = set()

_inference_lines = []
_last_mouse_pos = None
_dof_timer_handle = None
_pending_dof_props = None
_pending_dof_data = None








