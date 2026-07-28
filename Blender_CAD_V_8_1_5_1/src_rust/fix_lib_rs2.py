import os

filepath = r"G:\blender_addon\Blender_CAD\Blender_CAD_V_7_0_1\src_rust\src\lib.rs"

with open(filepath, 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if "caches.insert(stack_ptr, EdgeDataCache { total_hash, points: edge_points.clone()" in line:
        continue
    if "caches.insert(stack_ptr, MeshDataCache { total_hash, deflection: f_deflection" in line:
        continue
    if "MeshDataCache { total_hash, deflection, angular_deflection, verts:" in line:
        continue
    new_lines.append(line)

with open(filepath, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print("Fixed lib.rs successfully.")
