#pragma once
#include <TopoDS_Shape.hxx>
#include <TopoDS_Wire.hxx>
#include <string>

namespace occ_core {

    TopoDS_Shape make_curve_or_surface(const double* all_pts, int pts_offset, int count, bool make_surface);
    TopoDS_Shape make_curve_or_surface_from_segments(const double* segments, int seg_offset, int count, bool make_surface);
    TopoDS_Shape make_polyline(const double* all_pts, int pts_offset, int count, double fillet_radius);

}
