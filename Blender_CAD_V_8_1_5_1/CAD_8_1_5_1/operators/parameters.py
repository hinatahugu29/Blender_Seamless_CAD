import bpy

from .. import utils
from ..core.parameters import BINDABLE_FIELDS, apply_parameters, field_value


def _active_prim(props):
    if props and 0 <= props.active_primitive_index < len(props.primitives):
        return props.primitives[props.active_primitive_index]
    return None


class SEAMLESS_OT_AddParameter(bpy.types.Operator):
    """Add a named value that feature fields can refer to"""
    bl_idname = "seamless.add_parameter"
    bl_label = "Add Parameter"
    bl_options = {'REGISTER', 'UNDO'}

    name: bpy.props.StringProperty(name="Name", default="")
    expression: bpy.props.StringProperty(name="Expression", default="1")

    def execute(self, context):
        props = utils.get_active_props(context)
        if props is None:
            return {'CANCELLED'}
        name = self.name
        if not name:
            taken = {p.name for p in props.parameters}
            i = 1
            while f"p{i}" in taken:
                i += 1
            name = f"p{i}"
        item = props.parameters.add()
        item.expression = self.expression
        item.name = name
        apply_parameters(props)
        return {'FINISHED'}


class SEAMLESS_OT_RemoveParameter(bpy.types.Operator):
    """Remove this parameter. Fields that use it will show an error"""
    bl_idname = "seamless.remove_parameter"
    bl_label = "Remove Parameter"
    bl_options = {'REGISTER', 'UNDO'}

    index: bpy.props.IntProperty()

    def execute(self, context):
        props = utils.get_active_props(context)
        if props is None or not (0 <= self.index < len(props.parameters)):
            return {'CANCELLED'}
        props.parameters.remove(self.index)
        apply_parameters(props)
        return {'FINISHED'}


class SEAMLESS_OT_AddBinding(bpy.types.Operator):
    """Drive a field of the active feature with an expression"""
    bl_idname = "seamless.add_binding"
    bl_label = "Drive Field"
    bl_options = {'REGISTER', 'UNDO'}

    field: bpy.props.EnumProperty(
        name="Field",
        items=[(f[0], f[3], "") for f in BINDABLE_FIELDS],
    )
    expression: bpy.props.StringProperty(name="Expression", default="")

    def execute(self, context):
        props = utils.get_active_props(context)
        prim = _active_prim(props)
        if prim is None:
            return {'CANCELLED'}
        existing = next((b for b in prim.bindings if b.field == self.field), None)
        b = existing or prim.bindings.add()
        b.field = self.field
        # 既定の式は今の値。付けた瞬間に形が変わらないようにする
        b.expression = self.expression or f"{field_value(prim, self.field):.6g}"
        apply_parameters(props)
        return {'FINISHED'}


class SEAMLESS_OT_RemoveBinding(bpy.types.Operator):
    """Stop driving this field. It keeps its current value"""
    bl_idname = "seamless.remove_binding"
    bl_label = "Remove Driven Field"
    bl_options = {'REGISTER', 'UNDO'}

    index: bpy.props.IntProperty()

    def execute(self, context):
        prim = _active_prim(utils.get_active_props(context))
        if prim is None or not (0 <= self.index < len(prim.bindings)):
            return {'CANCELLED'}
        prim.bindings.remove(self.index)
        return {'FINISHED'}
