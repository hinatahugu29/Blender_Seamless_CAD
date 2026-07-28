import bpy
import uuid
import math
import mathutils
import os
import copy
from bpy_extras import view3d_utils
from ..core_bridge import get_core, update_cad_preview, update_cad_preview_high_quality, update_cad_preview_fast, is_core_busy, get_or_create_stack_ptr
from ..drawing import get_wireframe_engine
from .. import utils

RESULT_COLLECTION_NAME = "Result"

def _serialize_primitive(source):
    return {
        "name": source.name,
        "uuid": source.uuid,
        "type": source.type,
        "operation": source.operation,
        "location": source.location[:],
        "rotation": source.rotation[:],
        "size": source.size[:],
        "radius": source.radius,
        "radius2": source.radius2,
        "minor_radius": source.minor_radius,
        "pipe_radius": source.pipe_radius,
        "extrude_height": source.extrude_height,
        "turns": source.turns,
        "fill_closed": source.fill_closed,
        "use_pipe": source.use_pipe,
        "top_shape": source.top_shape,
        "bot_shape": source.bot_shape,
        "sides": source.sides,
        "module": source.module,
        "pressure_angle": source.pressure_angle,
        "target_uuid": source.target_uuid,
        "target_lineages": source.target_lineages,
        "reference_lineage": source.reference_lineage,
        "edge_ref_snapshot": getattr(source, "edge_ref_snapshot", ""),
        "reference_ref_snapshot": getattr(source, "reference_ref_snapshot", ""),
        "count": source.count,
        "distance": source.distance,
        "pattern_axis": source.pattern_axis,
        "angle_start": source.angle_start,
        "angle_end": source.angle_end,
        "step_scale": getattr(source, "step_scale", 1.0),
        "step_source_path": getattr(source, "step_source_path", ""),
        "step_source_index": getattr(source, "step_source_index", -1),
        "sweep_path_uuid": getattr(source, "sweep_path_uuid", ""),
        "sweep_profile_uuid": getattr(source, "sweep_profile_uuid", ""),
        "loft_uuids": getattr(source, "loft_uuids", ""),
        "unify_faces": getattr(source, "unify_faces", True),
        "unify_edges": getattr(source, "unify_edges", True),
        "use_independent_transform": getattr(source, "use_independent_transform", False),
        "group_selected": False,
        "points": [{"co": pt.co[:], "use_fillet": getattr(pt, "use_fillet", True)} for pt in source.points],
    }

def _apply_primitive_data(item, data):
    item.name = data["name"]
    item.uuid = data["uuid"]
    item.type = data["type"]
    item.operation = data["operation"]
    item.location = data["location"]
    item.rotation = data["rotation"]
    item.radius = data["radius"]
    item.radius2 = data["radius2"]
    item.minor_radius = data["minor_radius"]
    item.pipe_radius = data["pipe_radius"]
    item.extrude_height = data["extrude_height"]
    item.turns = data["turns"]
    item.fill_closed = data["fill_closed"]
    item.use_pipe = data["use_pipe"]
    item.top_shape = data["top_shape"]
    item.bot_shape = data["bot_shape"]
    item.sides = data["sides"]
    item.module = data["module"]
    item.pressure_angle = data["pressure_angle"]
    item.target_uuid = data["target_uuid"]
    item.target_lineages = data["target_lineages"]
    item.reference_lineage = data["reference_lineage"]
    if hasattr(item, "edge_ref_snapshot"):
        item.edge_ref_snapshot = data.get("edge_ref_snapshot", "")
    if hasattr(item, "reference_ref_snapshot"):
        item.reference_ref_snapshot = data.get("reference_ref_snapshot", "")
    item.count = data["count"]
    item.distance = data["distance"]
    item.pattern_axis = data["pattern_axis"]
    item.angle_start = data["angle_start"]
    item.angle_end = data["angle_end"]
    if hasattr(item, "step_scale"):
        item.step_scale = data.get("step_scale", 1.0)
    item.size = data["size"]
    if hasattr(item, "step_source_path"):
        item.step_source_path = data.get("step_source_path", "")
    if hasattr(item, "step_source_index"):
        item.step_source_index = data.get("step_source_index", -1)
    if hasattr(item, "sweep_path_uuid"):
        item.sweep_path_uuid = data.get("sweep_path_uuid", "")
    if hasattr(item, "sweep_profile_uuid"):
        item.sweep_profile_uuid = data.get("sweep_profile_uuid", "")
    if hasattr(item, "loft_uuids"):
        item.loft_uuids = data.get("loft_uuids", "")
    if hasattr(item, "unify_faces"):
        item.unify_faces = data.get("unify_faces", True)
    if hasattr(item, "unify_edges"):
        item.unify_edges = data.get("unify_edges", True)
    if hasattr(item, "use_independent_transform"):
        item.use_independent_transform = data.get("use_independent_transform", False)
    if hasattr(item, "group_selected"):
        item.group_selected = data.get("group_selected", False)
    for pt in data.get("points", []):
        new_pt = item.points.add()
        new_pt.co = pt["co"]
        if hasattr(new_pt, "use_fillet"):
            new_pt.use_fillet = pt.get("use_fillet", True)

def _rebuild_primitives(props, rebuilt_data, active_index):
    from ..utils import set_updating_flag
    set_updating_flag(True)
    try:
        while props.primitives:
            props.primitives.remove(len(props.primitives) - 1)
        for data in rebuilt_data:
            item = props.primitives.add()
            _apply_primitive_data(item, data)
        props.active_primitive_index = min(max(active_index, 0), len(props.primitives) - 1) if rebuilt_data else 0
    finally:
        set_updating_flag(False)

def _replace_uuid_string(value, uuid_map):
    if not value:
        return value
    for old_uuid, new_uuid in uuid_map.items():
        value = value.replace(old_uuid, new_uuid)
    return value

def _remap_primitive_links(data, uuid_map):
    for key in ("target_uuid", "sweep_path_uuid", "sweep_profile_uuid"):
        value = data.get(key, "")
        data[key] = uuid_map.get(value, value)

    loft_uuids = [u.strip() for u in data.get("loft_uuids", "").split("|") if u.strip()]
    data["loft_uuids"] = "|".join(uuid_map.get(u, u) for u in loft_uuids)
    data["target_lineages"] = _replace_uuid_string(data.get("target_lineages", ""), uuid_map)
    data["reference_lineage"] = _replace_uuid_string(data.get("reference_lineage", ""), uuid_map)
    data["edge_ref_snapshot"] = _replace_uuid_string(data.get("edge_ref_snapshot", ""), uuid_map)
    data["reference_ref_snapshot"] = _replace_uuid_string(data.get("reference_ref_snapshot", ""), uuid_map)
    return data

def _find_group_start_index(primitives, group_end_index):
    depth = 0
    for i in range(group_end_index, -1, -1):
        prim_type = primitives[i].type
        if prim_type == 'GROUP_END':
            depth += 1
        elif prim_type == 'GROUP_START':
            depth -= 1
            if depth == 0:
                return i
    return -1

def _build_single_duplicate_data(source, total_count):
    data_copy = _serialize_primitive(source)
    data_copy["name"] = f"{source.name}_copy"
    data_copy["uuid"] = str(uuid.uuid4())[:8]
    data_copy["operation"] = 'ADD' if total_count > 1 else 'BASE'
    if data_copy["type"] in {'CLEANUP', 'GROUP_START', 'GROUP_END'}:
        data_copy["operation"] = 'ADD'
        data_copy["size"] = [1.0, 1.0, 1.0]
        data_copy["radius"] = 1.0
        data_copy["radius2"] = 1.0
        data_copy["minor_radius"] = 0.25
        data_copy["pipe_radius"] = 0.1
        data_copy["extrude_height"] = 1.0
    data_copy["group_selected"] = False
    return data_copy

def ensure_result_collection(parent_col):
    if not parent_col:
        return None
    result_col = bpy.data.collections.get(RESULT_COLLECTION_NAME)
    if result_col is None:
        result_col = bpy.data.collections.new(RESULT_COLLECTION_NAME)
    if result_col.name not in parent_col.children:
        parent_col.children.link(result_col)
    return result_col

class SEAMLESS_OT_RemovePrimitive(bpy.types.Operator):
    bl_idname = "seamless.remove_primitive"
    bl_label = "Remove Primitive"
    bl_options = {'REGISTER', 'UNDO'}
    index: bpy.props.IntProperty()
    def execute(self, context):
        # 🌟 オブジェクトモード以外の場合は自動的かつ安全にオブジェクトモードへ移行
        if context.active_object and context.active_object.mode != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except Exception as e:
                utils.debug_print(f"DEBUG: Mode-set OBJECT error: {e}")

        props = utils.get_active_props(context)
        if not props:
            return {'CANCELLED'}
        
        # 🌟 削除するプリミティブの UUID を即座に非表示リストに登録し、バッチを再構築して画面から消す
        if 0 <= self.index < len(props.primitives):
            prim = props.primitives[self.index]
            uuid_to_remove = prim.uuid
            if uuid_to_remove:
                engine = get_wireframe_engine()
                engine.hidden_primitive_uuids.add(uuid_to_remove)
                
                # 強制的に現在のバッチデータを更新（削除されたUUIDを非表示化）
                stack_ptr = int(getattr(utils.get_active_collection(context), "seamless_cad_stack_ptr", "0"))
                if stack_ptr != 0:
                    selected_f_ids = set(x.strip() for x in props.selected_faces_str.split("|") if x.strip())
                    stack_data = engine.get_stack(stack_ptr)
                    if stack_data and stack_data._cache_verts is not None and len(stack_data._cache_verts) > 0:
                        engine.update_face_data(
                            stack_ptr, 
                            stack_data._cache_verts,
                            stack_data._cache_tris,
                            stack_data._cache_fids,
                            stack_data._cache_counts,
                            opacity=props.viewport_opacity,
                            selected_f_ids=selected_f_ids
                        )
                    # エッジのバッチも再構築
                    preselected_id = getattr(props, "preselected_face_id", "")
                    engine._build_highlight_batches_ext(stack_ptr, set(), preselected_id, set())
                    
                    for window in context.window_manager.windows:
                        for area in window.screen.areas:
                            if area.type == 'VIEW_3D':
                                area.tag_redraw()

        props.primitives.remove(self.index)
        if props.active_primitive_index >= len(props.primitives):
            props.active_primitive_index = max(0, len(props.primitives) - 1)
        update_cad_preview(None, context)
        return {'FINISHED'}

class SEAMLESS_OT_SetActivePrimitive(bpy.types.Operator):
    bl_idname = "seamless.set_active_primitive"
    bl_label = "Set Active Primitive"
    index: bpy.props.IntProperty()
    def execute(self, context):
        # 🌟 オブジェクトモード以外の場合は自動的にオブジェクトモードへ移行してアクティブ変更時の選択エラーを完全防止！
        if context.active_object and context.active_object.mode != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except Exception as e:
                utils.debug_print(f"DEBUG: Mode-set OBJECT error: {e}")

        props = utils.get_active_props(context)
        if not props:
            return {'CANCELLED'}
        props.active_primitive_index = self.index
        
        # プロキシオブジェクトを自動選択
        if 0 <= self.index < len(props.primitives):
            prim = props.primitives[self.index]
            for obj in bpy.data.objects:
                if obj.get("is_seamless_proxy") and obj.get("primitive_uuid") == prim.uuid:
                    # 他の選択を解除して、対象をアクティブ＆選択状態にする
                    bpy.ops.object.select_all(action='DESELECT')
                    context.view_layer.objects.active = obj
                    obj.select_set(True)
                    break
                    
        update_cad_preview(None, context)
        utils.redraw_all_view3d(context)
        return {'FINISHED'}

class SEAMLESS_OT_DuplicatePrimitive(bpy.types.Operator):
    bl_idname = "seamless.duplicate_primitive"
    bl_label = "Duplicate Primitive"
    bl_description = "Duplicate primitive. For GROUP_END, duplicate the whole closed group"
    bl_options = {'REGISTER', 'UNDO'}
    index: bpy.props.IntProperty()

    @classmethod
    def description(cls, context, properties):
        props = utils.get_active_props(context)
        index = getattr(properties, "index", -1)
        if props and 0 <= index < len(props.primitives) and props.primitives[index].type == 'GROUP_END':
            return "Duplicate Group"
        return cls.bl_description

    def execute(self, context):
        def _dlog(msg):
            # 複製の成否を cad_profile.log にも記録(切り分け用・rareなので無ゲート)。
            try:
                from ..core_bridge import _profile_log_line
                _profile_log_line(f"[Duplicate] {msg}")
            except Exception:
                pass

        # 🌟 オブジェクトモード以外の場合は自動的かつ安全にオブジェクトモードへ移行
        if context.active_object and context.active_object.mode != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except Exception as e:
                utils.debug_print(f"DEBUG: Mode-set OBJECT error: {e}")

        props = utils.get_active_props(context)
        col_name = getattr(utils.get_active_collection(context), 'name', '?')
        _dlog(f"execute called index={self.index} col={col_name} prims={len(props.primitives) if props else 'NO_PROPS'}")
        # サイレント失敗の可視化。無反応の切り分け用: 警告が出れば execute は
        # 走って CANCELLED(=アクティブCADコレクションの解決ズレやindex範囲外)、
        # 何も出なければクリック自体が届いていない(直前の配置/選択モーダルが
        # クリックを飲んでいる等)と判別できる。
        if not props:
            _dlog("CANCELLED: no active CAD part resolved")
            self.report({'WARNING'}, "Duplicate: no active CAD part resolved (select the part first)")
            return {'CANCELLED'}
        if self.index < 0 or self.index >= len(props.primitives):
            _dlog(f"CANCELLED: index {self.index} out of range (col={col_name}, {len(props.primitives)} prims)")
            self.report(
                {'WARNING'},
                f"Duplicate: index {self.index} out of range for '{col_name}' "
                f"({len(props.primitives)} prims) — active CAD part may have changed"
            )
            return {'CANCELLED'}

        source = props.primitives[self.index]
        if source.type == 'GROUP_END':
            start_index = _find_group_start_index(props.primitives, self.index)
            if start_index < 0:
                self.report({'WARNING'}, "Matching GROUP_START was not found")
                return {'CANCELLED'}

            serialized = [_serialize_primitive(prim) for prim in props.primitives]
            original_block = serialized[start_index:self.index + 1]
            duplicated_block = []
            uuid_map = {}

            for data in original_block:
                new_data = copy.deepcopy(data)
                uuid_map[data["uuid"]] = str(uuid.uuid4())[:8]
                new_data["name"] = f"{data['name']}_copy"
                new_data["group_selected"] = False
                if new_data["type"] in {'CLEANUP', 'GROUP_START', 'GROUP_END'}:
                    new_data["operation"] = 'ADD'
                    new_data["size"] = [1.0, 1.0, 1.0]
                    new_data["radius"] = 1.0
                    new_data["radius2"] = 1.0
                    new_data["minor_radius"] = 0.25
                    new_data["pipe_radius"] = 0.1
                    new_data["extrude_height"] = 1.0
                elif new_data.get("operation") == 'BASE':
                    new_data["operation"] = 'ADD'
                duplicated_block.append(new_data)

            for source_data, new_data in zip(original_block, duplicated_block):
                new_data["uuid"] = uuid_map[source_data["uuid"]]
                _remap_primitive_links(new_data, uuid_map)

            rebuilt = serialized[:self.index + 1] + duplicated_block + serialized[self.index + 1:]
            _rebuild_primitives(props, rebuilt, self.index + len(duplicated_block))
        else:
            serialized = [_serialize_primitive(prim) for prim in props.primitives]
            rebuilt = serialized + [_build_single_duplicate_data(source, len(props.primitives) + 1)]
            _rebuild_primitives(props, rebuilt, len(rebuilt) - 1)

        # 複製直後は複製プリミティブのプロキシがまだ存在しない。この状態で下の
        # bpy.ops(select_all 等)を呼ぶと depsgraph がフラッシュされ、depsgraph
        # ハンドラの「プロキシの無いプリミティブを削除」掃除(utils.py:1088-1101)が
        # 発火して、追加したばかりの複製が消えてしまう(=たまに複製が効かない真因)。
        # そこで先に sync_proxies で複製のプロキシを生成しておく。プロキシが在れば
        # 以降のフラッシュでも掃除対象にならない。
        utils.sync_proxies(context)

        # Avoid carrying a stale child selection across a structural rebuild.
        try:
            bpy.ops.object.select_all(action='DESELECT')
        except Exception:
            pass
        try:
            context.view_layer.objects.active = None
        except Exception:
            pass

        # Activate the duplicated item (set_active_primitive re-syncs + selects it).
        bpy.ops.seamless.set_active_primitive(index=props.active_primitive_index)

        _dlog(f"OK: duplicated -> now {len(props.primitives)} prims, active={props.active_primitive_index}")
        return {'FINISHED'}

class SEAMLESS_OT_PickActiveAsTarget(bpy.types.Operator):
    bl_idname = "seamless.pick_active_as_target"
    bl_label = "Pick Pattern Target (List)"
    bl_description = "Select target primitive from list"
    bl_options = {'REGISTER', 'UNDO'}
    
    index: bpy.props.IntProperty()
    prop_name: bpy.props.StringProperty(default="target_uuid")
    
    def target_items_callback(self, context):
        props = utils.get_active_props(context)
        items = []
        if not props:
            items.append(("", "No other primitives available", ""))
            return items
        for i, prim in enumerate(props.primitives):
            if i == self.index: continue
            items.append((prim.uuid, prim.name, f"UUID: {prim.uuid}"))
        if not items:
            items.append(("", "No other primitives available", ""))
        return items

    target_uuid_enum: bpy.props.EnumProperty(
        name="Target Primitive",
        items=target_items_callback
    )

    def execute(self, context):
        props = utils.get_active_props(context)
        if not props or self.index < 0 or self.index >= len(props.primitives):
            return {'CANCELLED'}
        prim = props.primitives[self.index]
        
        if self.prop_name == 'loft_uuids':
            current = getattr(prim, "loft_uuids", "")
            if current:
                setattr(prim, "loft_uuids", f"{current}|{self.target_uuid_enum}")
            else:
                setattr(prim, "loft_uuids", self.target_uuid_enum)
        else:
            setattr(prim, self.prop_name, self.target_uuid_enum)
            
        update_cad_preview(None, context)
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

class SEAMLESS_OT_PickTargetModal(bpy.types.Operator):
    bl_idname = "seamless.pick_target_modal"
    bl_label = "Pick Target in Viewport"
    bl_description = "Click a CAD object in the viewport to set as target"
    
    index: bpy.props.IntProperty()
    prop_name: bpy.props.StringProperty(default="target_uuid")

    def modal(self, context, event):
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            # レイキャストによるオブジェクト選択
            from bpy_extras import view3d_utils
            coord = event.mouse_region_x, event.mouse_region_y
            region = context.region
            rv3d = context.region_data
            ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
            ray_direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
            
            has_hit, hit_pos, hit_norm, hit_idx, hit_obj, matrix = context.scene.ray_cast(context.view_layer.depsgraph, ray_origin, ray_direction)
            
            if has_hit and hit_obj and hit_obj.get("is_seamless_proxy"):
                target_uuid = hit_obj.get("primitive_uuid", "")
                if target_uuid:
                    props = utils.get_active_props(context)
                    if props and 0 <= self.index < len(props.primitives):
                        prim = props.primitives[self.index]
                        if prim.uuid != target_uuid: # 自己ターゲット防止
                            final_val = target_uuid

                            # 拡張: SWEEPの場合、FaceやEdgeの取得を試みる
                            if prim.type == 'SWEEP':
                                from ..core_bridge import get_core, is_core_busy, get_or_create_stack_ptr
                                core = get_core()
                                if core and not is_core_busy():
                                    stack_ptr = get_or_create_stack_ptr(utils.get_active_collection(context))
                                    if self.prop_name == 'sweep_profile_uuid' and hasattr(core, "pick_face"):
                                        res = core.pick_face(stack_ptr, list(ray_origin), list(ray_direction), 0.6)
                                        if res:
                                            final_val = res[0] # Face:1@...
                                    elif self.prop_name == 'sweep_path_uuid' and hasattr(core, "pick_edge"):
                                        res = core.pick_edge(stack_ptr, list(ray_origin), list(ray_direction), 0.6)
                                        if res:
                                            final_val = res[0] # Edge:1@...

                            if self.prop_name == 'loft_uuids':
                                current = getattr(prim, "loft_uuids", "")
                                if current:
                                    setattr(prim, "loft_uuids", f"{current}|{final_val}")
                                else:
                                    setattr(prim, "loft_uuids", final_val)
                            else:
                                setattr(prim, self.prop_name, final_val)
                            update_cad_preview(None, context)
                            self.report({'INFO'}, f"Target set to: {final_val}")
                            return {'FINISHED'}

            self.report({'WARNING'}, "No CAD object found under mouse")
            return {'FINISHED'}

        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        context.window_manager.modal_handler_add(self)
        self.report({'INFO'}, "Click a CAD object in viewport to select target")
        return {'RUNNING_MODAL'}

from bpy_extras.io_utils import ImportHelper, ExportHelper

class SEAMLESS_OT_ImportStep(bpy.types.Operator, ImportHelper):
    bl_idname = "seamless.import_step"
    bl_label = "Import STEP (.stp)"
    filename_ext = ".stp"
    filter_glob: bpy.props.StringProperty(default="*.stp;*.step", options={'HIDDEN'})
    import_scale: bpy.props.FloatProperty(
        name="Scale",
        description="Uniform scale applied while importing STEP geometry",
        default=1.0,
        min=1e-6,
        soft_min=0.001,
        soft_max=1000.0,
        precision=6
    )

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.prop(self, "import_scale")
        col.label(text="Examples: 0.001 for mm→m, 1.0 for native scale", icon='INFO')

    def execute(self, context):
        props = utils.get_active_props(context)
        if not props:
            self.report({'WARNING'}, "No active Seamless CAD collection.")
            return {'CANCELLED'}
        
        from ..core_bridge import import_step
        filepath = os.path.abspath(self.filepath)
        import_scale = float(self.import_scale)
        uuids = import_step(filepath, import_scale)
        if not uuids:
            self.report({'WARNING'}, "Failed to import STEP file.")
            return {'CANCELLED'}
        
        for idx, u in enumerate(uuids):
            p = props.primitives.add()
            p.type = 'STEP_PART'
            p.operation = 'ADD' if len(props.primitives) > 1 else 'BASE'
            p.uuid = str(uuid.uuid4())[:8]
            p.target_uuid = u
            p.size = (import_scale, import_scale, import_scale)
            p.step_scale = import_scale
            p.step_source_path = filepath
            p.step_source_index = idx
            p.name = f"STEP Part {u}"
            
        update_cad_preview(None, context)
        return {'FINISHED'}

class SEAMLESS_OT_ImportSvg(bpy.types.Operator, ImportHelper):
    bl_idname = "seamless.import_svg"
    bl_label = "Import SVG (.svg)"
    filename_ext = ".svg"
    filter_glob: bpy.props.StringProperty(default="*.svg", options={'HIDDEN'})
    import_scale: bpy.props.FloatProperty(
        name="Scale",
        description="Uniform scale applied while importing SVG geometry",
        default=1.0,
        min=1e-6,
        soft_min=0.001,
        soft_max=1000.0,
        precision=6
    )

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.prop(self, "import_scale")

    def execute(self, context):
        props = utils.get_active_props(context)
        if not props:
            self.report({'WARNING'}, "No active Seamless CAD collection.")
            return {'CANCELLED'}
        
        from ..core_bridge import import_svg
        filepath = os.path.abspath(self.filepath)
        import_scale = float(self.import_scale)
        uuids = import_svg(filepath, import_scale)
        if not uuids:
            self.report({'WARNING'}, "Failed to import SVG file. Check system console for details.")
            return {'CANCELLED'}
        
        for idx, u in enumerate(uuids):
            p = props.primitives.add()
            p.type = 'SVG_PART'
            p.operation = 'ADD' if len(props.primitives) > 1 else 'BASE'
            p.uuid = str(uuid.uuid4())[:8]
            p.target_uuid = u
            p.size = (import_scale, import_scale, import_scale)
            p.step_scale = import_scale
            p.step_source_path = filepath
            p.step_source_index = idx
            p.name = f"SVG Part {idx + 1}"
            p.fill_closed = True
            
        update_cad_preview(None, context)
        return {'FINISHED'}

class SEAMLESS_OT_ExportStep(bpy.types.Operator, ExportHelper):
    bl_idname = "seamless.export_step"
    bl_label = "Export STEP (.stp)"
    filename_ext = ".stp"
    filter_glob: bpy.props.StringProperty(default="*.stp;*.step", options={'HIDDEN'})

    def execute(self, context):
        props = utils.get_active_props(context)
        if not props:
            self.report({'WARNING'}, "No active Seamless CAD collection.")
            return {'CANCELLED'}
            
        from ..core_bridge import export_stack_to_step, get_or_create_stack_ptr
        col = utils.get_active_collection(context)
        stack_ptr = get_or_create_stack_ptr(col)
        
        success = export_stack_to_step(stack_ptr, self.filepath)
        if success:
            self.report({'INFO'}, f"Successfully exported to {self.filepath}")
            return {'FINISHED'}
        else:
            self.report({'ERROR'}, "Failed to export STEP file.")
            return {'CANCELLED'}

class SEAMLESS_OT_SeparateByBase(bpy.types.Operator):
    bl_idname = "seamless.separate_by_base"
    bl_label = "Separate Previous to New Part"
    bl_description = "Move or Copy all primitives above this one into a new CAD collection"
    bl_options = {'REGISTER', 'UNDO'}
    index: bpy.props.IntProperty()
    
    mode: bpy.props.EnumProperty(
        name="Action Mode",
        description="Choose whether to Move (delete from original) or Copy (keep in original) the previous primitives",
        items=[
            ('MOVE', "Move (Clean up original)", "Move primitives to new part and delete from original stack (May break target references)"),
            ('COPY', "Copy (Keep references)", "Copy primitives to new part and keep them in original stack (Safe for references)"),
        ],
        default='MOVE'
    )
    
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=400)
    
    def draw(self, context):
        layout = self.layout
        layout.label(text="How would you like to separate?", icon='QUESTION')
        layout.prop(self, "mode", expand=True)
        if self.mode == 'MOVE':
            layout.label(text="Warning: Moving will delete past primitives from the current stack.", icon='ERROR')
            layout.label(text="If any modifiers depend on them (e.g. Target Face), they will break.", icon='INFO')
        else:
            layout.label(text="Safe: Past primitives will remain in the current stack as history.", icon='INFO')

    def execute(self, context):
        from ..utils import set_updating_flag, get_active_collection, get_active_props
        current_col = get_active_collection(context)
        props = get_active_props(context)
        if not props or not current_col:
            return {'CANCELLED'}
            
        if self.index <= 0 or self.index >= len(props.primitives):
            self.report({'WARNING'}, "Cannot separate at this index.")
            return {'CANCELLED'}
            
        # 1. 新しいコレクションを作成
        mode_suffix = "_Part_Copied" if self.mode == 'COPY' else "_Part"
        new_col_name = current_col.name + mode_suffix
        new_col = bpy.data.collections.new(new_col_name)
        
        # Seamless_CAD コレクションを親にする（UIのリストに表示させるため）
        parent_col = bpy.data.collections.get("Seamless_CAD")
        if parent_col:
            parent_col.children.link(new_col)
        else:
            context.scene.collection.children.link(new_col)
        
        # 2. プロパティのコピー（新しいコレクションへ）
        new_props = getattr(new_col, "seamless_props", None)
        if not new_props:
            self.report({'ERROR'}, "Failed to access seamless_props property on new collection.")
            return {'CANCELLED'}
            
        set_updating_flag(True)
        try:
            uuid_map = {}
            import uuid
            
            for i in range(self.index):
                source = props.primitives[i]
                new_item = new_props.primitives.add()
                new_item.name = source.name
                new_item.type = source.type
                new_item.operation = source.operation
                new_item.location = source.location[:]
                new_item.rotation = source.rotation[:]
                new_item.size = source.size[:]
                new_item.radius = source.radius
                new_item.radius2 = source.radius2
                new_item.minor_radius = source.minor_radius
                new_item.pipe_radius = source.pipe_radius
                new_item.extrude_height = source.extrude_height
                new_item.fill_closed = source.fill_closed
                new_item.use_pipe = source.use_pipe
                new_item.sides = source.sides
                new_item.module = source.module
                new_item.pressure_angle = source.pressure_angle
                new_item.top_shape = source.top_shape
                new_item.bot_shape = source.bot_shape
                new_item.target_uuid = source.target_uuid
                new_item.target_lineages = source.target_lineages
                new_item.reference_lineage = source.reference_lineage
                if hasattr(new_item, 'edge_ref_snapshot'):
                    new_item.edge_ref_snapshot = getattr(source, 'edge_ref_snapshot', '')
                if hasattr(new_item, 'reference_ref_snapshot'):
                    new_item.reference_ref_snapshot = getattr(source, 'reference_ref_snapshot', '')
                new_item.count = source.count
                new_item.distance = source.distance
                new_item.pattern_axis = source.pattern_axis
                new_item.angle_start = source.angle_start
                new_item.angle_end = source.angle_end
                
                if self.mode == 'COPY':
                    new_uuid = str(uuid.uuid4())
                    uuid_map[source.uuid] = new_uuid
                    new_item.uuid = new_uuid
                else:
                    new_item.uuid = source.uuid  # MOVEならそのまま引き継ぐ
                
                for pt in source.points:
                    new_pt = new_item.points.add()
                    new_pt.co = pt.co[:]
            
            # 内部リンクの再接続（UUIDの置換）
            if self.mode == 'COPY':
                for new_item in new_props.primitives:
                    for old_u, new_u in uuid_map.items():
                        if new_item.target_uuid == old_u:
                            new_item.target_uuid = new_u
                        if new_item.sweep_path_uuid == old_u:
                            new_item.sweep_path_uuid = new_u
                        if new_item.sweep_profile_uuid == old_u:
                            new_item.sweep_profile_uuid = new_u
                        
                        if old_u in new_item.target_lineages:
                            new_item.target_lineages = new_item.target_lineages.replace(old_u, new_u)
                        if old_u in new_item.reference_lineage:
                            new_item.reference_lineage = new_item.reference_lineage.replace(old_u, new_u)
                        if old_u in new_item.loft_uuids:
                            new_item.loft_uuids = new_item.loft_uuids.replace(old_u, new_u)
                        # V8.0.1: edge_ref_snapshot内のUUIDも置換
                        if hasattr(new_item, 'edge_ref_snapshot') and old_u in new_item.edge_ref_snapshot:
                            new_item.edge_ref_snapshot = new_item.edge_ref_snapshot.replace(old_u, new_u)
                        if hasattr(new_item, 'reference_ref_snapshot') and old_u in new_item.reference_ref_snapshot:
                            new_item.reference_ref_snapshot = new_item.reference_ref_snapshot.replace(old_u, new_u)
            
            # 3. 元のコレクションからの削除処理（MOVEの場合のみ）
            if self.mode == 'MOVE':
                for _ in range(self.index):
                    props.primitives.remove(0)
                props.active_primitive_index = 0
                
            new_props.active_primitive_index = len(new_props.primitives) - 1
        finally:
            set_updating_flag(False)
            
        # 4. 更新処理
        update_cad_preview(None, context)
        
        # 新しいコレクションをアクティブにしてプレビュー生成を促す
        prev_active = context.scene.active_cad_collection
        context.scene.active_cad_collection = new_col
        update_cad_preview(None, context)
        context.scene.active_cad_collection = prev_active
        
        action_name = "Copied" if self.mode == 'COPY' else "Separated/Moved"
        self.report({'INFO'}, f"{action_name} previous items to {new_col_name}")
        return {'FINISHED'}

class SEAMLESS_OT_SetRollbackIndex(bpy.types.Operator):
    bl_idname = "seamless.set_rollback_index"
    bl_label = "Set Rollback Index"
    bl_description = "Stop calculation at this primitive (Rollback)"
    bl_options = {'REGISTER', 'UNDO'}
    
    index: bpy.props.IntProperty()
    
    def execute(self, context):
        from ..utils import get_active_props
        props = get_active_props(context)
        if not props:
            return {'CANCELLED'}
            
        if props.rollback_index == self.index:
            # 既にセットされている場合は解除
            props.rollback_index = -1
        else:
            props.rollback_index = self.index
            
        # 選択状態を解除して再描画（UIの一貫性のため）
        props.selected_edges_str = ""
        props.selected_faces_str = ""

        return {'FINISHED'}


class SEAMLESS_OT_ForceRecompute(bpy.types.Operator):
    """プレビューが古い/壊れたジオメトリのまま固まって見えるときの手動リカバリ用。
    _rebuild_face_batch (drawing.py) は無効な面データを受け取ると直前の面バッチを
    意図的に保持する(チラつき防止)ため、Cleanup等の重い計算が失敗/停滞すると
    無関係な古い形状が残り続けることがある。ここではキャッシュされた面/エッジ
    バッチを明示的に破棄してから強制再計算し、古い残留物ごとクリアする。"""
    bl_idname = "seamless.force_recompute"
    bl_label = "Recompute"
    bl_description = "Clear the cached preview and force a full recompute (use if the shaded preview looks stuck or wrong)"
    bl_options = {'REGISTER'}

    def execute(self, context):
        from ..core_bridge import update_cad_preview_forced
        col = utils.get_active_collection(context)
        if col:
            try:
                stack_ptr = int(getattr(col, "seamless_cad_stack_ptr", "0"))
            except (ValueError, TypeError):
                stack_ptr = 0
            if stack_ptr:
                get_wireframe_engine().clear(stack_ptr)
        update_cad_preview_forced(context)
        utils.redraw_all_view3d(context)
        self.report({'INFO'}, "Recomputed")
        return {'FINISHED'}


class SEAMLESS_OT_EditSketch(bpy.types.Operator):
    """V8.1.5: スケッチ編集履歴 - 確定済みスケッチ由来のprimitiveを選び直し、元のスケッチ
    (点・線・拘束)をスケッチスナップショットから復元してスケッチモーダルを再度開く。
    Apply時にはfinalize_sketch_edit_inplace経由でin-place更新され、下流の
    REVOLVE/EXTRUDE等は自動的に新しいジオメトリへ追従する。"""
    bl_idname = "seamless.edit_sketch"
    bl_label = "Edit Sketch"
    bl_description = "Re-open the source sketch of this feature for editing"
    bl_options = {'REGISTER', 'UNDO'}

    prim_index: bpy.props.IntProperty()

    def execute(self, context):
        from ..utils import get_active_props
        props = get_active_props(context)
        if not props or not (0 <= self.prim_index < len(props.primitives)):
            return {'CANCELLED'}
        prim = props.primitives[self.prim_index]
        sketch_uuid = getattr(prim, "sketch_source_uuid", "")
        if not sketch_uuid:
            self.report({'WARNING'}, "This feature has no editable sketch source (created before V8.1.5?).")
            return {'CANCELLED'}
        # rollback中でこのprimitiveが非表示範囲にある場合、隠れた下流を編集させない
        if 0 <= props.rollback_index < self.prim_index:
            self.report({'WARNING'}, "Cannot edit a sketch hidden by the current rollback point.")
            return {'CANCELLED'}
        if props.is_sketch_active:
            self.report({'WARNING'}, "Finish or cancel the current sketch first.")
            return {'CANCELLED'}

        from ..sketch.sketch_snapshot import restore_sketch_snapshot
        if not restore_sketch_snapshot(props, sketch_uuid):
            self.report({'WARNING'}, "Sketch snapshot not found (created before V8.1.5?).")
            return {'CANCELLED'}

        from ..sketch import sketch_globals
        sketch_globals._history_stack = []
        sketch_globals._arc_points = []
        sketch_globals._circle_points = []
        sketch_globals._semicircle_points = []
        sketch_globals._rectangle_points = []

        props.sketch_editing_uuid = sketch_uuid
        props.is_sketch_active = True
        props.sketch_pen_mode = 'SELECT'
        bpy.ops.seamless.sketch_draw_tool('INVOKE_DEFAULT')
        return {'FINISHED'}


class SEAMLESS_OT_ToggleFilletEdgeDefault(bpy.types.Operator):
    """V8.1.5: 可変フィレット - 指定エッジの半径を「親のradiusに従う(-1)」と
    「個別指定」の間でトグルする。個別指定に切り替えた際は現在の親radiusを初期値にする。"""
    bl_idname = "seamless.toggle_fillet_edge_default"
    bl_label = "Toggle Fillet Edge Default Radius"
    bl_description = "Toggle between using the primitive's default radius and a custom per-edge radius"
    bl_options = {'REGISTER', 'UNDO'}

    prim_index: bpy.props.IntProperty()
    edge_index: bpy.props.IntProperty()

    def execute(self, context):
        from ..utils import get_active_props
        props = get_active_props(context)
        if not props or not (0 <= self.prim_index < len(props.primitives)):
            return {'CANCELLED'}
        prim = props.primitives[self.prim_index]
        if not (0 <= self.edge_index < len(prim.edge_radii)):
            return {'CANCELLED'}
        er = prim.edge_radii[self.edge_index]
        if er.radius < 0.0:
            er.radius = prim.radius
        else:
            er.radius = -1.0
        return {'FINISHED'}

class SEAMLESS_OT_GroupSelection(bpy.types.Operator):
    bl_idname = "seamless.group_selection"
    bl_label = "Group Selection"
    bl_description = "Wrap the checked contiguous range with GROUP_START and GROUP_END"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = utils.get_active_props(context)
        if not props or not props.primitives:
            return {'CANCELLED'}

        selected_indices = [i for i, prim in enumerate(props.primitives) if getattr(prim, "group_selected", False)]
        if len(selected_indices) < 2:
            self.report({'WARNING'}, "Select at least 2 consecutive items for grouping")
            return {'CANCELLED'}

        start_idx = min(selected_indices)
        end_idx = max(selected_indices)
        expected_range = list(range(start_idx, end_idx + 1))
        if selected_indices != expected_range:
            self.report({'WARNING'}, "Group selection must be a contiguous range")
            return {'CANCELLED'}

        nesting = 0
        for i, prim in enumerate(props.primitives):
            if prim.type == 'GROUP_END':
                nesting = max(0, nesting - 1)
            inside = start_idx <= i <= end_idx
            if inside and ((i == start_idx and nesting > 0) or (i == end_idx and prim.type == 'GROUP_START')):
                self.report({'WARNING'}, "Crossing an existing group boundary is not supported")
                return {'CANCELLED'}
            if prim.type == 'GROUP_START':
                nesting += 1

        selected_uuid_set = {props.primitives[i].uuid for i in selected_indices}
        warning_count = 0
        for i in selected_indices:
            prim = props.primitives[i]
            target_uuid = prim.target_uuid.strip()
            sweep_path_uuid = getattr(prim, "sweep_path_uuid", "").strip()
            sweep_profile_uuid = getattr(prim, "sweep_profile_uuid", "").strip()
            loft_uuids = [u.strip() for u in getattr(prim, "loft_uuids", "").split("|") if u.strip()]
            refs = [target_uuid, sweep_path_uuid, sweep_profile_uuid, *loft_uuids]
            if any(u and u not in selected_uuid_set for u in refs):
                warning_count += 1

        serialized = [_serialize_primitive(prim) for prim in props.primitives]
        group_start = _serialize_primitive(props.primitives[start_idx])
        group_start.update({
            "name": f"{start_idx}_GROUP_START",
            "uuid": str(uuid.uuid4())[:8],
            "type": "GROUP_START",
            "operation": "ADD",
            "size": [1.0, 1.0, 1.0],
            "radius": 1.0,
            "radius2": 1.0,
            "minor_radius": 0.25,
            "pipe_radius": 0.1,
            "extrude_height": 1.0,
            "target_uuid": "",
            "target_lineages": "",
            "reference_lineage": "",
            "edge_ref_snapshot": "",
            "reference_ref_snapshot": "",
            "sweep_path_uuid": "",
            "sweep_profile_uuid": "",
            "loft_uuids": "",
            "group_selected": False,
            "points": [],
        })
        group_end = _serialize_primitive(props.primitives[end_idx])
        group_end.update({
            "name": f"{end_idx + 2}_GROUP_END",
            "uuid": str(uuid.uuid4())[:8],
            "type": "GROUP_END",
            "operation": "ADD",
            "size": [1.0, 1.0, 1.0],
            "radius": 1.0,
            "radius2": 1.0,
            "minor_radius": 0.25,
            "pipe_radius": 0.1,
            "extrude_height": 1.0,
            "target_uuid": "",
            "target_lineages": "",
            "reference_lineage": "",
            "edge_ref_snapshot": "",
            "reference_ref_snapshot": "",
            "sweep_path_uuid": "",
            "sweep_profile_uuid": "",
            "loft_uuids": "",
            "group_selected": False,
            "points": [],
        })

        for data in serialized:
            data["group_selected"] = False

        rebuilt = serialized[:start_idx] + [group_start] + serialized[start_idx:end_idx + 1] + [group_end] + serialized[end_idx + 1:]

        from ..utils import set_updating_flag
        set_updating_flag(True)
        try:
            while props.primitives:
                props.primitives.remove(len(props.primitives) - 1)
            for data in rebuilt:
                item = props.primitives.add()
                _apply_primitive_data(item, data)
            props.active_primitive_index = min(len(props.primitives) - 1, end_idx + 2)
        finally:
            set_updating_flag(False)

        update_cad_preview(None, context)
        utils.sync_proxies(context)

        if warning_count:
            self.report({'WARNING'}, f"Grouped selection with {warning_count} external dependency reference(s)")
        else:
            self.report({'INFO'}, "Grouped selection")
        return {'FINISHED'}
