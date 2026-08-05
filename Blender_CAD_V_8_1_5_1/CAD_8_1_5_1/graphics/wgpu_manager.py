import bpy
import gpu
import os
import tempfile
from datetime import datetime
from gpu_extras.batch import batch_for_shader
from . import draw_handlers

_batch = None
_shader = None
_edge_batch = None
_edge_shader = None
_handler = None
_handler_ns_key = "cad3_draw_handler_post_view"
_highlight_cache_key = None
_highlight_batches = []
_face_highlight_batches = []

# Vertex buffers are built once per mesh revision and shared by every batch that
# draws from them (base geometry, hover, selection). Highlights only supply their
# own index buffer. Building one buffer per highlighted edge used to reallocate
# the whole wireframe on the GPU for each selected edge, which exhausted VRAM on
# dense models and took the display driver down with it.
_face_vbo = None
_edge_vbo = None
_face_vert_count = 0
_edge_vert_count = 0

# Debug logging is off unless explicitly asked for, and never writes to a path
# from the development machine.
_debug_enabled = bool(os.environ.get("SEAMLESS_CAD_WGPU_DEBUG"))
_debug_log_path = os.path.join(tempfile.gettempdir(), "seamless_cad_wgpu_debug.log")

_FACE_DEFAULT_COLOR = (0.0, 0.7, 1.0, 0.5)
_FACE_HOVER_COLOR = (1.0, 1.0, 0.0, 0.8)
_FACE_SELECT_COLOR = (1.0, 0.5, 0.0, 0.8)


def _debug_log(msg):
    if not _debug_enabled:
        return
    try:
        with open(_debug_log_path, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {msg}\n")
    except Exception:
        pass


def _safe_parse_edge_token(token: str):
    if "|" in token:
        token = token.split("|")[0]
    base = token.split("@")[0].strip()
    if base.startswith("Edge:"):
        base = base[5:]
    try:
        idx = int(base)
    except ValueError:
        return None
    if idx > 0:
        idx -= 1
    return idx if idx >= 0 else None


def _safe_parse_edge_base(token: str):
    base = token.split("@")[0].strip()
    if base.startswith("Edge:"):
        return base
    idx = _safe_parse_edge_token(token)
    if idx is None:
        return ""
    return f"Edge:{idx + 1}"


def _make_pos_vbo(verts):
    """Upload a position-only vertex buffer that several batches can share."""
    fmt = gpu.types.GPUVertFormat()
    fmt.attr_add(id="pos", comp_type='F32', len=3, fetch_mode='FLOAT')
    vbo = gpu.types.GPUVertBuf(len=len(verts), format=fmt)
    vbo.attr_fill(id="pos", data=verts)
    return vbo


def _make_indexed_batch(prim_type, vbo, indices):
    """Batch drawing `indices` out of an already-uploaded vertex buffer."""
    if not indices:
        return None
    ibo = gpu.types.GPUIndexBuf(type=prim_type, seq=indices)
    return gpu.types.GPUBatch(type=prim_type, buf=vbo, elem=ibo)


def _get_selection_state():
    props = bpy.context.scene.cad3_props
    if not props.is_selection_mode:
        return "", set()
    pre_face = props.preselected_face_id.split("@")[0] if props.preselected_face_id else ""
    sel_faces = {s.split("@")[0] for s in props.selected_faces_str.split("|") if s.strip()}
    return pre_face, sel_faces


def _face_triangle_ranges(state):
    """Yield (base_id, first_tri, tri_count) for each face of the current mesh."""
    lineages = getattr(state, 'mesh_lineages', None)
    counts = getattr(state, 'mesh_tri_counts', None)
    if not lineages or counts is None or len(counts) == 0:
        return

    tri_idx = 0
    for i, base_id in enumerate(lineages):
        if i >= len(counts):
            break
        tri_count = counts[i] // 3
        yield base_id, tri_idx, tri_count
        tri_idx += tri_count


def _create_batch():
    global _batch, _shader, _edge_batch, _edge_shader
    global _highlight_cache_key, _highlight_batches, _face_highlight_batches
    global _face_vbo, _edge_vbo, _face_vert_count, _edge_vert_count
    from ..core.state_manager import get_state
    state = get_state()

    _face_vbo = None
    _edge_vbo = None
    _face_vert_count = 0
    _edge_vert_count = 0

    if len(state.mesh_verts) > 0 and len(state.mesh_tris) > 0:
        try:
            mv = state.mesh_verts
            mt = state.mesh_tris
            # Indexed, so shared vertices stay shared. The previous code expanded
            # this into a flat triangle soup with a per-vertex colour, which cost
            # three Python tuples per triangle and tripled the GPU footprint.
            verts = [(mv[i], mv[i + 1], mv[i + 2]) for i in range(0, len(mv), 3)]
            tris = [(mt[i], mt[i + 1], mt[i + 2]) for i in range(0, len(mt), 3)]

            try:
                _shader = gpu.shader.from_builtin('UNIFORM_COLOR')
            except Exception:
                _shader = gpu.shader.from_builtin('3D_FLAT_COLOR')

            _face_vert_count = len(verts)
            _face_vbo = _make_pos_vbo(verts)
            _batch = _make_indexed_batch('TRIS', _face_vbo, tris)
        except Exception as e:
            _batch = None
            _face_vbo = None
            _debug_log(f"create_batch(mesh) failed: {e} verts={len(state.mesh_verts)} tris={len(state.mesh_tris)}")
    else:
        _batch = None

    if len(state.wire_points) > 0 and len(state.wire_edges) > 0:
        try:
            wp = state.wire_points
            edge_verts = [(wp[i], wp[i + 1], wp[i + 2]) for i in range(0, len(wp), 3)]
            edge_indices = []
            v_offset = 0
            for count in state.wire_edges:
                for j in range(count - 1):
                    edge_indices.append((v_offset + j, v_offset + j + 1))
                v_offset += count

            try:
                _edge_shader = gpu.shader.from_builtin('UNIFORM_COLOR')
            except Exception:
                _edge_shader = gpu.shader.from_builtin('3D_FLAT_COLOR')

            _edge_vert_count = len(edge_verts)
            _edge_vbo = _make_pos_vbo(edge_verts)
            _edge_batch = _make_indexed_batch('LINES', _edge_vbo, edge_indices)
        except Exception as e:
            _edge_batch = None
            _edge_vbo = None
            _debug_log(f"create_batch(wire) failed: {e} points={len(state.wire_points)} edges={len(state.wire_edges)}")
    else:
        _edge_batch = None

    _highlight_cache_key = None
    _highlight_batches = []
    _face_highlight_batches = []


def _build_highlight_batches_if_needed(state):
    """Rebuild hover/selection overlays when the selection changed.

    Both edge and face highlights live here so that hovering a face no longer
    depends on the mesh revision changing; they draw index buffers over the
    vertex buffers uploaded by _create_batch, so nothing is re-uploaded.
    """
    global _highlight_cache_key, _highlight_batches, _face_highlight_batches
    props = bpy.context.scene.cad3_props

    selected = []
    selected_bases = []
    candidate_texts = []
    if props.is_selection_mode:
        candidate_texts.append(props.selected_edges_str)
        if 0 <= props.active_modifier_idx < len(props.modifiers):
            candidate_texts.append(props.modifiers[props.active_modifier_idx].edge_ids)

    for raw_text in candidate_texts:
        if not raw_text:
            continue
        for token in raw_text.split("|"):
            token = token.strip()
            if not token:
                continue
            b = _safe_parse_edge_base(token)
            if b:
                selected_bases.append(b)
            idx = _safe_parse_edge_token(token)
            if idx is not None:
                selected.append(idx)

    hover = None
    if props.is_selection_mode and props.preselected_edge_id:
        hover = _safe_parse_edge_token(props.preselected_edge_id)

    pre_face, sel_faces = _get_selection_state()

    lineage_key = tuple(state.wire_lineages) if getattr(state, "wire_lineages", None) else ()
    key = (
        tuple(sorted(set(selected_bases))),
        hover,
        tuple(state.wire_edges),
        lineage_key,
        pre_face,
        tuple(sorted(sel_faces)),
    )
    if key == _highlight_cache_key:
        return

    _highlight_cache_key = key
    _highlight_batches = []
    _face_highlight_batches = []

    _build_edge_highlights(state, selected, selected_bases, hover)
    _build_face_highlights(state, pre_face, sel_faces)


def _build_edge_highlights(state, selected, selected_bases, hover):
    """One batch for hover, one for selection — both over the shared edge VBO."""
    global _highlight_batches

    if _edge_vbo is None or len(state.wire_edges) == 0 or not _edge_shader:
        return

    selected_set = set(selected)
    selected_base_set = set(selected_bases)

    hover_indices = []
    select_indices = []
    v_offset = 0
    for edge_i, count in enumerate(state.wire_edges):
        if getattr(state, "wire_lineages", None) and edge_i < len(state.wire_lineages):
            edge_base = str(state.wire_lineages[edge_i]).split("@")[0]
        else:
            edge_base = f"Edge:{edge_i + 1}"

        is_hover = (hover is not None and edge_i == hover)
        is_selected = edge_i in selected_set or edge_base in selected_base_set
        if is_hover or is_selected:
            target = hover_indices if is_hover else select_indices
            end = v_offset + count
            if end <= _edge_vert_count:
                target.extend((v_offset + j, v_offset + j + 1) for j in range(count - 1))
        v_offset += count

    try:
        select_batch = _make_indexed_batch('LINES', _edge_vbo, select_indices)
        if select_batch is not None:
            _highlight_batches.append((select_batch, (1.0, 0.78, 0.0, 1.0), 4.0))
        hover_batch = _make_indexed_batch('LINES', _edge_vbo, hover_indices)
        if hover_batch is not None:
            _highlight_batches.append((hover_batch, (0.0, 1.0, 0.3, 1.0), 5.0))
    except Exception as e:
        _highlight_batches = []
        _debug_log(f"edge highlight build failed: {e}")


def _build_face_highlights(state, pre_face, sel_faces):
    """Only the highlighted faces get their own index buffer; the rest of the
    mesh keeps drawing from the base batch in its uniform colour."""
    global _face_highlight_batches

    if _face_vbo is None or not _shader:
        return
    if not pre_face and not sel_faces:
        return

    mt = state.mesh_tris
    hover_indices = []
    select_indices = []
    for base_id, first_tri, tri_count in _face_triangle_ranges(state):
        if base_id == pre_face and pre_face:
            target = hover_indices
        elif base_id in sel_faces:
            target = select_indices
        else:
            continue
        for t in range(first_tri, first_tri + tri_count):
            i = t * 3
            if i + 2 < len(mt):
                target.append((mt[i], mt[i + 1], mt[i + 2]))

    try:
        select_batch = _make_indexed_batch('TRIS', _face_vbo, select_indices)
        if select_batch is not None:
            _face_highlight_batches.append((select_batch, _FACE_SELECT_COLOR))
        hover_batch = _make_indexed_batch('TRIS', _face_vbo, hover_indices)
        if hover_batch is not None:
            _face_highlight_batches.append((hover_batch, _FACE_HOVER_COLOR))
    except Exception as e:
        _face_highlight_batches = []
        _debug_log(f"face highlight build failed: {e}")


def draw_callback():
    global _batch, _shader, _edge_batch, _edge_shader
    from ..core.state_manager import get_state
    state = get_state()

    if state.render_revision != state.last_drawn_revision:
        _create_batch()
        prev_drawn = state.last_drawn_revision
        state.last_drawn_revision = state.render_revision
        _debug_log(
            f"draw refresh rev={state.render_revision} prev_rev={prev_drawn} "
            f"reason=render-revision-changed mesh_v={len(state.mesh_verts)} mesh_t={len(state.mesh_tris)} "
            f"wire_p={len(state.wire_points)} wire_e={len(state.wire_edges)}"
        )

    _build_highlight_batches_if_needed(state)

    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('LESS_EQUAL')
    gpu.state.line_width_set(1.0)
    try:
        if _batch and _shader:
            gpu.state.depth_test_set('NONE')
            _shader.bind()
            try:
                _shader.uniform_float("color", _FACE_DEFAULT_COLOR)
            except Exception:
                pass
            _batch.draw(_shader)

            for sub_batch, color in _face_highlight_batches:
                try:
                    _shader.uniform_float("color", color)
                except Exception:
                    pass
                sub_batch.draw(_shader)

        if _edge_batch and _edge_shader:
            gpu.state.depth_test_set('NONE')
            _edge_shader.bind()
            try:
                # 線の描画時は常にカラーを再設定
                _edge_shader.uniform_float("color", (0.3, 0.3, 0.3, 0.6))
            except Exception:
                pass
            gpu.state.line_width_set(2.0)
            _edge_batch.draw(_edge_shader)

            # ハイライト線はさらに少し太くして上書き描画
            for sub_batch, color, width in _highlight_batches:
                try:
                    _edge_shader.uniform_float("color", color)
                except Exception:
                    pass
                gpu.state.line_width_set(width)
                sub_batch.draw(_edge_shader)
    finally:
        gpu.state.line_width_set(1.0)
        gpu.state.depth_test_set('LESS')
        gpu.state.blend_set('NONE')


def start_drawing():
    global _handler
    if _handler is not None:
        return

    draw_handlers.clear_namespace_handler(_handler_ns_key)

    from ..core.state_manager import get_state
    state = get_state()
    state.mark_dirty()
    _create_batch()
    _handler = draw_handlers.register_handler(draw_callback, 'WINDOW', 'POST_VIEW')
    bpy.app.driver_namespace[_handler_ns_key] = _handler


def stop_drawing():
    global _handler, _batch, _shader, _edge_batch, _edge_shader
    global _highlight_cache_key, _highlight_batches, _face_highlight_batches
    global _face_vbo, _edge_vbo, _face_vert_count, _edge_vert_count
    if _handler is not None:
        draw_handlers.remove_handler(_handler)
        _handler = None

    draw_handlers.clear_namespace_handler(_handler_ns_key)

    try:
        import rust_engine
        rust_engine.cleanup_engine()
    except Exception:
        pass

    _batch = None
    _shader = None
    _edge_batch = None
    _edge_shader = None
    _highlight_cache_key = None
    _highlight_batches = []
    _face_highlight_batches = []
    _face_vbo = None
    _edge_vbo = None
    _face_vert_count = 0
    _edge_vert_count = 0


def register():
    pass


def unregister():
    stop_drawing()
