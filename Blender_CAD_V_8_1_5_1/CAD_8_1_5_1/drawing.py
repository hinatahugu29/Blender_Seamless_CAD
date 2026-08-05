import bpy
import gpu
import time
import mathutils
import numpy as np
from gpu_extras.batch import batch_for_shader
from .core.semantic_targets import get_display_edge_targets
from . import utils

class StackRenderData:
    def __init__(self):
        self.coords = []
        self.edge_indices = []
        self.lineages = []
        self.batch = None
        self.vbo = None
        self.ibo = None
        self.face_vbo_main = None
        self.face_ibo_main = None
        self.batch_sel = None
        self.batch_pre = None
        self.batch_mod = None
        self.matrix = mathutils.Matrix.Identity(4)
        
        # 面データのキャッシュ
        self._cache_verts = None
        self._cache_tris = None
        self._cache_fids = None
        self._cache_counts = None
        self._face_geom_signature = None
        self.face_batch_main = None
        self.face_vbo_static = None
        self.face_vbo_static_size = 0
        self.face_batch_static = None
        self.face_vbo_moving = None
        self.face_vbo_moving_size = 0
        self.face_batch_moving = None
        self.face_vbo_main_size = 0

        # V8.1.5: ブーリアンのゴーストプレビュー(削除/追加される体積の半透明表示)。
        # ドラッグ中のみ _csg_preview_tick で更新され、settle時に必ずNoneへ戻す。
        self.face_batch_ghost = None
        self.ghost_op = None

class SeamlessWireframeManager:
    def __init__(self):
        # stack_ptr ごとに描画用バッチなどのデータを保持する辞書
        self.stacks = {}
        self.shader = None
        self.face_shader = None
        self.wgpu_shader = None
        
        self.face_coords = []
        self.face_colors = {}
        
        self.wgpu_tex = None
        self.wgpu_batch = None
        self.wgpu_batch_size = (0, 0)
        self._overlay_dirty = True
        self._overlay_last_signature = None
        self._overlay_last_render_time = 0.0
        self._overlay_min_interval = 1.0 / 30.0
        
        self._handler = None
        self.enabled = True
        
        # スナップマーカー用
        self.snap_pos = None
        self.snap_type = "" # "VERTEX", "MIDPOINT", "CENTER"
        self.transient_batch = None
        self.hidden_primitive_uuids = set()

    def get_stack(self, stack_ptr):
        try:
            stack_ptr = int(stack_ptr)
        except (ValueError, TypeError):
            stack_ptr = 0
        if stack_ptr not in self.stacks:
            self.stacks[stack_ptr] = StackRenderData()
        return self.stacks[stack_ptr]

    def _make_face_geom_signature(self, verts_flat, tris_flat, face_ids, tri_counts):
        try:
            v_len = len(verts_flat) if verts_flat is not None else 0
            t_len = len(tris_flat) if tris_flat is not None else 0
            f_len = len(face_ids) if face_ids is not None else 0
            c_len = len(tri_counts) if tri_counts is not None else 0
            if v_len == 0 or t_len == 0:
                return (v_len, t_len, f_len, c_len)

            if isinstance(verts_flat, np.ndarray):
                v_arr = verts_flat.reshape(-1)
            else:
                v_arr = np.asarray(verts_flat, dtype=np.float32).reshape(-1)
            if isinstance(tris_flat, np.ndarray):
                t_arr = tris_flat.reshape(-1)
            else:
                t_arr = np.asarray(tris_flat, dtype=np.int32).reshape(-1)
            if isinstance(tri_counts, np.ndarray):
                c_arr = tri_counts.reshape(-1)
            else:
                c_arr = np.asarray(tri_counts, dtype=np.int32).reshape(-1)

            v_head = tuple(np.round(v_arr[:6], 5).tolist())
            v_tail = tuple(np.round(v_arr[-6:], 5).tolist()) if v_len >= 6 else v_head
            t_head = tuple(t_arr[:6].tolist())
            t_tail = tuple(t_arr[-6:].tolist()) if t_len >= 6 else t_head
            c_sum = int(c_arr.sum()) if c_len > 0 else 0
            fid_head = tuple(str(x) for x in list(face_ids[:3])) if f_len > 0 else ()
            fid_tail = tuple(str(x) for x in list(face_ids[-3:])) if f_len > 3 else fid_head

            return (v_len, t_len, f_len, c_len, c_sum, v_head, v_tail, t_head, t_tail, fid_head, fid_tail)
        except Exception:
            return None

    def init_shaders(self):
        import bpy
        if bpy.app.background:
            return False
        try:
            if self.shader is None:
                try:
                    self.shader = gpu.shader.from_builtin('UNIFORM_COLOR')
                except Exception:
                    self.shader = gpu.shader.from_builtin('UNIFORM_COLOR')
            if self.face_shader is None:
                try:
                    self.face_shader = gpu.shader.from_builtin('3D_SMOOTH_COLOR')
                except Exception:
                    self.face_shader = gpu.shader.from_builtin('SMOOTH_COLOR')
            if self.wgpu_shader is None:
                try:
                    self.wgpu_shader = gpu.shader.from_builtin('2D_IMAGE')
                except Exception:
                    self.wgpu_shader = gpu.shader.from_builtin('IMAGE')
            return True
        except Exception:
            return False

    def draw_wgpu_overlay(self, context, opacity=0.3):
        if not self.enabled: return
        region = context.region
        width, height = region.width, region.height
        
        # Blenderの行列を取得 (View * Projection)
        matrix = context.region_data.perspective_matrix
        vp_list = [matrix[i][j] for i in range(4) for j in range(4)]
        signature = (width, height, tuple(round(v, 5) for v in vp_list))
        
        from .core_bridge import get_core
        core = get_core()
        if not core or not hasattr(core, "render_viewport"): return
        
        try:
            # Rust側でレンダリングを実行しピクセルデータをバイナリで受け取る
            now = time.perf_counter()
            elapsed = now - self._overlay_last_render_time
            # The interval is a throttle, not a trigger. It used to be OR'd in
            # with the other conditions, so an idle viewport still re-rendered
            # the whole overlay 30 times a second: a Rust offscreen render, a
            # GPU->CPU readback and a freshly allocated full-screen texture each
            # time. That churn is what dragged whole machines down.
            refresh_reasons = []
            if self._overlay_dirty:
                refresh_reasons.append("dirty")
            if self.wgpu_tex is None:
                refresh_reasons.append("no-texture")
            if self._overlay_last_signature != signature:
                refresh_reasons.append("signature-changed")

            should_refresh = bool(refresh_reasons)
            if should_refresh and self.wgpu_tex is not None and not self._overlay_dirty:
                # Camera moves are paced; only a data change bypasses the pace.
                if elapsed < self._overlay_min_interval:
                    should_refresh = False
            if should_refresh:
                utils.debug_print(
                    "WGPU overlay refresh: "
                    f"reasons={','.join(refresh_reasons) or 'unknown'} "
                    f"size={width}x{height}"
                )
                
                is_sdf_preview = getattr(context.scene, "is_sdf_preview_mode", False)
                if is_sdf_preview and hasattr(core, "render_viewport_sdf"):
                    inv_matrix = matrix.inverted()
                    inv_vp_list = [inv_matrix[i][j] for i in range(4) for j in range(4)]
                    
                    camera_matrix = context.region_data.view_matrix.inverted()
                    camera_pos = [camera_matrix.translation.x, camera_matrix.translation.y, camera_matrix.translation.z]
                    
                    fillet_radius = getattr(context.scene, "sdf_preview_fillet_radius", 0.1)
                    box_size = getattr(context.scene, "sdf_preview_box_size", (1.0, 1.0, 1.0))
                    
                    pixels_bytes = core.render_viewport_sdf(width, height, vp_list, inv_vp_list, camera_pos, fillet_radius, list(box_size))
                else:
                    pixels_bytes = core.render_viewport(width, height, vp_list)
                    
                if not pixels_bytes:
                    return
                pixels_len = len(pixels_bytes)
                expected_u8_size = width * height * 4
                # Drop the previous texture before allocating the replacement,
                # so the driver never has to hold two full-screen textures at
                # once while Python's collector catches up.
                self.wgpu_tex = None

                if pixels_len == expected_u8_size:
                    tex = None
                    try:
                        # 8 bits per channel is what the renderer produced, so
                        # RGBA8 is lossless here and a quarter of the VRAM of
                        # the RGBA32F copy this used to expand into.
                        buffer = gpu.types.Buffer('UBYTE', (height, width, 4), pixels_bytes)
                        tex = gpu.types.GPUTexture((width, height), format='RGBA8', data=buffer)
                    except Exception:
                        import numpy as np
                        arr = np.frombuffer(pixels_bytes, dtype=np.uint8).astype(np.float32) / 255.0
                        buffer = gpu.types.Buffer('FLOAT', (height, width, 4), arr)
                        tex = gpu.types.GPUTexture((width, height), format='RGBA32F', data=buffer)
                    self.wgpu_tex = tex
                else:
                    floats_view = memoryview(pixels_bytes).cast('f')
                    buffer = gpu.types.Buffer('FLOAT', (height, width, 4), floats_view)
                    self.wgpu_tex = gpu.types.GPUTexture((width, height), format='RGBA32F', data=buffer)
                self._overlay_last_signature = signature
                self._overlay_last_render_time = now
                self._overlay_dirty = False
            else:
                utils.debug_print(
                    "WGPU overlay cache reuse: "
                    f"size={width}x{height} age={(now - self._overlay_last_render_time):.4f}s"
                )
            
            # バッチの初期化/更新
            if not self.wgpu_batch or self.wgpu_batch_size != (width, height):
                self.wgpu_batch = batch_for_shader(
                    self.wgpu_shader, 'TRI_FAN',
                    {"pos": [(-1, -1), (1, -1), (1, 1), (-1, 1)],
                     "texCoord": [(0, 1), (1, 1), (1, 0), (0, 0)]} # Y-Flip
                )
                self.wgpu_batch_size = (width, height)
            
            # スクリーンスペースブリット: 深度テスト不要（Rust側で処理済み）
            gpu.state.depth_test_set('NONE')
            gpu.state.blend_set('ALPHA')

            try:
                self.wgpu_shader.bind()
                from mathutils import Matrix
                self.wgpu_shader.uniform_float("ModelViewProjectionMatrix", Matrix.Identity(4))
                self.wgpu_shader.uniform_sampler("image", self.wgpu_tex)
                self.wgpu_batch.draw(self.wgpu_shader)
            finally:
                gpu.state.depth_test_set('LESS_EQUAL')
                gpu.state.blend_set('NONE')
            
        except Exception as e:
            utils.error_print(f"WGPU Overlay Draw Error: {e}")

    def set_transform_delta(self, stack_ptr, matrix):
        stack = self.get_stack(stack_ptr)
        stack.matrix = matrix if matrix is not None else mathutils.Matrix.Identity(4)

    def clear(self, stack_ptr=None):
        if stack_ptr is not None:
            try:
                s_ptr = int(stack_ptr)
                if s_ptr in self.stacks:
                    del self.stacks[s_ptr]
            except (ValueError, TypeError):
                pass
        else:
            self.stacks.clear()
        self._overlay_dirty = True
        self._overlay_last_signature = None

    def update_data(self, stack_ptr, points, counts, lineages):
        self.set_transform_delta(stack_ptr, None)
        self.hidden_primitive_uuids.clear()
        self._overlay_dirty = True
        if not self.init_shaders(): return
        if len(points) == 0:
            self.clear(stack_ptr)
            return
            
        stack = self.get_stack(stack_ptr)
        stack.lineages = list(lineages) if lineages else []
        if isinstance(points, np.ndarray):
            stack.coords = points.reshape(-1, 3).tolist()
        else:
            stack.coords = [(points[i], points[i+1], points[i+2]) for i in range(0, len(points), 3)]
        
        stack.edge_indices = []
        all_line_indices = []
        offset = 0
        for c in counts:
            edge_idx = []
            for i in range(c - 1):
                idx = offset + i
                pair = (idx, idx + 1)
                edge_idx.append(pair)
                all_line_indices.append(pair)
            stack.edge_indices.append(edge_idx)
            offset += c
        
        if all_line_indices and stack.coords:
            try:
                stack.batch = batch_for_shader(self.shader, 'LINES', {"pos": stack.coords}, indices=all_line_indices)
            except Exception as e:
                stack.batch = None
                utils.error_print(f"Seamless CAD: batch_for_shader error: {e}")
            
        # Also clear the highlight batches so old indices aren't drawn over new geometry
        stack.batch_sel = None
        stack.batch_pre = None
        stack.batch_mod = None

    def update_ghost_batch(self, stack_ptr, verts_flat, tris_flat, op):
        """V8.1.5: ブーリアンのゴーストプレビュー(削除/追加される体積)の半透明バッチを構築する。
        verts_flat/tris_flatが空、またはNoneの場合はゴーストバッチをクリアする
        (settle時や旧サーバー応答でghostデータが無い場合に必ず呼ばれる想定)。"""
        if not self.init_shaders(): return
        stack = self.get_stack(stack_ptr)
        if verts_flat is None or tris_flat is None or len(verts_flat) == 0 or len(tris_flat) == 0:
            stack.face_batch_ghost = None
            stack.ghost_op = None
            return
        try:
            if isinstance(verts_flat, np.ndarray):
                flat_verts = verts_flat.reshape(-1, 3)
            else:
                flat_verts = np.array(verts_flat, dtype=np.float32).reshape(-1, 3)
            if isinstance(tris_flat, np.ndarray):
                indices = tris_flat.reshape(-1, 3).tolist()
            else:
                indices = [(tris_flat[i], tris_flat[i+1], tris_flat[i+2]) for i in range(0, len(tris_flat), 3)]

            op_u = str(op).upper()
            if op_u in ("ADD", "UNION", "FUSE"):
                color = (0.1, 1.0, 0.2, 0.45)  # 追加される体積: 緑
            else:
                color = (1.0, 0.15, 0.1, 0.45)  # 削除される体積(SUB既定): 赤
            colors = np.tile(np.array(color, dtype=np.float32), (len(flat_verts), 1))

            shader = self.face_shader
            stack.face_batch_ghost = batch_for_shader(shader, 'TRIS', {"pos": flat_verts, "color": colors}, indices=indices)
            stack.ghost_op = op_u
        except Exception as e:
            utils.error_print(f"Seamless CAD: update_ghost_batch error: {e}")
            stack.face_batch_ghost = None
            stack.ghost_op = None

    def update_face_data(self, stack_ptr, verts_flat, tris_flat, face_ids, tri_counts, opacity=0.3, selected_f_ids=None, preselected_f_id="", modifier_f_ids=None, reference_f_ids=None):
        self.set_transform_delta(stack_ptr, None)
        self._overlay_dirty = True
        stack = self.get_stack(stack_ptr)
        new_signature = self._make_face_geom_signature(verts_flat, tris_flat, face_ids, tri_counts)
        if stack._face_geom_signature is not None and new_signature is not None and stack._face_geom_signature == new_signature:
            self.refresh_face_colors(
                stack_ptr,
                opacity=opacity,
                selected_f_ids=selected_f_ids,
                preselected_f_id=preselected_f_id,
                modifier_f_ids=modifier_f_ids,
                reference_f_ids=reference_f_ids,
            )
            return
        stack._cache_verts = verts_flat
        stack._cache_tris = tris_flat
        stack._cache_fids = face_ids
        stack._cache_counts = tri_counts
        stack._face_geom_signature = new_signature
        
        self._rebuild_face_batch(stack_ptr, opacity, selected_f_ids, preselected_f_id, modifier_f_ids, reference_f_ids)

    def refresh_face_colors(self, stack_ptr, opacity=0.3, selected_f_ids=None, preselected_f_id="", modifier_f_ids=None, reference_f_ids=None):
        """ジオメトリを再計算せず、色属性だけを更新してバッチを再構築する"""
        stack = self.get_stack(stack_ptr)
        if stack is None or stack._cache_verts is None or len(stack._cache_verts) == 0: return
        self._rebuild_face_batch(stack_ptr, opacity, selected_f_ids, preselected_f_id, modifier_f_ids, reference_f_ids)

    def _rebuild_face_batch(self, stack_ptr, opacity, selected_f_ids, preselected_f_id, modifier_f_ids, reference_f_ids):
        if not self.init_shaders(): return
        stack = self.get_stack(stack_ptr)
        if stack is None: return
        verts_flat = stack._cache_verts
        tris_flat = stack._cache_tris
        face_ids = stack._cache_fids
        tri_counts = stack._cache_counts
        
        if verts_flat is None or tris_flat is None or len(verts_flat) == 0 or len(tris_flat) == 0 or len(tris_flat) < 3 or len(verts_flat) < 9:
            # When mesh data is empty or invalid (e.g. C++ tessellation failed because a modifier target is missing),
            # preserve the existing face batches to prevent the mesh from completely disappearing.
            if not getattr(stack, "face_batch_main", None):
                stack.face_batch_main = None
                stack.face_batch_static = None
                stack.face_batch_moving = None
            return
        
        if selected_f_ids is None: selected_f_ids = set()
        if modifier_f_ids is None: modifier_f_ids = set()
        if reference_f_ids is None: reference_f_ids = set()
 
        try:
            if isinstance(verts_flat, np.ndarray):
                verts = verts_flat.reshape(-1, 3)
                tris = tris_flat
            else:
                verts = np.array(verts_flat, dtype=np.float32).reshape(-1, 3)
                tris = np.array(tris_flat, dtype=np.int32)
            
            # 安全策: tris を (-1, 3) に変形できる長さに切り詰める
            rem = len(tris) % 3
            if rem > 0:
                tris = tris[:-rem]
                
            if len(tris) > 0:
                tris_nx3 = tris.reshape(-1, 3)
                max_idx = len(verts) - 1
                # もし範囲外のインデックスが存在する場合、その三角形(行)自体を除外する
                if tris_nx3.max() > max_idx:
                    valid_mask = np.all(tris_nx3 <= max_idx, axis=1)
                    tris_nx3 = tris_nx3[valid_mask]
                
                flat_verts = verts[tris_nx3.flatten()]
            else:
                flat_verts = np.empty((0, 3), dtype=np.float32)
            
            if len(flat_verts) > 0:
                v1 = flat_verts[0::3]; v2 = flat_verts[1::3]; v3 = flat_verts[2::3]
                normals = np.cross(v2 - v1, v3 - v1)
                norms = np.linalg.norm(normals, axis=1, keepdims=True)
                
                # 面の面積がゼロに近く、法線が取れない縮退ポリゴン（ConeのVertex等）に対する安全保護
                zero_mask = (norms < 1e-8).flatten()
                
                normals = np.divide(normals, norms, out=np.zeros_like(normals), where=norms>=1e-8)
                
                # 法線が計算できなかった不正な面には上向きのダミー法線を割り当て、真っ黒なゴミとして描画されるのを防ぐ
                if np.any(zero_mask):
                    normals[zero_mask] = [0.0, 0.0, 1.0]
                    
                vertex_normals = np.repeat(normals, 3, axis=0)
                
                # 疑似マルチライト（主光源、フィルライト、リムライト）で立体感を向上
                light_dir1 = np.array([0.3, 0.5, 1.0], dtype=np.float32)
                light_dir1 /= np.linalg.norm(light_dir1)
                
                light_dir2 = np.array([-0.6, -0.2, 0.5], dtype=np.float32)
                light_dir2 /= np.linalg.norm(light_dir2)
                
                light_dir3 = np.array([0.2, -0.8, -0.5], dtype=np.float32)
                light_dir3 /= np.linalg.norm(light_dir3)

                diff1 = np.abs(np.dot(vertex_normals, light_dir1)) * 0.55
                diff2 = np.abs(np.dot(vertex_normals, light_dir2)) * 0.25
                diff3 = np.abs(np.dot(vertex_normals, light_dir3)) * 0.15
                diff = diff1 + diff2 + diff3 + 0.15
            else:
                diff = np.ones(0, dtype=np.float32)
            
            base_colors = np.full((len(flat_verts), 4), [0.5, 0.5, 0.5, opacity], dtype=np.float32)
            
            offset = 0
            pre_base = preselected_f_id.split("@")[0] if "@" in preselected_f_id else preselected_f_id
            
            s_bases = {s.split("@")[0] if "@" in s else s for s in selected_f_ids}
            m_bases = {m.split("@")[0] if "@" in m else m for m in modifier_f_ids}
            r_bases = {r.split("@")[0] if "@" in r else r for r in reference_f_ids}
 
            is_moving = np.zeros(len(flat_verts), dtype=bool)
            import bpy
            from . import utils
            active_col = utils.get_active_collection(bpy.context)
            props = active_col.seamless_props if active_col else None
            active_uuid = ""
            if props and 0 <= props.active_primitive_index < len(props.primitives):
                active_uuid = props.primitives[props.active_primitive_index].uuid

            for i, lid in enumerate(face_ids):
                count = tri_counts[i]
                if count <= 0: continue
                start, end = offset, offset + count
                if not isinstance(lid, str): lid = str(lid)
                lid_base = lid.split("@")[0] if "@" in lid else lid
                
                is_hidden = False
                for hidden_uuid in self.hidden_primitive_uuids:
                    if hidden_uuid in lid:
                        is_hidden = True
                        break
                
                if is_hidden:
                    color = [0.0, 0.0, 0.0, 0.0]
                else:
                    color = [0.5, 0.5, 0.5, opacity]
                    if lid_base == pre_base and pre_base != "":
                        color = [1.0, 1.0, 0.0, min(1.0, opacity * 2.0)]
                    elif lid_base in s_bases:
                        color = [1.0, 0.5, 0.0, min(1.0, opacity * 1.5)]
                    elif lid_base in m_bases:
                        color = [1.0, 0.0, 1.0, opacity]
                    elif lid_base in r_bases:
                        color = [0.2, 0.4, 1.0, min(1.0, opacity * 1.5)]
                
                if start < len(base_colors) and end <= len(base_colors):
                    base_colors[start:end] = color
                    if not is_hidden and active_uuid and str(active_uuid) in lid:
                        is_moving[start:end] = True
                offset += count
            # 疑似マルチライトと色の積算
            base_colors[:, 0:3] *= diff[:, np.newaxis]
            
            shader = self.face_shader
            stack.face_batch_main = batch_for_shader(shader, 'TRIS', {"pos": flat_verts, "color": base_colors})

            static_verts = flat_verts[~is_moving]
            static_colors = base_colors[~is_moving]
            moving_verts = flat_verts[is_moving]
            moving_colors = base_colors[is_moving]
            
            if len(static_verts) > 0:
                stack.face_batch_static = batch_for_shader(shader, 'TRIS', {"pos": static_verts, "color": static_colors})
            else:
                stack.face_batch_static = None
                
            if len(moving_verts) > 0:
                stack.face_batch_moving = batch_for_shader(shader, 'TRIS', {"pos": moving_verts, "color": moving_colors})
            else:
                stack.face_batch_moving = None

        except Exception as e:
            utils.error_print(f"DEBUG: Rebuild Face Batch Error: {e}")
            stack.face_batch_main = None
            stack.face_batch_static = None
            stack.face_batch_moving = None

    def update_transient_mesh(self, verts_flat, tris_flat):
        if not self.init_shaders(): return
        if len(verts_flat) == 0:
            self.transient_batch = None
            return
        v_count = len(verts_flat) // 3
        coords = [(verts_flat[i*3], verts_flat[i*3+1], verts_flat[i*3+2]) for i in range(v_count)]
        indices = [(tris_flat[i], tris_flat[i+1], tris_flat[i+2]) for i in range(0, len(tris_flat), 3)]
        try:
            self.transient_batch = batch_for_shader(
                self.face_shader, 'TRIS', {"pos": coords}, indices=indices
            )
        except Exception as e:
            utils.error_print(f"Transient Batch Create Error: {e}")

    def _garbage_collect_leaked_stacks(self):
        # 存在しない（削除された）コレクションの描画データとC++メモリを自動GC
        try:
            valid_ptrs = set()
            for col in bpy.data.collections:
                ptr_str = getattr(col, "seamless_cad_stack_ptr", "")
                if ptr_str and ptr_str.strip():
                    try:
                        valid_ptrs.add(int(ptr_str))
                    except (ValueError, TypeError):
                        pass
            
            invalid_ptrs = [ptr for ptr in self.stacks.keys() if ptr not in valid_ptrs]
            if invalid_ptrs:
                from . import core_bridge
                for ptr in invalid_ptrs:
                    self.clear(ptr)
                    core_bridge.delete_cad_stack(ptr)
                    if utils.DEBUG_LOGS:
                        utils.info_print(f"Seamless CAD: Auto-cleaned leaked GPU drawing and C++ native memory for deleted stack_ptr {ptr}")
        except Exception as e:
            utils.debug_print(f"DEBUG: GPU drawing/C++ GC Error: {e}")

    def _get_shaded_color(self, lid, base_color):
        diff = self.face_colors.get(lid, 1.0)
        return (base_color[0] * diff, base_color[1] * diff, base_color[2] * diff, base_color[3])

    def draw(self, context, selected_ids=None, preselected_id="", modifier_ids=None, edge_depth_test='LESS_EQUAL'):
        self._garbage_collect_leaked_stacks()
        if not self.init_shaders(): return
        if not self.enabled or not self.stacks: return
        if not self.shader: return
        
        # 現在のアクティブなスタックポインタを安全に取得
        from . import utils
        active_col = utils.get_active_collection(context)
        try:
            active_ptr = int(getattr(active_col, "seamless_cad_stack_ptr", "0"))
        except (ValueError, TypeError):
            active_ptr = 0

        # アクティブなCADがドラッグ操作中か(移動/回転/リサイズいずれも含む)。
        # has_transform は移動系のデルタ行列が無いと真にならずリサイズを取りこぼすため、
        # ドラッグ全体で立つ is_dragging を青いエッジのスキップ判定に使う。
        active_props = getattr(active_col, "seamless_props", None) if active_col else None
        # is_placing: Surface-Snapping interactive placement in motion. Treat it
        # like a drag so the result wireframe is skipped (thin/light) while the
        # primitive follows the cursor; the placement modal's settle timer clears
        # it on pause and the result redraws.
        active_is_dragging = bool(getattr(active_props, "is_dragging", False)) or \
                             bool(getattr(active_props, "is_placing", False))

        if selected_ids is None: selected_ids = set()
        if modifier_ids is None: modifier_ids = set()
        
        if active_ptr != 0 and active_ptr in self.stacks:
            stack = self.get_stack(active_ptr)
            if selected_ids or preselected_id or modifier_ids:
                self._build_highlight_batches_ext(active_ptr, selected_ids, preselected_id, modifier_ids)
            else:
                stack.batch_sel = None
                stack.batch_pre = None
                stack.batch_mod = None
                # reg_idx needs to have all edges, but update_data handles that for stack.batch.
                # Just clearing the highlight batches is enough to remove the residue!
                
        self.shader.bind()
        
        # 全てのONなスタックのCAD形状をビューポート上に同時に一括描画！！！
        for ptr, stack in self.stacks.items():
            has_transform = hasattr(stack, "matrix") and stack.matrix and not stack.matrix.is_identity
            is_active = (ptr == active_ptr)

            # --- 1. 通常のエッジ (Cyan) ---
            # アクティブなスタックをドラッグ中は、青い結果エッジは開始前の位置に凍結された
            # ままになり、追従するオレンジの選択エッジや動いた実体とズレて「バラバラ」に
            # 見えるため、ドラッグ中は描画自体をスキップする(A案)。動いている要素だけを残す。
            # 非アクティブなスタックで万が一変形行列が指定された場合は、従来通り全体を変形させて描画の不整合を防ぐ完璧な防衛設計。
            is_active_dragging = is_active and active_is_dragging
            gpu.matrix.push()
            if has_transform and not is_active:
                gpu.matrix.multiply_matrix(stack.matrix)
            
            # デバッグログの出力
            if not hasattr(self, "_dbg_count"): self._dbg_count = 0
            self._dbg_count += 1
            if self._dbg_count % 30 == 0:
                print(f"[CAD Draw Debug] stack={ptr} active={is_active} active_dragging={active_is_dragging} is_active_dragging={is_active_dragging} coords_len={len(stack.coords) if hasattr(stack, 'coords') else 0} batch={stack.batch is not None}")
                
            if stack.batch and not is_active_dragging:
                gpu.state.depth_test_set(edge_depth_test)
                gpu.state.blend_set('ALPHA')
                gpu.state.line_width_set(3.0)
                try:
                    self.shader.uniform_float("color", (0.2, 0.8, 1.0, 0.8))
                    stack.batch.draw(self.shader)
                finally:
                    gpu.state.depth_test_set('LESS')
                    gpu.state.blend_set('NONE')
                    gpu.state.line_width_set(1.0)
            gpu.matrix.pop()
                
            # --- 2. 特殊・選択ハイライト (最前面に表示、アクティブなスタックに対してのみ描画) ---
            if ptr == active_ptr:
                # モディファイア対象 (Magenta) - ドラッグ中も元の位置に留める
                gpu.matrix.push()
                if stack.batch_mod:
                    gpu.state.depth_test_set('ALWAYS')
                    gpu.state.line_width_set(3.5)
                    try:
                        self.shader.uniform_float("color", (1.0, 0.0, 1.0, 1.0))
                        stack.batch_mod.draw(self.shader)
                    finally:
                        gpu.state.depth_test_set('LESS')
                        gpu.state.line_width_set(1.0)
                gpu.matrix.pop()
                    
                # 選択中 (Orange) (＝操作しているプリミティブ自身！！！)
                # ドラッグ中はこの選択中バッチに対してのみアフィン変換差分行列を適用し、極限60fpsで追従変形！！！
                gpu.matrix.push()
                if has_transform:
                    gpu.matrix.multiply_matrix(stack.matrix)
                if stack.batch_sel:
                    gpu.state.depth_test_set('ALWAYS')
                    gpu.state.line_width_set(4.0)
                    try:
                        self.shader.uniform_float("color", (1.0, 0.5, 0.0, 1.0))
                        stack.batch_sel.draw(self.shader)
                    finally:
                        gpu.state.depth_test_set('LESS')
                        gpu.state.line_width_set(1.0)
                gpu.matrix.pop()
                    
                # ホバー中 (Yellow) - 通常通り
                gpu.matrix.push()
                if stack.batch_pre:
                    gpu.state.depth_test_set('ALWAYS')
                    gpu.state.line_width_set(6.0)
                    try:
                        self.shader.uniform_float("color", (1.0, 1.0, 0.0, 1.0))
                        stack.batch_pre.draw(self.shader)
                    finally:
                        gpu.state.depth_test_set('LESS')
                        gpu.state.line_width_set(1.0)
                gpu.matrix.pop()

        self.draw_snap_marker()

    def set_snap_info(self, pos, snap_type):
        self.snap_pos = pos
        self.snap_type = snap_type

    def draw_snap_marker(self):
        if not self.init_shaders(): return
        if not self.snap_pos: return
        
        pos = self.snap_pos
        stype = self.snap_type
        size = 0.08 
        color = (1, 1, 1, 1)
        verts = []
        
        if stype == "VERTEX":
            color = (0.1, 0.6, 1.0, 1.0)
            verts = [
                (pos[0]-size, pos[1]-size, pos[2]), (pos[0]+size, pos[1]-size, pos[2]),
                (pos[0]+size, pos[1]-size, pos[2]), (pos[0]+size, pos[1]+size, pos[2]),
                (pos[0]+size, pos[1]+size, pos[2]), (pos[0]-size, pos[1]+size, pos[2]),
                (pos[0]-size, pos[1]+size, pos[2]), (pos[0]-size, pos[1]-size, pos[2]),
            ]
        elif stype == "MIDPOINT":
            color = (0.0, 1.0, 1.0, 1.0)
            verts = [
                (pos[0], pos[1]+size*1.2, pos[2]), (pos[0]-size, pos[1]-size, pos[2]),
                (pos[0]-size, pos[1]-size, pos[2]), (pos[0]+size, pos[1]-size, pos[2]),
                (pos[0]+size, pos[1]-size, pos[2]), (pos[0], pos[1]+size*1.2, pos[2]),
            ]
        elif stype == "CENTER":
            color = (0.0, 1.0, 0.5, 1.0)
            verts = [
                (pos[0], pos[1]+size, pos[2]), (pos[0]+size, pos[1], pos[2]),
                (pos[0]+size, pos[1], pos[2]), (pos[0], pos[1]-size, pos[2]),
                (pos[0], pos[1]-size, pos[2]), (pos[0]-size, pos[1], pos[2]),
                (pos[0]-size, pos[1], pos[2]), (pos[0], pos[1]+size, pos[2]),
            ]

        if verts:
            gpu.state.depth_test_set('NONE')
            gpu.state.line_width_set(3.0)
            try:
                self.shader.bind()
                self.shader.uniform_float("color", color)
                batch = batch_for_shader(self.shader, 'LINES', {"pos": verts})
                batch.draw(self.shader)
            finally:
                gpu.state.depth_test_set('LESS')
                gpu.state.line_width_set(1.0)

    def _build_highlight_batches_ext(self, stack_ptr, selected_ids, preselected_id, modifier_ids):
        stack = self.get_stack(stack_ptr)
        if not stack.coords or not stack.edge_indices: return
        reg_idx, sel_idx, pre_idx, mod_idx = [], [], [], []
        
        pre_bases = set()
        if preselected_id:
            pre_bases = {x.split("@")[0].strip() for x in preselected_id.split("|") if x.strip()}

        s_bases = {x.split("@")[0].strip() for x in selected_ids}
        m_bases = {x.split("@")[0].strip() for x in modifier_ids}

        for i, lid in enumerate(stack.lineages):
            if i >= len(stack.edge_indices): break
            
            is_hidden = False
            for hidden_uuid in self.hidden_primitive_uuids:
                if hidden_uuid in lid:
                    is_hidden = True
                    break
            if is_hidden:
                continue

            lid_base = lid.split("@")[0].strip() if isinstance(lid, str) else str(lid)

            if lid_base in pre_bases: pre_idx.extend(stack.edge_indices[i])
            elif lid_base in s_bases: sel_idx.extend(stack.edge_indices[i])
            elif lid_base in m_bases: mod_idx.extend(stack.edge_indices[i])
            else: reg_idx.extend(stack.edge_indices[i])
        stack.batch = batch_for_shader(self.shader, 'LINES', {"pos": stack.coords}, indices=reg_idx) if reg_idx else None
        stack.batch_sel = batch_for_shader(self.shader, 'LINES', {"pos": stack.coords}, indices=sel_idx) if sel_idx else None
        stack.batch_pre = batch_for_shader(self.shader, 'LINES', {"pos": stack.coords}, indices=pre_idx) if pre_idx else None
        stack.batch_mod = batch_for_shader(self.shader, 'LINES', {"pos": stack.coords}, indices=mod_idx) if mod_idx else None

    def draw_faces(self, opacity=0.3, selected_f_ids=None, preselected_f_id="", modifier_f_ids=None, reference_f_ids=None):
        self._garbage_collect_leaked_stacks()
        if not self.init_shaders(): return
        if not self.enabled or not self.stacks: return
        shader = self.face_shader
        shader.bind()
        is_opaque = (opacity > 0.99)
        if is_opaque:
            gpu.state.blend_set('NONE')
            gpu.state.depth_mask_set(True)
        else:
            gpu.state.blend_set('ALPHA')
            gpu.state.depth_mask_set(False)
        gpu.state.depth_test_set('LESS_EQUAL')
        
        try:
            # 全てのONなスタックの面データをビューポート上に同時に一括描画！！！
            for ptr, stack in self.stacks.items():
                has_transform = hasattr(stack, "matrix") and stack.matrix and not stack.matrix.is_identity
                is_active = False
                from . import utils
                import bpy
                active_col = utils.get_active_collection(bpy.context)
                try:
                    active_ptr = int(getattr(active_col, "seamless_cad_stack_ptr", "0"))
                    is_active = (ptr == active_ptr)
                except (ValueError, TypeError):
                    pass
    
                if hasattr(stack, "face_batch_static") and stack.face_batch_static:
                    gpu.matrix.push()
                    stack.face_batch_static.draw(shader)
                    gpu.matrix.pop()
                    
                if hasattr(stack, "face_batch_moving") and stack.face_batch_moving:
                    gpu.matrix.push()
                    if has_transform and is_active:
                        gpu.matrix.multiply_matrix(stack.matrix)
                    stack.face_batch_moving.draw(shader)
                    gpu.matrix.pop()

                # V8.1.5: ブーリアンのゴーストプレビュー(削除/追加される体積の半透明表示)。
                # サーバーから返るverts+trisは既にドラッグ後のワールド座標なので、
                # face_batch_movingと違いドラッグデルタ行列は適用しない。
                if getattr(stack, "face_batch_ghost", None):
                    gpu.matrix.push()
                    stack.face_batch_ghost.draw(shader)
                    gpu.matrix.pop()

                # fallback if split batches are missing for some reason
                if stack.face_batch_main and not hasattr(stack, "face_batch_static"):
                    gpu.matrix.push()
                    stack.face_batch_main.draw(shader)
                    gpu.matrix.pop()
                    
            if hasattr(self, "transient_batch") and self.transient_batch:
                self.face_shader.uniform_float("color", (1.0, 1.0, 1.0, opacity))
                self.transient_batch.draw(self.face_shader)
        finally:
            gpu.state.depth_mask_set(True)
            gpu.state.blend_set('NONE')
            gpu.state.depth_test_set('LESS')

class SeamlessGizmoManager:
    def __init__(self):
        self.shader = None
        self.axis_batches = {}
        self.point_batches = []
        self.hover_axis = ""
        self.hover_point_idx = -1
        self.active_prim_idx = -1
        self.drag_constraint_mode = ""
        self.drag_start_pos = (0, 0, 0)
        self.snap_pos = None
        self.snap_type = ""
        self.is_dragging_point = False
        self.snap_enabled = True
        self.snap_mode = "VERTEX"
        self.alignment_guides = [] # List of tuples: (p1, p2, color)

    def draw_alignment_guides(self):
        if not self.init_shaders() or not self.alignment_guides:
            return
        gpu.state.depth_test_set('NONE')
        gpu.state.line_width_set(1.5)
        gpu.state.blend_set('ALPHA')
        try:
            self.shader.bind()
            for p1, p2, color in self.alignment_guides:
                # 破線（Dashed Line）を生成するためにセグメントに分割
                segments = []
                steps = 15
                v1 = mathutils.Vector(p1)
                v2 = mathutils.Vector(p2)
                diff = v2 - v1
                dist = diff.length
                if dist < 1e-4:
                    continue
                dir_vec = diff / dist
                seg_len = dist / steps
                for i in range(steps):
                    if i % 2 == 0:
                        pt_start = v1 + dir_vec * (i * seg_len)
                        pt_end = v1 + dir_vec * ((i + 1) * seg_len)
                        segments.append(tuple(pt_start))
                        segments.append(tuple(pt_end))
                
                if segments:
                    batch = batch_for_shader(self.shader, 'LINES', {"pos": segments})
                    self.shader.uniform_float("color", color)
                    batch.draw(self.shader)
        finally:
            gpu.state.blend_set('NONE')
            gpu.state.line_width_set(1.0)
            gpu.state.depth_test_set('LESS')

    def draw_hud(self, context):
        if not getattr(self, "is_dragging_point", False):
            return
            
        import blf
        import bpy
        font_id = 0
        
        ui_scale = bpy.context.preferences.system.ui_scale
        char_size = int(14 * ui_scale)
        blf.size(font_id, char_size)
        
        x = int(35 * ui_scale)
        y = int(45 * ui_scale)
        
        enabled_str = "ON" if getattr(self, "snap_enabled", True) else "OFF"
        mode_str = getattr(self, "snap_mode", "VERTEX")
        
        guide_text = f"CAD Snap: {enabled_str} [{mode_str}] | S: Toggle ON/OFF | V: Vert | M: Mid | F: Face | C: None"
        
        if enabled_str == "ON":
            color = (0.0, 1.0, 0.4, 1.0) # 緑
        else:
            color = (0.7, 0.7, 0.7, 1.0) # 灰色
            
        # ドロップシャドウ
        blf.color(font_id, 0.0, 0.0, 0.0, 0.8)
        blf.position(font_id, x + 1, y - 1, 0)
        blf.draw(font_id, guide_text)
        
        blf.color(font_id, color[0], color[1], color[2], color[3])
        blf.position(font_id, x, y, 0)
        blf.draw(font_id, guide_text)

    def init_shaders(self):
        import bpy
        if bpy.app.background:
            return False
        try:
            if self.shader is None:
                try:
                    self.shader = gpu.shader.from_builtin('UNIFORM_COLOR')
                except Exception:
                    self.shader = gpu.shader.from_builtin('UNIFORM_COLOR')
            return True
        except Exception:
            return False

    def update_gizmo(self, context, prim_idx):
        if not self.init_shaders(): return
        if prim_idx < 0:
            self.axis_batches = {}; self.active_prim_idx = -1
            return
        from . import utils
        props = utils.get_active_props(context)
        if not props or prim_idx >= len(props.primitives):
            self.axis_batches = {}; self.active_prim_idx = -1
            return
        self.active_prim_idx = prim_idx
        length = 1.2
        self.axis_batches = {
            "X": batch_for_shader(self.shader, 'LINES', {"pos": [(0,0,0), (length,0,0)]}),
            "Y": batch_for_shader(self.shader, 'LINES', {"pos": [(0,0,0), (0,length,0)]}),
            "Z": batch_for_shader(self.shader, 'LINES', {"pos": [(0,0,0), (0,0,length)]}),
        }
        
        self.point_batches = []
        prim = props.primitives[prim_idx]
        if prim.type in {'CURVE', 'SURFACE', 'POLYLINE'}:
            for pt in prim.points:
                self.point_batches.append(batch_for_shader(self.shader, 'POINTS', {"pos": [tuple(pt.co)]}))

        plane_verts = [(-0.5, -0.5, 0), (0.5, -0.5, 0), (0.5, 0.5, 0), (-0.5, 0.5, 0)]
        plane_indices = [(0,1), (1,2), (2,3), (3,0)]
        self.plane_batch = batch_for_shader(self.shader, 'LINES', {"pos": plane_verts}, indices=plane_indices)
        axis_dots = [(0,0,-2.0), (0,0,2.0)]
        self.revolve_axis_batch = batch_for_shader(self.shader, 'LINES', {"pos": axis_dots})
    def draw(self, context):
        if not self.init_shaders(): return
        from . import utils
        props = utils.get_active_props(context)
        if not props: return
        idx = props.active_primitive_index
        if idx < 0 or idx >= len(props.primitives): return
        prim = props.primitives[idx]
        pos = mathutils.Vector(prim.location)
        rv3d = context.region_data
        view_matrix = rv3d.view_matrix
        dist = (view_matrix @ pos).z
        scale_factor = abs(dist) * 0.15
        self.shader.bind()
        gpu.state.depth_test_set('NONE')
        try:
            if props.is_alt_pressed and self.axis_batches and idx == self.active_prim_idx:
                colors = {"X": (1.0, 0.2, 0.2, 1.0), "Y": (0.2, 1.0, 0.2, 1.0), "Z": (0.2, 0.5, 1.0, 1.0)}
                for axis, batch in self.axis_batches.items():
                    matrix = mathutils.Matrix.Translation(pos)
                    matrix @= mathutils.Matrix.Scale(scale_factor, 4)
                    gpu.matrix.push()
                    gpu.matrix.multiply_matrix(matrix)
                    color = colors[axis]
                    if self.hover_axis == axis:
                        color = (1.0, 1.0, 1.0, 1.0); gpu.state.line_width_set(4.0)
                    else:
                        gpu.state.line_width_set(2.0)
                    self.shader.uniform_float("color", color)
                    batch.draw(self.shader)
                    gpu.matrix.pop()
                if prim.type == 'MIRROR' and hasattr(self, 'plane_batch'):
                    normal_axis = prim.pattern_axis
                    matrix = mathutils.Matrix.Translation(pos)
                    if normal_axis == 'X': matrix @= mathutils.Euler((0, 1.5708, 0)).to_matrix().to_4x4()
                    elif normal_axis == 'Y': matrix @= mathutils.Euler((1.5708, 0, 0)).to_matrix().to_4x4()
                    matrix @= mathutils.Matrix.Scale(scale_factor * 2.0, 4)
                    gpu.matrix.push()
                    gpu.matrix.multiply_matrix(matrix)
                    self.shader.uniform_float("color", (1.0, 0.0, 1.0, 0.6))
                    gpu.state.line_width_set(1.0)
                    self.plane_batch.draw(self.shader)
                    gpu.matrix.pop()
                elif (prim.type == 'REVOLVE' or prim.type == 'ARRAY_CIRCULAR') and hasattr(self, 'revolve_axis_batch'):
                    axis = prim.pattern_axis
                    matrix = mathutils.Matrix.Translation(pos)
                    if axis == 'X': matrix @= mathutils.Euler((0, 1.5708, 0)).to_matrix().to_4x4()
                    elif axis == 'Y': matrix @= mathutils.Euler((1.5708, 0, 0)).to_matrix().to_4x4()
                    matrix @= mathutils.Matrix.Scale(scale_factor, 4)
                    gpu.matrix.push()
                    gpu.matrix.multiply_matrix(matrix)
                    self.shader.uniform_float("color", (1.0, 1.0, 0.0, 0.8))
                    gpu.state.line_width_set(1.0)
                    self.revolve_axis_batch.draw(self.shader)
                    gpu.matrix.pop()
                    
            if prim.type in {'CURVE', 'SURFACE', 'POLYLINE'}:
                from gpu_extras.batch import batch_for_shader
                
                active_col = utils.get_active_collection(context)
                obj_matrix = None
                if active_col:
                    target_name = f"{idx}_{prim.type}_Seamless_Proxy"
                    for ob in active_col.all_objects:
                        if ob.name == target_name:
                            obj_matrix = ob.matrix_world
                            break
                    if obj_matrix is None:
                        for ob in active_col.all_objects:
                            if ("Proxy" in ob.name or "CURVE" in ob.name or "SURFACE" in ob.name) and ob.visible_get() and ob.scale.length > 1e-4:
                                obj_matrix = ob.matrix_world
                                break
                
                if obj_matrix:
                    loc, rot, scale = obj_matrix.decompose()
                    draw_matrix = mathutils.Matrix.Translation(loc) @ rot.to_matrix().to_4x4()
                else:
                    draw_matrix = mathutils.Matrix.Translation(pos) @ mathutils.Euler(prim.rotation).to_matrix().to_4x4()
                
                d = 0.08
                cross_verts = [
                    (-d, 0, 0), (d, 0, 0),
                    (0, -d, 0), (0, d, 0),
                    (0, 0, -d), (0, 0, d)
                ]
                
                gpu.state.line_width_set(3.0)
                gpu.state.blend_set('ALPHA')
                try:
                    for i, pt in enumerate(prim.points):
                        world_pos = draw_matrix @ mathutils.Vector(pt.co)
                        
                        gpu.matrix.push()
                        gpu.matrix.multiply_matrix(mathutils.Matrix.Translation(world_pos))
                        
                        batch = batch_for_shader(self.shader, 'LINES', {"pos": cross_verts})
                        color = (1.0, 1.0, 0.0, 1.0) if (self.hover_point_idx == i and idx == self.active_prim_idx) else (0.2, 0.9, 0.2, 1.0)
                        self.shader.uniform_float("color", color)
                        batch.draw(self.shader)
                        
                        gpu.matrix.pop()
                finally:
                    gpu.state.blend_set('NONE')
                    gpu.state.line_width_set(1.0)

            # --- ガイドラインの描画 (ドラッグ拘束中のみ) ---
            if hasattr(self, "drag_constraint_mode") and self.drag_constraint_mode:
                start_co = mathutils.Vector(self.drag_start_pos)
                gpu.state.depth_test_set('NONE')
                gpu.state.line_width_set(1.5)
                gpu.state.blend_set('ALPHA')
                try:
                    L = 1000.0
                    lines = []
                    colors = []
                    
                    if self.drag_constraint_mode == "AXIS_X":
                        lines.append((start_co - mathutils.Vector((L, 0, 0)), start_co + mathutils.Vector((L, 0, 0))))
                        colors.append((1.0, 0.2, 0.2, 0.8))
                    elif self.drag_constraint_mode == "AXIS_Y":
                        lines.append((start_co - mathutils.Vector((0, L, 0)), start_co + mathutils.Vector((0, L, 0))))
                        colors.append((0.2, 1.0, 0.2, 0.8))
                    elif self.drag_constraint_mode == "AXIS_Z":
                        lines.append((start_co - mathutils.Vector((0, 0, L)), start_co + mathutils.Vector((0, 0, L))))
                        colors.append((0.2, 0.5, 1.0, 0.8))
                    elif self.drag_constraint_mode == "PLANE_X": # YZ平面
                        lines.append((start_co - mathutils.Vector((0, L, 0)), start_co + mathutils.Vector((0, L, 0))))
                        lines.append((start_co - mathutils.Vector((0, 0, L)), start_co + mathutils.Vector((0, 0, L))))
                        colors.extend([(0.2, 1.0, 0.2, 0.6), (0.2, 0.5, 1.0, 0.6)])
                    elif self.drag_constraint_mode == "PLANE_Y": # XZ平面
                        lines.append((start_co - mathutils.Vector((L, 0, 0)), start_co + mathutils.Vector((L, 0, 0))))
                        lines.append((start_co - mathutils.Vector((0, 0, L)), start_co + mathutils.Vector((0, 0, L))))
                        colors.extend([(1.0, 0.2, 0.2, 0.6), (0.2, 0.5, 1.0, 0.6)])
                    elif self.drag_constraint_mode == "PLANE_Z": # XY平面
                        lines.append((start_co - mathutils.Vector((L, 0, 0)), start_co + mathutils.Vector((L, 0, 0))))
                        lines.append((start_co - mathutils.Vector((0, L, 0)), start_co + mathutils.Vector((0, L, 0))))
                        colors.extend([(1.0, 0.2, 0.2, 0.6), (0.2, 1.0, 0.2, 0.6)])
                    
                    for idx_l, (p1, p2) in enumerate(lines):
                        batch = batch_for_shader(self.shader, 'LINES', {"pos": [tuple(p1), tuple(p2)]})
                        self.shader.uniform_float("color", colors[idx_l])
                        batch.draw(self.shader)
                finally:
                    gpu.state.blend_set('NONE')
                    gpu.state.line_width_set(1.0)
                
            # --- スナップフィードバックの描画 ---
            if hasattr(self, "snap_pos") and self.snap_pos:
                snap_co = mathutils.Vector(self.snap_pos)
                gpu.state.depth_test_set('NONE')
                gpu.state.line_width_set(2.5)
                gpu.state.blend_set('ALPHA')
                try:
                    import math
                    if self.snap_type == "VERTEX": # オレンジ色の正方形
                        s = 0.04
                        square_verts = [
                            (-s, -s, -s), (s, -s, -s), (s, s, -s), (-s, s, -s),
                            (-s, -s, s), (s, -s, s), (s, s, s), (-s, s, s),
                        ]
                        square_indices = [
                            (0, 1), (1, 2), (2, 3), (3, 0),
                            (4, 5), (5, 6), (6, 7), (7, 4),
                            (0, 4), (1, 5), (2, 6), (3, 7)
                        ]
                        
                        gpu.matrix.push()
                        gpu.matrix.multiply_matrix(mathutils.Matrix.Translation(snap_co))
                        batch = batch_for_shader(self.shader, 'LINES', {"pos": square_verts}, indices=square_indices)
                        self.shader.uniform_float("color", (1.0, 0.5, 0.0, 0.9)) # オレンジ
                        batch.draw(self.shader)
                        gpu.matrix.pop()
                        
                    elif self.snap_type == "MIDPOINT": # 黄色の正四面体
                        s = 0.05
                        tri_verts = [
                            (0, 0, s), (-s, -s, -s), (s, -s, -s), (0, s, -s)
                        ]
                        tri_indices = [
                            (0, 1), (0, 2), (0, 3),
                            (1, 2), (2, 3), (3, 1)
                        ]
                        gpu.matrix.push()
                        gpu.matrix.multiply_matrix(mathutils.Matrix.Translation(snap_co))
                        batch = batch_for_shader(self.shader, 'LINES', {"pos": tri_verts}, indices=tri_indices)
                        self.shader.uniform_float("color", (1.0, 0.9, 0.0, 0.9)) # 黄色
                        batch.draw(self.shader)
                        gpu.matrix.pop()
                        
                    elif self.snap_type == "FACE": # 水色の円
                        s = 0.06
                        circle_verts = []
                        segments = 16
                        for idx_c in range(segments):
                            angle = idx_c * (2.0 * math.pi / segments)
                            circle_verts.append((s * math.cos(angle), s * math.sin(angle), 0.0))
                        
                        circle_indices = [(idx_c, (idx_c + 1) % segments) for idx_c in range(segments)]
                        
                        gpu.matrix.push()
                        rv3d = context.region_data
                        cam_rot = rv3d.view_matrix.to_3x3().inverted().to_4x4()
                        gpu.matrix.multiply_matrix(mathutils.Matrix.Translation(snap_co) @ cam_rot)
                        
                        batch = batch_for_shader(self.shader, 'LINES', {"pos": circle_verts}, indices=circle_indices)
                        self.shader.uniform_float("color", (0.0, 0.8, 1.0, 0.9)) # 水色
                        batch.draw(self.shader)
                        gpu.matrix.pop()
                finally:
                    gpu.state.blend_set('NONE')
                    gpu.state.line_width_set(1.0)
                    gpu.state.depth_test_set('LESS')
                
        finally:
            gpu.state.depth_test_set('LESS')
            gpu.state.line_width_set(1.0)

_wireframe_engine = SeamlessWireframeManager()
_gizmo_engine = SeamlessGizmoManager()
def get_wireframe_engine(): return _wireframe_engine
def get_gizmo_engine(): return _gizmo_engine

def draw_cad_3d(self, context, props):
    wireframe = get_wireframe_engine()
    gizmo = get_gizmo_engine()
    
    selected_ids = set(x.strip() for x in props.selected_edges_str.split("|") if x.strip())
    selected_f_ids = set(x.strip() for x in props.selected_faces_str.split("|") if x.strip())

    modifier_ids = set()
    modifier_f_ids = set()
    reference_f_ids = set()
    is_modifier_zero = False
    if 0 <= props.active_primitive_index < len(props.primitives):
        prim = props.primitives[props.active_primitive_index]
        if prim.type in {'FILLET', 'CHAMFER', 'FACE_OFFSET', 'DRAFT', 'SHELL', 'FACE_INSET'}:
            targets = get_display_edge_targets(prim) if prim.type in {'FILLET', 'CHAMFER'} else [x.strip() for x in prim.target_lineages.split("|") if x.strip()]
            for t in targets:
                if "Edge:" in t or ":E" in t: 
                    modifier_ids.add(t)
                elif "Face:" in t or ":F" in t:
                    modifier_f_ids.add(t)
            
            if hasattr(prim, "reference_lineage") and prim.reference_lineage:
                reference_f_ids.add(prim.reference_lineage)
                
            is_modifier_zero = (abs(prim.radius) < 1e-5)
            if prim.type == 'FACE_INSET' and hasattr(prim, 'extrude_height'):
                is_modifier_zero = is_modifier_zero and (abs(prim.extrude_height) < 1e-5)

    show_mod = props.is_selection_mode or is_modifier_zero

    safe_selected_ids = selected_ids if props.is_selection_mode else set()
    safe_modifier_ids = modifier_ids if show_mod else set()
    safe_selected_f_ids = selected_f_ids if props.is_selection_mode else set()
    safe_modifier_f_ids = modifier_f_ids if show_mod else set()
    safe_reference_f_ids = reference_f_ids if show_mod else set()
    safe_preselected_f_id = props.preselected_face_id if props.is_selection_mode else ""
    safe_preselected_id = props.preselected_edge_id if props.is_selection_mode else ""

    if not hasattr(draw_cad_3d, "_last_pre_f_id"): draw_cad_3d._last_pre_f_id = ""
    if not hasattr(draw_cad_3d, "_last_opacity"): draw_cad_3d._last_opacity = 0.4
    if not hasattr(draw_cad_3d, "_last_sel_f_ids"): draw_cad_3d._last_sel_f_ids = set()
    if not hasattr(draw_cad_3d, "_last_mod_f_ids"): draw_cad_3d._last_mod_f_ids = set()
    if not hasattr(draw_cad_3d, "_last_active_idx"): draw_cad_3d._last_active_idx = -1
    
    needs_refresh = (safe_preselected_f_id != draw_cad_3d._last_pre_f_id) or \
                    (abs(props.viewport_opacity - draw_cad_3d._last_opacity) > 0.001) or \
                    (safe_selected_f_ids != draw_cad_3d._last_sel_f_ids) or \
                    (safe_modifier_f_ids != draw_cad_3d._last_mod_f_ids) or \
                    (props.active_primitive_index != draw_cad_3d._last_active_idx)

    if needs_refresh:
        active_col = utils.get_active_collection(context)
        try:
            active_ptr = int(getattr(active_col, "seamless_cad_stack_ptr", "0"))
        except (ValueError, TypeError):
            active_ptr = 0
        if active_ptr != 0:
            wireframe.refresh_face_colors(
                active_ptr,
                opacity=props.viewport_opacity,
                selected_f_ids=safe_selected_f_ids, 
                preselected_f_id=safe_preselected_f_id,
                modifier_f_ids=safe_modifier_f_ids,
                reference_f_ids=safe_reference_f_ids
            )
        draw_cad_3d._last_pre_f_id = safe_preselected_f_id
        draw_cad_3d._last_opacity = props.viewport_opacity
        draw_cad_3d._last_sel_f_ids = safe_selected_f_ids
        draw_cad_3d._last_mod_f_ids = safe_modifier_f_ids
        draw_cad_3d._last_active_idx = props.active_primitive_index

    if props.is_selection_mode:
        wireframe.draw_faces(
            opacity=props.viewport_opacity,
            selected_f_ids=safe_selected_f_ids, 
            preselected_f_id=props.preselected_face_id,
            modifier_f_ids=safe_modifier_f_ids,
            reference_f_ids=safe_reference_f_ids
        )
    else:
        wireframe.draw_faces(
            opacity=props.viewport_opacity,
            selected_f_ids=safe_selected_f_ids, 
            modifier_f_ids=safe_modifier_f_ids, 
            reference_f_ids=safe_reference_f_ids
        )

    safe_preselected_id = props.preselected_edge_id if props.is_selection_mode else ""

    if props.use_wgpu_overlay:
        wireframe.draw_wgpu_overlay(context, opacity=props.viewport_opacity)
        wireframe.draw(context, selected_ids=safe_selected_ids, preselected_id=safe_preselected_id, modifier_ids=safe_modifier_ids)
    else:
        # WGPU オーバーレイOFF時は、Rust側で焼き込まれたシースルーのエッジが無いため
        # Python描画のエッジが実メッシュ/不透明面に深度遮蔽されて消える。
        # そのため既定は深度テスト無効('ALWAYS')で、ONと同じ「透けて見えるワイヤー」。
        #
        # ただし不透明(opacity 1.0)のときだけは draw_faces() が depth_mask を有効にして
        # 面が深度を書き込む(is_opaque 分岐)。この条件では 'LESS_EQUAL' にすると
        # 面の奥の辺が正しく隠れる。半透明では面が深度を書かないので、切り替えると
        # 辺が丸ごと消える(§5 の H そのもの)。だから不透明であることが必須条件。
        opaque = props.viewport_opacity > 0.99
        hide_occluded = getattr(props, "hide_occluded_edges", False) and opaque
        wireframe.draw(
            context,
            selected_ids=safe_selected_ids,
            preselected_id=safe_preselected_id,
            modifier_ids=safe_modifier_ids,
            edge_depth_test='LESS_EQUAL' if hide_occluded else 'ALWAYS'
        )

    if props.is_selection_mode and (props.preselected_edge_id or props.preselected_face_id):
        import gpu
        from gpu_extras.batch import batch_for_shader
        try:
            shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        except Exception:
            shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        gpu.state.point_size_set(10.0)
        gpu.state.blend_set('ALPHA')
        try:
            batch = batch_for_shader(shader, 'POINTS', {"pos": [tuple(props.preselected_point)]})
            shader.bind()
            shader.uniform_float("color", (1.0, 1.0, 0.0, 1.0))
            batch.draw(shader)
        finally:
            gpu.state.blend_set('NONE')
            gpu.state.point_size_set(1.0)
        
    gizmo.draw_alignment_guides()
    gizmo.draw(context)
