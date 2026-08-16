import bpy
from .. import utils
from .. import core_bridge

def poll_main(context):
    scene = getattr(context, "scene", None)
    if not scene or not getattr(scene, "is_seamless_cad_started", False):
        return False
    props = utils.get_active_props(context)
    if not props or getattr(props, "is_sketch_active", False):
        return False
    if not scene.active_cad_collection:
        return False
    return True

class SEAMLESS_PT_WorkspacePanel(bpy.types.Panel):
    bl_label = "Active CAD Workspace"
    bl_idname = "SEAMLESS_PT_WorkspacePanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Seamless'

    @classmethod
    def poll(cls, context):
        props = utils.get_active_props(context)
        return not (props and props.is_sketch_active)

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        if not scene.is_seamless_cad_started:
            box = layout.column(align=True)
            box.label(text="Welcome to Seamless CAD", icon='GHOST_ENABLED')
            box.operator("seamless.start_cad", text="Start Seamless CAD", icon='PLAY')
            return

        box_parts = layout.column(align=True)
        box_parts.label(text="Active CAD Workspace:", icon='OUTLINER_COLLECTION')
        row = box_parts.row(align=True)
        row.prop(scene, "active_cad_collection", text="")
        if scene.active_cad_collection:
            row.operator("seamless.remove_part", text="", icon='TRASH')
        row_btns = box_parts.row(align=True)
        row_btns.operator("seamless.add_part", text="Add New CAD Part", icon='ADD')

        props = utils.get_active_props(context)
        if not props or not scene.active_cad_collection:
            layout.label(text="※Please select or create a valid Part collection above", icon='ERROR')
            return


class SEAMLESS_PT_DisplayPanel(bpy.types.Panel):
    bl_label = "Viewport Display"
    bl_idname = "SEAMLESS_PT_DisplayPanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Seamless'

    @classmethod
    def poll(cls, context):
        return poll_main(context)

    def draw(self, context):
        layout = self.layout
        props = utils.get_active_props(context)

        box_v = layout.column(align=True)
        box_v.label(text="Viewport Display:", icon='RESTRICT_VIEW_OFF')
        box_v.prop(props, "viewport_opacity", text="Opacity", slider=True)
        box_v.prop(props, "use_wgpu_overlay", text="Use WGPU Overlay")

        # 面が深度を書くのは「WGPU OFF かつ不透明」のときだけなので、それ以外では
        # 切り替えても効かない。押せてしまうと不具合に見えるのでグレーアウトする。
        row_occ = box_v.row()
        row_occ.enabled = (not props.use_wgpu_overlay) and props.viewport_opacity > 0.99
        row_occ.prop(props, "hide_occluded_edges", text="Hide Occluded Edges")


class SEAMLESS_PT_QualityBakePanel(bpy.types.Panel):
    bl_label = "Quality & Export"
    bl_idname = "SEAMLESS_PT_QualityBakePanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Seamless'

    @classmethod
    def poll(cls, context):
        return poll_main(context)

    def draw(self, context):
        layout = self.layout
        props = utils.get_active_props(context)

        box_q = layout.column(align=True)
        box_q.label(text="Quality Settings:", icon='STRANDS')
        row = box_q.row(align=True)
        row.prop(props, "mesh_quality", text="Linear")
        row.prop(props, "mesh_angular_quality", text="Curvature")
        box_q.prop(props, "fast_modifier_preview", toggle=True, icon='MOD_BEVEL')
        box_q.prop(props, "live_boolean_preview", toggle=True, icon='MOD_BOOLEAN')
        if props.live_boolean_preview:
            box_q.prop(props, "show_boolean_ghost_preview", toggle=True, icon='GHOST_ENABLED')

        box_q.prop(props, "use_high_quality_bake", toggle=True, icon='MOD_BUILD')
        if props.use_high_quality_bake:
            row = box_q.row(align=True)
            row.prop(props, "bake_quality", text="Bake Linear")
            row.prop(props, "bake_angular_quality", text="Bake Curvature")
        
        layout.operator("seamless.bake_mesh", text="Bake to Mesh", icon='MESH_DATA')
        
        # 取り込みと書き出しは、方向を見出しで示してボタン側は形式名だけにする。
        # 各ボタンに "Export STEP" と書くと N パネルの幅では "Expo.." に潰れ、
        # 3つ並べた時点でどれがどれか読めなくなる。見出しに逃がせば、
        # 形式が増えても横に足せる。
        box_io = layout.column(align=True)

        box_io.label(text="Import:", icon='IMPORT')
        row_in = box_io.row(align=True)
        row_in.operator("seamless.import_step", text="STEP")
        row_in.operator("seamless.import_svg", text="SVG")

        box_io.separator()
        box_io.label(text="Export:", icon='EXPORT')
        row_out = box_io.row(align=True)
        row_out.operator("seamless.export_step", text="STEP")
        row_out.operator("seamless.export_stl", text="STL")
        row_out.operator("seamless.export_iges", text="IGES")

class SEAMLESS_PT_MeasurePanel(bpy.types.Panel):
    """アクティブな Part の質量特性を表示する。

    測るのはボタンを押したときだけ。draw() はマウスを動かすだけでも走るので、
    ここからカーネルを呼ぶと「パネルを開いているだけで重い」ことになる。
    このアドオンの性能設計は「毎フレーム仕事をしない」で成り立っているので、
    そこに例外を作らない。
    """
    bl_label = "Measure"
    bl_idname = "SEAMLESS_PT_MeasurePanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Seamless'
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return poll_main(context)

    def draw(self, context):
        layout = self.layout
        props = utils.get_active_props(context)

        # モディファイアの対象を選び直している最中は、カーネルが計算している
        # 形状が**そのモディファイアを適用する前**のものになる。
        # core_bridge が選択途中の中途半端な対象で適用しないよう、ターゲットを
        # 空で送っているため(_is_modifier_retargeting)。対象ゼロのフィレットは
        # 何もしないので、結果として素の形が返る。
        #
        # そのまま数字を出すと「Measure Active Part」がフィレット前の体積を
        # 平然と表示することになる。**測っている対象が違うと言うのが先。**
        retargeting = None
        active = core_bridge._get_active_preview_primitive(props)
        if active is not None and core_bridge._is_modifier_retargeting(props, active):
            retargeting = active.type
            box_warn = layout.box()
            box_warn.label(text=f"Picking targets for {retargeting}", icon='INFO')
            box_warn.label(text="Measurements below describe the shape")
            box_warn.label(text=f"BEFORE {retargeting} is applied.")
            box_warn.label(text="Exit Selection Mode for the finished part.")

        # --- 選択している辺/面 ---
        #
        # Part 全体より先に置く。選択モードで何かを摘まんでいるときは、
        # 知りたいのはたいてい「今つまんでいるもの」のほう。
        box_sel = layout.box()
        box_sel.operator("seamless.measure_selected", text="Measure Selection", icon='EDGESEL')

        state = props.measure_sel_state
        if state == 'UNRESOLVED':
            # 値は出さない。lineage が現在の形状に一致しないとき、近い別の辺の
            # 数字を出すのは「間違いを自信満々に表示する」ことになる。
            col = box_sel.column(align=True)
            col.label(text="Selection no longer matches", icon='ERROR')
            col.label(text="the current shape. Re-pick it.")
        elif state in {'EDGE', 'FACE'}:
            col = box_sel.column(align=True)
            label = "Face" if state == 'FACE' else "Edge"
            col.label(text=f"{label}: {props.measure_sel_shape}")
            if state == 'FACE':
                col.label(text=f"Area: {props.measure_sel_amount:.4f}")
            else:
                col.label(text=f"Length: {props.measure_sel_amount:.4f}")
            if props.measure_sel_radius > 0.0:
                col.label(text=f"Radius: {props.measure_sel_radius:.4f}", icon='SPHERECURVE')
            elif state == 'FACE':
                # 面取りは平面、可変フィレットは BSpline になる。半径が
                # 出ないことと、測れなかったことは違う。
                col.label(text="No constant radius")
            if props.measure_sel_count > 1:
                col.label(text=f"({props.measure_sel_count} picked; showing the last)")
        else:
            box_sel.label(text="Pick an edge or face in Selection Mode.", icon='INFO')

        layout.separator()

        # --- Part 全体 ---
        layout.operator("seamless.measure_part", text="Measure Active Part", icon='DRIVER_DISTANCE')

        if not props.measure_valid:
            layout.label(text="Not measured yet.", icon='INFO')
            return

        col = layout.column(align=True)

        # 体積 0 は測定失敗ではなく「閉じたソリッドではない」。ここで
        # 言わないと、ユーザーは計測が壊れていると解釈する。
        if props.measure_volume <= 1e-12:
            box = col.box()
            box.label(text="Not a closed solid", icon='ERROR')
            box.label(text="Volume is undefined for an open shell.")
        else:
            col.label(text=f"Volume: {props.measure_volume:.4f}", icon='MESH_CUBE')

        col.label(text=f"Surface area: {props.measure_area:.4f}", icon='MESH_GRID')

        col.separator()
        col.label(text="Size (X / Y / Z):")
        row = col.row(align=True)
        for v in props.measure_size:
            row.label(text=f"{v:.4f}")

        col.separator()
        col.label(text="Centre of mass:")
        row = col.row(align=True)
        for v in props.measure_centre:
            row.label(text=f"{v:.4f}")

        col.separator()
        # 1 Blender unit = 1 mm は STEP 書き出しの前提でもある
        # (docs/en/limitations.md)。単位を書かずに数字だけ出すと、
        # 体積が mm^3 なのか m^3 なのか判断できない。
        col.label(text="1 Blender unit = 1 mm on STEP export.", icon='INFO')
        col.label(text="Values are stale if you edited since measuring.")


class SEAMLESS_PT_SelectionPanel(bpy.types.Panel):
    bl_label = "Selection Mode"
    bl_idname = "SEAMLESS_PT_SelectionPanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Seamless'
    
    @classmethod
    def poll(cls, context):
        return poll_main(context)

    def draw(self, context):
        layout = self.layout
        props = utils.get_active_props(context)
        
        col = layout.column(align=True)
        sel_text = "EXIT Selection Mode" if props.is_selection_mode else "ENTER Selection Mode"
        col.operator("seamless.selection_modal", text=sel_text, icon='RESTRICT_SELECT_OFF', depress=props.is_selection_mode)
        if props.is_selection_mode:
            col.label(text="Hint: Hold [Alt] to use Gizmo", icon='INFO')
        
        row = col.row(align=True)
        row.prop(props, "selection_type", expand=True)


class SEAMLESS_PT_PlacementSnapPanel(bpy.types.Panel):
    bl_label = "Placement & Snap"
    bl_idname = "SEAMLESS_PT_PlacementSnapPanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Seamless'
    
    @classmethod
    def poll(cls, context):
        return poll_main(context)

    def draw(self, context):
        layout = self.layout
        props = utils.get_active_props(context)
        
        col = layout.column(align=True)
        col.prop(props, "use_snapping", text="Surface Snapping", toggle=True, icon='SNAP_FACE')
        col.operator("seamless.interactive_transform", text="Interactive Placement", icon='TRANSFORM_ORIGINS')
        col.operator("seamless.visual_snap", text="Visual Snap Move", icon='SNAP_ON')


class SEAMLESS_PT_CreatePanel(bpy.types.Panel):
    bl_label = "Create"
    bl_idname = "SEAMLESS_PT_CreatePanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Seamless'
    
    @classmethod
    def poll(cls, context):
        return poll_main(context)

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        
        row = col.row(align=True)
        row.operator("seamless.add_primitive", text="Box", icon='MESH_CUBE').type = 'BOX'
        row.operator("seamless.add_primitive", text="Cyl", icon='MESH_CYLINDER').type = 'CYLINDER'
        row.operator("seamless.add_primitive", text="Sph", icon='MESH_UVSPHERE').type = 'SPHERE'
        row.operator("seamless.add_primitive", text="Cone", icon='MESH_CONE').type = 'CONE'
        row.operator("seamless.add_primitive", text="Torus", icon='MESH_TORUS').type = 'TORUS'
        
        row = col.row(align=True)
        row.operator("seamless.add_primitive", text="Curv", icon='CURVE_BEZCURVE').type = 'CURVE'
        row.operator("seamless.add_primitive", text="Plin", icon='CURVE_PATH').type = 'POLYLINE'
        row.operator("seamless.add_primitive", text="Arc", icon='CURVE_NCIRCLE').type = 'ARC'
        row.operator("seamless.add_primitive", text="Surf", icon='SURFACE_DATA').type = 'SURFACE'
        row.operator("seamless.add_primitive", text="Slot", icon='LIGHT_DATA').type = 'SLOT'
        row.operator("seamless.add_primitive", text="Poly", icon='MESH_CIRCLE').type = 'POLYGON'
        row.operator("seamless.add_primitive", text="Gear", icon='SETTINGS').type = 'GEAR'
        row.operator("seamless.add_primitive", text="Helix", icon='MOD_SCREW').type = 'HELIX'
        row.operator("seamless.add_primitive", text="Rev", icon='MOD_SCREW').type = 'REVOLVE'
        
        row = col.row(align=True)
        row.operator("seamless.add_primitive", text="Sweep", icon='MOD_CURVE').type = 'SWEEP'
        row.operator("seamless.add_primitive", text="Loft", icon='SURFACE_NCURVE').type = 'LOFT'

        row_group = col.row(align=True)
        row_group.operator("seamless.add_primitive", text="Group (", icon='COLLECTION_NEW').type = 'GROUP_START'
        row_group.operator("seamless.add_primitive", text="Group )", icon='FILE_FOLDER').type = 'GROUP_END'
 
        row_sketch = col.row(align=True)
        row_sketch.operator("seamless.start_sketch", text="Start Sketch", icon='GREASEPENCIL')
        row_sketch.operator("seamless.select_reference_plane", text="on Face", icon='SNAP_FACE')
        col.operator("seamless.add_dynamic_loft_hole", text="Dynamic Box Hole", icon='SCULPTMODE_HLT')


class SEAMLESS_PT_ModifyPatternPanel(bpy.types.Panel):
    bl_label = "Modify & Pattern"
    bl_idname = "SEAMLESS_PT_ModifyPatternPanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Seamless'
    
    @classmethod
    def poll(cls, context):
        return poll_main(context)

    def draw(self, context):
        layout = self.layout
        
        layout.label(text="Modification:", icon='MODIFIER')
        row = layout.row(align=True)
        row.operator("seamless.add_primitive", text="Fillet", icon='MOD_BEVEL').type = 'FILLET'
        row.operator("seamless.add_primitive", text="Chamf", icon='MOD_BEVEL').type = 'CHAMFER'
        row.operator("seamless.add_primitive", text="Offset", icon='MOD_OFFSET').type = 'FACE_OFFSET'
        row.operator("seamless.add_primitive", text="Inset", icon='MOD_SOLIDIFY').type = 'FACE_INSET'
        row.operator("seamless.add_primitive", text="Draft", icon='MOD_SIMPLEDEFORM').type = 'DRAFT'
        row.operator("seamless.add_primitive", text="Shell", icon='MOD_SOLIDIFY').type = 'SHELL'
        row.operator("seamless.add_primitive", text="Face Loft", icon='SURFACE_NCURVE').type = 'FACE_LOFT'
        row.operator("seamless.add_primitive", text="Face Rev", icon='MOD_SCREW').type = 'FACE_REVOLVE'
        
        layout.label(text="Topology:", icon='MOD_DECIM')
        row = layout.row(align=True)
        row.operator("seamless.add_primitive", text="Cleanup (Unify)", icon='MOD_DECIM').type = 'CLEANUP'
        row.operator("seamless.force_recompute", text="", icon='FILE_REFRESH')

        layout.label(text="Layout & Patterns:", icon='OUTLINER_OB_GROUP_INSTANCE')
        row = layout.row(align=True)
        row.operator("seamless.add_primitive", text="Mirror", icon='MOD_MIRROR').type = 'MIRROR'
        row.operator("seamless.add_primitive", text="Array", icon='MOD_ARRAY').type = 'ARRAY_LINEAR'
        row.operator("seamless.add_primitive", text="Circ", icon='MOD_PARTICLES').type = 'ARRAY_CIRCULAR'
        row.operator("seamless.add_primitive", text="Link", icon='OUTLINER_OB_GROUP_INSTANCE').type = 'INSTANCE'


class SEAMLESS_PT_FeatureTreePanel(bpy.types.Panel):
    bl_label = "Feature Tree"
    bl_idname = "SEAMLESS_PT_FeatureTreePanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Seamless'
    
    @classmethod
    def poll(cls, context):
        return poll_main(context)

    def draw(self, context):
        layout = self.layout
        props = utils.get_active_props(context)
        
        box = layout.column(align=True)
        header = box.row(align=True)
        header.label(text="Selection")
        header.operator("seamless.group_selection", text="Group Selection", icon='FILE_FOLDER')

        nesting_level = 0
        for i, prim in enumerate(props.primitives):
            row = box.row(align=True)
            
            is_rolled_back = getattr(props, "rollback_index", -1) != -1 and i > getattr(props, "rollback_index", -1)
            is_active = (i == props.active_primitive_index)
            icon_active = 'RADIOBUT_ON' if is_active else 'RADIOBUT_OFF'
            
            sel_op_icon = row.operator("seamless.set_active_primitive", text="", icon=icon_active, emboss=False)
            sel_op_icon.index = i
            row.prop(prim, "group_selected", text="")
            
            if prim.type == 'GROUP_END':
                nesting_level = max(0, nesting_level - 1)
            
            icon = 'MESH_CUBE' if prim.type == 'BOX' else 'MESH_CYLINDER'
            if prim.type == 'STEP_PART': icon = 'FILE_3D'
            if prim.type == 'SVG_PART': icon = 'FILE_IMAGE'
            if prim.type == 'CURVE': icon = 'CURVE_BEZCURVE'
            if prim.type == 'ARC': icon = 'CURVE_NCIRCLE'
            if prim.type in {'FILLET', 'CHAMFER'}: icon = 'MOD_BEVEL'
            if prim.type in {'REVOLVE', 'HELIX', 'FACE_REVOLVE'}: icon = 'MOD_SCREW'
            if prim.type == 'MIRROR': icon = 'MOD_MIRROR'
            if prim.type.startswith('ARRAY'): icon = 'MOD_ARRAY'
            if prim.type == 'INSTANCE': icon = 'OUTLINER_OB_GROUP_INSTANCE'
            if prim.type == 'GROUP_START': icon = 'COLLECTION_NEW'
            if prim.type == 'GROUP_END': icon = 'FILE_FOLDER'
            if prim.type == 'CLEANUP': icon = 'MOD_DECIM'
            
            btn_row = row.row(align=True)
            if is_rolled_back:
                btn_row.enabled = False
            
            indent_str = "    " * nesting_level
            display_name = indent_str + prim.name
            sel_op_name = btn_row.operator("seamless.set_active_primitive", text=display_name, icon=icon, emboss=False)
            sel_op_name.index = i
            
            if prim.type == 'GROUP_START':
                nesting_level += 1
            
            if prim.type in {'CURVE', 'SURFACE', 'POLYLINE'} and i == props.active_primitive_index:
                pts_box = box.column(align=True)
                for j, pt in enumerate(prim.points):
                    prow = pts_box.row(align=True)
                    prow.prop(pt, "co", text=f"P{j}")
                    if prim.type == 'POLYLINE':
                        prow.prop(pt, "use_fillet", text="", icon='MOD_BEVEL', toggle=True)
                    op_add = prow.operator("seamless.add_curve_point_at", text="", icon='ADD')
                    op_add.prim_index = i
                    op_add.point_index = j + 1
                    op_del = prow.operator("seamless.remove_curve_point_at", text="", icon='X')
                    op_del.prim_index = i
                    op_del.point_index = j
                
                op_add_end = pts_box.operator("seamless.add_curve_point_at", text="Add Point", icon='ADD')
                op_add_end.prim_index = i
                op_add_end.point_index = len(prim.points)
            
            dup_op = btn_row.operator("seamless.duplicate_primitive", text="", icon='DUPLICATE')
            dup_op.index = i
            remove_op = btn_row.operator("seamless.remove_primitive", text="", icon='X')
            remove_op.index = i
            
            is_rollback_point = getattr(props, "rollback_index", -1) == i
            rb_icon = 'PINNED' if is_rollback_point else 'UNPINNED'
            rb_op = row.operator("seamless.set_rollback_index", text="", icon=rb_icon, depress=is_rollback_point)
            rb_op.index = i


class SEAMLESS_PT_PropertyEditorPanel(bpy.types.Panel):
    bl_label = "Active Property Editor"
    bl_idname = "SEAMLESS_PT_PropertyEditorPanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Seamless'
    
    @classmethod
    def poll(cls, context):
        props = utils.get_active_props(context)
        if not poll_main(context): return False
        return bool(props and props.primitives and 0 <= props.active_primitive_index < len(props.primitives))

    def draw(self, context):
        layout = self.layout
        props = utils.get_active_props(context)
        idx = props.active_primitive_index
        active_prim = props.primitives[idx]
        
        # Header
        col = layout.column(align=True)
        
        row = col.row(align=True)
        row.label(text=f"Active: {active_prim.name}", icon='EDITMODE_HLT')
        col.prop(active_prim, "operation") 
        
        if active_prim.operation == 'BASE' and idx > 0:
            row_sep = col.row(align=True)
            row_sep.alert = True
            op = row_sep.operator("seamless.separate_by_base", text="Separate Previous to New Part", icon='MOD_EXPLODE')
            op.index = idx

        # V8.1.5: スケッチ編集履歴 - このprimitiveがスケッチのfinalizeで生成された場合のみ表示
        if getattr(active_prim, "sketch_source_uuid", ""):
            row_edit = col.row(align=True)
            hidden_by_rollback = 0 <= props.rollback_index < idx
            row_edit.enabled = not hidden_by_rollback
            op = row_edit.operator("seamless.edit_sketch", text="Edit Sketch", icon='GREASEPENCIL')
            op.prim_index = idx
            if hidden_by_rollback:
                col.label(text="Hidden by rollback point", icon='INFO')

        col = layout.column(align=True)
        
        if active_prim.type in {'FILLET', 'CHAMFER', 'FACE_OFFSET', 'FACE_INSET', 'DRAFT', 'SHELL', 'FACE_LOFT', 'FACE_REVOLVE'}:
            label = "Radius" if active_prim.type not in {'FACE_LOFT', 'FACE_REVOLVE'} else ""
            if active_prim.type == 'FILLET': label = "Fillet Radius"
            elif active_prim.type == 'CHAMFER': label = "Chamfer Distance"
            elif active_prim.type == 'FACE_OFFSET': label = "Offset Distance"
            elif active_prim.type == 'FACE_INSET': label = "Inset Distance"
            elif active_prim.type == 'DRAFT': label = "Draft Angle"
            elif active_prim.type == 'SHELL': label = "Thickness"
            
            if active_prim.type not in {'FACE_LOFT', 'FACE_REVOLVE'}:
                if active_prim.type == 'FACE_OFFSET':
                    row = col.row(align=True)
                    row.prop(active_prim, "radius", text=label)
                    op = row.operator("seamless.interactive_offset_pick", text="", icon='EYEDROPPER')
                    op.index = idx
                    # 明示すること。既定値任せにすると、直前に Inset の
                    # スポイトを使った後で extrude_height が残り、拾った値が
                    # このパネルに出ないプロパティへ入る
                    op.depth_attr = "radius"
                else:
                    col.prop(active_prim, "radius", text=label)
            
            if active_prim.type == 'FACE_INSET':
                row = col.row(align=True)
                row.prop(active_prim, "extrude_height", text="Depth (Push/Pull)")
                op = row.operator("seamless.interactive_offset_pick", text="", icon='EYEDROPPER')
                op.index = idx
                op.depth_attr = "extrude_height"

                # Inset は平らな面が要る。内側へのオフセットに平面ワイヤーの
                # 処理を使っており(occ_modifiers.cpp の BRepOffsetAPI_MakeOffset)、
                # 円柱面や円錐面では成立せず**何も起きずに終わる**。エラーも
                # 出ないので「効かない」としか見えない(2026-08-14 報告)。
                #
                # **見出し行そのものを事実にしてある。** 詳細だけを畳むのが要点で、
                # 全部を畳むと必要な人に届かない --- 「押したのに何も起きない」と
                # 思っている人が、その前に注意書きを開くことはまずない。
                row_note = col.row(align=True)
                row_note.prop(
                    props, "show_inset_note",
                    icon='TRIA_DOWN' if props.show_inset_note else 'TRIA_RIGHT',
                    text="Needs a flat face", emboss=False,
                )
                if props.show_inset_note:
                    box_note = col.box()
                    box_note.label(text="On the curved side of a cylinder or")
                    box_note.label(text="cone, Inset has no effect at all.")
                    box_note.label(text="Flat ends and box faces are fine.")
                
            if active_prim.type == 'DRAFT':
                box_mod = col.column(align=True)
                box_mod.label(text="Neutral Plane (Reference):", icon='ORIENTATION_LOCAL')
                row = box_mod.row(align=True)
                row.prop(active_prim, "reference_lineage", text="")
                op = row.operator("seamless.selection_modal", text="", icon='RESTRICT_SELECT_OFF')
                box_mod.prop(props, "is_selecting_reference", text="Click Face to Set Neutral", toggle=True, icon='MOUSE_LMB')
                
                col.prop(active_prim, "target_lineages", text="Faces to Taper")
                if not active_prim.reference_lineage or not active_prim.target_lineages:
                    col.label(text="Select base face and draft face", icon='INFO')
            elif active_prim.type == 'SHELL':
                col.prop(active_prim, "target_lineages", text="Faces to Remove")
                if not active_prim.target_lineages:
                    col.label(text="Select face to open", icon='INFO')
            else:
                col.prop(active_prim, "target_lineages", text="Targets")
                if not active_prim.target_lineages:
                    col.label(text="Select components in viewport (Shift+Click)", icon='RESTRICT_SELECT_OFF')

            if active_prim.type == 'FILLET' and len(active_prim.edge_radii) > 0:
                er_box = col.column(align=True)
                er_box.label(text="Per-Edge Radius (Variable Fillet):", icon='MOD_BEVEL')
                for er_idx, er in enumerate(active_prim.edge_radii):
                    er_row = er_box.row(align=True)
                    er_row.label(text=f"Edge {er_idx + 1}")
                    use_default = er.radius < 0.0
                    default_toggle = er_row.operator(
                        "seamless.toggle_fillet_edge_default",
                        text="Use Default" if use_default else "Custom",
                        depress=not use_default,
                    )
                    default_toggle.prim_index = idx
                    default_toggle.edge_index = er_idx
                    if not use_default:
                        er_row.prop(er, "radius", text="")

        if active_prim.type not in {'FILLET', 'CHAMFER', 'FACE_OFFSET', 'FACE_INSET', 'DRAFT', 'SHELL', 'FACE_LOFT'}:
            row = col.row(align=True)
            row.label(text="Transform:", icon='ORIENTATION_GLOBAL')
            
            col_g = col.column(align=True)
            row = col_g.row(align=True)
            row.label(text="Global:", icon='WORLD')
            if active_prim.type in {'MIRROR', 'ARRAY_LINEAR', 'ARRAY_CIRCULAR', 'REVOLVE', 'INSTANCE'}:
                row.prop(active_prim, "use_independent_transform", text="Independent", toggle=True, icon='CON_TRANSLIKE')
            col_g.prop(active_prim, "location", text="")
            
            col_l = col.column(align=True)
            col_l.label(text="Local Offset:", icon='ORIENTATION_PARENT')
            col_l.prop(active_prim, "local_location", text="")
            
            col_tf = col.column(align=True)
            col_tf.prop(active_prim, "rotation")

        if active_prim.type in {'MIRROR', 'ARRAY_LINEAR', 'ARRAY_CIRCULAR', 'REVOLVE', 'INSTANCE'}:
            box_pat = col.column(align=True)
            box_pat.label(text="Pattern/Link Setup:", icon='LINKED')
            
            if active_prim.type == 'INSTANCE':
                box_pat.prop(active_prim, "target_collection", text="Target Part (Col)")
                if active_prim.target_collection:
                    box_pat.label(text=f"Part Address: {active_prim.target_uuid}", icon='LINKED')
                else:
                    box_pat.label(text="Select a CAD part (Collection) to insert", icon='INFO')
            else:
                row = box_pat.row(align=True)
                row.prop(active_prim, "target_uuid", text="Target UUID")
                op_pick_list = row.operator("seamless.pick_active_as_target", text="", icon='COLLAPSEMENU')
                op_pick_list.index = idx
                op_pick_list.prop_name = 'target_uuid'
                op_pick_view = row.operator("seamless.pick_target_modal", text="", icon='EYEDROPPER')
                op_pick_view.index = idx
                op_pick_view.prop_name = 'target_uuid'
            
            target_name = "None"
            if active_prim.target_uuid:
                target = next((p.name for p in props.primitives if p.uuid == active_prim.target_uuid), "Unknown")
                target_name = target
            box_pat.label(text=f"Target: {target_name}", icon='LINKED')
            
            if active_prim.type == 'REVOLVE':
                box_pat.prop(active_prim, "pattern_axis", text="Rotation Axis")
                box_pat.prop(active_prim, "distance", text="Total Angle")
            elif active_prim.type == 'MIRROR':
                box_pat.prop(active_prim, "pattern_axis", text="Mirror Plane")
            elif active_prim.type == 'ARRAY_LINEAR':
                box_pat.prop(active_prim, "count", text="Copies")
                box_pat.prop(active_prim, "distance", text="Spacing")
                box_pat.prop(active_prim, "pattern_axis", text="Direction")
            elif active_prim.type == 'ARRAY_CIRCULAR':
                box_pat.prop(active_prim, "count", text="Copies")
                box_pat.prop(active_prim, "distance", text="Total Angle")
                box_pat.prop(active_prim, "pattern_axis", text="Rotation Axis")
            

        elif active_prim.type == 'STEP_PART':
            box_step = col.column(align=True)
            box_step.label(text="STEP Import:", icon='FILE_3D')
            box_step.prop(active_prim, "step_scale", text="Scale")
            box_step.prop(active_prim, "target_uuid", text="STEP Cache ID")
            box_step.prop(active_prim, "step_source_index", text="Part Index")
            if active_prim.step_source_path:
                box_step.prop(active_prim, "step_source_path", text="Source File")
            else:
                box_step.label(text="No STEP source file recorded", icon='ERROR')

        elif active_prim.type == 'SVG_PART':
            box_svg = col.column(align=True)
            box_svg.label(text="SVG Import:", icon='FILE_IMAGE')
            box_svg.prop(active_prim, "step_scale", text="Scale")
            box_svg.prop(active_prim, "target_uuid", text="SVG Cache ID")
            if active_prim.step_source_path:
                box_svg.prop(active_prim, "step_source_path", text="Source File")
            else:
                box_svg.label(text="No SVG source file recorded", icon='ERROR')
                
            box_svg.separator()
            row = box_svg.row(align=True)
            row.prop(active_prim, "fill_closed")
            row.prop(active_prim, "use_pipe", toggle=True, icon='MOD_SOLIDIFY')
            if active_prim.use_pipe:
                box_svg.prop(active_prim, "pipe_radius")
            if not active_prim.use_pipe:
                box_svg.prop(active_prim, "extrude_height")

        elif active_prim.type == 'SWEEP':
            box_pat = col.column(align=True)
            box_pat.label(text="Sweep Setup:", icon='MOD_CURVE')
            
            row = box_pat.row(align=True)
            row.prop(active_prim, "target_lineages", text="Profile")
            op1 = row.operator("seamless.pick_active_as_target", text="", icon='COLLAPSEMENU')
            op1.index = idx
            op1.prop_name = 'target_lineages'
            op1_m = row.operator("seamless.selection_modal", text="", icon='RESTRICT_SELECT_OFF', depress=props.is_selection_mode)

            row = box_pat.row(align=True)
            row.prop(active_prim, "sweep_path_uuid", text="Path")
            op2 = row.operator("seamless.pick_active_as_target", text="", icon='COLLAPSEMENU')
            op2.index = idx
            op2.prop_name = 'sweep_path_uuid'
            op2_m = row.operator("seamless.pick_target_modal", text="", icon='EYEDROPPER')
            op2_m.index = idx
            op2_m.prop_name = 'sweep_path_uuid'
            
            profile_val = active_prim.target_lineages
            if not profile_val: profile_val = active_prim.sweep_profile_uuid 
            profile_name = profile_val.split("@")[0] if (profile_val.startswith("Face:") or profile_val.startswith("Edge:")) else next((p.name for p in props.primitives if p.uuid == profile_val), "None")
                
            path_val = active_prim.sweep_path_uuid
            path_name = path_val.split("@")[0] if (path_val.startswith("Face:") or path_val.startswith("Edge:")) else next((p.name for p in props.primitives if p.uuid == path_val), "None")
                
            box_pat.label(text=f"Profile: {profile_name} | Path: {path_name}", icon='INFO')
            box_pat.prop(active_prim, "sweep_frame_mode", text="Frame")
            if active_prim.sweep_frame_mode == 'HELIX_AXIS':
                box_pat.prop(active_prim, "sweep_roll_degrees", text="Roll / Turn")
            
        elif active_prim.type == 'LOFT':
            box_pat = col.column(align=True)
            box_pat.label(text="Loft Setup:", icon='SURFACE_NCURVE')
            
            row = box_pat.row(align=True)
            row.prop(active_prim, "loft_uuids", text="Sections")
            op1 = row.operator("seamless.pick_active_as_target", text="", icon='ADD')
            op1.index = idx
            op1.prop_name = 'loft_uuids'
            op1_m = row.operator("seamless.pick_target_modal", text="", icon='EYEDROPPER')
            op1_m.index = idx
            op1_m.prop_name = 'loft_uuids'

            uuids = [u.strip() for u in active_prim.loft_uuids.split("|") if u.strip()]
            names = [next((p.name for p in props.primitives if p.uuid == u), "Unknown") for u in uuids]
            box_pat.label(text=f"Profiles: {', '.join(names)}", icon='INFO')

        elif active_prim.type == 'FACE_REVOLVE':
            box_pat = col.column(align=True)
            box_pat.label(text="Face Revolve Setup:", icon='MOD_SCREW')
            box_pat.prop(active_prim, "pattern_axis", text="Rotation Axis")
            box_pat.prop(active_prim, "distance", text="Total Angle")

        # ここは「専用の UI を持たない型」の受け皿。専用ブロックを持つ型は必ず
        # この集合に入れること。入れ忘れるとここで吸い込まれ、下の専用ブロックが
        # 永久に実行されない。CLEANUP が実際そうなっていて、無関係な size が出ていた。
        elif active_prim.type not in {'FILLET', 'CHAMFER', 'FACE_OFFSET', 'FACE_INSET', 'DRAFT', 'SHELL', 'FACE_LOFT', 'FACE_REVOLVE', 'SLOT', 'CONE', 'TORUS', 'POLYGON', 'GEAR', 'VARIABLE_BOX', 'SWEEP', 'LOFT', 'HELIX', 'POLYLINE', 'CLEANUP', 'GROUP_START', 'GROUP_END'}:
            # ARC は make_arc(radius, a_start, a_end) だけで作られ size を読まない。
            # 大きさは Radius で決まるので、size を出すと死んだ欄になる。
            if active_prim.type != 'ARC':
                col.prop(active_prim, "size")
            # radius を出すのは、カーネルが実際に読む型だけにする。
            # この分岐に入る型のうち radii[i] を使うのは ARC だけ
            # (occ_core.cpp: make_arc(radii[i], ...))。CYLINDER と SPHERE は
            # make_cylinder(sx,sy,sz) / make_sphere(sx,sy,sz) で size からしか
            # 作られないため、Radius を出すと「触っても何も起きない欄」になる。
            # 大きさは size で変える。CONE/TORUS/SLOT/POLYGON/HELIX 等は
            # 上の除外リストに入っていて、それぞれ専用の UI を持つ。
            if active_prim.type == 'ARC':
                col.prop(active_prim, "radius")

            if active_prim.type in {'CURVE', 'SURFACE', 'ARC'}:
                row = col.row(align=True)
                row.prop(active_prim, "fill_closed")
                row.prop(active_prim, "use_pipe", toggle=True, icon='MOD_SOLIDIFY')
                if active_prim.use_pipe:
                    col.prop(active_prim, "pipe_radius")
                if not active_prim.use_pipe:
                    col.prop(active_prim, "extrude_height")
                if active_prim.type == 'ARC':
                    row = col.row(align=True)
                    row.prop(active_prim, "angle_start")
                    row.prop(active_prim, "angle_end")
        
        elif active_prim.type == 'POLYLINE':
            col.prop(active_prim, "radius", text="Fillet Radius")
            row = col.row(align=True)
            row.prop(active_prim, "fill_closed")
            row.prop(active_prim, "use_pipe", toggle=True, icon='MOD_SOLIDIFY')
            if active_prim.use_pipe:
                col.prop(active_prim, "pipe_radius")
            if not active_prim.use_pipe:
                col.prop(active_prim, "extrude_height")
        
        elif active_prim.type == 'VARIABLE_BOX':
            box_top = col.column(align=True)
            box_top.label(text="Top Profile:")
            box_top.row().prop(active_prim, "top_shape", expand=True)
            if active_prim.top_shape == 'BOX':
                # size.z は出さない。ペイロード側で高さ(extrude_height)に
                # 上書きされるので、ここに出すと「触っても何も起きない欄」になる。
                # 高さはこのブロック末尾の "Height" が担当する。
                box_top.prop(active_prim, "size", index=0, text="Width")
                box_top.prop(active_prim, "size", index=1, text="Depth")
            else:
                box_top.prop(active_prim, "size", text="Radius", index=0)
            
            box_bot = col.column(align=True)
            box_bot.label(text="Bottom Profile:")
            box_bot.row().prop(active_prim, "bot_shape", expand=True)
            if active_prim.bot_shape == 'BOX':
                row = box_bot.row(align=True)
                row.prop(active_prim, "radius", text="W")
                row.prop(active_prim, "radius2", text="H")
            else:
                box_bot.prop(active_prim, "radius", text="Radius")
            
            col.prop(active_prim, "extrude_height", text="Height")

        elif active_prim.type == 'SLOT':
            col.prop(active_prim, "radius", text="End Radius")
            # size は3成分あるが make_slot(radii[i], sx) が使うのは X だけ。
            # 3つ並べると Y/Z が「触っても何も起きない欄」になるので X のみ出す。
            col.prop(active_prim, "size", index=0, text="Center-to-Center")
            col.prop(active_prim, "extrude_height", text="Thickness")

        elif active_prim.type == 'CONE':
            col.prop(active_prim, "radius", text="Base Radius")
            col.prop(active_prim, "radius2", text="Top Radius")
            # make_cone(radii[i], radii2[i], sz) が使うのは Z だけ。
            # ラベルが "Height (Z)" なのに X/Y も並んでいて紛らわしかった。
            col.prop(active_prim, "size", index=2, text="Height (Z)")
        
        elif active_prim.type == 'TORUS':
            col.prop(active_prim, "radius", text="Major Radius")
            col.prop(active_prim, "minor_radius", text="Minor Radius")
        
        elif active_prim.type == 'POLYGON':
            col.prop(active_prim, "radius", text="Radius")
            col.prop(active_prim, "sides", text="Sides")
            col.prop(active_prim, "extrude_height", text="Thickness")
        
        elif active_prim.type == 'GEAR':
            col.prop(active_prim, "module", text="Module")
            col.prop(active_prim, "sides", text="Teeth")
            col.prop(active_prim, "pressure_angle", text="Pressure Angle")
            col.prop(active_prim, "extrude_height", text="Thickness")
        
        elif active_prim.type == 'HELIX':
            col.prop(active_prim, "radius", text="Radius")
            col.prop(active_prim, "extrude_height", text="Height")
            col.prop(active_prim, "turns", text="Turns")
            
            row = col.row(align=True)
            row.prop(active_prim, "use_pipe", toggle=True, icon='MOD_SOLIDIFY')
            if active_prim.use_pipe:
                col.prop(active_prim, "pipe_radius")
                
        elif active_prim.type == 'CLEANUP':
            # unify_faces / unify_edges のチェックボックスは出さない。
            # カーネルの呼び出しが ShapeUpgrade_UnifySameDomain(mod_c, true, true, true) の
            # べた書きで、送られてきた値を読んでいない(cargo build も
            # "fields `unify_faces` and `unify_edges` are never read" と警告する)。
            # つまり触っても何も起きない欄だった。常に両方効くので、その旨を書く。
            #
            # プロパティ自体は properties.py に残してある。片方だけ効かせたい要求が
            # 実際に出たら、C++ 側の FFI シグネチャに2つ足して配線すれば UI を戻すだけで済む。
            # ただし引数の並びがずれると全プリミティブが壊れるので、やるなら慎重に。
            col.label(text="Merges coplanar faces and", icon='INFO')
            col.label(text="collinear edges. Always both.")
