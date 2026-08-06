#pragma once
#include <TopoDS_Shape.hxx>
#include <string>
#include <map>

namespace occ_core {
    TopoDS_Shape apply_boolean(const TopoDS_Shape& base_shape, const TopoDS_Shape& tool_shape, const std::string& p_op, std::map<std::string, TopoDS_Shape>* face_map = nullptr, bool base_is_fused = false);
    TopoDS_Shape apply_boolean_batch(const TopoDS_Shape& base_shape, const TopTools_ListOfShape& tool_shapes, const std::string& p_op, std::map<std::string, TopoDS_Shape>* face_map = nullptr, bool base_is_fused = false);
    TopoDS_Shape fuse_compound(const TopoDS_Shape& shape, std::map<std::string, TopoDS_Shape>* face_map = nullptr);
}
