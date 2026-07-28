import bpy
import math
import mathutils

# これらは register 時に ui_preferences._apply_log_preferences() が
# アドオン設定の値で上書きする。ここの既定値は「設定が取れなかったときに
# 効いてしまう値」なので、Preferences 側の既定と必ず一致させること。
# 特に ENABLE_PERF_LOGGING が True で残ると、プレビュー1回ごとに
# stdout 20行 + プロファイルログへの同期書き込みが走りメインスレッドを止める。
DEBUG_LOGS = False
INFO_LOGS = False
WARN_LOGS = False
ERROR_LOGS = True
USE_WGPU_OVERLAY = True
ENABLE_PERF_LOGGING = False

def debug_print(*args, **kwargs):
    if DEBUG_LOGS:
        print(*args, **kwargs)

def info_print(*args, **kwargs):
    if INFO_LOGS:
        print(*args, **kwargs)

def warn_print(*args, **kwargs):
    if WARN_LOGS:
        print(*args, **kwargs)

def error_print(*args, **kwargs):
    if ERROR_LOGS:
        print(*args, **kwargs)

_is_updating_proxies = False
_was_transform_modal = False
_last_change_time = 0.0
_last_update_render_time = 0.0
_last_fast_preview_by_col = {}
_pending_step_scales = {}
_registered_cad_collections = set()

# --- Interactive CSG (subtract) preview state, keyed by collection name ---
# When dragging an eligible SUBtract tool, we show a real-time mesh-boolean
# preview (pure-Rust BSP CSG on OCC-tessellated meshes) instead of the frozen
# result. Falls back to freeze if begin fails or the tool is ineligible.
_csg_preview_state = {}          # col_name -> {"stack_ptr", "tool_index", "tool_uuid", "init_mat", "last_t"}
_CSG_PREVIEW_TOOL_TYPES = {'BOX', 'CYLINDER', 'SPHERE', 'CONE', 'TORUS', 'POLYGON', 'SLOT', 'GEAR'}
_CSG_PREVIEW_OPS = {'SUB', 'SUBTRACT', 'ADD', 'UNION', 'FUSE', 'INT', 'INTERSECT', 'COMMON'}
_CSG_PREVIEW_INTERVAL = 1.0 / 30.0  # throttle live updates to ~30 fps

def _is_live_cad_collection(col):
    return bool(col and hasattr(col, "seamless_props") and getattr(col, "seamless_cad_stack_ptr", "0") != "0")

def _register_cad_collection(col):
    global _registered_cad_collections
    if _is_live_cad_collection(col):
        _registered_cad_collections.add(col.name)

def _get_registered_cad_cols():
    global _registered_cad_collections
    if not _registered_cad_collections:
        for col in bpy.data.collections:
            if _is_live_cad_collection(col):
                _registered_cad_collections.add(col.name)

    cad_cols = []
    for name in list(_registered_cad_collections):
        col = bpy.data.collections.get(name)
        if _is_live_cad_collection(col):
            cad_cols.append(col)
        else:
            _registered_cad_collections.discard(name)
    return cad_cols

def _find_proxy_cad_collection(obj):
    if not obj:
        return None
    for col in obj.users_collection:
        if _is_live_cad_collection(col):
            return col
    return None

def _is_other_live_cad_proxy_owner(obj, proxy_col):
    for col in obj.users_collection:
        if col != proxy_col and _is_live_cad_collection(col):
            return True
    return False

def _build_proxy_maps(proxy_col):
    all_proxies = [obj for obj in proxy_col.all_objects if obj.get("is_seamless_proxy")]
    proxy_map = {}
    for obj in all_proxies:
        p_uuid = obj.get("primitive_uuid")
        if p_uuid and p_uuid not in proxy_map:
            proxy_map[p_uuid] = obj
    return all_proxies, proxy_map

def _build_proxy_map_for_cols(cols):
    proxy_map = {}
    for col in cols:
        if not _is_live_cad_collection(col):
            continue
        for obj in col.all_objects:
            if not obj.get("is_seamless_proxy"):
                continue
            p_uuid = obj.get("primitive_uuid")
            if p_uuid and p_uuid not in proxy_map:
                proxy_map[p_uuid] = obj
    return proxy_map

def _backfill_missing_proxy_map(proxy_col, missing_uuids, proxy_map, all_proxies):
    if not missing_uuids:
        return
    remaining = set(missing_uuids)
    for obj in bpy.data.objects:
        if not remaining:
            break
        if not obj.get("is_seamless_proxy"):
            continue
        if _is_other_live_cad_proxy_owner(obj, proxy_col):
            continue
        p_uuid = obj.get("primitive_uuid")
        if p_uuid in remaining and p_uuid not in proxy_map:
            proxy_map[p_uuid] = obj
            all_proxies.append(obj)
            remaining.discard(p_uuid)

def _collect_closed_groups(primitives):
    closed_groups = []
    group_stack = []
    for prim in primitives:
        for frame in group_stack:
            frame["member_uuids"].add(prim.uuid)

        if prim.type == 'GROUP_START':
            group_stack.append({
                "start_uuid": prim.uuid,
                "member_uuids": {prim.uuid},
            })
        elif prim.type == 'GROUP_END' and group_stack:
            frame = group_stack.pop()
            frame["end_uuid"] = prim.uuid
            closed_groups.append(frame)
    return closed_groups

def _build_expected_parent_uuids(primitives, proxies):
    expected_parent_uuids = {}

    for prim in primitives:
        modifier_obj = proxies.get(prim.uuid)
        target_uuid = prim.target_uuid.strip()
        target_obj = proxies.get(target_uuid)
        if not (modifier_obj and target_obj and target_uuid):
            continue
        if prim.type == "INSTANCE":
            continue

        curr = modifier_obj.parent
        is_desc = False
        while curr:
            if curr == target_obj:
                is_desc = True
                break
            curr = curr.parent
        if is_desc or modifier_obj == target_obj:
            continue

        expected_parent_uuids[target_uuid] = prim.uuid

    for frame in _collect_closed_groups(primitives):
        end_uuid = frame.get("end_uuid")
        if end_uuid not in proxies:
            continue
        member_uuids = frame.get("member_uuids", set())
        for member_uuid in member_uuids:
            if member_uuid == end_uuid or member_uuid not in proxies:
                continue
            parent_uuid = expected_parent_uuids.get(member_uuid)
            if parent_uuid and parent_uuid in member_uuids:
                continue
            expected_parent_uuids[member_uuid] = end_uuid

    return expected_parent_uuids

def _apply_expected_parent_uuids(expected_parent_uuids, proxies):
    global _is_updating_proxies

    for child_uuid, obj in proxies.items():
        expected_parent_uuid = expected_parent_uuids.get(child_uuid, "")
        expected_parent = proxies.get(expected_parent_uuid) if expected_parent_uuid else None

        if expected_parent:
            if obj.parent != expected_parent:
                _is_updating_proxies = True
                try:
                    world_mtx = obj.matrix_world.copy()
                    obj.parent = expected_parent
                    obj.matrix_parent_inverse = expected_parent.matrix_world.inverted()
                    obj.matrix_world = world_mtx
                finally:
                    _is_updating_proxies = False
        else:
            if obj.parent and obj.parent.get("is_seamless_proxy"):
                _is_updating_proxies = True
                try:
                    world_mtx = obj.matrix_world.copy()
                    obj.parent = None
                    obj.matrix_world = world_mtx
                finally:
                    _is_updating_proxies = False

def _get_prim_display_scale(prim):
    prim_type = getattr(prim, "type", "")
    if prim_type in {'CURVE', 'SURFACE'}:
        size_to_use = [0.001, 0.001, 0.001]
    elif prim_type in {'CLEANUP'}:
        size_to_use = [1.0, 1.0, 1.0]
    else:
        size_to_use = list(prim.size)

    size_to_use = [max(0.001, float(s)) for s in size_to_use]
    return mathutils.Vector(size_to_use)

def _build_box_proxy_mesh():
    verts = [
        (-0.5, -0.5, -0.5), (0.5, -0.5, -0.5), (0.5, 0.5, -0.5), (-0.5, 0.5, -0.5),
        (-0.5, -0.5, 0.5), (0.5, -0.5, 0.5), (0.5, 0.5, 0.5), (-0.5, 0.5, 0.5),
    ]
    faces = [(0, 1, 2, 3), (4, 5, 6, 7), (0, 4, 7, 3), (1, 5, 6, 2), (0, 1, 5, 4), (3, 2, 6, 7)]
    return verts, faces

def _build_cylinder_proxy_mesh(segments=20):
    verts = []
    top = []
    bottom = []
    for i in range(segments):
        ang = (math.pi * 2.0 * i) / segments
        x = math.cos(ang) * 0.5
        y = math.sin(ang) * 0.5
        bottom.append(len(verts))
        verts.append((x, y, -0.5))
        top.append(len(verts))
        verts.append((x, y, 0.5))

    faces = [tuple(bottom), tuple(reversed(top))]
    for i in range(segments):
        n = (i + 1) % segments
        faces.append((bottom[i], bottom[n], top[n], top[i]))
    return verts, faces

def _build_cone_proxy_mesh(segments=20):
    verts = []
    base = []
    for i in range(segments):
        ang = (math.pi * 2.0 * i) / segments
        x = math.cos(ang) * 0.5
        y = math.sin(ang) * 0.5
        base.append(len(verts))
        verts.append((x, y, -0.5))
    apex_idx = len(verts)
    verts.append((0.0, 0.0, 0.5))

    faces = [tuple(base)]
    for i in range(segments):
        n = (i + 1) % segments
        faces.append((base[i], base[n], apex_idx))
    return verts, faces

def _build_sphere_proxy_mesh(rings=8, segments=16):
    verts = []
    faces = []
    for r in range(rings + 1):
        phi = math.pi * r / rings
        z = math.cos(phi) * 0.5
        radius = math.sin(phi) * 0.5
        for s in range(segments):
            ang = (math.pi * 2.0 * s) / segments
            x = math.cos(ang) * radius
            y = math.sin(ang) * radius
            verts.append((x, y, z))

    for r in range(rings):
        for s in range(segments):
            sn = (s + 1) % segments
            a = r * segments + s
            b = r * segments + sn
            c = (r + 1) * segments + sn
            d = (r + 1) * segments + s
            if r == 0:
                faces.append((a, c, d))
            elif r == rings - 1:
                faces.append((a, b, d))
            else:
                faces.append((a, b, c, d))
    return verts, faces

def _get_proxy_mesh_data(prim):
    prim_type = getattr(prim, "type", "")
    if prim_type in {'CYLINDER', 'PIPE'}:
        return _build_cylinder_proxy_mesh(), prim_type
    if prim_type == 'CONE':
        return _build_cone_proxy_mesh(), prim_type
    if prim_type in {'SPHERE', 'TORUS'}:
        return _build_sphere_proxy_mesh(), prim_type
    return _build_box_proxy_mesh(), prim_type

def _sync_proxy_mesh_geometry(obj, prim):
    mesh = getattr(obj, "data", None)
    if mesh is None:
        return

    (verts, faces), shape_key = _get_proxy_mesh_data(prim)
    signature = f"{shape_key}:{len(verts)}:{len(faces)}"
    if obj.get("proxy_mesh_signature") == signature:
        return

    if hasattr(mesh, "clear_geometry"):
        mesh.clear_geometry()
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj["proxy_mesh_signature"] = signature

def _compose_prim_world_matrix(prim):
    return (
        mathutils.Matrix.Translation(prim.location) @
        mathutils.Euler(prim.rotation).to_matrix().to_4x4() @
        mathutils.Matrix.Diagonal(_get_prim_display_scale(prim)).to_4x4()
    )

def _get_group_parent_prim(obj, uuid_to_prim):
    if not obj or not obj.parent or not obj.parent.get("is_seamless_proxy"):
        return None
    parent_uuid = obj.parent.get("primitive_uuid", "")
    parent_prim = uuid_to_prim.get(parent_uuid)
    if parent_prim and parent_prim.type == 'GROUP_END':
        return parent_prim
    return None

def _normalize_uniform_scale(scale):
    try:
        scale = float(scale)
    except Exception:
        scale = 1.0
    return max(scale, 1e-6)

def _extract_uniform_scale(world_scale):
    vals = [abs(float(v)) for v in world_scale]
    vals = [max(v, 1e-6) for v in vals]
    return sum(vals) / len(vals) if vals else 1.0

def _set_step_part_uniform_scale(prim, scale):
    scale = _normalize_uniform_scale(scale)
    uniform = (scale, scale, scale)
    changed = False
    if tuple(prim.size) != uniform:
        prim.size = uniform
        changed = True
    if abs(float(getattr(prim, "step_scale", 1.0)) - scale) > 1e-9:
        prim.step_scale = scale
        changed = True
    return changed

def _commit_pending_step_scales(cad_cols):
    global _pending_step_scales, _is_updating_proxies
    changed_cols = set()
    if not _pending_step_scales:
        return changed_cols
    previous_updating = _is_updating_proxies
    _is_updating_proxies = True
    try:
        for col in cad_cols:
            props = getattr(col, "seamless_props", None)
            if not props:
                continue
            col_changed = False
            for prim in props.primitives:
                pending_key = (col.name, prim.uuid)
                pending_scale = _pending_step_scales.pop(pending_key, None)
                if pending_scale is None or prim.type not in ('STEP_PART', 'SVG_PART'):
                    continue
                if _set_step_part_uniform_scale(prim, pending_scale):
                    col_changed = True
            if col_changed:
                changed_cols.add(col)
    finally:
        _is_updating_proxies = previous_updating
    return changed_cols

def _collection_has_instance(col):
    props = getattr(col, "seamless_props", None)
    if not props:
        return False
    for prim in props.primitives:
        if prim.type == 'INSTANCE':
            return True
    return False

def _should_issue_fast_preview(col, is_transform_modal=False, has_instance=False, transform_kind=""):
    import time
    now = time.time()
    col_name = getattr(col, "name", "")
    last_t = _last_fast_preview_by_col.get(col_name, 0.0)
    is_translate = ("TRANSLATE" in transform_kind) or ("TRANSLATION" in transform_kind) or ("MOVE" in transform_kind)
    if is_transform_modal:
        if has_instance:
            min_interval = 0.12 if is_translate else 0.14
        else:
            min_interval = 0.08 if is_translate else 0.10
    else:
        min_interval = 0.12 if has_instance else 0.08
    if (now - last_t) < min_interval:
        return False
    _last_fast_preview_by_col[col_name] = now
    return True

def get_active_collection(context):
    """Return the active CAD collection, preferring the UI-selected one."""
    if hasattr(context.scene, "active_cad_collection") and context.scene.active_cad_collection:
        return context.scene.active_cad_collection
        
    if context.active_object:
        cols = context.active_object.users_collection
        if cols:
            return cols[0]
            
    if context.view_layer.active_layer_collection:
        return context.view_layer.active_layer_collection.collection
        
    return context.scene.collection

def get_active_props(context):
    """Return Seamless properties for the active CAD collection."""
    col = get_active_collection(context)
    if col and hasattr(col, "seamless_props"):
        return col.seamless_props
    return None

def get_active_stack_ptr(context):
    """Return the CAD stack pointer for the active CAD collection."""
    col = get_active_collection(context)
    if col and hasattr(col, "seamless_cad_stack_ptr"):
        return col.seamless_cad_stack_ptr
    return "0"

def set_updating_flag(val):
    global _is_updating_proxies
    _is_updating_proxies = val

def redraw_all_view3d(context):
    """Tag redraw for every VIEW_3D area across all windows."""
    if not context:
        return
    wm = getattr(context, "window_manager", None)
    if not wm:
        return
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()

_active_object_msgbus_owner = object()

def _on_active_object_changed():
    """msgbus通知コールバック: 選択のみでdepsgraphが更新されないケースでも
    Feature TreeのSelection表示を即座に追従させる。"""
    if sync_active_primitive_from_active_object():
        redraw_all_view3d(bpy.context)

def subscribe_active_object_msgbus():
    """view_layer.objects.active の変更をmsgbusで購読する。
    load_post(ファイル読み込み)のたびに購読がクリアされるため再購読が必要。
    二重購読(=通知が複数回発火)を避けるため、購読前に自分のownerを必ずクリアして
    冪等にする。"""
    bpy.msgbus.clear_by_owner(_active_object_msgbus_owner)
    bpy.msgbus.subscribe_rna(
        key=(bpy.types.LayerObjects, "active"),
        owner=_active_object_msgbus_owner,
        args=(),
        notify=_on_active_object_changed,
    )

def unsubscribe_active_object_msgbus():
    bpy.msgbus.clear_by_owner(_active_object_msgbus_owner)

def sync_proxies(context, props=None, collection_name=None, apply_parenting=True):
    global _is_updating_proxies
    if _is_updating_proxies: return
    
    _is_updating_proxies = True
    try:
        if props is None:
            props = get_active_props(context)
        if not props:
            return
        import uuid
        for prim in props.primitives:
            if not prim.uuid:
                prim.uuid = str(uuid.uuid4())[:8]
        uuid_to_prim = {prim.uuid: prim for prim in props.primitives if prim.uuid}
        
        # 1. プロキシを置く CAD コレクションを決める
        proxy_col = bpy.data.collections.get(collection_name) if collection_name else get_active_collection(context)
        if not proxy_col:
            return
        _register_cad_collection(proxy_col)
            
        # 2. 既存プロキシを uuid -> オブジェクト で引けるようにする
        all_proxies, proxy_map = _build_proxy_maps(proxy_col)
        
        # プロキシが足りない場合は、コレクションからリンクが外れたものを全走査で拾い直す
        if len(all_proxies) < len(props.primitives):
            for obj in bpy.data.objects:
                if obj.get("is_seamless_proxy"):
                    # 他の生きている CAD コレクションが持つプロキシは対象外(下で判定する)
                    is_other_cad = False
                    for c in obj.users_collection:
                        if c != proxy_col and hasattr(c, "seamless_props") and getattr(c, "seamless_cad_stack_ptr", "0") != "0":
                            is_other_cad = True
                            break
                    if not is_other_cad and obj not in all_proxies:
                        all_proxies.append(obj)
                        p_uuid = obj.get("primitive_uuid")
                        if p_uuid and p_uuid not in proxy_map:
                            proxy_map[p_uuid] = obj

        active_uuids = set(uuid_to_prim.keys())
        missing_uuids = active_uuids.difference(proxy_map.keys())
        _backfill_missing_proxy_map(proxy_col, missing_uuids, proxy_map, all_proxies)
        
        # 0. 他プリミティブのターゲットとして使われている UUID を集める (Stealth Mode 用)
        consumed_uuids = {prim.target_uuid.strip() for prim in props.primitives if prim.target_uuid.strip()}

        # 1. 不要になったプロキシを削除する
        for obj in all_proxies:
            uuid = obj.get("primitive_uuid")
            if uuid not in active_uuids:
                # 他の生きている CAD コレクションが参照しているプロキシは消さない
                if not _is_other_live_cad_proxy_owner(obj, proxy_col):
                    bpy.data.objects.remove(obj, do_unlink=True)
        
        # 2. プリミティブごとにプロキシを作成/更新する
        for i, prim in enumerate(props.primitives):
            obj = proxy_map.get(prim.uuid)
            is_new = False
            if not obj:
                is_new = True
                # 新規プロキシ用のメッシュを作る
                mesh = bpy.data.meshes.new(f"ProxyMesh_{prim.uuid}")
                
                # 初期形状は Box。実際の形状は下の _sync_proxy_mesh_geometry で差し替える
                verts, faces = _build_box_proxy_mesh()
                mesh.from_pydata(verts, [], faces)
                mesh.update()
                
                obj = bpy.data.objects.new(prim.name, mesh)
                proxy_col.objects.link(obj)
                
                obj["is_seamless_proxy"] = True
                obj["primitive_uuid"] = prim.uuid
                
                # CAD の実体は GPU オーバーレイ側が描くので、プロキシはワイヤー表示にする
                obj.display_type = 'WIRE'
                obj.show_name = True
                obj.show_in_front = True

            _sync_proxy_mesh_geometry(obj, prim)
            obj.show_in_front = True
                
            # 表示名はインデックス+型で固定する(UI リストと 3D ビューの対応を保つ)
            expected_name = f"{i}_{prim.type}_Seamless_Proxy"
            if obj.name != expected_name:
                obj.name = expected_name
            obj["primitive_index"] = i
            
            # アクティブな CAD コレクションにのみリンクする
            if obj.name not in proxy_col.objects:
                proxy_col.objects.link(obj)
            for col in obj.users_collection:
                if col != proxy_col:
                    # 他の生きている CAD コレクションのリンクは外さない
                    if hasattr(col, "seamless_props") and getattr(col, "seamless_cad_stack_ptr", "0") != "0":
                        continue
                    col.objects.unlink(obj)
            # グループ追従の判定
            # GROUP_END を親に持つ非アクティブな既存プロキシは、行列の上書きをスキップする
            group_parent_uuid = ""
            group_parent_prim = None
            if obj.parent and obj.parent.get("is_seamless_proxy"):
                group_parent_uuid = obj.parent.get("primitive_uuid", "")
                group_parent_prim = uuid_to_prim.get(group_parent_uuid)

            preserve_group_follow = bool(
                group_parent_prim and
                group_parent_prim.type == 'GROUP_END' and
                not is_new and
                i != props.active_primitive_index
            )

            if (not props.is_dragging or is_new) and not preserve_group_follow:
                if prim.type == "INSTANCE" and prim.target_uuid.strip():
                    master_uuid = prim.target_uuid.strip()
                    master_prim = uuid_to_prim.get(master_uuid)
                    display_scale = _get_prim_display_scale(master_prim) if master_prim else _get_prim_display_scale(prim)
                else:
                    display_scale = _get_prim_display_scale(prim)
                obj.matrix_world = mathutils.Matrix.Translation(prim.location) @ mathutils.Euler(prim.rotation).to_matrix().to_4x4() @ mathutils.Matrix.Diagonal(display_scale).to_4x4()
            elif preserve_group_follow:
                debug_print(
                    f"[GROUP_PARENT_SKIP] child={prim.uuid[:8]} parent={group_parent_uuid[:8]}"
                )

                
            # 新規作成したアクティブなプリミティブだけをアクティブオブジェクトにする
            # ドラッグ中に選択を触ると変形操作が壊れるため、その間は行わない
            if is_new and i == props.active_primitive_index and not props.is_dragging:
                if context.view_layer.objects.active != obj:
                    context.view_layer.objects.active = obj
                    obj.select_set(True)

            
            
            # ステルス表示の判定: 他プリミティブのターゲットとして消費されているか
            is_consumed = prim.uuid in consumed_uuids
            # アクティブなプリミティブかどうか
            is_active = (i == props.active_primitive_index)
            
            # 消費済みでもアクティブなら編集対象なので通常表示のままにする
            # (非アクティブなものだけ BOUNDS 表示へ落として視覚ノイズを減らす)
            should_stealth = is_consumed and not is_active
            
            obj.hide_set(False) # 常に表示
            obj.hide_viewport = False
            obj.hide_select = False 
            obj.hide_render = True
            
            if should_stealth:
                obj.display_type = 'BOUNDS'
                obj.show_name = False
            else:
                obj.display_type = 'WIRE'
                obj.show_name = True
        if apply_parenting and props:
            expected_parent_uuids = _build_expected_parent_uuids(props.primitives, proxy_map)
            _apply_expected_parent_uuids(expected_parent_uuids, proxy_map)
    finally:
        _is_updating_proxies = False

def update_parenting(context, props=None):
    """Synchronize parent-child relations between modifiers and targets."""
    if props is None:
        props = get_active_props(context)
    if not props:
        return
    active_col = get_active_collection(context)
    candidate_cols = []
    if _is_live_cad_collection(active_col):
        candidate_cols.append(active_col)
    for col in _get_registered_cad_cols():
        if col not in candidate_cols:
            candidate_cols.append(col)
    proxies = _build_proxy_map_for_cols(candidate_cols)

    def is_descendant(potential_descendant, obj):
        """Return True if potential_descendant is a descendant of obj."""
        curr = potential_descendant.parent
        while curr:
            if curr == obj:
                return True
            curr = curr.parent
        return False

    global _is_updating_proxies
    
    # 1. モディファイアとターゲットから、期待される親子関係を組み立てる
    expected_parents = {}
    expected_parent_uuids = {}
    for prim in props.primitives:
        modifier_obj = proxies.get(prim.uuid)
        target_uuid = prim.target_uuid.strip()
        target_obj = proxies.get(target_uuid)
        
        if modifier_obj and target_obj and target_uuid:
            # INSTANCE (Body Link) はマスターを親にすると二重変形になるので対象外
            if prim.type == "INSTANCE":
                continue
            # 循環参照の防止:
            # ターゲットがモディファイアの子孫になっている場合、親付けすると循環する
            # 自分自身がターゲットの場合も同様に除外する
            if not (is_descendant(modifier_obj, target_obj) or modifier_obj == target_obj):
                expected_parents[target_uuid] = modifier_obj
                expected_parent_uuids[target_uuid] = prim.uuid

    closed_groups = []
    group_stack = []
    for prim in props.primitives:
        for frame in group_stack:
            frame["member_uuids"].add(prim.uuid)

        if prim.type == 'GROUP_START':
            group_stack.append({
                "start_uuid": prim.uuid,
                "member_uuids": {prim.uuid},
            })
        elif prim.type == 'GROUP_END' and group_stack:
            frame = group_stack.pop()
            frame["end_uuid"] = prim.uuid
            closed_groups.append(frame)

    for frame in closed_groups:
        end_uuid = frame.get("end_uuid")
        end_obj = proxies.get(end_uuid)
        member_uuids = frame.get("member_uuids", set())
        if not end_uuid or not end_obj or not member_uuids:
            continue

        top_level_members = []
        for member_uuid in member_uuids:
            if member_uuid == end_uuid:
                continue
            if member_uuid not in proxies:
                continue

            parent_uuid = expected_parent_uuids.get(member_uuid)
            if parent_uuid and parent_uuid in member_uuids:
                continue

            top_level_members.append(member_uuid)

        if top_level_members:
            info_print(
                f"[GROUP_PARENT] group_end={end_uuid[:8]} roots="
                f"{[uuid[:8] for uuid in top_level_members]}"
            )

        for member_uuid in top_level_members:
            expected_parents[member_uuid] = end_obj
            expected_parent_uuids[member_uuid] = end_uuid

    # 2. 組み立てた親子関係を実際に適用する
    for prim in props.primitives:
        obj = proxies.get(prim.uuid)
        if not obj:
            continue
            
        expected_parent = expected_parents.get(prim.uuid)
        
        if expected_parent:
            # 親が変わる場合は、ワールド行列を保ったまま付け替える
            if obj.parent != expected_parent:
                _is_updating_proxies = True
                try:
                    world_mtx = obj.matrix_world.copy()
                    obj.parent = expected_parent
                    obj.matrix_parent_inverse = expected_parent.matrix_world.inverted()
                    obj.matrix_world = world_mtx
                finally:
                    _is_updating_proxies = False
        else:
            # 期待される親が無い場合はプロキシ親から外す(ワールド行列は保つ)
            if obj.parent and obj.parent.get("is_seamless_proxy"):
                _is_updating_proxies = True
                try:
                    world_mtx = obj.matrix_world.copy()
                    obj.parent = None
                    obj.matrix_world = world_mtx
                finally:
                    _is_updating_proxies = False

_proxy_initial_matrices = {}

def _csg_preview_eligible(prim, idx):
    """A tool is eligible for live CSG preview if it's a solid primitive doing a
    boolean (subtract / add / intersect) and there's a base before it in the DAG.
    The pure-Rust BSP path handles all three ops off the OCC edit path."""
    if idx < 1:
        return False
    op = str(getattr(prim, "operation", "")).upper()
    if op not in _CSG_PREVIEW_OPS:
        return False
    if getattr(prim, "type", "") not in _CSG_PREVIEW_TOOL_TYPES:
        return False
    # Independent-transform tools don't track the proxy the usual way, so the
    # drag delta wouldn't map to the OCC tool shape correctly — fall back to freeze.
    if getattr(prim, "use_independent_transform", False):
        return False
    return True

def _csg_preview_try_begin(col):
    """If the active primitive of `col` is an eligible dragged SUB tool, start a
    Rust-side CSG preview. Records state on success."""
    from . import core_bridge
    props = getattr(col, "seamless_props", None)
    if not props:
        return
    # ドラッグ中のライブブーリアン(毎フレーム BSP CSG + 結果ワイヤー再構築)は
    # トグルで明示的に有効化された時だけ動かす。既定OFFでは起動せず、凍結+アフィン
    # 差分のみの軽い経路になる。正確な結果は確定時(force=True)の OCC が再計算する。
    if not getattr(props, "live_boolean_preview", False):
        return
    idx = getattr(props, "active_primitive_index", -1)
    if not (0 <= idx < len(props.primitives)):
        return
    prim = props.primitives[idx]
    if not _csg_preview_eligible(prim, idx):
        return
    try:
        stack_ptr = int(getattr(col, "seamless_cad_stack_ptr", "0"))
    except (ValueError, TypeError):
        stack_ptr = 0
    if stack_ptr == 0:
        return
    init_mat = _proxy_initial_matrices.get(prim.uuid)
    if init_mat is None:
        return
    op = str(getattr(prim, "operation", "SUB")).upper()
    ok = core_bridge.csg_preview_begin(stack_ptr, idx, prim.uuid, op=op)
    if ok:
        _csg_preview_state[col.name] = {
            "stack_ptr": stack_ptr, "tool_index": idx, "tool_uuid": prim.uuid,
            "init_mat": init_mat.copy(), "last_t": 0.0, "op": op,
        }
        # Preview shows the crisp CSG wireframe; suppress the (now-stale) frozen
        # faces during the drag to avoid an edge/face mismatch. Faces are restored
        # by the exact OCC recompute on drag end.
        try:
            from .drawing import get_wireframe_engine
            rstack = get_wireframe_engine().get_stack(stack_ptr)
            rstack.face_batch_main = None
            rstack.face_batch_static = None
            rstack.face_batch_moving = None
            rstack.face_batch_ghost = None
            # Invalidate the face-geometry signature cache. A pure translation of a
            # SUB tool yields an identical mesh topology (same vert/tri counts, same
            # boundary samples), so update_face_data would signature-match on drag
            # end and re-render the STALE cached vertices (old position) while the
            # wireframe shows the new one. Forcing None guarantees a full rebuild.
            rstack._face_geom_signature = None
        except Exception:
            pass

def _csg_preview_tick(col):
    """Send the tool's current drag transform, draw the returned feature edges."""
    import time as _t
    st = _csg_preview_state.get(col.name)
    if not st:
        return False
    now = _t.time()
    if (now - st["last_t"]) < _CSG_PREVIEW_INTERVAL:
        return True  # active but throttled
    obj = None
    for o in bpy.context.selected_objects:
        if o.get("is_seamless_proxy") and o.get("primitive_uuid") == st["tool_uuid"]:
            obj = o
            break
    # 配置/カスタム移動モーダルではプロキシが選択状態でないことがあるため、
    # 見つからなければ対象コレクションのオブジェクトからも探す(BSPを確実に駆動)。
    if obj is None:
        col = bpy.data.collections.get(col.name) if isinstance(col, str) else col
        try:
            for o in col.objects:
                if o.get("is_seamless_proxy") and o.get("primitive_uuid") == st["tool_uuid"]:
                    obj = o
                    break
        except Exception:
            pass
    if obj is None:
        return True
    try:
        delta = obj.matrix_world @ st["init_mat"].inverted()
        flat = [delta[i][j] for i in range(4) for j in range(4)]  # row-major
        from . import core_bridge
        props = getattr(col, "seamless_props", None)
        want_ghost = bool(getattr(props, "live_boolean_preview", False)) and bool(getattr(props, "show_boolean_ghost_preview", False))
        res = core_bridge.csg_preview_update(st["stack_ptr"], flat, include_ghost=want_ghost)
        if res is not None:
            if want_ghost:
                points, counts, ghost_verts, ghost_tris = res
            else:
                points, counts = res
                ghost_verts, ghost_tris = None, None
            # Only redraw when the boolean produced geometry; an empty result
            # (e.g. tool momentarily covering the base) would blank the wireframe
            # via update_data's clear() and cause flicker, so keep the last frame.
            if len(points) > 0:
                from .drawing import get_wireframe_engine
                get_wireframe_engine().update_data(st["stack_ptr"], points, counts, [])
                for window in bpy.context.window_manager.windows:
                    for area in window.screen.areas:
                        if area.type == 'VIEW_3D':
                            area.tag_redraw()
            if want_ghost:
                from .drawing import get_wireframe_engine
                get_wireframe_engine().update_ghost_batch(st["stack_ptr"], ghost_verts, ghost_tris, st.get("op", "SUB"))
        st["last_t"] = now
    except Exception:
        pass
    return True

def _csg_preview_end_all():
    """End all active CSG previews (called on drag end)."""
    if not _csg_preview_state:
        return
    from . import core_bridge
    from .drawing import get_wireframe_engine
    for col_name, st in list(_csg_preview_state.items()):
        try:
            core_bridge.csg_preview_end(st["stack_ptr"])
        except Exception:
            pass
        # V8.1.5: settle(確定)後の高品質再描画にゴーストが残留しないよう必ずクリアする
        try:
            get_wireframe_engine().update_ghost_batch(st["stack_ptr"], None, None, None)
        except Exception:
            pass
    _csg_preview_state.clear()

_drag_settle_token = 0

def _arm_drag_settle(delay=0.28):
    """ヒューリスティックなドラッグ検出(is_transform_modal 取りこぼし時)で
    is_dragging=True にした後、停止後に確実にフラグを下ろして正確な結果を
    再描画するためのワンショット・セトルタイマーを(再)armする。最新トークンだけが
    発火するので毎フレーム呼んでも安全(古い予約は no-op)。"""
    global _drag_settle_token
    _drag_settle_token += 1
    tok = _drag_settle_token

    def _cb(tok=tok):
        global _was_transform_modal, _was_recent_change, _last_change_time
        if tok != _drag_settle_token:
            return None
        try:
            from .core_bridge import update_cad_preview_high_quality_for_col
            from .drawing import get_wireframe_engine
            any_cleared = False
            for col in _get_registered_cad_cols():
                props = getattr(col, "seamless_props", None)
                if props and getattr(props, "is_dragging", False):
                    props.is_dragging = False
                    any_cleared = True
                try:
                    stack_ptr = int(getattr(col, "seamless_cad_stack_ptr", "0"))
                    if stack_ptr != 0:
                        get_wireframe_engine().set_transform_delta(stack_ptr, None)
                except Exception:
                    pass
                if props:
                    try:
                        update_cad_preview_high_quality_for_col(col, bpy.context, force=True, sync=False)
                    except Exception:
                        pass
            if any_cleared:
                _was_transform_modal = False
                _was_recent_change = False
                _last_change_time = 0
                _proxy_initial_matrices.clear()
                redraw_all_view3d(bpy.context)
        except Exception:
            pass
        return None

    try:
        bpy.app.timers.register(_cb, first_interval=max(0.05, float(delay)))
    except Exception:
        pass

def _handle_settle(cad_cols, modal_ended, activity_ended, is_fast_mode, is_transform_modal):
    """確定フェーズ: is_dragging を下ろし、delta を外し、高品質再計算へ戻す。

    depsgraph_update_handler から挙動を変えずに切り出したもの
    (DEPSGRAPH_STATE_MACHINE.md のフェーズ表 #9)。呼び出し側の末尾で
    _was_transform_modal / _was_recent_change を更新する前に一度だけ呼ぶ。
    """
    import time
    global _last_change_time, _proxy_initial_matrices

    # Phase 4: 変形/アクティビティ終了時に is_dragging を下ろし、高品質再計算へ戻す
    if modal_ended or activity_ended:
        for col in cad_cols:
            props = getattr(col, "seamless_props", None)
            if props:
                props.is_dragging = False
        from .drawing import get_wireframe_engine
        for col in cad_cols:
            try:
                stack_ptr = int(getattr(col, "seamless_cad_stack_ptr", "0"))
                if stack_ptr != 0:
                    engine = get_wireframe_engine()
                    engine.set_transform_delta(stack_ptr, None)
                    # Force the drag-end face rebuild. A pure translation preserves
                    # mesh topology, so update_face_data's signature cache could match
                    # and re-render stale (pre-drag) vertices; invalidating guarantees
                    # the faces track the wireframe on commit.
                    engine.get_stack(stack_ptr)._face_geom_signature = None
            except Exception:
                pass
        if modal_ended:
            _proxy_initial_matrices.clear()

    if modal_ended or activity_ended:
        from .core_bridge import update_cad_preview_high_quality_for_col
        for col in cad_cols:
            update_cad_preview_high_quality_for_col(col, bpy.context, force=True, sync=False)
        _last_change_time = 0
    elif not is_fast_mode and _last_change_time > 0 and not is_transform_modal:
        if time.time() - _last_change_time > 0.3:
            from .core_bridge import update_cad_preview_high_quality_for_col
            for col in cad_cols:
                update_cad_preview_high_quality_for_col(col, bpy.context, force=True, sync=False)
            _last_change_time = 0


def _handle_nonmodal_sync(cad_cols, is_transform_modal):
    """非モーダル同期フェーズ: 削除されたプロキシの掃除と proxy -> prim の書き戻し。

    depsgraph_update_handler から挙動を変えずに切り出したもの
    (DEPSGRAPH_STATE_MACHINE.md のフェーズ表 #6)。変化のあった
    コレクションの集合を返す。
    """
    global _is_updating_proxies

    # --- 通常時(モーダル外)の同期処理 ---
    changed_cols = set()
    
    # 各 CAD コレクションを順に見て、更新の有無を判定する
    for col in cad_cols:
        props = col.seamless_props
        if not props:
            continue
            
        # ドラッグ中フラグ。ここは is_transform_modal のみを見る(is_recent_change は
        # 意図的に含めない)。かつて「直近も変化し続けている proxy 更新もドラッグとみなす」
        # 案があったが、それだと L996-999 と同じ latch 問題を起こし、WGPU Overlay OFF 時に
        # Python ワイヤーフレームが消える。広げる方向の変更は H の回帰確認が必須。
        props.is_dragging = is_transform_modal

        # A. 削除されたプロキシに対応するプリミティブを掃除する(変形中は行わない)
        if not is_transform_modal:
            all_proxy_uuids = {obj.get("primitive_uuid") for obj in col.objects if obj.get("is_seamless_proxy")}
            indices_to_remove = []
            removed_uuids = []
            for i, prim in enumerate(props.primitives):
                if prim.uuid and prim.uuid not in all_proxy_uuids:
                    indices_to_remove.append(i)
                    removed_uuids.append(prim.uuid)
            
            if indices_to_remove:
                _is_updating_proxies = True
                try:
                    for idx in reversed(indices_to_remove):
                        props.primitives.remove(idx)
                    if props.active_primitive_index >= len(props.primitives):
                        props.active_primitive_index = max(0, len(props.primitives) - 1)
                    
                    # 削除された UUID を描画エンジンの非表示集合へ入れ、ワイヤーを即座に消す
                    from .drawing import get_wireframe_engine
                    engine = get_wireframe_engine()
                    for u in removed_uuids:
                        engine.hidden_primitive_uuids.add(u)
                    
                    stack_ptr = int(getattr(col, "seamless_cad_stack_ptr", "0"))
                    if stack_ptr != 0:
                        selected_f_ids = set(x.strip() for x in props.selected_faces_str.split("|") if x.strip())
                        engine.update_face_data(
                            stack_ptr, 
                            engine.get_stack(stack_ptr)._cache_verts,
                            engine.get_stack(stack_ptr)._cache_tris,
                            engine.get_stack(stack_ptr)._cache_fids,
                            engine.get_stack(stack_ptr)._cache_counts,
                            opacity=props.viewport_opacity,
                            selected_f_ids=selected_f_ids
                        )
                        for window in bpy.context.window_manager.windows:
                            for area in window.screen.areas:
                                if area.type == 'VIEW_3D':
                                    area.tag_redraw()

                    changed_cols.add(col)
                finally:
                    _is_updating_proxies = False
                continue

        # B. 既存プロキシの全走査
        import uuid
        for prim in props.primitives:
            if not prim.uuid:
                prim.uuid = str(uuid.uuid4())[:8]
                
        uuid_to_prim = {prim.uuid: prim for prim in props.primitives}
        proxy_data = []
        
        for obj in col.objects:
            if obj.get("is_seamless_proxy"):
                p_uuid = obj.get("primitive_uuid")
                if p_uuid in uuid_to_prim:
                    # INSTANCE 等も含め、実際の値は matrix_world から読む
                    # (このループ内で選択状態を触ると変形が壊れるので参照のみ)
                    proxy_data.append({
                        "prim": uuid_to_prim[p_uuid],
                        "world_loc": obj.matrix_world.to_translation(),
                        "world_rot": obj.matrix_world.to_euler(),
                        "world_scale": obj.matrix_world.to_scale(),
                        "name": obj.name
                    })

        col_changed = False
        _is_updating_proxies = True
        try:
            for data in proxy_data:
                prim = data["prim"]
                world_loc, world_rot, world_scale = data["world_loc"], data["world_rot"], data["world_scale"]
                
                EPSILON = 5e-4
                obj = col.objects.get(data["name"])
                is_independent = prim.use_independent_transform and obj and obj.parent
                group_parent_prim = _get_group_parent_prim(obj, uuid_to_prim)
                active_uuid = ""
                if 0 <= props.active_primitive_index < len(props.primitives):
                    active_uuid = props.primitives[props.active_primitive_index].uuid
                is_group_follow = bool(
                    group_parent_prim and
                    prim.uuid != active_uuid
                )
                
                if not is_independent:
                    if prim.type in ('STEP_PART', 'SVG_PART'):
                        uniform_scale = _extract_uniform_scale(world_scale)
                        target_scale = mathutils.Vector((uniform_scale, uniform_scale, uniform_scale))
                        scale_changed = (target_scale - mathutils.Vector(prim.size)).length > EPSILON
                    else:
                        uniform_scale = None
                        scale_changed = (world_scale - mathutils.Vector(prim.size)).length > EPSILON
                    if (world_loc - mathutils.Vector(prim.location)).length > EPSILON or \
                       (mathutils.Vector(world_rot) - mathutils.Vector(prim.rotation)).length > EPSILON or \
                       (scale_changed):
                         
                        # 変形量の差分行列を作り、GPU 側のワイヤー/面をその場で動かす
                        try:
                            old_world = _compose_prim_world_matrix(prim)
                            delta_matrix = obj.matrix_world @ old_world.inverted()
                            from .drawing import get_wireframe_engine
                            stack_ptr = int(getattr(col, "seamless_cad_stack_ptr", "0"))
                            if stack_ptr != 0:
                                get_wireframe_engine().set_transform_delta(stack_ptr, delta_matrix)
                        except Exception:
                            pass

                        prim.location = world_loc
                        prim.rotation = world_rot
                        if prim.type in ('STEP_PART', 'SVG_PART'):
                            _set_step_part_uniform_scale(prim, uniform_scale)
                        else:
                            prim.size = world_scale
                        col_changed = True
                
                if prim.name != data["name"]:
                    prim.name = data["name"]
                    col_changed = True
        finally:
            _is_updating_proxies = False
            
        if col_changed:
            changed_cols.add(col)

    return changed_cols


def depsgraph_update_handler(scene, depsgraph):
    global _is_updating_proxies, _was_transform_modal, _was_recent_change, _proxy_initial_matrices, _pending_step_scales
    if _is_updating_proxies: 
        return
    
    # 変形モーダル中かの判定(トランスフォーム系オペレータの検出)
    is_transform_modal = False
    active_op_looks_transform = False
    current_transform_kind = ""
    active_op = bpy.context.active_operator
    if active_op:
        op_id = active_op.bl_idname.upper()
        current_transform_kind = op_id
        if any(kw in op_id for kw in ["TRANSFORM_OT", "GIZMO", "MOVE", "ROTATE", "SCALE", "RESIZE", "TWEAK"]):
            active_op_looks_transform = True
    
    # depsgraph.updates に CAD プロキシ / CAD コレクションの更新が含まれるか
    has_proxy_update = False
    touched_col_names = set()
    for update in depsgraph.updates:
        if isinstance(update.id, bpy.types.Object) and (update.id.get("is_seamless_proxy") or update.id.name.endswith("_Seamless_Proxy")):
            has_proxy_update = True
            owner_col = _find_proxy_cad_collection(update.id)
            if owner_col:
                touched_col_names.add(owner_col.name)
            continue
        if isinstance(update.id, bpy.types.Collection) and _is_live_cad_collection(update.id):
            has_proxy_update = True
            touched_col_names.add(update.id.name)

    # active_operator remains set while Blender shows the post-confirm Move/Resize
    # redo panel. Treat it as an active transform only when CAD proxies are still
    # producing depsgraph updates; otherwise it would keep is_dragging latched and
    # suppress the Python wireframe when WGPU Overlay is off.
    is_transform_modal = active_op_looks_transform and has_proxy_update
    modal_state_changed = (is_transform_modal != _was_transform_modal)

    # モーダルでもなく、直近の変更でもなく、プロキシ更新も無いフレームは
    # 何もせず即 return する(全コレクション走査のコストを避ける)
    if not modal_state_changed and not is_transform_modal and not has_proxy_update:
        _was_transform_modal = is_transform_modal
        return
            
    import time
    global _last_change_time
    if not "_last_change_time" in globals(): _last_change_time = 0
    
    is_recent_change = (time.time() - _last_change_time) < 0.3
    is_fast_mode = is_transform_modal or is_recent_change

    # 登録済みの全 CAD コレクション
    all_cad_cols = _get_registered_cad_cols()
    if is_transform_modal or modal_state_changed or _was_transform_modal or not touched_col_names:
        cad_cols = all_cad_cols
    else:
        cad_cols = [col for col in all_cad_cols if col.name in touched_col_names]
        if not cad_cols:
            cad_cols = all_cad_cols

    if not "_proxy_initial_matrices" in globals():
        _proxy_initial_matrices = {}

    # --- Phase 4: 変形モーダル開始時に、ドラッグ前のワールド行列を記録する ---
    if is_transform_modal and not _was_transform_modal:
        _proxy_initial_matrices.clear()
        _pending_step_scales.clear()
        for obj in bpy.context.selected_objects:
            if obj.get("is_seamless_proxy"):
                p_uuid = obj.get("primitive_uuid")
                if p_uuid:
                    _proxy_initial_matrices[p_uuid] = obj.matrix_world.copy()
        # Try to engage live CSG preview for the active collection's dragged SUB tool.
        _csg_preview_state.clear()
        active_col = get_active_collection(bpy.context)
        if active_col:
            _csg_preview_try_begin(active_col)

    # --- 変形中のプロキシ -> プリミティブ書き戻し (Phase 1 + Phase 4) ---
    # 選択中のプロキシだけを見て、変形量をプリミティブのプロパティへ反映する
    # 全コレクション走査やプロキシの削除判定はここでは行わない
    if is_transform_modal:
        selected_proxies = [obj for obj in bpy.context.selected_objects if obj.get("is_seamless_proxy")]
        if selected_proxies:
            changed_cols = set()
            _is_updating_proxies = True
            try:
                for obj in selected_proxies:
                    # このプロキシが属する CAD コレクションを引く
                    col = None
                    for c in obj.users_collection:
                        if hasattr(c, "seamless_props") and getattr(c, "seamless_cad_stack_ptr", "0") != "0":
                            col = c
                            break
                    if not col:
                        continue
                        
                    props = col.seamless_props
                    p_uuid = obj.get("primitive_uuid")
                    p_idx = obj.get("primitive_index")
                    
                    if p_uuid and p_idx is not None and 0 <= p_idx < len(props.primitives):
                        prim = props.primitives[p_idx]
                        if prim.uuid == p_uuid:
                            world_loc = obj.matrix_world.to_translation()
                            world_rot = obj.matrix_world.to_euler()
                            world_scale = obj.matrix_world.to_scale()
                            group_parent_prim = _get_group_parent_prim(obj, {p.uuid: p for p in props.primitives})
                            is_group_follow = bool(
                                group_parent_prim and
                                p_idx != props.active_primitive_index
                            )
                            
                            EPSILON = 5e-4
                            is_independent = prim.use_independent_transform and obj.parent
                            
                            if not is_independent:
                                if prim.type in ('STEP_PART', 'SVG_PART'):
                                    uniform_scale = _extract_uniform_scale(world_scale)
                                    target_scale = mathutils.Vector((uniform_scale, uniform_scale, uniform_scale))
                                    scale_changed = (target_scale - mathutils.Vector(prim.size)).length > EPSILON
                                    if (world_loc - mathutils.Vector(prim.location)).length > EPSILON or \
                                       (mathutils.Vector(world_rot) - mathutils.Vector(prim.rotation)).length > EPSILON or \
                                       (scale_changed):
                                        prim.location = world_loc
                                        prim.rotation = world_rot
                                        prim.size = target_scale
                                        _pending_step_scales[(col.name, prim.uuid)] = uniform_scale
                                        props.is_dragging = True
                                        changed_cols.add(col)
                                else:
                                    scale_changed = (world_scale - mathutils.Vector(prim.size)).length > EPSILON
                                    if (world_loc - mathutils.Vector(prim.location)).length > EPSILON or \
                                       (mathutils.Vector(world_rot) - mathutils.Vector(prim.rotation)).length > EPSILON or \
                                       (scale_changed):
                                        prim.location = world_loc
                                        prim.rotation = world_rot
                                        prim.size = world_scale
                                        props.is_dragging = True
                                        changed_cols.add(col)
                                    
                            if prim.name != obj.name:
                                prim.name = obj.name
                                changed_cols.add(col)

                            # Phase 4: ドラッグ開始時の行列との差分を GPU 側へ渡してプレビューを動かす
                            if p_uuid in _proxy_initial_matrices:
                                init_mat = _proxy_initial_matrices[p_uuid]
                                try:
                                    delta_matrix = obj.matrix_world @ init_mat.inverted()
                                    from .drawing import get_wireframe_engine
                                    stack_ptr = int(getattr(col, "seamless_cad_stack_ptr", "0"))
                                    if stack_ptr != 0:
                                        get_wireframe_engine().set_transform_delta(stack_ptr, delta_matrix)
                                except Exception:
                                    pass
            finally:
                _is_updating_proxies = False
                
            # ドラッグ中は重い OCC ブーリアン再計算は行わない（fast_mode はテッセレーション
            # 解像度にしか効かず、BRepAlgoAPI 本体 ~140ms が同期ブロックするため）。
            # 代わりに、対象が SUB ツールなら純Rust BSP CSG でリアルタイムプレビューを表示する。
            # 非対象/開始失敗時は従来どおり凍結（何もしない）。確定はドラッグ終了時に OCC が行う。
            if changed_cols:
                _last_change_time = time.time()
                _arm_drag_settle()
                if _csg_preview_state:
                    active_col = get_active_collection(bpy.context)
                    if active_col:
                        _csg_preview_tick(active_col)

        _was_transform_modal = is_transform_modal
        _was_recent_change = is_recent_change
        return

    changed_cols = _handle_nonmodal_sync(cad_cols, is_transform_modal)
            
    # --- 変形終了の検出 ---
    if not "_was_recent_change" in globals(): _was_recent_change = False
    
    modal_ended = _was_transform_modal and not is_transform_modal
    activity_ended = _was_recent_change and not is_recent_change and not is_transform_modal
    if modal_ended:
        # End any live CSG preview; the exact result is recomputed by OCC below.
        _csg_preview_end_all()
        changed_cols.update(_commit_pending_step_scales(cad_cols))



    # 確定直後やアクティビティ終了直後のフレームでは、高速プレビューの誤送信を抑止するため
    # changed_cols による更新処理（高速プレビュー呼び出し）をスキップさせる
    if _was_transform_modal or activity_ended:
        changed_cols = set()

    if changed_cols and not modal_ended:
        from .core_bridge import update_cad_preview_fast_for_col, update_cad_preview_high_quality_for_col
        # 進行中のネイティブ変形(グラブ/スケール中)は wm.operators[-1] にまだ載らず
        # is_transform_modal が False に化けることが多い。その間このブランチが毎フレーム
        # フル高品質再計算(defl=0.1+face_mesh)を叩き、重い・結果ワイヤーが太いままになる。
        # ドラッグ判定を is_transform_modal だけに頼らず「直近も変化し続けている
        # (is_recent_change)proxy更新」もドラッグとみなし、その間は fast パスに回す。
        # 単発(非ドラッグ)の proxy 変化だけ従来どおり即時フル高品質。正確な結果は
        # 停止後のセトル(activity_ended)/確定時が再計算する。
        # ドラッグ中またはトランスフォーム中の時のみ、最終変更時刻を更新して高速モードを維持する
        any_dragging = is_transform_modal or any(getattr(getattr(col, "seamless_props", None), "is_dragging", False) for col in changed_cols)
        if any_dragging:
            _last_change_time = time.time()
            
        if not is_transform_modal and not is_recent_change and has_proxy_update:
            for col in changed_cols:
                update_cad_preview_high_quality_for_col(col, bpy.context, force=True, sync=False)
            _was_transform_modal = is_transform_modal
            _was_recent_change = is_recent_change
            return
            
        for col in changed_cols:
            props = getattr(col, "seamless_props", None)
            is_dragging = getattr(props, "is_dragging", False) if props else False
            
            # ドラッグ中（またはトランスフォーム中）のみ高速プレビューを許可する。
            # 確定後の不要な depsgraph 更新によってエッジデータが空の高速プレビューで上書きされ、WGPU OFFで辺が消えるのを防ぐ。
            if (is_transform_modal or is_dragging) and _should_issue_fast_preview(
                col,
                is_transform_modal=is_transform_modal,
                has_instance=_collection_has_instance(col),
                transform_kind=current_transform_kind,
            ):
                # Shift+S 等のネイティブな高速変形も検知して高速プレビューを回す
                update_cad_preview_fast_for_col(col, bpy.context)
        # is_transform_modal を取りこぼしたヒューリスティックなドラッグでは modal_ended が
        # 来ず、停止後の高品質再計算(結果の再描画)が走らないことがある。停止を検知して
        # is_dragging を下ろし正確な結果を描くセトルを毎フレーム re-arm する(保険)。
        if not is_transform_modal and has_proxy_update:
            _arm_drag_settle()



    _handle_settle(cad_cols, modal_ended, activity_ended, is_fast_mode, is_transform_modal)

    _was_transform_modal = is_transform_modal
    _was_recent_change = is_recent_change

    # 3. アクティブオブジェクト変更時、Feature Treeのアクティブ選択インデックスを同期する
    sync_active_primitive_from_active_object()


def sync_active_primitive_from_active_object():
    """bpy.context.active_object がシームレスプロキシの場合、そのプリミティブindexを
    active_primitive_index に反映する。depsgraph_update_post と msgbus(active_object)
    の両方から呼ばれる想定。データ変更を伴わない選択切り替え(msgbus経由)でも
    Feature Tree の Selection 表示が追従するようにするための共通処理。"""
    global _is_updating_proxies
    active_obj = bpy.context.active_object
    if not (active_obj and active_obj.get("is_seamless_proxy")):
        return False
    new_idx = active_obj.get("primitive_index")
    active_col = get_active_collection(bpy.context)
    if not (active_col and active_obj.name in active_col.objects):
        return False
    active_props = active_col.seamless_props if hasattr(active_col, "seamless_props") else None
    if not (active_props and new_idx is not None and active_props.active_primitive_index != new_idx):
        return False
    if new_idx >= len(active_props.primitives):
        return False
    _is_updating_proxies = True
    active_props.active_primitive_index = new_idx
    _is_updating_proxies = False
    return True


def smart_round(val):
    import mathutils
    if isinstance(val, (int, float)):
        return round(val, 6)
    elif isinstance(val, mathutils.Vector):
        return mathutils.Vector((round(val.x, 6), round(val.y, 6), round(val.z, 6)))
    elif isinstance(val, mathutils.Euler):
        return mathutils.Euler((round(val.x, 6), round(val.y, 6), round(val.z, 6)), val.order)
    elif isinstance(val, mathutils.Quaternion):
        return mathutils.Quaternion((round(val.w, 6), round(val.x, 6), round(val.y, 6), round(val.z, 6)))
    elif isinstance(val, mathutils.Matrix):
        rows = []
        for r in val:
            rows.append([round(x, 6) for x in r])
        return mathutils.Matrix(rows)
    return val

