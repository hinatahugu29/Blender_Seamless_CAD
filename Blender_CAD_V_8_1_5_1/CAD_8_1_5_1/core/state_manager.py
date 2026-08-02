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
import os
import tempfile
from datetime import datetime


class CadState:
    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.active_tool_mode = 'IDLE'
        self.hovered_face_id = None
        self.selected_face_ids = set()

        self.primitives = []
        self.mesh_verts = []
        self.mesh_tris = []
        self.wire_points = []
        self.wire_edges = []
        self.wire_lineages = []

        self.mesh_lineages = []
        self.mesh_tri_counts = []

        self.render_revision = 0
        self.last_drawn_revision = -1
        self._recompute_pending = False
        # アドオン配下ではなく tempdir に書く。Extensions としてインストール
        # した場合、アドオンのディレクトリは書き込み不可になり得る。
        self._debug_log_path = os.path.join(
            tempfile.gettempdir(),
            "seamless_cad_state_debug.log",
        )

    def _debug_log(self, msg):
        try:
            with open(self._debug_log_path, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {msg}\n")
        except Exception:
            pass

    def add_primitive(self, p_type, location=(0.0, 0.0, 0.0), size=(1.0, 1.0, 1.0), operation="ADD"):
        p = {
            "type": p_type,
            "location": list(location),
            "size": list(size),
            "operation": operation,
        }
        if not self.primitives:
            p["operation"] = "BASE"
        self.primitives.append(p)
        self.mark_dirty()
        return len(self.primitives) - 1

    def update_primitive(self, idx, **kwargs):
        if 0 <= idx < len(self.primitives):
            for k, v in kwargs.items():
                if k in self.primitives[idx]:
                    self.primitives[idx][k] = v
            self.mark_dirty()

    def remove_primitive(self, idx):
        if 0 <= idx < len(self.primitives):
            self.primitives.pop(idx)
            if self.primitives:
                self.primitives[0]["operation"] = "BASE"
            self.mark_dirty()

    def mark_dirty(self):
        self.render_revision += 1
        self._schedule_recompute()

    def _schedule_recompute(self):
        if self._recompute_pending:
            return
        self._recompute_pending = True

        def _run():
            try:
                self.recompute_geometry()
            finally:
                self._recompute_pending = False
            return None

        try:
            bpy.app.timers.register(_run, first_interval=0.0)
        except Exception:
            # Fallback path for unusual timer failures.
            self.recompute_geometry()
            self._recompute_pending = False

    @staticmethod
    def _parse_edge_tokens(edge_str):
        edge_indices = []
        if not edge_str:
            return edge_indices
        for token in edge_str.split("|"):
            token = token.strip()
            if not token:
                continue
            base = token.split("@")[0]
            if base.startswith("Edge:"):
                base = base[5:]
            try:
                idx = int(base)
            except ValueError:
                continue
            if idx > 0:
                idx -= 1
            if idx >= 0:
                edge_indices.append(idx)
        return edge_indices

    def _resolve_edge_indices(self, edge_text):
        if not edge_text:
            return []
        lineage_map = {}
        for i, lid in enumerate(self.wire_lineages):
            base = str(lid).split("@")[0]
            lineage_map[base] = i

        out = []
        seen = set()
        for token in edge_text.split("|"):
            token = token.strip()
            if not token:
                continue
            base = token.split("@")[0]
            idx = None
            if base in lineage_map:
                idx = lineage_map[base]
            else:
                parsed = self._parse_edge_tokens(base)
                if parsed:
                    idx = parsed[0]
            if idx is None or idx < 0:
                continue
            if idx in seen:
                continue
            seen.add(idx)
            out.append(idx)
        return out

    def _build_modifiers_from_props(self, props):
        modifiers = []
        for mod in props.modifiers:
            if not mod.enabled:
                continue
            edge_ids = self._resolve_edge_indices(mod.edge_ids)
            if not edge_ids:
                continue
            radius = float(mod.radius)
            if radius <= 0.0:
                continue
            modifiers.append({
                "type": mod.mod_type,
                "radius": radius,
                "edge_indices": edge_ids,
            })

        # fallback for legacy single modifier fields
        if not modifiers:
            fallback_edges = self._resolve_edge_indices(props.selected_edges_str)
            if fallback_edges:
                if props.fillet_radius > 0.0:
                    modifiers.append({
                        "type": "FILLET",
                        "radius": float(props.fillet_radius),
                        "edge_indices": fallback_edges,
                    })
                if props.chamfer_radius > 0.0:
                    modifiers.append({
                        "type": "CHAMFER",
                        "radius": float(props.chamfer_radius),
                        "edge_indices": fallback_edges,
                    })
        return modifiers

    @staticmethod
    def _normalize_edge_token_text(raw_text, valid_count):
        if not raw_text or valid_count <= 0:
            return ""
        seen = set()
        out = []
        for idx in CadState._parse_edge_tokens(raw_text):
            if idx >= valid_count or idx in seen:
                continue
            seen.add(idx)
            out.append(f"Edge:{idx + 1}")
        return "|".join(out)

    def _normalize_selection_props(self, props):
        valid_count = len(self.wire_edges) if self.wire_edges else 0
        valid_bases = set(self.wire_lineages) if self.wire_lineages else set()
        lineage_centers = {}
        for lid in self.wire_lineages:
            lid = str(lid)
            base = lid.split("@")[0]
            if "@" not in lid:
                continue
            try:
                xs, ys, zs = lid.split("@", 1)[1].split(";")
                lineage_centers[base] = (float(xs), float(ys), float(zs))
            except Exception:
                continue

        resolve_dist = float(getattr(props, "lineage_resolve_distance", 0.5))
        resolve_d2_limit = resolve_dist * resolve_dist

        def _closest_lineage_base(coord_text):
            try:
                coord_text = coord_text.split("@", 1)[0]
                xs, ys, zs = coord_text.split(";")
                px, py, pz = float(xs), float(ys), float(zs)
            except Exception:
                return ""
            best = ""
            best_d2 = 1e100
            for base, (cx, cy, cz) in lineage_centers.items():
                dx = cx - px
                dy = cy - py
                dz = cz - pz
                d2 = dx * dx + dy * dy + dz * dz
                if d2 < best_d2:
                    best_d2 = d2
                    best = base
            if best and best_d2 <= resolve_d2_limit:
                return best
            return ""

        def _normalize_by_lineage(raw_text):
            if not raw_text:
                return ""
            out = []
            seen = set()
            for token in raw_text.split("|"):
                token = token.strip()
                if not token:
                    continue
                if token.startswith("SemLoop:"):
                    if token in seen:
                        continue
                    seen.add(token)
                    out.append(token)
                    continue
                raw = token
                base = token.split("@")[0]
                idxs = self._parse_edge_tokens(base)
                if idxs:
                    idx = idxs[0]
                    if idx >= valid_count:
                        if "@" in raw:
                            base = _closest_lineage_base(raw.split("@", 1)[1])
                            if not base:
                                continue
                        else:
                            continue
                    else:
                        base = f"Edge:{idx + 1}"
                elif "@" in raw:
                    base = _closest_lineage_base(raw.split("@", 1)[1])
                    if not base:
                        continue
                if valid_bases and base not in valid_bases:
                    continue
                if base in seen:
                    continue
                seen.add(base)
                out.append(base)
            return "|".join(out)

        from . import state as state_props
        state_props.set_internal_sync(True)
        try:
            props.selected_edges_str = _normalize_by_lineage(props.selected_edges_str)
            props.preselected_edge_id = _normalize_by_lineage(props.preselected_edge_id)
            for mod in props.modifiers:
                mod.edge_ids = _normalize_by_lineage(mod.edge_ids)
        finally:
            state_props.set_internal_sync(False)

    def recompute_geometry(self):
        from .core_bridge import compute_geometry
        if not self.primitives:
            self.mesh_verts.clear()
            self.mesh_tris.clear()
            self.mesh_lineages.clear()
            self.mesh_tri_counts.clear()
            self.wire_points.clear()
            self.wire_edges.clear()
            self.wire_lineages.clear()
            self._debug_log("recompute: no primitives; buffers cleared")
            return

        modifiers = []
        tess = {
            "mesh_linear_deflection": 0.1,
            "mesh_angular_deflection": 0.5,
            "wire_deflection": 0.01,
        }
        try:
            props = bpy.context.scene.cad3_props
            modifiers = self._build_modifiers_from_props(props)
            tess = {
                "mesh_linear_deflection": float(props.mesh_linear_deflection),
                "mesh_angular_deflection": float(props.mesh_angular_deflection),
                "wire_deflection": float(props.wire_deflection),
            }
        except Exception:
            pass

        prev_mesh_verts = self.mesh_verts
        prev_mesh_tris = self.mesh_tris
        prev_mesh_lineages = self.mesh_lineages
        prev_mesh_tri_counts = self.mesh_tri_counts
        prev_wire_points = self.wire_points
        prev_wire_edges = self.wire_edges
        prev_wire_lineages = self.wire_lineages

        self._debug_log(f"recompute: input prim={len(self.primitives)} mods={len(modifiers)} tess={tess}")
        wire_res, mesh_res = compute_geometry(self.primitives, modifiers=modifiers, tess=tess)
        if wire_res is None and mesh_res is None:
            # Keep previous render buffers on transient compute failure
            # (matches V2 behavior where visuals do not disappear on bad targets).
            self._debug_log("recompute: compute_geometry returned None/None; keep previous")
            return

        if mesh_res:
            self.mesh_verts, self.mesh_tris = mesh_res[0], mesh_res[1]
            if len(mesh_res) >= 4 and mesh_res[2] and mesh_res[3]:
                self.mesh_lineages = [str(x).split("@")[0] for x in mesh_res[2]]
                self.mesh_tri_counts = mesh_res[3]
            else:
                self.mesh_lineages = []
                self.mesh_tri_counts = []
        else:
            # Keep previous mesh when tessellation fails transiently.
            self.mesh_verts, self.mesh_tris = prev_mesh_verts, prev_mesh_tris
            self.mesh_lineages, self.mesh_tri_counts = prev_mesh_lineages, prev_mesh_tri_counts
            self._debug_log("recompute: mesh result empty; keep previous mesh")

        if wire_res:
            self.wire_points, self.wire_edges = wire_res[0], wire_res[1]
            if len(wire_res) >= 3 and wire_res[2]:
                self.wire_lineages = [str(x).split("@")[0] for x in wire_res[2]]
            else:
                self.wire_lineages = [f"Edge:{i+1}" for i in range(len(self.wire_edges))]
        else:
            self.wire_points, self.wire_edges, self.wire_lineages = (
                prev_wire_points,
                prev_wire_edges,
                prev_wire_lineages,
            )
            self._debug_log("recompute: wire result empty; keep previous wire")
        self._debug_log(
            f"recompute: ok mesh_v={len(self.mesh_verts)} mesh_t={len(self.mesh_tris)} wire_p={len(self.wire_points)} wire_e={len(self.wire_edges)}"
        )
        try:
            self._normalize_selection_props(bpy.context.scene.cad3_props)
        except Exception:
            self._debug_log("recompute: normalize_selection_props failed")
            pass

    def reset(self):
        self.active_tool_mode = 'IDLE'
        self.hovered_face_id = None
        self.selected_face_ids.clear()
        self.primitives.clear()
        self.mark_dirty()


def get_state() -> CadState:
    return CadState.get_instance()

