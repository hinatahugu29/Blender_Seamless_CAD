import collections

import bpy

from .. import utils


class SEAMLESS_PT_SketchPanel(bpy.types.Panel):
    bl_label = "Seamless CAD - Sketch Mode"
    bl_idname = "SEAMLESS_PT_SketchPanel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Seamless"

    @classmethod
    def poll(cls, context):
        props = utils.get_active_props(context)
        return bool(props and props.is_sketch_active)

    def draw(self, context):
        layout = self.layout
        props = utils.get_active_props(context)
        if not props:
            return

        box = layout.box()
        box.label(text="Sketch Command Palette", icon="GREASEPENCIL")

        row_grid = box.row(align=True)
        row_grid.prop(props, "sketch_show_grid", text="Show Grid", icon="SNAP_GRID")
        row_grid.prop(props, "sketch_grid_snap", text="Grid Snap", icon="SNAP_GRID")
        box.separator()

        box.label(text="Pen Tools:", icon="LINE_DATA")
        col_tools = box.column(align=True)
        row = col_tools.row(align=True)
        row.prop_enum(props, "sketch_pen_mode", "SELECT", text="Select", icon="RESTRICT_SELECT_OFF")
        row.prop_enum(props, "sketch_pen_mode", "POINT", text="Point", icon="DOT")
        row = col_tools.row(align=True)
        row.prop_enum(props, "sketch_pen_mode", "LINE", text="Line", icon="LINE_DATA")
        row.prop_enum(props, "sketch_pen_mode", "ARC", text="Arc", icon="CURVE_NCIRCLE")
        row = col_tools.row(align=True)
        row.prop_enum(props, "sketch_pen_mode", "CIRCLE", text="Circle", icon="MESH_CIRCLE")
        row.prop_enum(props, "sketch_pen_mode", "SEMICIRCLE", text="Semi-circle", icon="OUTLINER_OB_FORCE_FIELD")
        row = col_tools.row(align=True)
        row.prop_enum(props, "sketch_pen_mode", "RECTANGLE", text="Rectangle", icon="MESH_PLANE")
        row.prop_enum(props, "sketch_pen_mode", "CENTER_RECT", text="Center Rect", icon="PIVOT_BOUNDBOX")
        row = col_tools.row(align=True)
        row.prop_enum(props, "sketch_pen_mode", "TRIM_EXTEND", text="Trim / Extend", icon="MOD_BOOLEAN")
        row.prop_enum(props, "sketch_pen_mode", "SLOT", text="Slot", icon="OUTLINER_OB_FORCE_FIELD")
        box.separator()

        found_dist_const = self._find_distance_constraint(props)

        box_coord = box.box()
        box_coord.label(text="Selection Info:", icon="INFO")
        self._draw_selection_info(box_coord, props, found_dist_const)
        box.separator()

        box_constraints = box.box()
        box_constraints.label(text="Constraints:", icon="CONSTRAINT")
        col_constraints = box_constraints.column(align=True)
        col_constraints.operator(
            "seamless.sketch_action",
            text="Fixed",
            icon="LOCKED",
        ).action = "CONSTRAINT_FIXED"

        if (
            (props.sketch_selected_point_id >= 0 and props.sketch_selected_point_id_2 >= 0)
            or props.sketch_selected_line_id >= 0
        ) and not found_dist_const:
            col_constraints.operator(
                "seamless.sketch_action",
                text="Distance",
                icon="DRIVER_DISTANCE",
            ).action = "CONSTRAINT_DISTANCE"

        row = col_constraints.row(align=True)
        row.operator(
            "seamless.sketch_action",
            text="Align X",
            icon="ALIGN_MIDDLE",
        ).action = "CONSTRAINT_HORIZONTAL"
        row.operator(
            "seamless.sketch_action",
            text="Align Y",
            icon="ALIGN_CENTER",
        ).action = "CONSTRAINT_VERTICAL"

        row = col_constraints.row(align=True)
        row.operator(
            "seamless.sketch_action",
            text="Parallel",
            icon="CON_TRANSLIKE",
        ).action = "CONSTRAINT_PARALLEL"
        row.operator(
            "seamless.sketch_action",
            text="Perpendicular",
            icon="CON_ROTLIKE",
        ).action = "CONSTRAINT_PERPENDICULAR"

        col_constraints.operator(
            "seamless.sketch_action",
            text="Coincident (Point Merge)",
            icon="SNAP_VERTEX",
        ).action = "CONSTRAINT_COINCIDENT"
        col_constraints.operator(
            "seamless.sketch_action",
            text="Midpoint",
            icon="PIVOT_MEDIAN",
        ).action = "CONSTRAINT_MIDPOINT"
        col_constraints.operator(
            "seamless.sketch_action",
            text="Tangent",
            icon="SNAP_EDGE",
        ).action = "CONSTRAINT_TANGENT"
        box.separator()

        box_geom = box.box()
        box_geom.label(text="Geometry & Actions:", icon="MESH_DATA")
        col_geom = box_geom.column(align=True)
        col_geom.operator(
            "seamless.sketch_action",
            text="Toggle Construction",
            icon="MOD_DASH",
        ).action = "TOGGLE_CONSTRUCTION"

        row = col_geom.row(align=True)
        row.operator(
            "seamless.sketch_action",
            text="Select All (Ctrl+A)",
            icon="SELECT_SET",
        ).action = "SELECT_ALL"
        row.operator(
            "seamless.sketch_action",
            text="Chain Select (L)",
            icon="LINKED",
        ).action = "SELECT_CHAIN"

        row = col_geom.row(align=True)
        row.operator(
            "seamless.sketch_action",
            text="Copy (Ctrl+C)",
            icon="COPYDOWN",
        ).action = "COPY_SELECTION"
        paste_row = row.row(align=True)
        paste_row.enabled = props.sketch_clipboard_has_data
        paste_row.operator(
            "seamless.sketch_action",
            text="Paste (Ctrl+V)",
            icon="PASTEDOWN",
        ).action = "PASTE_SELECTION"

        row = col_geom.row(align=True)
        row.operator(
            "seamless.sketch_action",
            text="Trim",
            icon="MOD_BOOLEAN",
        ).action = "TRIM_SELECTION"
        row.operator(
            "seamless.sketch_action",
            text="Extend",
            icon="TRACKING_FORWARDS",
        ).action = "EXTEND_SELECTION"

        row = col_geom.row(align=True)
        row.prop(props, "sketch_offset_distance", text="Offset")
        row.operator(
            "seamless.sketch_action",
            text="Offset Lines",
            icon="MOD_OFFSET",
        ).action = "OFFSET_SELECTION"

        row = col_geom.row(align=True)
        row.operator(
            "seamless.sketch_action",
            text="Mirror X",
            icon="MOD_MIRROR",
        ).action = "MIRROR_X"
        row.operator(
            "seamless.sketch_action",
            text="Mirror Y",
            icon="MOD_MIRROR",
        ).action = "MIRROR_Y"
        box.separator()

        box_corner = box.box()
        box_corner.label(text="Corner Tools:", icon="MOD_BEVEL")
        col_fillet = box_corner.column(align=True)
        col_fillet.prop(props, "sketch_fillet_radius", text="Fillet Radius")
        col_fillet.operator(
            "seamless.sketch_action",
            text="Fillet",
            icon="MOD_BEVEL",
        ).action = "CORNER_FILLET"

        box_corner.separator()

        col_chamfer = box_corner.column(align=True)
        col_chamfer.prop(props, "sketch_chamfer_distance", text="Chamfer Distance")
        col_chamfer.operator(
            "seamless.sketch_action",
            text="Chamfer",
            icon="MOD_BEVEL",
        ).action = "CORNER_CHAMFER"
        box.separator()

        box_list = box.box()
        row = box_list.row()
        row.prop(
            props,
            "sketch_show_constraints",
            text="Constraints / Parameters",
            icon="CONSTRAINT",
            toggle=True,
        )
        if props.sketch_show_constraints:
            self._draw_constraint_list(box_list.column(align=True), props)

        box.separator()

        row = box.row(align=True)
        row.operator(
            "seamless.sketch_action",
            text="Undo (Ctrl+Z)",
            icon="BACK",
        ).action = "UNDO"

        box.separator()

        row = box.row(align=True)
        row.operator(
            "seamless.sketch_action",
            text="Apply",
            icon="CHECKMARK",
        ).action = "APPLY"
        row.operator(
            "seamless.sketch_action",
            text="Cancel",
            icon="CANCEL",
        ).action = "CANCEL"

    def _draw_selection_info(self, layout, props, found_dist_const):
        if props.sketch_selected_point_id >= 0 and props.sketch_selected_point_id_2 >= 0:
            layout.label(text=f"Point 1: ID={props.sketch_selected_point_id}", icon="VERTEXSEL")
            layout.label(text=f"Point 2: ID={props.sketch_selected_point_id_2}", icon="VERTEXSEL")
            self._draw_distance_editor(layout, props, found_dist_const)
            row = layout.row(align=True)
            row.operator("seamless.sketch_action", text="Clear Selection", icon="X").action = "CLEAR_SELECTION"
            return

        if props.sketch_selected_point_id >= 0:
            layout.label(text=f"Point: ID={props.sketch_selected_point_id}", icon="VERTEXSEL")
            row = layout.row(align=True)
            row.prop(props, "sketch_selected_point_x", text="X")
            row.prop(props, "sketch_selected_point_y", text="Y")
            self._draw_distance_editor(layout, props, found_dist_const)
            row = layout.row(align=True)
            row.operator("seamless.sketch_action", text="Clear Selection", icon="X").action = "CLEAR_SELECTION"
            row.operator("seamless.sketch_action", text="Delete Point", icon="TRASH").action = "DELETE_SELECTED"
            return

        if props.sketch_selected_line_id >= 0 and props.sketch_selected_line_id_2 >= 0:
            layout.label(text=f"Line 1: ID={props.sketch_selected_line_id}", icon="EDGESEL")
            layout.label(text=f"Line 2: ID={props.sketch_selected_line_id_2}", icon="EDGESEL")
            row = layout.row(align=True)
            row.operator("seamless.sketch_action", text="Clear Selection", icon="X").action = "CLEAR_SELECTION"
            return

        if props.sketch_selected_line_id >= 0:
            layout.label(text=f"Line: ID={props.sketch_selected_line_id}", icon="EDGESEL")
            line = next((item for item in props.sketch_lines if item.id == props.sketch_selected_line_id), None)
            if line:
                layout.label(text=f"Start {line.start_point_id}  End {line.end_point_id}")
            self._draw_distance_editor(layout, props, found_dist_const)
            row = layout.row(align=True)
            row.operator("seamless.sketch_action", text="Clear Selection", icon="X").action = "CLEAR_SELECTION"
            row.operator("seamless.sketch_action", text="Delete Line", icon="TRASH").action = "DELETE_SELECTED"
            return

        layout.label(text="No selected object", icon="INFO")

    def _draw_distance_editor(self, layout, props, found_dist_const):
        if not found_dist_const:
            return
        layout.separator()
        if self._is_arc_radius_constraint(props, found_dist_const):
            layout.label(text="Arc Radius:", icon="CONSTRAINT")
            layout.prop(found_dist_const, "value", text="Radius")
        else:
            layout.label(text="Distance Constraint:", icon="CONSTRAINT")
            layout.prop(found_dist_const, "value", text="Length")

    def _draw_constraint_list(self, layout, props):
        if not props.sketch_constraints:
            layout.label(text="No active constraints", icon="INFO")
            return

        for constraint in props.sketch_constraints:
            row = layout.row(align=True)
            name, editable = self._constraint_display_name(props, constraint)
            row.label(text=name)
            if editable:
                row.prop(constraint, "value", text="")
            else:
                row.label(text="-")
            op = row.operator("seamless.sketch_action", text="", icon="TRASH")
            op.action = "DELETE_CONSTRAINT"
            op.constraint_id = constraint.id

    def _constraint_display_name(self, props, constraint):
        targets = self._parse_target_ids(constraint.target_ids_str)

        if constraint.type == "DISTANCE":
            if self._is_arc_radius_constraint(props, constraint):
                arc_id = self._find_arc_id_for_radius_constraint(props, constraint)
                return (f"Arc Radius (Arc:{arc_id})", True)
            return (f"Distance ({'-'.join(map(str, targets))})", True)
        if constraint.type == "FIXED":
            return (f"Fixed ({', '.join(map(str, targets))})", False)
        if constraint.type == "HORIZONTAL":
            return (f"Horizontal ({'-'.join(map(str, targets))})", False)
        if constraint.type == "VERTICAL":
            return (f"Vertical ({'-'.join(map(str, targets))})", False)
        if constraint.type == "PARALLEL":
            return (f"Parallel ({', '.join(map(str, targets))})", False)
        if constraint.type == "PERPENDICULAR":
            return ("Perpendicular", False)
        if constraint.type == "TANGENT":
            return ("Tangent", False)
        if constraint.type == "MIDPOINT":
            return ("Midpoint", False)
        if constraint.type == "ARC":
            arc_id = targets[0] if targets else "?"
            return (f"Arc ({arc_id})", False)
        return (f"{constraint.type} (ID:{constraint.id})", False)

    def _find_distance_constraint(self, props):
        targets = []
        if props.sketch_selected_point_id >= 0 and props.sketch_selected_point_id_2 >= 0:
            targets = [props.sketch_selected_point_id, props.sketch_selected_point_id_2]
        elif props.sketch_selected_line_id >= 0:
            line = next((item for item in props.sketch_lines if item.id == props.sketch_selected_line_id), None)
            if line:
                targets = [line.start_point_id, line.end_point_id]

        if len(targets) == 2:
            found = self._find_distance_constraint_by_pair(props, targets[0], targets[1])
            if found:
                return found

        arc = self._find_selected_arc(props)
        if arc:
            return self._find_distance_constraint_by_pair(props, arc.center_point_id, arc.mid_point_id)
        return None

    def _find_distance_constraint_by_pair(self, props, first_id, second_id):
        direct = f"{first_id},{second_id}"
        reverse = f"{second_id},{first_id}"
        for constraint in props.sketch_constraints:
            if constraint.type == "DISTANCE" and constraint.target_ids_str in (direct, reverse):
                return constraint
        return None

    def _find_selected_arc(self, props):
        if props.sketch_selected_line_id >= 0:
            line_id = props.sketch_selected_line_id
            line = next((item for item in props.sketch_lines if item.id == line_id), None)
            if not line:
                return None
            point_ids = {line.start_point_id, line.end_point_id}
            point_objs = [point for point in props.sketch_points if point.id in point_ids]
            for arc in props.sketch_arcs:
                if point_ids & {arc.start_point_id, arc.end_point_id, arc.mid_point_id}:
                    return arc
                if any(point.is_segment for point in point_objs) and self._line_is_on_arc_path(props, line_id, arc):
                    return arc

        if props.sketch_selected_point_id >= 0 and props.sketch_selected_point_id_2 < 0:
            point_id = props.sketch_selected_point_id
            point = next((item for item in props.sketch_points if item.id == point_id), None)
            if not point:
                return None
            for arc in props.sketch_arcs:
                if point_id in {
                    arc.start_point_id,
                    arc.end_point_id,
                    arc.mid_point_id,
                    arc.center_point_id,
                }:
                    return arc
                if point.is_segment and self._point_is_on_arc_path(props, point_id, arc):
                    return arc
        return None

    def _line_is_on_arc_path(self, props, line_id, arc):
        adjacency = collections.defaultdict(list)
        for line in props.sketch_lines:
            adjacency[line.start_point_id].append((line.end_point_id, line.id))
            adjacency[line.end_point_id].append((line.start_point_id, line.id))

        stack = [(arc.start_point_id, [])]
        visited = {arc.start_point_id}
        while stack:
            node, line_ids = stack.pop()
            if node == arc.end_point_id:
                return line_id in line_ids
            for neighbor, neighbor_line_id in adjacency[node]:
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                stack.append((neighbor, line_ids + [neighbor_line_id]))
        return False

    def _point_is_on_arc_path(self, props, point_id, arc):
        adjacency = collections.defaultdict(list)
        for line in props.sketch_lines:
            adjacency[line.start_point_id].append(line.end_point_id)
            adjacency[line.end_point_id].append(line.start_point_id)

        stack = [(arc.start_point_id, [arc.start_point_id])]
        visited = {arc.start_point_id}
        while stack:
            node, path = stack.pop()
            if node == arc.end_point_id:
                return point_id in path
            for neighbor in adjacency[node]:
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                stack.append((neighbor, path + [neighbor]))
        return False

    def _is_arc_radius_constraint(self, props, constraint):
        return self._find_arc_id_for_radius_constraint(props, constraint) is not None

    def _find_arc_id_for_radius_constraint(self, props, constraint):
        targets = self._parse_target_ids(constraint.target_ids_str)
        if len(targets) != 2:
            return None
        first_id, second_id = targets
        for arc in props.sketch_arcs:
            if (
                arc.center_point_id == first_id and arc.mid_point_id == second_id
            ) or (
                arc.center_point_id == second_id and arc.mid_point_id == first_id
            ):
                return arc.id
        return None

    def _parse_target_ids(self, target_ids_str):
        try:
            return [int(value.strip()) for value in target_ids_str.split(",") if value.strip()]
        except ValueError:
            return []
