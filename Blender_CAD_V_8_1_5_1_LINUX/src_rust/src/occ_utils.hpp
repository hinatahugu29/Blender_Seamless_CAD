#pragma once
#include <string>
#include <chrono>
#include <TopoDS_Shape.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Face.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <gp_Pnt.hxx>

#include <Bnd_Box.hxx>

namespace occ_core {
    extern bool g_debug_logging_enabled;
    extern double g_sum_perf_extrema;
    void log_debug(const std::string& msg);
    double bbox_distance_sq(const Bnd_Box& box, const gp_Pnt& p);
    double safe_edge_point_distance(const TopoDS_Edge& e, const gp_Pnt& target_p);
    double safe_edge_length(const TopoDS_Edge& e);
    gp_Pnt safe_edge_midpoint(const TopoDS_Edge& e);
    TopoDS_Edge find_edge_robust(const std::string& lid, const TopTools_IndexedMapOfShape& edge_map, const std::map<std::string, TopoDS_Shape>* face_map = nullptr);
    double safe_face_point_distance(const TopoDS_Face& f, const gp_Pnt& target_p);
    TopoDS_Face find_face_robust(const std::string& lid, const TopTools_IndexedMapOfShape& face_map);
    TopoDS_Shape apply_divide_closed(const TopoDS_Shape& shape);
}

