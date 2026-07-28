import os

cpp_path = r"G:\blender_addon\Blender_CAD\Blender_CAD_V_7_0_1\src_rust\src\occ_core.cpp"

with open(cpp_path, "r", encoding="utf-8") as f:
    cpp_data = f.read()

cpp_data = cpp_data.replace("return f.HashCode(INT_MAX);", "return (int)(std::hash<TopoDS_Shape>{}(f) & 0x7FFFFFFF);")
cpp_data = cpp_data.replace("return e.HashCode(INT_MAX);", "return (int)(std::hash<TopoDS_Shape>{}(e) & 0x7FFFFFFF);")

with open(cpp_path, "w", encoding="utf-8") as f:
    f.write(cpp_data)

print("Patched hash code syntax successfully.")
