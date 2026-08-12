import bpy
from .core_bridge import update_cad_preview, trigger_modifier_numeric_preview, trigger_transform_numeric_preview
from .core.semantic_targets import get_display_edge_targets
from . import utils

INTERACTIVE_MODIFIER_TYPES = {'FILLET', 'CHAMFER', 'FACE_OFFSET', 'FACE_INSET', 'DRAFT', 'SHELL', 'FACE_LOFT', 'FACE_REVOLVE', 'SWEEP'}

def update_primitive_numeric_preview(self, context):
    props = utils.get_active_props(context)
    if not props:
        update_cad_preview(self, context)
        return

    active_idx = getattr(props, "active_primitive_index", -1)
    active_prim = props.primitives[active_idx] if 0 <= active_idx < len(props.primitives) else None

    if isinstance(self, SeamlessPrimitive) and self == active_prim:
        if self.type in INTERACTIVE_MODIFIER_TYPES:
            trigger_modifier_numeric_preview(context)
        else:
            trigger_transform_numeric_preview(context)
        return
    elif active_prim:
        if active_prim.type in INTERACTIVE_MODIFIER_TYPES:
            trigger_modifier_numeric_preview(context)
        else:
            trigger_transform_numeric_preview(context)
        return

    update_cad_preview(self, context)

def update_modifier_numeric_preview(self, context):
    props = utils.get_active_props(context)
    if not props:
        update_cad_preview(self, context)
        return

    active_idx = getattr(props, "active_primitive_index", -1)
    active_prim = props.primitives[active_idx] if 0 <= active_idx < len(props.primitives) else None

    if isinstance(self, SeamlessPrimitive):
        if self == active_prim and self.type in INTERACTIVE_MODIFIER_TYPES:
            trigger_modifier_numeric_preview(context)
            return
    elif active_prim and active_prim.type in INTERACTIVE_MODIFIER_TYPES:
        trigger_modifier_numeric_preview(context)
        return

    update_cad_preview(self, context)

def update_transform_numeric_preview(self, context):
    props = utils.get_active_props(context)
    if not props:
        update_cad_preview(self, context)
        return

    active_idx = getattr(props, "active_primitive_index", -1)
    active_prim = props.primitives[active_idx] if 0 <= active_idx < len(props.primitives) else None

    if isinstance(self, SeamlessPrimitive) and self == active_prim:
        trigger_transform_numeric_preview(context)
        return
    elif self.__class__.__name__ == 'SeamlessPoint':
        trigger_transform_numeric_preview(context)
        return

    update_cad_preview(self, context)

def update_gizmo_callback(self, context):
    import bpy
    # バックグラウンド実行時はGPUコンテキストやビューポートが使えないため、早期リターンする
    if bpy.app.background:
        return
        
    from .drawing import get_gizmo_engine
    props = self
    try:
        get_gizmo_engine().update_gizmo(context, props.active_primitive_index)
    except Exception as e:
        utils.warn_print(f"Seamless: Warning - Failed to update gizmo in background: {e}")
    
    if 0 <= props.active_primitive_index < len(props.primitives):
        prim = props.primitives[props.active_primitive_index]
        if prim.type in {'FILLET', 'CHAMFER'}:
            props.selection_type = 'EDGE'
            props.selected_edges_str = "|".join(get_display_edge_targets(prim))
        elif prim.type in {'FACE_OFFSET', 'FACE_INSET', 'DRAFT', 'SHELL', 'FACE_LOFT', 'FACE_REVOLVE', 'SWEEP'}:
            props.selection_type = 'FACE'
            props.selected_faces_str = prim.target_lineages
        else:
            # 標準プリミティブの場合は選択ハイライトをクリア
            props.selected_edges_str = ""
            props.selected_faces_str = ""
            
    # context.area が None の場合（スクリプト経由やUndo時など）への対策
    if context.area:
        context.area.tag_redraw()
    else:
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()

class SeamlessPoint(bpy.types.PropertyGroup):
    co: bpy.props.FloatVectorProperty(name="Coordinate", size=3, update=update_transform_numeric_preview)
    use_fillet: bpy.props.BoolProperty(name="Use Fillet", default=True, update=update_transform_numeric_preview)

class SeamlessFilletEdgeRadius(bpy.types.PropertyGroup):
    # 可変フィレット: エッジ(またはSemLoop)トークンごとの個別半径。
    # radius < 0 は「未指定＝親プリミティブの radius をフォールバック値として使う」を意味する。
    token: bpy.props.StringProperty(name="Edge Token", default="")
    radius: bpy.props.FloatProperty(name="Radius", default=-1.0, min=-1.0, max=100.0, step=1, update=update_primitive_numeric_preview)

class SeamlessPrimitive(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty(name="Name", default="Primitive")
    uuid: bpy.props.StringProperty(name="UUID", default="")
    # V8.1.5: スケッチ編集履歴 - このprimitiveがスケッチのfinalizeで生成された場合、
    # 元スケッチの sketch_snapshots エントリを指すuuid。スケッチ由来でないprimitiveや
    # 旧.blendファイルでは空文字列のまま(=編集不可として安全にデグレードする)。
    sketch_source_uuid: bpy.props.StringProperty(name="Sketch Source UUID", default="")
    group_selected: bpy.props.BoolProperty(name="Group Selected", default=False)
    type: bpy.props.EnumProperty(
        name="Type",
        items=[
            ('BOX', "Box", "Standard rectangular box"),
            ('CYLINDER', "Cylinder", "Circular cylinder"),
            ('SPHERE', "Sphere", "Spherical primitive"),
            ('STEP_PART', "STEP Part", "Imported STEP body"),
            ('SVG_PART', "SVG Part", "Imported SVG path"),
            ('CURVE', "Curve", "Freeform curve / BSpline"),
            ('POLYLINE', "Polyline", "Straight connected points with fillets"),
            ('ARC', "Arc", "Circular arc or circle"),
            ('FILLET', "Fillet", "Apply fillet to selected edges"),
            ('CHAMFER', "Chamfer", "Apply chamfer to selected edges"),
            ('FACE_OFFSET', "Face Offset", "Push/Pull selected faces"),
            ('FACE_INSET', "Face Inset", "Inset selected faces"),
            ('SURFACE', "Surface", "Create a face from closed curves"),
            ('SLOT', "Slot", "Create a stadium-shaped primitive"),
            ('CONE', "Cone", "Conical primitive"),
            ('TORUS', "Torus", "Torus (donut) primitive"),
            ('POLYGON', "Polygon", "Regular polygon primitive"),
            ('GEAR', "Gear", "Involute gear primitive"),
            ('HELIX', "Helix", "Helical (spring) primitive"),
            ('REVOLVE', "Revolve", "Revolve a profile around an axis"),
            ('MIRROR', "Mirror", "Mirror a target primitive"),
            ('ARRAY_LINEAR', "Linear Array", "Repeat target along an axis"),
            ('ARRAY_CIRCULAR', "Circular Array", "Repeat target around an axis"),
            ('DRAFT', "Draft", "Taper selected faces"),
            ('SHELL', "Shell", "Make a thick solid (Hollow)"),
            ('VARIABLE_BOX', "Dynamic Loft", "Loft between independent top/bottom shapes"),
            ('SWEEP', "Sweep", "Sweep a profile along a path"),
            ('LOFT', "Loft", "Loft through multiple profiles"),
            ('FACE_LOFT', "Face Loft", "Loft between two faces and fuse"),
            ('FACE_REVOLVE', "Face Revolve", "Revolve a specific face"),
            ('INSTANCE', "Instance (Body Link)", "Clone a target primitive with transform"),
            ('GROUP_START', "Group Start", "Start a nested boolean group"),
            ('GROUP_END', "Group End", "End a nested boolean group"),
            ('CLEANUP', "Topology Cleanup", "Unify coplanar/cocylindrical faces (Slow)"),
        ],
        default='BOX',
        update=update_cad_preview
    )
    
    reference_lineage: bpy.props.StringProperty(name="Reference Lineage", default="", update=update_cad_preview)
    
    # For CURVE / SURFACE / ARC
    fill_closed: bpy.props.BoolProperty(
        name="Fill Closed",
        description="Create a face if the curve is closed",
        default=True,
        update=update_cad_preview
    )
    use_pipe: bpy.props.BoolProperty(
        name="Use Pipe",
        description="Treat curve as a solid tube",
        default=False,
        update=update_cad_preview
    )
    
    operation: bpy.props.EnumProperty(
        name="Operation",
        items=[
            ('BASE', "Base", "Initial base shape"),
            ('ADD', "Add (Fuse)", "Combine with previous shapes"),
            ('SUB', "Subtract (Cut)", "Subtract from previous shapes"),
            ('INT', "Intersect (Common)", "Intersection with previous shapes"),
        ],
        default='ADD',
        update=update_cad_preview
    )
    rotation: bpy.props.FloatVectorProperty(name="Rotation", size=3, subtype='EULER', update=update_transform_numeric_preview)
    size: bpy.props.FloatVectorProperty(name="Size/Scale", size=3, default=(1.0, 1.0, 1.0), update=update_transform_numeric_preview)
    radius: bpy.props.FloatProperty(name="Radius", default=1.0, min=-100.0, max=100.0, step=1, update=update_primitive_numeric_preview)
    radius2: bpy.props.FloatProperty(name="Radius 2", default=0.5, min=-100.0, max=100.0, step=1, update=update_primitive_numeric_preview)
    minor_radius: bpy.props.FloatProperty(name="Minor Radius", default=0.2, min=0.001, max=100.0, step=1, update=update_primitive_numeric_preview)
    pipe_radius: bpy.props.FloatProperty(name="Pipe Radius", default=0.1, min=0.001, max=100.0, step=1, update=update_primitive_numeric_preview)
    extrude_height: bpy.props.FloatProperty(name="Extrude Height", default=0.0, min=-100.0, max=100.0, step=1, update=update_primitive_numeric_preview)
    turns: bpy.props.FloatProperty(name="Turns", default=3.0, min=0.01, max=1000.0, update=update_primitive_numeric_preview)
    
    # For Loft (VARIABLE_BOX extension)
    top_shape: bpy.props.EnumProperty(
        name="Top Shape",
        items=[('BOX', "Box", ""), ('CIRCLE', "Circle", "")],
        default='BOX',
        update=update_cad_preview
    )
    bot_shape: bpy.props.EnumProperty(
        name="Bottom Shape",
        items=[('BOX', "Box", ""), ('CIRCLE', "Circle", "")],
        default='BOX',
        update=update_cad_preview
    )
    
    # For POLYGON / GEAR
    sides: bpy.props.IntProperty(name="Sides / Teeth", default=6, min=3, max=500, update=update_primitive_numeric_preview)
    module: bpy.props.FloatProperty(name="Module", default=1.0, min=0.01, max=100.0, update=update_primitive_numeric_preview)
    pressure_angle: bpy.props.FloatProperty(name="Pressure Angle", default=20.0, min=0.1, max=45.0, update=update_primitive_numeric_preview)
    
    # For Pattern / Layout
    def _update_target_uuid(self, context):
        from . import core_bridge
        if getattr(core_bridge, "_step_target_refresh_in_progress", False):
            return
        from .core_bridge import update_cad_preview
        from .utils import sync_proxies, update_parenting
        update_cad_preview(self, context)
        sync_proxies(context)
        update_parenting(context)

    target_uuid: bpy.props.StringProperty(
        name="Target/Profile", 
        default="", 
        update=_update_target_uuid
    )
    def _update_step_scale(self, context):
        from .core_bridge import update_cad_preview
        scale = max(float(getattr(self, "step_scale", 1.0)), 1e-6)
        new_size = (scale, scale, scale)
        if tuple(self.size) != new_size:
            self.size = new_size
        else:
            update_cad_preview(self, context)
    step_scale: bpy.props.FloatProperty(
        name="STEP Scale",
        description="Uniform scale applied to imported STEP geometry",
        default=1.0,
        min=1e-6,
        soft_min=0.001,
        soft_max=1000.0,
        precision=6,
        update=_update_step_scale
    )
    step_source_path: bpy.props.StringProperty(
        name="STEP Source Path",
        default=""
    )
    step_source_index: bpy.props.IntProperty(
        name="STEP Source Index",
        default=-1
    )
    sweep_path_uuid: bpy.props.StringProperty(
        name="Sweep Path", 
        default="", 
        update=_update_target_uuid
    )
    
    # For Cleanup
    unify_faces: bpy.props.BoolProperty(
        name="Unify Faces",
        description="Merge coplanar or cocylindrical faces",
        default=True,
        update=update_cad_preview
    )
    unify_edges: bpy.props.BoolProperty(
        name="Unify Edges",
        description="Merge collinear or co-circular edges",
        default=True,
        update=update_cad_preview
    )
    sweep_profile_uuid: bpy.props.StringProperty(
        name="Sweep Profile", 
        default="", 
        update=_update_target_uuid
    )
    sweep_frame_mode: bpy.props.EnumProperty(
        name="Sweep Frame",
        items=[
            ('AUTO', "Auto", "Use OCC corrected Frenet frame"),
            ('HELIX_AXIS', "Helix Axis", "Keep section orientation driven by helix axis"),
        ],
        default='AUTO',
        update=update_cad_preview
    )
    sweep_roll_degrees: bpy.props.FloatProperty(
        name="Roll / Turn",
        description="Additional roll in degrees for each helix turn when using Helix Axis frame",
        default=0.0,
        soft_min=-720.0,
        soft_max=720.0,
        update=update_primitive_numeric_preview
    )
    loft_uuids: bpy.props.StringProperty(
        name="Loft Profiles", 
        default="", 
        description="Pipe-separated UUIDs for Loft sections",
        update=_update_target_uuid
    )
    target_collection: bpy.props.PointerProperty(
        type=bpy.types.Collection,
        name="Target Collection",
        description="Select another CAD Collection to instantiate",
        poll=lambda s, col: hasattr(col, "seamless_props") and col.seamless_cad_stack_ptr != "0" and col.name != "Seamless_CAD",
        update=lambda s, c: (
            setattr(s, "target_uuid", s.target_collection.seamless_cad_stack_ptr if s.target_collection else ""),
            update_cad_preview(s, c)
        ) and None
    )
    count: bpy.props.IntProperty(name="Count", default=3, min=1, max=100, update=update_primitive_numeric_preview)
    distance: bpy.props.FloatProperty(name="Value/Angle", default=2.0, update=update_primitive_numeric_preview)
    pattern_axis: bpy.props.EnumProperty(
        name="Base Axis",
        items=[
            ('X', "X", ""), 
            ('Y', "Y", ""), 
            ('Z', "Z", ""),
            ('POINT', "Point (Symmetry)", "Mirror across a point (180 deg rotation)")
        ],
        default='Z',
        update=update_cad_preview
    )
    
    use_independent_transform: bpy.props.BoolProperty(
        name="Independent Move",
        description="Move parent without affecting children's world position",
        default=False
    )

    def get_stack_props(self):
        """自身が所属している SeamlessProperties インスタンスを動的に解決します (マルチコレクション対応)"""
        # シナリオ①: self.id_data 直下に seamless_props がある場合 (現行のScene / Collection所属モデル)
        if hasattr(self.id_data, "seamless_props"):
            return self.id_data.seamless_props
        # シナリオ②: 全コレクションおよび全シーンから自身が含まれるプリミティブリストを探索
        for col in bpy.data.collections:
            if hasattr(col, "seamless_props"):
                # primitives の中に自身があるか探す
                for prim in col.seamless_props.primitives:
                    if prim == self:
                        return col.seamless_props
        for scene in bpy.data.scenes:
            if hasattr(scene, "seamless_props"):
                for prim in scene.seamless_props.primitives:
                    if prim == self:
                        return scene.seamless_props
        return None

    def get_local_pos(self):
        import mathutils
        props = self.get_stack_props()
        if not props:
            return self.location
        
        # 自身（子）をターゲット（target_uuid）に指定しているモディファイア（親）を探す
        my_uuid = self.uuid.strip().lower()
        for p in props.primitives:
            if p.target_uuid.strip().lower() == my_uuid:
                # 親（モディファイア）のワールド行列を作成
                parent_mtx = mathutils.Matrix.Translation(p.location) @ \
                             mathutils.Euler(p.rotation).to_matrix().to_4x4()
                # 自身のワールド行列
                my_mtx = mathutils.Matrix.Translation(self.location)
                # 親空間から見た自身のローカル座標を算出
                local_mtx = parent_mtx.inverted_safe() @ my_mtx
                return local_mtx.to_translation()
            
        return self.location

    def set_local_pos(self, value):
        import mathutils
        props = self.get_stack_props()
        if not props:
            self.location = value
            return
        
        # 自身（子）をターゲット（target_uuid）に指定しているモディファイア（親）を探す
        my_uuid = self.uuid.strip().lower()
        for p in props.primitives:
            if p.target_uuid.strip().lower() == my_uuid:
                # 親（モディファイア）のワールド行列を作成
                parent_mtx = mathutils.Matrix.Translation(p.location) @ \
                             mathutils.Euler(p.rotation).to_matrix().to_4x4()
                # ローカル座標からの変換行列
                local_mtx = mathutils.Matrix.Translation(value)
                # 自身の世界座標を算出して適用
                self.location = (parent_mtx @ local_mtx).to_translation()
                return
        
        self.location = value

    local_location: bpy.props.FloatVectorProperty(
        name="Local Offset",
        size=3,
        get=get_local_pos,
        set=set_local_pos,
        update=update_transform_numeric_preview,
        subtype='TRANSLATION'
    )
    
    # 世界座標もサブタイプを設定して単位を表示させる
    location: bpy.props.FloatVectorProperty(
        name="Location", 
        size=3, 
        update=update_transform_numeric_preview,
        subtype='TRANSLATION'
    )
    
    # For ARC
    angle_start: bpy.props.FloatProperty(name="Angle Start", default=0.0, min=0.0, max=360.0, update=update_primitive_numeric_preview)
    angle_end: bpy.props.FloatProperty(name="Angle End", default=360.0, min=0.0, max=360.0, update=update_primitive_numeric_preview)

    target_lineages: bpy.props.StringProperty(name="Target Lineages", default="", update=update_cad_preview)
    # V8.0.1: フィレット辺追従用 - 辺選択時の参照プリミティブとの相対座標を記録
    # JSON形式: {"Edge:5@x;y;z": {"ref":"uuid","rloc":[rx,ry,rz],"ref_loc":[x,y,z],"ref_rot":[rx,ry,rz]}}
    edge_ref_snapshot: bpy.props.StringProperty(name="Target Reference Snapshot", default="")
    # V8.1.5: 可変フィレット - target_lineages 内の各エッジトークンに個別半径を割り当てる。
    # 未登録のトークン、または radius<0 のエントリは prim.radius をフォールバックとして使う。
    edge_radii: bpy.props.CollectionProperty(type=SeamlessFilletEdgeRadius)
    edge_radii_active_index: bpy.props.IntProperty(name="Active Edge Radius Index", default=-1)
    reference_ref_snapshot: bpy.props.StringProperty(name="Reference Face Snapshot", default="")
    points: bpy.props.CollectionProperty(type=SeamlessPoint)
    segments_json: bpy.props.StringProperty(name="Segments JSON", default="")
class SeamlessSketchPoint(bpy.types.PropertyGroup):
    id: bpy.props.IntProperty(name="Point ID")
    co: bpy.props.FloatVectorProperty(name="Coordinate 2D", size=2)
    is_segment: bpy.props.BoolProperty(name="Is Segment Point", default=False)

class SeamlessSketchLine(bpy.types.PropertyGroup):
    id: bpy.props.IntProperty(name="Line ID")
    start_point_id: bpy.props.IntProperty(name="Start Point ID")
    end_point_id: bpy.props.IntProperty(name="End Point ID")
    is_construction: bpy.props.BoolProperty(name="Is Construction", default=False)

class SeamlessSketchCircle(bpy.types.PropertyGroup):
    id: bpy.props.IntProperty(name="Circle ID")
    center_point_id: bpy.props.IntProperty(name="Center Point ID")
    radius_point_id: bpy.props.IntProperty(name="Radius Point ID")
    is_construction: bpy.props.BoolProperty(name="Is Construction", default=False)

class SeamlessSketchArc(bpy.types.PropertyGroup):
    id: bpy.props.IntProperty(name="Arc ID")
    center_point_id: bpy.props.IntProperty(name="Center Point ID")
    start_point_id: bpy.props.IntProperty(name="Start Point ID")
    end_point_id: bpy.props.IntProperty(name="End Point ID")
    mid_point_id: bpy.props.IntProperty(name="Mid Point ID")
    is_construction: bpy.props.BoolProperty(name="Is Construction", default=False)
    # V8.1.5バグ修正: コーナーフィレットで生成された円弧かどうか。
    # フィレット円弧は常に劣弧(角の内側)を維持すべきで、ドラッグ後の
    # 「前回位置との一致判定」による反転ヒューリスティックの対象外とする
    # (sketch_solver.py参照。以前は実在しない'FILLET'拘束タイプで判定していたため
    # 常にFalse扱いになり、ドラッグ時に円弧が反対側へ反転する不具合があった)。
    is_fillet: bpy.props.BoolProperty(name="Is Fillet Corner Arc", default=False)

class SeamlessSketchSnapshot(bpy.types.PropertyGroup):
    # V8.1.5: スケッチ編集履歴 - finalize_sketch がスクラッチコレクション
    # (sketch_points/lines/circles/arcs/constraints + 参照平面行列)を破棄する直前に、
    # 元のパラメトリックデータをJSON blobとして退避しておく。segments_json と同じ
    # 「構造化データをJSON文字列で保存する」パターンに倣い、専用のCollectionProperty
    # スキーマを並行管理せずに済ませる。sketch_uuid は焼き込み済みprimitiveの
    # sketch_source_uuid から逆引きされる。
    sketch_uuid: bpy.props.StringProperty(name="Sketch UUID", default="")
    snapshot_json: bpy.props.StringProperty(name="Snapshot JSON", default="")

def update_sketch_constraint_value(self, context):
    import bpy
    props = None
    if hasattr(self.id_data, "seamless_props"):
        props = self.id_data.seamless_props
    else:
        for col in bpy.data.collections:
            if hasattr(col, "seamless_props"):
                if any(c.id == self.id for c in col.seamless_props.sketch_constraints):
                    props = col.seamless_props
                    break
        if not props:
            for scene in bpy.data.scenes:
                if hasattr(scene, "seamless_props"):
                    if any(c.id == self.id for c in scene.seamless_props.sketch_constraints):
                        props = scene.seamless_props
                        break
    if props:
        from .sketch.sketch_solver import solve_gcs_external
        solve_gcs_external(props, context)
        update_cad_preview(None, context)
        if context.area:
            context.area.tag_redraw()
        else:
            for window in context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == 'VIEW_3D':
                        area.tag_redraw()

class SeamlessSketchConstraint(bpy.types.PropertyGroup):
    id: bpy.props.IntProperty(name="Constraint ID")
    type: bpy.props.EnumProperty(
        name="Type",
        items=[
            ('FIXED', "Fixed", "Fix a point's coordinate"),
            ('DISTANCE', "Distance", "Fix distance between points"),
            ('HORIZONTAL', "Horizontal", "Make line horizontal"),
            ('VERTICAL', "Vertical", "Make line vertical"),
            ('PARALLEL', "Parallel", "Make lines parallel"),
            ('PERPENDICULAR', "Perpendicular", "Make lines perpendicular"),
            ('TANGENT', "Tangent", "Make arc tangent to line"),
            ('MIDPOINT', "Midpoint", "Point is midpoint between two points"),
            ('RADIUS', "Radius", "Fix the radius of a circle or arc"),
            ('ANGLE', "Angle", "Fix the angle between two lines, in degrees"),
            ('EQUAL', "Equal", "Make two lines the same length"),
            ('ARC', "Arc", "Constraint for circular arc shape")
        ],
        default='FIXED'
    )
    target_ids_str: bpy.props.StringProperty(name="Target IDs", default="")
    value: bpy.props.FloatProperty(name="Value", default=1.0, update=update_sketch_constraint_value)

class SeamlessProperties(bpy.types.PropertyGroup):
    primitives: bpy.props.CollectionProperty(type=SeamlessPrimitive)
    # V8.1.5: スケッチ編集履歴 - finalize済みスケッチのパラメトリックスナップショット群。
    # プリミティブの sketch_source_uuid から該当エントリを引いて再編集する。
    sketch_snapshots: bpy.props.CollectionProperty(type=SeamlessSketchSnapshot)
    # 空文字列 = 通常の新規スケッチ。非空 = 既存スケッチ(sketch_source_uuid)を再編集中で、
    # Apply時にin-place更新(同一primitive uuidを維持)を行う対象。
    sketch_editing_uuid: bpy.props.StringProperty(name="Editing Sketch UUID", default="")

    def update_rollback_index(self, context):
        from .core_bridge import update_cad_preview_forced
        update_cad_preview_forced(context)
        
    rollback_index: bpy.props.IntProperty(
        name="Rollback Index",
        description="Index of primitive to rollback to (-1 means no rollback)",
        default=-1,
        update=update_rollback_index
    )
    
    sketch_show_constraints: bpy.props.BoolProperty(name="Show Constraints List", default=True)
    active_primitive_index: bpy.props.IntProperty(
        name="Active Primitive Index", 
        default=0,
        update=update_gizmo_callback
    )
    fillet_radius: bpy.props.FloatProperty(name="Fillet Radius", default=0.0, min=0.0, max=10.0, step=1, update=update_modifier_numeric_preview)
    selection_type: bpy.props.EnumProperty(
        name="Selection Type",
        items=[
            ('EDGE', "Edge", "Select Edges", 'EDGESEL', 0),
            ('FACE', "Face", "Select Faces", 'FACESEL', 1),
        ],
        default='EDGE'
    )
    selected_edges_str: bpy.props.StringProperty(name="Selected Edges", default="", update=update_cad_preview)
    selected_faces_str: bpy.props.StringProperty(name="Selected Faces", default="", update=update_cad_preview)
    is_selection_mode: bpy.props.BoolProperty(name="Selection Mode", default=False)
    is_dragging: bpy.props.BoolProperty(name="Is Dragging", default=False)
    # Interactive placement (Surface Snapping add) is a custom modal, not a
    # Blender transform, so it can't ride is_dragging (the depsgraph handler
    # resets that to is_transform_modal=False). This dedicated flag lets the
    # drawing skip the heavy result wireframe while the primitive is being
    # placed/moved; a settle timer clears it on pause so the result redraws.
    is_placing: bpy.props.BoolProperty(name="Is Placing", default=False)
    is_selecting_reference: bpy.props.BoolProperty(name="Selecting Reference", default=False)
    preselected_edge_id: bpy.props.StringProperty(name="Preselected Edge ID", default="")
    preselected_face_id: bpy.props.StringProperty(name="Preselected Face ID", default="")
    preselected_point: bpy.props.FloatVectorProperty(name="Preselected Point", size=3)
    is_alt_pressed: bpy.props.BoolProperty(name="Alt Pressed", default=False)
    viewport_opacity: bpy.props.FloatProperty(name="Viewport Opacity", default=0.4, min=0.0, max=1.0)
    use_wgpu_overlay: bpy.props.BoolProperty(name="Use WGPU Overlay", default=False)
    hide_occluded_edges: bpy.props.BoolProperty(
        name="Hide Occluded Edges",
        description=(
            "Hide result edges that sit behind the surface, instead of letting them "
            "show through. Only applies when WGPU Overlay is off and Opacity is 1.0, "
            "because the faces only write depth when they are fully opaque. "
            "Selection, hover and modifier highlights always stay visible"
        ),
        default=True,
    )
    enable_perf_logging: bpy.props.BoolProperty(
        name="Perf Logging",
        description="Write timing logs to cad_profile.log for CAD preview pipeline",
        default=False
    )
    use_snapping: bpy.props.BoolProperty(
        name="Surface Snapping",
        description="Snap new primitives to existing CAD surfaces and align with normal",
        default=True
    )
    fast_modifier_preview: bpy.props.BoolProperty(
        name="Fast Modifier Drag",
        description=(
            "While dragging a fillet/chamfer/shell radius, skip the shaded-face "
            "tessellation (the heaviest per-frame cost) and show the live wireframe "
            "only. The full shaded surface is restored the moment you release. "
            "Off = always shade during drag (smoother-looking but heavier)."
        ),
        default=True
    )
    live_boolean_preview: bpy.props.BoolProperty(
        name="Live Boolean Drag",
        description=(
            "While dragging a boolean tool (SUB/ADD/etc.), show the live cut/union "
            "result in real time. This runs a per-frame BSP boolean and rebuilds the "
            "result wireframe, so it is the heaviest part of dragging. "
            "Off (default) = always light: the proxy just moves and the exact result "
            "is recomputed the moment you release."
        ),
        default=False
    )
    show_boolean_ghost_preview: bpy.props.BoolProperty(
        name="Ghost Preview (Removed/Added Volume)",
        description=(
            "While Live Boolean Drag is on, also show a translucent highlight of the "
            "volume that will be removed (SUB, red) or added (ADD, green) before you "
            "release. Adds an extra BSP computation each frame on top of Live Boolean "
            "Drag, so it only takes effect when that option is also enabled."
        ),
        default=True
    )

    # --- Quality Settings ---
    mesh_quality: bpy.props.FloatProperty(
        name="Linear Quality",
        description="Linear deflection for tessellation. Lower is smoother.",
        default=0.1,
        min=0.001,
        max=1.0,
        precision=3,
        update=update_cad_preview
    )
    mesh_angular_quality: bpy.props.FloatProperty(
        name="Curvature Quality (deg)",
        description="Angular deflection in degrees. Lower is smoother.",
        default=20.0,
        min=0.1,
        max=90.0,
        precision=1,
        update=update_cad_preview
    )
    bake_quality: bpy.props.FloatProperty(
        name="Bake Linear",
        description="Linear quality used when baking to mesh.",
        default=0.01,
        min=0.001,
        max=1.0,
        precision=3
    )
    bake_angular_quality: bpy.props.FloatProperty(
        name="Bake Curvature (deg)",
        description="Angular quality in degrees used when baking.",
        default=5.0,
        min=0.1,
        max=90.0,
        precision=1
    )
    use_high_quality_bake: bpy.props.BoolProperty(
        name="High Quality Bake",
        description="Automatically use Bake Quality when baking to mesh",
        default=True
    )
    
    # 2Dスケッチ用のプロパティ定義
    sketch_points: bpy.props.CollectionProperty(type=SeamlessSketchPoint)
    sketch_lines: bpy.props.CollectionProperty(type=SeamlessSketchLine)
    sketch_circles: bpy.props.CollectionProperty(type=SeamlessSketchCircle)
    sketch_arcs: bpy.props.CollectionProperty(type=SeamlessSketchArc)
    sketch_constraints: bpy.props.CollectionProperty(type=SeamlessSketchConstraint)
    
    # 2D CAD スケッチャー MVP用の動的プロパティ
    sketch_grid_snap: bpy.props.BoolProperty(
        name="Grid Snap", default=False, description="Snap to grid intersections"
    )
    sketch_show_grid: bpy.props.BoolProperty(
        name="Show Grid", default=True, description="Show grid in sketch mode"
    )
    is_sketch_active: bpy.props.BoolProperty(
        name="Is Sketch Active",
        description="Whether the sketch mode is currently running",
        default=False
    )
    
    def update_sketch_pen_mode(self, context):
        try:
            from .sketch.sketch_history import clear_sketch_temp_states
            clear_sketch_temp_states(self)
        except Exception as e:
            utils.error_print(f"Seamless CAD: Failed to clear sketch temp states on mode switch: {e}")
        if context.area:
            context.area.tag_redraw()
            
    sketch_pen_mode: bpy.props.EnumProperty(
        name="Pen Mode",
        items=[
            ('SELECT', "Select", "Select points or lines (Box selection)"),
            ('POINT', "Point", "Create standalone points"),
            ('LINE', "Line", "Create lines by clicking two points"),
            ('ARC', "Arc", "Create circular arcs"),
            ('CIRCLE', "Circle", "Create circles by clicking center and radius"),
            ('RECTANGLE', "Rectangle", "Create a corner-based rectangle"),
            ('CENTER_RECT', "Center Rectangle", "Create a center-based rectangle"),
            ('SEMICIRCLE', "Semi-circle", "Create semi-circles by clicking two diameter ends"),
            ('TRIM_EXTEND', "Trim/Extend", "Interactive Trim or Extend elements"),
            ('SLOT', "Slot", "Create a slot / stadium-shaped element"),
        ],
        default='SELECT',
        update=update_sketch_pen_mode
    )
    
    sketch_selected_point_id: bpy.props.IntProperty(
        name="Selected Point ID",
        default=-1
    )
    
    sketch_selected_point_id_2: bpy.props.IntProperty(
        name="Selected Point ID 2",
        default=-1
    )
    
    sketch_selected_points_str: bpy.props.StringProperty(
        name="Selected Points List",
        description="Comma-separated IDs of selected points",
        default=""
    )
    
    sketch_selected_lines_str: bpy.props.StringProperty(
        name="Selected Lines List",
        description="Comma-separated IDs of selected lines",
        default=""
    )
    sketch_clipboard_json: bpy.props.StringProperty(
        name="Sketch Clipboard",
        description="Serialized sketch clipboard payload used for copy/paste",
        default=""
    )
    sketch_clipboard_has_data: bpy.props.BoolProperty(
        name="Sketch Clipboard Has Data",
        description="Whether the sketch clipboard currently has data",
        default=False
    )
    
    def update_selected_sketch_point_x(self, context):
        if self.sketch_selected_point_id >= 0:
            for pt in self.sketch_points:
                if pt.id == self.sketch_selected_point_id:
                    if abs(pt.co[0] - self.sketch_selected_point_x) > 1e-4:
                        pt.co[0] = self.sketch_selected_point_x
                        from .sketch.sketch_solver import solve_gcs_external
                        solve_gcs_external(self, context)
                        update_cad_preview(None, context)
                        if context.area:
                            context.area.tag_redraw()
                        
    def update_selected_sketch_point_y(self, context):
        if self.sketch_selected_point_id >= 0:
            for pt in self.sketch_points:
                if pt.id == self.sketch_selected_point_id:
                    if abs(pt.co[1] - self.sketch_selected_point_y) > 1e-4:
                        pt.co[1] = self.sketch_selected_point_y
                        from .sketch.sketch_solver import solve_gcs_external
                        solve_gcs_external(self, context)
                        update_cad_preview(None, context)
                        if context.area:
                            context.area.tag_redraw()
                        
    sketch_selected_point_x: bpy.props.FloatProperty(
        name="X Coordinate",
        description="Local X coordinate of selected point",
        default=0.0,
        subtype='DISTANCE',
        update=update_selected_sketch_point_x
    )
    
    sketch_selected_point_y: bpy.props.FloatProperty(
        name="Y Coordinate",
        description="Local Y coordinate of selected point",
        default=0.0,
        subtype='DISTANCE',
        update=update_selected_sketch_point_y
    )
    
    sketch_pending_action: bpy.props.StringProperty(
        name="Pending Sketch Action",
        default=""
    )

    # 描画モーダルとの非同期通信や非モーダル描画のためのUIステートプロパティ
    sketch_hover_point_id: bpy.props.IntProperty(name="Hover Point ID", default=-1)
    sketch_hover_line_id: bpy.props.IntProperty(name="Hover Line ID", default=-1)
    sketch_selected_line_id: bpy.props.IntProperty(name="Selected Line ID", default=-1)
    sketch_selected_line_id_2: bpy.props.IntProperty(name="Selected Line ID 2", default=-1)
    sketch_is_drawing_line: bpy.props.BoolProperty(name="Is Drawing Line", default=False)
    sketch_draw_start_pt_id: bpy.props.IntProperty(name="Draw Start Pt ID", default=-1)
    
    # 2Dスケッチでのフィレット・面取り用のパラメータ
    sketch_fillet_radius: bpy.props.FloatProperty(
        name="Fillet Radius",
        description="Fillet radius for corner rounding",
        default=0.2,
        min=0.001,
        max=10.0,
        step=1,
        subtype='DISTANCE'
    )
    sketch_chamfer_distance: bpy.props.FloatProperty(
        name="Chamfer Distance",
        description="Chamfer distance for corner chamfering",
        default=0.2,
        min=0.001,
        max=10.0,
        step=1,
        subtype='DISTANCE'
    )
    sketch_offset_distance: bpy.props.FloatProperty(
        name="Offset Distance",
        description="Offset distance for selected sketch lines",
        default=0.2,
        min=-10.0,
        max=10.0,
        subtype='DISTANCE'
    )
