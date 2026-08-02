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
import uuid
import math
import mathutils
from bpy_extras import view3d_utils
from ..core_bridge import get_core, update_cad_preview, update_cad_preview_high_quality, update_cad_preview_fast, is_core_busy, get_or_create_stack_ptr
from ..drawing import get_wireframe_engine
from .. import utils

RESULT_COLLECTION_NAME = "Result"

def ensure_result_collection(parent_col):
    if not parent_col:
        return None
    result_col = bpy.data.collections.get(RESULT_COLLECTION_NAME)
    if result_col is None:
        result_col = bpy.data.collections.new(RESULT_COLLECTION_NAME)
    if result_col.name not in parent_col.children:
        parent_col.children.link(result_col)
    return result_col

class SEAMLESS_OT_StartCAD(bpy.types.Operator):
    bl_idname = "seamless.start_cad"
    bl_label = "Start Seamless CAD"
    bl_description = "Initialize Seamless CAD workspace with a parent collection and first part room"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        scene = context.scene
        
        # 1. 親コレクション "Seamless_CAD" の取得または作成
        parent_col = bpy.data.collections.get("Seamless_CAD")
        if not parent_col:
            parent_col = bpy.data.collections.new("Seamless_CAD")
            scene.collection.children.link(parent_col)
        ensure_result_collection(parent_col)
            
        # 2. 最初の子コレクション "Part_1" の作成
        part_name = "Part_1"
        part_col = bpy.data.collections.get(part_name)
        if not part_col:
            part_col = bpy.data.collections.new(part_name)
            parent_col.children.link(part_col)
            
        # properties を初期化
        part_col.seamless_cad_stack_ptr = "0"
        
        scene.is_seamless_cad_started = True
        scene.active_cad_collection = part_col
        
        self.report({'INFO'}, "Seamless CAD Workspace initialized!")
        return {'FINISHED'}

class SEAMLESS_OT_AddPart(bpy.types.Operator):
    bl_idname = "seamless.add_part"
    bl_label = "Add New CAD Part"
    bl_description = "Create a new non-interfering part collection inside Seamless_CAD"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        scene = context.scene
        parent_col = bpy.data.collections.get("Seamless_CAD")
        if not parent_col:
            bpy.ops.seamless.start_cad()
            parent_col = bpy.data.collections.get("Seamless_CAD")
        ensure_result_collection(parent_col)
            
        # 自動インクリメントで重複しない名前を決定
        idx = 1
        while True:
            part_name = f"Part_{idx}"
            if part_name not in bpy.data.collections:
                break
            idx += 1
            
        part_col = bpy.data.collections.new(part_name)
        parent_col.children.link(part_col)
        part_col.seamless_cad_stack_ptr = "0"
        
        scene.active_cad_collection = part_col
        self.report({'INFO'}, f"New part room '{part_name}' created!")
        return {'FINISHED'}

class SEAMLESS_OT_RemovePart(bpy.types.Operator):
    bl_idname = "seamless.remove_part"
    bl_label = "Remove CAD Part"
    bl_description = "Remove the current active part collection and free its CADStack"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        scene = context.scene
        col = scene.active_cad_collection
        if not col or col.name in {"Seamless_CAD", RESULT_COLLECTION_NAME}:
            self.report({'WARNING'}, "Invalid active part collection to remove!")
            return {'CANCELLED'}
            
        # メモリ解放
        # 親パッケージ(CAD_8_1_4/__init__.py)の safe_delete_stack を利用。
        # 以前は `from . import __init__` と operators パッケージ自身を
        # 再importしてしまい、safe_delete_stack が常に見つからず即時解放が
        # 一度も走らないバグがあった(受動的GCスイープ頼みになっていた)。
        try:
            from .. import safe_delete_stack
            safe_delete_stack(col)
        except ImportError as e:
            utils.error_print(f"Seamless: safe_delete_stack unavailable, native stack will rely on GC sweep: {e}")
        
        # コレクションのアンリンクと削除
        parent_col = bpy.data.collections.get("Seamless_CAD")
        if parent_col and col.name in parent_col.children:
            parent_col.children.unlink(col)
            
        # コレクション配下の全オブジェクトを削除 (プロキシも)
        for obj in list(col.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
            
        bpy.data.collections.remove(col)
        
        # 次のアクティブを設定
        scene.active_cad_collection = None
        if parent_col and parent_col.children:
            next_part = next((c for c in parent_col.children if c.name != RESULT_COLLECTION_NAME), None)
            scene.active_cad_collection = next_part
            
        if not scene.active_cad_collection:
            scene.is_seamless_cad_started = False
            
        self.report({'INFO'}, f"Removed part collection!")
        return {'FINISHED'}


class SEAMLESS_OT_GetVersion(bpy.types.Operator):
    bl_idname = "seamless.get_version"
    bl_label = "Get Core Version"
    def execute(self, context):
        core = get_core()
        if not core:
            self.report({'ERROR'}, "Seamless Core not found!")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Core Version: {core.get_version()}")
        return {'FINISHED'}

