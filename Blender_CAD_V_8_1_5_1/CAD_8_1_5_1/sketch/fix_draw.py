import os
import re

path = 'g:/blender_addon/Blender_CAD/Blender_CAD_V_6_0_3/CAD_6_0_3/sketch/sketch_draw.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

def replacer(match):
    var = match.group(1)
    if var.startswith('_transform_coords'):
        return match.group(0)
    return 'batch_for_shader(shader, \'LINES\', {"pos": _transform_coords(' + var + ')})'

content = re.sub(r"batch_for_shader\(shader, 'LINES', \{\"pos\": (.*?)\}\)", replacer, content)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("SUCCESS")
