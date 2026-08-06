#pragma once
#include <TopoDS_Shape.hxx>
#include <TopoDS_Wire.hxx>
#include <string>

namespace occ_core {

    TopoDS_Shape apply_mirror(const TopoDS_Shape& shape, const std::string& axis, double lx, double ly, double lz, double rx, double ry, double rz);
    TopoDS_Shape apply_array_linear(const TopoDS_Shape& shape, const std::string& axis, int count, double dist);
    TopoDS_Shape apply_array_circular(const TopoDS_Shape& shape, const std::string& axis, int count, double dist, double lx, double ly, double lz, double rx, double ry, double rz);
    TopoDS_Shape apply_revolve(const TopoDS_Shape& shape, const std::string& axis, double dist_angle, double lx, double ly, double lz, double rx, double ry, double rz);

}
