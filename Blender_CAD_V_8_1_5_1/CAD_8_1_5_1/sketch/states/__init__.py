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

from .state_base import SketchState
from .state_select import StateSelect
from .state_point import StatePoint
from .state_line import StateLine
from .state_arc import StateArc
from .state_circle import StateCircle
from .state_fillet import StateFillet
from .state_rectangle import StateRectangle
from .state_semicircle import StateSemicircle
from .state_trim_extend import StateTrimExtend
from .state_slot import StateSlot

STATE_CLASSES = {
    'SELECT': StateSelect,
    'POINT': StatePoint,
    'LINE': StateLine,
    'ARC': StateArc,
    'CIRCLE': StateCircle,
    'RECTANGLE': StateRectangle,
    'CENTER_RECT': StateRectangle,
    'FILLET': StateFillet,
    'SEMICIRCLE': StateSemicircle,
    'TRIM_EXTEND': StateTrimExtend,
    'SLOT': StateSlot
}
