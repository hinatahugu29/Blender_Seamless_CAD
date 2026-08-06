#pragma once
#include <gp_Pnt.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Shape.hxx>
#include <TopoDS_Wire.hxx>
#include <string>
#include <map>

namespace occ_core {

    struct ModifierPerfBreakdown {
        double fillet_setup_ms = 0.0;
        double fillet_target_resolve_ms = 0.0;
        double fillet_add_ms = 0.0;
        double fillet_build_ms = 0.0;
        double fillet_history_ms = 0.0;
        double fillet_added_edges = 0.0;
        double fillet_contours = 0.0;
    };

    void reset_modifier_tracking();
    void reset_modifier_perf_breakdown();
    ModifierPerfBreakdown get_modifier_perf_breakdown();
    bool describe_tracked_edge_loop(const TopoDS_Shape& shape, const TopoDS_Edge& edge, gp_Pnt& out_centroid, double& out_bbox_diag, int& out_edge_count);
    TopoDS_Face resolve_modifier_face_target(const TopoDS_Shape& shape, const std::string& token);
    // V8.1.5: 可変フィレット - "token=radius|token=radius" 形式の文字列を map にパースする。
    // 空文字列/nullptrの場合は空mapを返す(=全edgeがデフォルトradiusを使う、既存挙動と同一)。
    std::map<std::string, double> parse_edge_radii_joined(const char* joined);
    TopoDS_Shape apply_fillet(const TopoDS_Shape& result_shape, const std::string& target_lineage, double radius, std::map<std::string, TopoDS_Shape>* face_map = nullptr, const std::map<std::string, double>* edge_radii_map = nullptr);
    TopoDS_Shape apply_chamfer(const TopoDS_Shape& result_shape, const std::string& target_lineage, double radius, std::map<std::string, TopoDS_Shape>* face_map = nullptr);
    TopoDS_Shape apply_face_offset(const TopoDS_Shape& result_shape, const std::string& target_lineage, double radius, std::map<std::string, TopoDS_Shape>* face_map = nullptr);
    TopoDS_Shape apply_face_inset(const TopoDS_Shape& result_shape, const std::string& target_lineage, double inset_dist, double extrude_dist, std::map<std::string, TopoDS_Shape>* face_map = nullptr);
    TopoDS_Shape apply_draft(const TopoDS_Shape& result_shape, const std::string& ref_lineage, const std::string& target_lineage, double radius_angle, std::map<std::string, TopoDS_Shape>* face_map = nullptr, const TopoDS_Shape& global_shape = TopoDS_Shape());
    TopoDS_Shape apply_shell(const TopoDS_Shape& result_shape, const std::string& target_lineage, double thickness, std::map<std::string, TopoDS_Shape>* face_map = nullptr);
    TopoDS_Shape apply_face_loft(const TopoDS_Shape& result_shape, const std::string& target_lineage, std::map<std::string, TopoDS_Shape>* face_map = nullptr);
    TopoDS_Shape apply_face_revolve(const TopoDS_Shape& result_shape, const std::string& target_lineage, const std::string& axis, double angle_deg, double x, double y, double z, double rx, double ry, double rz, std::map<std::string, TopoDS_Shape>* face_map = nullptr);

}
