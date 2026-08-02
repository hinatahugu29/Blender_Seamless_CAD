# SPDX-License-Identifier: GPL-2.0-or-later
#
# Copyright (C) 2026 hinata_hugu
#
# This file is part of Seamless CAD.
#
# Seamless CAD is free software; you can redistribute it and/or modify it
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

import bpy
from ... import utils
from ..sketch_history import push_history
from ..sketch_solver import solve_gcs_external
from ...core_bridge import update_cad_preview


def _find_arc_id_for_radius_constraint(props, constraint):
    """SeamlessSketchConstraint(DISTANCE)が円弧の中心-半径点間の距離拘束かどうかを判定し、
    そうであれば対象のArc.idを返す(ui_sketch_panel.py の同名ロジックと同じ判定基準)。"""
    try:
        targets = [int(x.strip()) for x in constraint.target_ids_str.split(",") if x.strip()]
    except ValueError:
        return None
    if len(targets) != 2:
        return None
    first_id, second_id = targets
    for arc in props.sketch_arcs:
        if (arc.center_point_id == first_id and arc.mid_point_id == second_id) or \
           (arc.center_point_id == second_id and arc.mid_point_id == first_id):
            return arc.id
    return None


class SEAMLESS_OT_EditDimensionValue(bpy.types.Operator):
    """V8.1.5: 寸法駆動スケッチ - ビューポート上の寸法ラベルをクリックした際に呼ばれる。
    数値入力ポップアップで新しい値を受け取り、対象のDISTANCE拘束のvalueを書き換える。
    value書き込みは既存のupdate_sketch_constraint_valueコールバックを自動的にトリガーし、
    solve_gcs_external + update_cad_previewが実行される(新規の再ソルブ処理は不要)。"""
    bl_idname = "seamless.edit_dimension_value"
    bl_label = "Edit Dimension"
    bl_description = "Type a new value for this dimension"
    bl_options = {'REGISTER', 'UNDO'}

    constraint_id: bpy.props.IntProperty()
    value: bpy.props.FloatProperty(name="Value", default=1.0, min=0.0001)

    def invoke(self, context, event):
        self._is_radius = False
        props = utils.get_active_props(context)
        if not props:
            return {'CANCELLED'}
        constraint = next((c for c in props.sketch_constraints if c.id == self.constraint_id), None)
        if constraint is None:
            self.report({'WARNING'}, f"Constraint ID:{self.constraint_id} not found.")
            return {'CANCELLED'}
        self.value = constraint.value
        self._is_radius = _find_arc_id_for_radius_constraint(props, constraint) is not None
        return context.window_manager.invoke_props_dialog(self, width=200)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "value", text="Radius" if self._is_radius else "Distance")

    def execute(self, context):
        props = utils.get_active_props(context)
        if not props:
            return {'CANCELLED'}
        constraint = next((c for c in props.sketch_constraints if c.id == self.constraint_id), None)
        if constraint is None:
            self.report({'WARNING'}, f"Constraint ID:{self.constraint_id} not found.")
            return {'CANCELLED'}
        push_history(props)
        constraint.value = self.value
        # constraint.value の update コールバックが solve_gcs_external を既に呼ぶが、
        # 念のため明示的にも再ソルブ・プレビュー更新して確実に反映させる。
        solve_gcs_external(props, context)
        update_cad_preview(None, context)
        return {'FINISHED'}
