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
import gpu
import os
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
_debug_log_path = r"e:\blender_addon\Blender_CAD\scratch\wgpu_debug.log"


def _debug_log(msg):
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


def _create_face_batch_with_colors(state, verts, tris):
    if not hasattr(state, 'mesh_lineages') or not state.mesh_lineages:
        return None
    if not hasattr(state, 'mesh_tri_counts') or len(state.mesh_tri_counts) == 0:
        return None
        
    import bpy
    props = bpy.context.scene.cad3_props
    
    if props.is_selection_mode:
        pre_face = props.preselected_face_id.split("@")[0] if props.preselected_face_id else ""
        sel_faces = {s.split("@")[0] for s in props.selected_faces_str.split("|") if s.strip()}
    else:
        pre_face = ""
        sel_faces = set()
    
    colors = []
    flat_verts = []
    
    default_color = (0.0, 0.7, 1.0, 0.5)
    hover_color = (1.0, 1.0, 0.0, 0.8)
    select_color = (1.0, 0.5, 0.0, 0.8)
    
    tri_idx = 0
    for i, base_id in enumerate(state.mesh_lineages):
        if i >= len(state.mesh_tri_counts):
            break
        count = state.mesh_tri_counts[i]
        
        c = default_color
        if base_id == pre_face and pre_face:
            c = hover_color
        elif base_id in sel_faces:
            c = select_color
            
        tri_count = count // 3
        for _ in range(tri_count):
            if tri_idx < len(tris):
                idx_tuple = tris[tri_idx]
                flat_verts.append(verts[idx_tuple[0]])
                flat_verts.append(verts[idx_tuple[1]])
                flat_verts.append(verts[idx_tuple[2]])
                colors.extend([c, c, c])
                tri_idx += 1
            
    if len(colors) == 0:
        return None
        
    try:
        try:
            shader = gpu.shader.from_builtin('3D_SMOOTH_COLOR')
        except Exception:
            shader = gpu.shader.from_builtin('SMOOTH_COLOR')
            
        global _shader
        _shader = shader
        return batch_for_shader(shader, 'TRIS', {"pos": flat_verts, "color": colors})
    except Exception as e:
        _debug_log(f"Face color batch error: {e}")
        return None


def _create_batch():
    global _batch, _shader, _edge_batch, _edge_shader, _highlight_cache_key, _highlight_batches
    from ..core.state_manager import get_state
    state = get_state()

    verts = []
    tris = []
    if len(state.mesh_verts) > 0 and len(state.mesh_tris) > 0:
        try:
            for i in range(0, len(state.mesh_verts), 3):
                verts.append((state.mesh_verts[i], state.mesh_verts[i + 1], state.mesh_verts[i + 2]))
            for i in range(0, len(state.mesh_tris), 3):
                tris.append((state.mesh_tris[i], state.mesh_tris[i + 1], state.mesh_tris[i + 2]))
            
            _batch = _create_face_batch_with_colors(state, verts, tris)
            if _batch is None:
                # Fallback to plain color if color batch fails
                try:
                    _shader = gpu.shader.from_builtin('UNIFORM_COLOR')
                except Exception:
                    try:
                        _shader = gpu.shader.from_builtin('UNIFORM_COLOR')
                    except Exception:
                        _shader = gpu.shader.from_builtin('3D_FLAT_COLOR')
                _batch = batch_for_shader(_shader, 'TRIS', {"pos": verts}, indices=tris)
        except Exception as e:
            _batch = None
            _debug_log(f"create_batch(mesh) failed: {e} verts={len(state.mesh_verts)} tris={len(state.mesh_tris)}")
    else:
        _batch = None

    edge_verts = []
    edge_indices = []
    if len(state.wire_points) > 0 and len(state.wire_edges) > 0:
        try:
            for i in range(0, len(state.wire_points), 3):
                edge_verts.append((state.wire_points[i], state.wire_points[i + 1], state.wire_points[i + 2]))
            v_offset = 0
            for count in state.wire_edges:
                for j in range(count - 1):
                    edge_indices.append((v_offset + j, v_offset + j + 1))
                v_offset += count
            try:
                _edge_shader = gpu.shader.from_builtin('UNIFORM_COLOR')
            except Exception:
                try:
                    _edge_shader = gpu.shader.from_builtin('UNIFORM_COLOR')
                except Exception:
                    _edge_shader = gpu.shader.from_builtin('3D_FLAT_COLOR')
            _edge_batch = batch_for_shader(_edge_shader, 'LINES', {"pos": edge_verts}, indices=edge_indices)
        except Exception as e:
            _edge_batch = None
            _debug_log(f"create_batch(wire) failed: {e} points={len(state.wire_points)} edges={len(state.wire_edges)}")
    else:
        _edge_batch = None

    _highlight_cache_key = None
    _highlight_batches = []


def _build_highlight_batches_if_needed(state):
    global _highlight_cache_key, _highlight_batches
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

    lineage_key = tuple(state.wire_lineages) if getattr(state, "wire_lineages", None) else ()
    key = (tuple(sorted(set(selected_bases))), hover, tuple(state.wire_edges), lineage_key)
    if key == _highlight_cache_key:
        return

    _highlight_cache_key = key
    _highlight_batches = []

    if len(state.wire_points) == 0 or len(state.wire_edges) == 0 or not _edge_shader:
        return

    edge_verts = []
    for i in range(0, len(state.wire_points), 3):
        edge_verts.append((state.wire_points[i], state.wire_points[i + 1], state.wire_points[i + 2]))

    selected_set = set(selected)
    selected_base_set = set(selected_bases)
    v_offset = 0
    for edge_i, count in enumerate(state.wire_edges):
        if getattr(state, "wire_lineages", None) and edge_i < len(state.wire_lineages):
            edge_base = str(state.wire_lineages[edge_i]).split("@")[0]
        else:
            edge_base = f"Edge:{edge_i + 1}"
        is_selected = edge_i in selected_set or edge_base in selected_base_set
        is_hover = (hover is not None and edge_i == hover)
        if is_selected or is_hover:
            sub_indices = [(v_offset + j, v_offset + j + 1) for j in range(count - 1)]
            if sub_indices:
                sub_batch = batch_for_shader(_edge_shader, 'LINES', {"pos": edge_verts}, indices=sub_indices)
                color = (0.0, 1.0, 0.3, 1.0) if is_hover else (1.0, 0.78, 0.0, 1.0)
                width = 5.0 if is_hover else 4.0
                _highlight_batches.append((sub_batch, color, width))
        v_offset += count


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
                _shader.uniform_float("color", (0.0, 0.7, 1.0, 0.5))
            except Exception:
                pass
            _batch.draw(_shader)

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
    global _handler, _batch, _shader, _edge_batch, _edge_shader, _highlight_cache_key, _highlight_batches
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


def register():
    pass


def unregister():
    stop_drawing()
