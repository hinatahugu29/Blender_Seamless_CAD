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

from .primitives import SEAMLESS_OT_AddPrimitive, SEAMLESS_OT_AddDynamicLoftHole, SEAMLESS_OT_AddCurvePoint, SEAMLESS_OT_VariableBoxHole, SEAMLESS_OT_AddCurvePointAt, SEAMLESS_OT_RemoveCurvePointAt
from .part import SEAMLESS_OT_StartCAD, SEAMLESS_OT_AddPart, SEAMLESS_OT_RemovePart, SEAMLESS_OT_GetVersion
from .management import SEAMLESS_OT_RemovePrimitive, SEAMLESS_OT_SetActivePrimitive, SEAMLESS_OT_DuplicatePrimitive, SEAMLESS_OT_PickActiveAsTarget, SEAMLESS_OT_PickTargetModal, SEAMLESS_OT_ImportStep, SEAMLESS_OT_ImportSvg, SEAMLESS_OT_ExportStep, SEAMLESS_OT_SeparateByBase, SEAMLESS_OT_SetRollbackIndex, SEAMLESS_OT_GroupSelection, SEAMLESS_OT_ToggleFilletEdgeDefault, SEAMLESS_OT_EditSketch, SEAMLESS_OT_ForceRecompute
from .transform import SEAMLESS_OT_InteractivePlacement, SEAMLESS_OT_InteractiveTransform
from .bake import SEAMLESS_OT_BakeMesh
from .ops_visual_snap import CAD_OT_visual_snap
from .ops_offset_pick import SEAMLESS_OT_InteractiveOffsetPick

__all__ = [
    'SEAMLESS_OT_AddPrimitive',
    'SEAMLESS_OT_AddDynamicLoftHole',
    'SEAMLESS_OT_AddCurvePoint',
    'SEAMLESS_OT_AddCurvePointAt',
    'SEAMLESS_OT_RemoveCurvePointAt',
    'SEAMLESS_OT_VariableBoxHole',
    'SEAMLESS_OT_StartCAD',
    'SEAMLESS_OT_AddPart',
    'SEAMLESS_OT_RemovePart',
    'SEAMLESS_OT_GetVersion',
    'SEAMLESS_OT_RemovePrimitive',
    'SEAMLESS_OT_SetActivePrimitive',
    'SEAMLESS_OT_DuplicatePrimitive',
    'SEAMLESS_OT_PickActiveAsTarget',
    'SEAMLESS_OT_PickTargetModal',
    'SEAMLESS_OT_ImportStep',
    'SEAMLESS_OT_ImportSvg',
    'SEAMLESS_OT_ExportStep',
    'SEAMLESS_OT_SeparateByBase',
    'SEAMLESS_OT_SetRollbackIndex',
    'SEAMLESS_OT_GroupSelection',
    'SEAMLESS_OT_ToggleFilletEdgeDefault',
    'SEAMLESS_OT_EditSketch',
    'SEAMLESS_OT_ForceRecompute',
    'SEAMLESS_OT_InteractivePlacement',
    'SEAMLESS_OT_InteractiveTransform',
    'SEAMLESS_OT_BakeMesh',
    'CAD_OT_visual_snap',
    'SEAMLESS_OT_InteractiveOffsetPick',
]
