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

# sketch package
from .modal_sketch import (
    SEAMLESS_OT_StartSketch,
    SEAMLESS_OT_SketchDrawTool
)
from .sketch_actions import SEAMLESS_OT_SketchAction
from .actions.dimension_edit import SEAMLESS_OT_EditDimensionValue
from . import ops_reference_plane

classes = (
    SEAMLESS_OT_StartSketch,
    SEAMLESS_OT_SketchAction,
    SEAMLESS_OT_SketchDrawTool,
    SEAMLESS_OT_EditDimensionValue,
    ops_reference_plane.SEAMLESS_OT_select_reference_plane
)
