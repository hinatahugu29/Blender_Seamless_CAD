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
