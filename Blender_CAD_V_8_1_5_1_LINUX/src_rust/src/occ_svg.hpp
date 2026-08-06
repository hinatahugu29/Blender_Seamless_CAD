#pragma once
#include <vector>
#include <string>
#include <TopoDS_Shape.hxx>

namespace occ {
    std::vector<std::string> import_svg(const char* filepath, double scale, const double* data, int data_len);
    TopoDS_Shape get_svg_shape(const std::string& uuid);
}
