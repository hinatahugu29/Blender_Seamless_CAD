#pragma once
#include <TopoDS_Shape.hxx>
#include <TopoDS_Wire.hxx>
#include <string>
#include <vector>

namespace occ_core {

    TopoDS_Shape make_curve_or_surface(const double* all_pts, int pts_offset, int count, bool make_surface);
    TopoDS_Shape make_curve_or_surface_from_segments(const double* segments, int seg_offset, int count, bool make_surface);
    TopoDS_Shape make_polyline(const double* all_pts, int pts_offset, int count, double fillet_radius);

    // 既存形状をスケッチ平面へ正射影して 2D エンティティの平坦な数値列を返す。
    // 書式は occ_sketch.cpp の project_edge_2d のコメントを見ること。
    bool project_to_sketch_plane(void* stack_ptr, const char* lineage, bool is_face,
                                 const double* plane_origin, const double* plane_x, const double* plane_z,
                                 std::vector<double>& out);

    int project_to_sketch_plane_buf(void* stack_ptr, const char* lineage, bool is_face,
                                    const double* plane_origin, const double* plane_x, const double* plane_z,
                                    double* out_buf, int buf_len);

}
