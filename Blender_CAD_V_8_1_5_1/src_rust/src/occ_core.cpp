#define _CRT_SECURE_NO_WARNINGS
#include <Standard_Version.hxx>
#include <Standard_DefineAlloc.hxx>
#include <Standard_Handle.hxx>
#include <gp_Pnt.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Shape.hxx>
#include <TopoDS_Vertex.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Face.hxx>
#include <BRepAdaptor_Curve.hxx>
#include <TopoDS_Wire.hxx>
#include <TopoDS_Shell.hxx>
#include <TopoDS_Solid.hxx>
#include <TopoDS_Compound.hxx>
#include <TopTools_ShapeMapHasher.hxx>
#include <TopTools_MapOfShape.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopTools_DataMapOfShapeShape.hxx>
#include <TopTools_DataMapOfShapeInteger.hxx>
#include <TopTools_ListOfShape.hxx>
#include <BRep_Builder.hxx>
#include <ShapeFix_Face.hxx>
#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <TopTools_DataMapOfShapeListOfShape.hxx>
#include <TopTools_HSequenceOfShape.hxx>
#include "occ_core.hpp"
#include <TopExp.hxx>
#include <iostream>
#include <string>
#include <fstream>
#include <sstream>
#include <chrono>


#include <map>
#include <cmath>
#include <cstring>
#include <algorithm>
#include <vector>
#include <thread>
#include <mutex>
#include <BRep_Builder.hxx>
#include <TopoDS_Compound.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <BRepPrimAPI_MakeSphere.hxx>
#include <BRepPrimAPI_MakeCone.hxx>
#include <BRepPrimAPI_MakeTorus.hxx>
#include <BRepPrimAPI_MakeRevol.hxx>
#include <BRepPrimAPI_MakePrism.hxx>
#include <BRepAlgoAPI_Cut.hxx>
#include <BRepAlgoAPI_Fuse.hxx>
#include <BRepAlgoAPI_Common.hxx>
#include <BRepBuilderAPI_Transform.hxx>
#include <BRepBuilderAPI_GTransform.hxx>
#include <BRepBuilderAPI_MakeVertex.hxx>
#include <BRepGProp.hxx>
#include <GProp_GProps.hxx>
#include <ShapeUpgrade_UnifySameDomain.hxx>
#include <BRepIntCurveSurface_Inter.hxx>
#include <IntCurveSurface_HInter.hxx>
#include <GeomAdaptor_Curve.hxx>
#include <Geom_Line.hxx>
#include <TopoDS.hxx>
#include <TopAbs_ShapeEnum.hxx>
#include <TopExp_Explorer.hxx>
#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <GCPnts_UniformDeflection.hxx>
#include <GCPnts_UniformAbscissa.hxx>
#include <GCPnts_TangentialDeflection.hxx>
#include <gp_Pnt.hxx>
#include <gp_Trsf.hxx>
#include <gp_Vec.hxx>
#include <gp_GTrsf.hxx>
#include <gp_Lin.hxx>
#include <gp_Dir.hxx>
#include <BRepExtrema_DistShapeShape.hxx>
#include <BRep_Tool.hxx>
#include <Geom_Curve.hxx>
#include <GeomAPI_ProjectPointOnCurve.hxx>
#include <BRepFilletAPI_MakeFillet.hxx>
#include <BRepFilletAPI_MakeChamfer.hxx>
#include <BRepMesh_IncrementalMesh.hxx>
#include <BRepTools.hxx>
#include <Geom_Surface.hxx>
#include <Poly_Triangulation.hxx>
#include <Poly_Triangle.hxx>
#include <Standard_ErrorHandler.hxx>
#include <Standard_Failure.hxx>
#include <TopTools_DataMapOfShapeInteger.hxx>
#include <TCollection_AsciiString.hxx>
#include <BRepGProp.hxx>
#include <GProp_GProps.hxx>
#include <ShapeFix_Face.hxx>
#include <GeomAPI_PointsToBSpline.hxx>
#include <Geom_BSplineCurve.hxx>
#include <TColgp_Array1OfPnt.hxx>
#include <BRepAdaptor_CompCurve.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakePolygon.hxx>
#include <BRepOffsetAPI_MakePipe.hxx>
#include <BRepOffsetAPI_DraftAngle.hxx>
#include <BRepOffsetAPI_MakeThickSolid.hxx>
#include <BRepOffsetAPI_MakeOffset.hxx>
#include <BRepFeat_SplitShape.hxx>
#include <gp_Circ.hxx>
#include <gp_Ax2.hxx>
#include <TColgp_Array1OfPnt.hxx>
#include <Extrema_ExtCC.hxx>
#include <Extrema_POnCurv.hxx>
#include <GC_MakeArcOfCircle.hxx>
#include <gp_Quaternion.hxx>
#include <gp_EulerSequence.hxx>
#include <BRepOffsetAPI_ThruSections.hxx>
#include <mutex>
#include <Bnd_Box.hxx>
#include <BRepBndLib.hxx>
#include <BRepTools_WireExplorer.hxx>
#include <ShapeAnalysis_FreeBounds.hxx>

#include "occ_modifiers.hpp"
#include "occ_primitives.hpp"
#include "occ_booleans.hpp"
#include "occ_utils.hpp"
#include "occ_sketch.hpp"
#include "occ_arrays.hpp"
#include "occ_step.hpp"
#include "occ_svg.hpp"

namespace occ_core {
void ensure_cluster_fused(ClusterData& c) {
    if (!c.is_fused_valid) {
        try { c.fused = fuse_compound(c.raw); }
        catch(...) { c.fused = c.raw; }
        c.is_fused_valid = true;
    }
}
void ensure_cluster_bbox(ClusterData& c) {
    if (!c.is_bbox_valid) {
        ensure_cluster_fused(c);
        BRepBndLib::Add(c.fused, c.bbox);
        c.is_bbox_valid = true;
    }
}
void ensure_cluster_index(ClusterData& c) {
    if (!c.is_index_valid) {
        ensure_cluster_fused(c);
        TopTools_IndexedMapOfShape em; TopExp::MapShapes(c.fused, TopAbs_EDGE, em);
        c.edge_grid.clear();
        for (int i=1; i<=em.Extent(); ++i) {
            c.edges.push_back(TopoDS::Edge(em.FindKey(i)));
            c.edge_midpoints.push_back(safe_edge_midpoint(c.edges.back()));
            c.edge_grid.add(c.edge_midpoints.back(), c.edges.size() - 1);
        }
        TopTools_IndexedMapOfShape fm; TopExp::MapShapes(c.fused, TopAbs_FACE, fm);
        c.face_grid.clear();
        for (int i=1; i<=fm.Extent(); ++i) {
            c.faces.push_back(TopoDS::Face(fm.FindKey(i)));
            GProp_GProps props; BRepGProp::SurfaceProperties(c.faces.back(), props);
            c.face_centroids.push_back(props.CentreOfMass());
            c.face_grid.add(c.face_centroids.back(), c.faces.size() - 1);
        }
        c.is_index_valid = true;
    }
}

static std::vector<std::string> split_target_tokens(const std::string& targets_str) {
    std::vector<std::string> targets;
    std::string t_str = targets_str;
    size_t pos = 0;
    while ((pos = t_str.find('|')) != std::string::npos) {
        if (pos > 0) targets.push_back(t_str.substr(0, pos));
        t_str.erase(0, pos + 1);
    }
    if (!t_str.empty()) targets.push_back(t_str);
    return targets;
}

static std::string build_cluster_assignment_signature(ClusterData& cluster) {
    ensure_cluster_bbox(cluster);
    ensure_cluster_index(cluster);
    Standard_Real xmin = 0.0, ymin = 0.0, zmin = 0.0, xmax = 0.0, ymax = 0.0, zmax = 0.0;
    if (!cluster.bbox.IsVoid()) {
        cluster.bbox.Get(xmin, ymin, zmin, xmax, ymax, zmax);
    }

    std::ostringstream ss;
    ss.setf(std::ios::fixed);
    ss.precision(4);
    ss << "E" << cluster.edges.size()
       << "|F" << cluster.faces.size()
       << "|B" << xmin << "," << ymin << "," << zmin << "," << xmax << "," << ymax << "," << zmax;
    return ss.str();
}

static std::string build_modifier_target_assignment_cache_key(
    const std::string& mod_type,
    const std::string& targets_str,
    std::vector<ClusterData>& clusters
) {
    std::ostringstream ss;
    ss << mod_type << "|T:" << targets_str << "|C:" << clusters.size();
    for (auto& cluster : clusters) {
        ss << "|[" << build_cluster_assignment_signature(cluster) << "]";
    }
    return ss.str();
}

static gp_Pnt bbox_center_point(const Bnd_Box& box) {
    Standard_Real xmin = 0.0, ymin = 0.0, zmin = 0.0, xmax = 0.0, ymax = 0.0, zmax = 0.0;
    if (box.IsVoid()) return gp_Pnt(0.0, 0.0, 0.0);
    box.Get(xmin, ymin, zmin, xmax, ymax, zmax);
    return gp_Pnt((xmin + xmax) * 0.5, (ymin + ymax) * 0.5, (zmin + zmax) * 0.5);
}

static std::string build_modifier_target_cluster_cache_key(
    const std::string& mod_type,
    const std::string& target_token,
    size_t cluster_count
) {
    std::ostringstream ss;
    ss << mod_type << "|N" << cluster_count << "|" << target_token;
    return ss.str();
}

static double compute_cluster_target_distance(
    ClusterData& cluster,
    const std::string& target_t,
    const gp_Pnt& target_coord
) {
    double d_min = 1e10;
    const double search_radius = 2.0;
    if (target_t.find("Edge:") == 0 || target_t.rfind("SemLoop", 0) == 0) {
        auto cands = cluster.edge_grid.get_candidates(target_coord, search_radius);
        if (cands.empty()) {
            for (size_t edge_idx = 0; edge_idx < cluster.edge_midpoints.size(); ++edge_idx) {
                double d = cluster.edge_midpoints[edge_idx].Distance(target_coord);
                if (d < d_min) d_min = d;
            }
        } else {
            for (size_t edge_idx : cands) {
                double d = cluster.edge_midpoints[edge_idx].Distance(target_coord);
                if (d < d_min) d_min = d;
            }
        }
        if (d_min < 1e-3) d_min = 0.0;
    } else if (target_t.find("Face:") == 0) {
        auto cands = cluster.face_grid.get_candidates(target_coord, search_radius);
        if (cands.empty()) {
            for (size_t face_idx = 0; face_idx < cluster.face_centroids.size(); ++face_idx) {
                double d = cluster.face_centroids[face_idx].Distance(target_coord);
                if (d < d_min) d_min = d;
            }
        } else {
            for (size_t face_idx : cands) {
                double d = cluster.face_centroids[face_idx].Distance(target_coord);
                if (d < d_min) d_min = d;
            }
        }
    }
    return d_min;
}


void set_debug_logging(bool enabled) {
    g_debug_logging_enabled = enabled;
}

// g_semantic_edge_history / g_face_history 等(occ_modifiers.cpp)はスタック単位でなく
// プロセス全体で共有される static キャッシュであり、update_geometry() の冒頭で
// reset_modifier_tracking() により無条件にクリアされる。Rust側は「スタックごとに
// 並列実行可能」という設計のため、複数スタックのワーカースレッドが同時に
// update_geometry() を呼ぶと、片方のフィレット/シェル解決用履歴をもう片方が
// リセットしてしまい、クラッシュや静かなジオメトリ破損を引き起こしうる。
// このミューテックスで update_geometry() 全体を直列化し、キャッシュ破壊を防ぐ。
static std::mutex g_occ_mutex;

    void* create_cad_stack() {
        return new CADStack();
    }

    void delete_cad_stack(void* stack_ptr) {
        if (stack_ptr) {
            delete static_cast<CADStack*>(stack_ptr);
        }
    }









    void update_cad_geometry(
        const std::string& json_str, 
        const std::vector<std::string>& lineages, 
        double fillet_radius, 
        double deflection,
        double angular_deflection,
        void* v_ptr, void* c_ptr, void* l_ptr,
        PushPointFn push_point, PushCountFn push_count, PushStringFn push_string
    ) {
        // 髴托ｽｴ繝ｻ・ｾ髯懶ｽｨ繝ｻ・ｨ驍ｵ・ｲ遶丞､ｲ・ｼ繝ｻ・ｸ・ｺ繝ｻ・ｮ鬯ｮ・｢繝ｻ・｢髫ｰ・ｨ繝ｻ・ｰ驍ｵ・ｺ繝ｻ・ｯ髯ｷﾂ郢晢ｽｻ・主､青・ｧ郢晢ｽｻ遶翫・g_current_shape 驛｢・ｧ陷ｻ莠･・ｳ・ｩ髫ｴ繝ｻ・ｽ・ｰ驍ｵ・ｺ陷会ｽｱ・つ遶丞｢・豪・ｹ譏ｴ繝ｻ邵ｺ蜥擾ｽｹ譎｢・ｽ・｣驛｢譎｢・ｽ・ｼ驛｢・ｧ陞ｳ螟ｲ・ｽ・ｵ繝ｻ・ｰ驛｢・ｧ陝ｲ・ｨ隨ｳ迢暦ｽｹ・ｧ陷ｿ・･繝ｻ・ｽ繝ｻ・ｹ髯ｷ謇假ｽｽ・ｲ驛｢・ｧ陷ｻ閧ｲ蟶･驍ｵ・ｺ郢晢ｽｻ
        // 髯橸ｽｳ雋翫・諤咎し・ｺ繝ｻ・ｮ髴難ｽ､繝ｻ・ｹ髫ｰ螟ｲ・ｽ・ｽ髯ｷ繝ｻ・ｽ・ｺ驍ｵ・ｺ繝ｻ・ｯ髯具ｽｻ繝ｻ・･鬯ｨ・ｾ郢晢ｽｻget_edge_points 驍ｵ・ｺ繝ｻ・ｧ鬮ｯ・ｦ陟暮ｯ会ｽｽ蜀暦ｽｹ・ｧ陟暮ｯ会ｽｽ迢暦ｽｸ・ｺ雋・∞・ｽ竏ｫ・ｸ・ｲ遶丞､ｲ・ｼ繝ｻ・ｸ・ｺ髦ｮ蜷ｶﾂ蝣､・ｸ・ｺ繝ｻ・ｯ髯溷私・ｽ・｢髴托ｽ･繝ｻ・ｶ驍ｵ・ｺ繝ｻ・ｮ髫ｴ蜴・ｽｽ・ｴ髫ｴ繝ｻ・ｽ・ｰ驍ｵ・ｺ繝ｻ・ｨ髯ｷﾂ鬮ｦ・ｪ・朱豪・ｹ譏ｴ繝ｻ邵ｺ蜥擾ｽｹ譎｢・ｽ・･驛｢・ｧ陞ｳ螟ｲ・ｽ・｡陟募ｨｯ魘ｬ
        // lib.rs 髯句ｹ｢・ｽ・ｴ驍ｵ・ｺ繝ｻ・ｧ json 驍ｵ・ｺ闕ｵ譎｢・ｽ繝ｻupdate_geometry 驛｢・ｧ髮区ｨ費ｽｻ荵滂ｽｸ・ｺ繝ｻ・ｳ髯ｷ繝ｻ・ｽ・ｺ驍ｵ・ｺ陷会ｽｱ遯ｶ・ｻ驍ｵ・ｺ郢晢ｽｻ繝ｻ邇厄ｽｭ魃会ｽｽ・｢髯昴・ﾂ・･郢晢ｽｻ驛｢譎・ｽｼ驥・ｺｽ・ｹ譎｢・ｽ・ｼ驛｢・ｧ陜｣・､繝ｻ・ｶ繝ｻ・ｭ髫ｰ蝠上・繝ｻ・ｽ驍ｵ・ｺ繝ｻ・､驍ｵ・ｺ繝ｻ・､驍ｵ・ｲ郢晢ｽｻ
    }

// --- Modular Primitive and Modifier Helper Functions ---
    bool update_geometry(
        void* stack_ptr,
        int n_prims, const char** types, const char** ops, const char** uuids,
        const double* locs, const double* rots, const double* rots_quat, const double* sizes,
        const double* radii, const double* pipe_radii,
        const double* a_starts, const double* a_ends,
        const char** target_lineages, const char** reference_lineages,
        const int* fill_closed, const int* use_pipe,
        const double* extrude_heights, const double* radii2, const double* minor_radii,
        const int* sides, const double* modules, const double* pressure_angles,
        const char** target_uuids, const int* p_counts, const double* distances, const char** pattern_axes,
        const char** top_shapes, const char** bot_shapes, const char** sweep_frame_modes, const double* sweep_rolls,
        const double* all_pts, const int* pt_counts,
        const double* all_segments, const int* segment_counts,
        const uint64_t* hashes, const uint64_t* geo_hashes,
        // V8.1.5: 可変フィレット - primitive毎に "token=radius|token=radius" 形式で
        // 個別半径の上書きを渡す(空文字列 = 上書きなし、全edgeがprimitiveのradiusを使う)
        const char** edge_radii_joined,
        double f_radius, double deflection, const char** f_lineages, int n_lineages,
        void* points_vec,        void* counts_vec,
        void* lineages_out_vec,
        PushPointFn push_point,
        PushCountFn push_count,
        PushStringFn push_string,
        bool fast_mode,
        double* perf_out
    ) {
    CADStack* stack = static_cast<CADStack*>(stack_ptr);
    if (!stack) return false;
    // グローバルなモディファイア履歴キャッシュ(g_semantic_edge_history等)を
    // 保護するため、update_geometry全体を直列化する。
    std::lock_guard<std::mutex> lock(g_occ_mutex);
    auto t_very_start = std::chrono::high_resolution_clock::now();
    try {
        g_sum_perf_extrema = 0.0;
        bool first = true; TopoDS_Shape result_shape; std::map<std::string, TopoDS_Shape> uuid_to_shape;
        int pts_offset = 0, seg_offset = 0, first_dirty_idx = 0; uint64_t current_cum_hash = 0;
        
        // --- 1. 髫ｴ魃会ｽｽ・ｩ髫ｴ蟶ｶ・ｺ菴ｩ諛・ｽｹ・ｧ繝ｻ・ｿ驛｢譎｢・ｽ・ｼ驛｢譎｢・ｽ・ｳ髯具ｽｻ繝ｻ・､髯橸ｽｳ郢晢ｽｻ 髯ｷ闌ｨ・ｽ・ｨ髣厄ｽｴ髦ｮ蜷ｶ繝ｻ驛｢譏懶ｽｸ鄙ｫﾎ暮Δ・ｧ繝ｻ・ｷ驛｢譎｢・ｽ・･驍ｵ・ｺ陟包ｽ｡繝ｻ・ｸ・つ鬮｢・ｾ繝ｻ・ｴ驍ｵ・ｺ陷ｷ・ｶ繝ｻ迢暦ｽｸ・ｺ郢晢ｽｻ---
        uint64_t total_cum_hash = 0;
        for (int i = 0; i < n_prims; ++i) {
            total_cum_hash = total_cum_hash * 31 + hashes[i];
        }
        {
            std::stringstream ss;
            ss << "DEBUG: C++ update_geometry called! n_prims: " << n_prims
               << ", stack_results: " << stack->stack_results.size()
               << ", total_cum_hash: " << total_cum_hash;
            log_debug(ss.str());
        }
        if (n_prims > 0 && n_prims == (int)stack->stack_results.size() && stack->stack_results.back().cumulative_hash == total_cum_hash && std::abs(stack->last_deflection - deflection) < 1e-9 && stack->last_fast_mode == fast_mode) {
            log_debug(
                "DEBUG: C++ update_geometry EARLY RETURN (Cache HIT) n_prims=" +
                std::to_string(n_prims) +
                " total_cum_hash=" + std::to_string(total_cum_hash) +
                " deflection=" + std::to_string(deflection) +
                " fast_mode=" + std::to_string(fast_mode)
            );
            return true; 
        }

        // 髯ｷ・ｷ郢晢ｽｻ郢晢ｽｻ驛｢譎｢・ｽ・ｪ驛｢譎・ｽｺ蛟･ﾎ倬Δ・ｧ繝ｻ・｣驛｢譎・§郢晢ｽｻ驛｢譏懶ｽｻ・｣・主ｸｷ・ｹ譎｢・ｽ・｡驛｢譎｢・ｽ・ｼ驛｢・ｧ繝ｻ・ｿ驛｢・ｧ繝ｻ・ｭ驛｢譎｢・ｽ・｣驛｢譏ｴ繝ｻ邵ｺ蜥擾ｽｹ譎｢・ｽ・･驛｢・ｧ陷ｻ莠･・ｳ・ｩ髫ｴ繝ｻ・ｽ・ｰ郢晢ｽｻ闔�蛹・ｽｽ・ｺ驕停・陬滄Δ譎冗樟・主ｸｷ・ｹ譎｢・ｽ・ｳ驛｢・ｧ繝ｻ・ｹ驛｢譎・ｽｼ譁青ｰ驛｢譎｢・ｽ・ｼ驛｢譎｢・｣・ｰ鬨ｾ・ｶ繝ｻ・ｸ髫ｹ・ｿ繝ｻ・ｺ鬨ｾ蛹・ｽｽ・ｨ郢晢ｽｻ郢晢ｽｻ
        stack->transform_cache.clear();
        for (int i = 0; i < n_prims; ++i) {
            TransformCache tc;
            tc.op = ops[i];
            tc.loc[0] = locs[i*3+0]; tc.loc[1] = locs[i*3+1]; tc.loc[2] = locs[i*3+2];
            tc.rot[0] = rots[i*3+0]; tc.rot[1] = rots[i*3+1]; tc.rot[2] = rots[i*3+2];
            stack->transform_cache[uuids[i]] = tc;
        }

        // --- 2. 驛｢・ｧ繝ｻ・ｭ驛｢譎｢・ｽ・｣驛｢譏ｴ繝ｻ邵ｺ蜥擾ｽｹ譎｢・ｽ・･髯ｷﾂ隶朱｡俶・鬨ｾ蛹・ｽｽ・ｨ鬩阪ｅ繝ｻ陜ｨ蝣､・ｸ・ｺ繝ｻ・ｮ髴大､ｲ・ｽ・ｹ髯橸ｽｳ郢晢ｽｻ---
        bool prevent_unify_faces = false;
        for (int i = 0; i < n_prims; ++i) {
            if (std::string(types[i]) == "FACE_INSET") prevent_unify_faces = true;
        }

        for (int i = 0; i < n_prims; ++i) {
            current_cum_hash = current_cum_hash * 31 + hashes[i];
            if (i < (int)stack->stack_results.size() && stack->stack_results[i].cumulative_hash == current_cum_hash) {
                first_dirty_idx = i + 1;
            } else {
                break;
            }
        }
        log_debug(
            "[CACHE_ANALYSIS] update_geometry first_dirty_idx=" + std::to_string(first_dirty_idx) +
            " stack_results=" + std::to_string(stack->stack_results.size()) +
            " n_prims=" + std::to_string(n_prims) +
            " reused_prefix=" + std::to_string(first_dirty_idx) +
            " recompute_count=" + std::to_string((n_prims > first_dirty_idx) ? (n_prims - first_dirty_idx) : 0)
        );

        reset_modifier_tracking();
        reset_modifier_perf_breakdown();

        double sum_perf_prim = 0.0;
        double sum_perf_bool_main = 0.0;
        double sum_perf_bool_modifier = 0.0;
        double sum_perf_unify = 0.0;
        double sum_perf_resume_restore = 0.0;
        double sum_perf_modifier_target_assign = 0.0;
        double sum_perf_modifier_apply = 0.0;
        double sum_perf_modifier_recluster = 0.0;

        std::vector<ClusterData> current_clusters;
        std::map<std::string, TopoDS_Shape> current_face_map;
        if (first_dirty_idx > 0) {
            auto t_start_resume = std::chrono::high_resolution_clock::now();
            int resume_idx = first_dirty_idx - 1;
            current_clusters = stack->stack_results[resume_idx].clusters;
            if (stack->stack_results[resume_idx].unified_shape.IsNull()) {
                // Optional: unify each cluster
                std::vector<ClusterData> unif_clusters;
                for(auto& c : current_clusters) {
                    ensure_cluster_fused(c); TopoDS_Shape temp = c.fused;
//                     ShapeUpgrade_UnifySameDomain unif(temp, true, !prevent_unify_faces, true);
//                     unif.Build();
                     unif_clusters.push_back({temp});
                }
                current_clusters = unif_clusters;
                
                BRep_Builder bb; TopoDS_Compound comp; bb.MakeCompound(comp);
                for(auto& c : current_clusters) bb.Add(comp, c.raw);
                stack->stack_results[resume_idx].unified_shape = comp;
            }
            result_shape = stack->stack_results[resume_idx].unified_shape;
            uuid_to_shape = stack->stack_results[resume_idx].uuid_to_shape;
            current_face_map = stack->stack_results[resume_idx].face_id_map;
            first = false;
            auto t_end_resume = std::chrono::high_resolution_clock::now();
            sum_perf_resume_restore += std::chrono::duration<double, std::milli>(t_end_resume - t_start_resume).count();
        }

        std::vector<std::vector<ClusterData>> cluster_stack;
        std::vector<std::map<std::string, TopoDS_Shape>> face_map_stack;
        if (first_dirty_idx > 0) {
            for (int k = 0; k < first_dirty_idx; ++k) {
                std::string k_type = types[k];
                if (k_type == "GROUP_START") {
                    if (k > 0) {
                        cluster_stack.push_back(stack->stack_results[k - 1].clusters);
                        face_map_stack.push_back(stack->stack_results[k - 1].face_id_map);
                    } else {
                        cluster_stack.push_back({});
                        face_map_stack.push_back({});
                    }
                } else if (k_type == "GROUP_END") {
                    if (!cluster_stack.empty()) {
                        cluster_stack.pop_back();
                        face_map_stack.pop_back();
                    }
                }
            }
        }

        if (stack->stack_results.size() > (size_t)first_dirty_idx) stack->stack_results.erase(stack->stack_results.begin() + first_dirty_idx, stack->stack_results.end());
        for (int i = 0; i < first_dirty_idx; ++i) {
            if (std::string(types[i]) == "CURVE" || std::string(types[i]) == "SURFACE" || std::string(types[i]) == "POLYLINE") {
                pts_offset += pt_counts[i] * 4;
                seg_offset += segment_counts[i] * 17;
            }
        }

        current_cum_hash = (first_dirty_idx > 0) ? stack->stack_results[first_dirty_idx - 1].cumulative_hash : 0;

        for (int i = first_dirty_idx; i < n_prims; ++i) {
            auto t_start_prim = std::chrono::high_resolution_clock::now();
            std::string p_type = types[i], p_op = ops[i], p_uuid = uuids[i];
            log_debug("[LOOP] i=" + std::to_string(i) + " type=" + p_type + " op=" + p_op);
            // V8.1.5: 可変フィレット - このprimitiveの個別edge半径マップ(FILLET以外は常に空)
            std::map<std::string, double> p_edge_radii_map;
            if (p_type == "FILLET" && edge_radii_joined) {
                p_edge_radii_map = parse_edge_radii_joined(edge_radii_joined[i]);
            }
            uint64_t p_hash = hashes[i];
            uint64_t p_geo_hash = geo_hashes[i];
            current_cum_hash = current_cum_hash * 31 + p_hash;
            log_debug("[LOOP] i=" + std::to_string(i) + " hash_ok p_hash=" + std::to_string(p_hash));
            bool is_p = (p_type == "MIRROR" || p_type == "ARRAY_LINEAR" || p_type == "ARRAY_CIRCULAR" || p_type == "REVOLVE" || p_type == "SWEEP" || p_type == "LOFT" || p_type == "FACE_REVOLVE" || p_type == "FACE_LOFT");
            
            bool prim_params_dirty = is_p || (stack->param_hashes.count(p_uuid) == 0 || stack->param_hashes[p_uuid] != p_geo_hash);
            bool is_mod = (p_type == "FILLET" || p_type == "CHAMFER" || p_type == "FACE_OFFSET" || p_type == "FACE_INSET" || p_type == "DRAFT" || p_type == "SHELL" || p_type == "CLEANUP");
            log_debug("[LOOP] i=" + std::to_string(i) + " is_mod=" + std::to_string(is_mod) + " is_p=" + std::to_string(is_p) + " dirty=" + std::to_string(prim_params_dirty));
            
            if (is_mod) {
                if (!current_clusters.empty()) {
                    auto t_mod_start = std::chrono::high_resolution_clock::now();
                    auto t_target_assign_start = std::chrono::high_resolution_clock::now();
                    const std::string target_lineage_str = target_lineages[i] ? target_lineages[i] : "";
                    std::vector<std::string> targets = split_target_tokens(target_lineage_str);
                    const std::string assign_cache_key = build_modifier_target_assignment_cache_key(p_type, target_lineage_str, current_clusters);
                    auto assign_cache_it = stack->modifier_target_assignment_cache.find(assign_cache_key);
                    const bool has_cached_assignment = (
                        assign_cache_it != stack->modifier_target_assignment_cache.end() &&
                        assign_cache_it->second.size() == current_clusters.size()
                    );
                    if (has_cached_assignment) {
                        log_debug(std::string("[MOD_TARGET_CACHE_HIT] ") + p_type + " clusters=" + std::to_string(current_clusters.size()));
                    }

                    std::vector<ClusterData> new_clusters;
                    std::vector<std::string> computed_sub_target_lineages(current_clusters.size());
                    if (!has_cached_assignment && !targets.empty()) {
                        VoxelGrid cluster_grid;
                        cluster_grid.voxel_size = 2.5;
                        for (size_t c_idx = 0; c_idx < current_clusters.size(); ++c_idx) {
                            ensure_cluster_index(current_clusters[c_idx]);
                            ensure_cluster_bbox(current_clusters[c_idx]);
                            cluster_grid.add_bbox(current_clusters[c_idx].bbox, c_idx);
                        }

                        for (const auto& target_t : targets) {
                            if (current_clusters.size() == 1) {
                                if (!computed_sub_target_lineages[0].empty()) computed_sub_target_lineages[0] += "|";
                                computed_sub_target_lineages[0] += target_t;
                                continue;
                            }

                            gp_Pnt target_coord(1e10, 1e10, 1e10);
                            bool has_coord = false;
                            size_t target_at = target_t.find("@");
                            if (target_at != std::string::npos) {
                                double cx = 0, cy = 0, cz = 0;
                                const char* coord_ptr = target_t.c_str() + target_at + 1;
                                if (sscanf(coord_ptr, "%lf;%lf;%lf", &cx, &cy, &cz) == 3) {
                                    target_coord = gp_Pnt(cx, cy, cz);
                                    has_coord = true;
                                }
                            }

                            if (!has_coord) {
                                for (size_t c_idx = 0; c_idx < current_clusters.size(); ++c_idx) {
                                    if (!computed_sub_target_lineages[c_idx].empty()) computed_sub_target_lineages[c_idx] += "|";
                                    computed_sub_target_lineages[c_idx] += target_t;
                                }
                                continue;
                            }

                            double best_d_min = 1e10;
                            int best_c_idx = -1;
                            const std::string target_cluster_cache_key = build_modifier_target_cluster_cache_key(
                                p_type, target_t, current_clusters.size()
                            );
                            auto target_cluster_cache_it = stack->modifier_target_cluster_cache.find(target_cluster_cache_key);
                            if (target_cluster_cache_it != stack->modifier_target_cluster_cache.end()) {
                                int cached_idx = target_cluster_cache_it->second;
                                if (cached_idx >= 0 && cached_idx < static_cast<int>(current_clusters.size())) {
                                    ClusterData& cached_cluster = current_clusters[cached_idx];
                                    if (bbox_distance_sq(cached_cluster.bbox, target_coord) <= 4.0) {
                                        double cached_d = compute_cluster_target_distance(cached_cluster, target_t, target_coord);
                                        if (cached_d < 2.0) {
                                            best_d_min = cached_d;
                                            best_c_idx = cached_idx;
                                        }
                                    }
                                }
                            }

                            std::vector<size_t> cluster_candidates = cluster_grid.get_candidates(target_coord, 4.0);
                            if (cluster_candidates.empty()) {
                                cluster_candidates.reserve(current_clusters.size());
                                for (size_t c_idx = 0; c_idx < current_clusters.size(); ++c_idx) {
                                    cluster_candidates.push_back(c_idx);
                                }
                            }

                            for (size_t c_idx : cluster_candidates) {
                                if (static_cast<int>(c_idx) == best_c_idx) continue;
                                if (bbox_distance_sq(current_clusters[c_idx].bbox, target_coord) > 4.0) continue;
                                double d_min = compute_cluster_target_distance(current_clusters[c_idx], target_t, target_coord);

                                if (d_min < best_d_min) {
                                    best_d_min = d_min;
                                    best_c_idx = static_cast<int>(c_idx);
                                }
                            }

                            if (best_c_idx >= 0 && best_d_min < 2.0) {
                                stack->modifier_target_cluster_cache[target_cluster_cache_key] = best_c_idx;
                                if (stack->modifier_target_cluster_cache.size() > 1024) {
                                    stack->modifier_target_cluster_cache.clear();
                                }
                                std::string& assigned = computed_sub_target_lineages[best_c_idx];
                                if (!assigned.empty()) assigned += "|";
                                assigned += target_t;
                            } else {
                                log_debug("[assign_targets] Target left unassigned: " + target_t + " cluster_count=" + std::to_string(current_clusters.size()));
                            }
                        }
                    }

                    BRep_Builder bb_glob; TopoDS_Compound global_comp; bb_glob.MakeCompound(global_comp);
                    for (const auto& c : current_clusters) {
                        if (!c.raw.IsNull()) bb_glob.Add(global_comp, c.raw);
                    }

                    if (p_type == "DRAFT" && current_clusters.size() > 1) {
                        try {
                            TopoDS_Shape drafted_global = apply_draft(
                                global_comp,
                                reference_lineages[i],
                                target_lineage_str,
                                radii[i],
                                &current_face_map,
                                global_comp
                            );

                            std::vector<ClusterData> drafted_clusters;
                            try {
                                if (!drafted_global.IsNull() && drafted_global.ShapeType() == TopAbs_COMPOUND) {
                                    TopoDS_Iterator drafted_it(drafted_global);
                                    while (drafted_it.More()) {
                                        TopoDS_Shape child = drafted_it.Value();
                                        if (!child.IsNull()) drafted_clusters.push_back({child});
                                        drafted_it.Next();
                                    }
                                }
                            } catch (Standard_Failure const& e) {
                                log_debug(std::string("[DRAFT_GLOBAL] Compound decomposition Standard_Failure: ") + e.GetMessageString());
                            } catch (const std::exception& e) {
                                log_debug(std::string("[DRAFT_GLOBAL] Compound decomposition std::exception: ") + e.what());
                            } catch (...) {
                                log_debug("[DRAFT_GLOBAL] Compound decomposition unknown exception");
                            }
                            if (drafted_clusters.empty() && !drafted_global.IsNull()) {
                                drafted_clusters.push_back({drafted_global});
                            }

                            if (!drafted_clusters.empty()) {
                                current_clusters = drafted_clusters;
                            } else {
                                log_debug("[DRAFT_GLOBAL] Draft returned empty shape set; preserving previous clusters");
                            }
                        } catch (Standard_Failure const& e) {
                            log_debug(std::string("[DRAFT_GLOBAL] Exception while drafting compound: ") + e.GetMessageString());
                            log_debug("[DRAFT_GLOBAL] Preserving previous clusters");
                        } catch (const std::exception& e) {
                            log_debug(std::string("[DRAFT_GLOBAL] std::exception while drafting compound: ") + e.what());
                            log_debug("[DRAFT_GLOBAL] Preserving previous clusters");
                        } catch (...) {
                            log_debug("[DRAFT_GLOBAL] Unknown exception while drafting compound; preserving previous clusters");
                        }

                        auto t_recluster_start = std::chrono::high_resolution_clock::now();
                        std::vector<ClusterData> next_clusters;
                        std::vector<bool> merged_flags(current_clusters.size(), false);
                        std::vector<Bnd_Box> boxes(current_clusters.size());
                        for (size_t i = 0; i < current_clusters.size(); ++i) {
                            try {
                                ensure_cluster_bbox(current_clusters[i]);
                                boxes[i] = current_clusters[i].bbox;
                            } catch (Standard_Failure const& e) {
                                log_debug(std::string("[DRAFT_GLOBAL] ensure_cluster_bbox Standard_Failure idx=") + std::to_string(i) + " msg=" + e.GetMessageString());
                            } catch (const std::exception& e) {
                                log_debug(std::string("[DRAFT_GLOBAL] ensure_cluster_bbox std::exception idx=") + std::to_string(i) + " msg=" + e.what());
                            } catch (...) {
                                log_debug("[DRAFT_GLOBAL] ensure_cluster_bbox unknown exception idx=" + std::to_string(i));
                            }
                        }

                        for (size_t i = 0; i < current_clusters.size(); ++i) {
                            if (merged_flags[i]) continue;
                            std::vector<int> group = { (int)i };
                            merged_flags[i] = true;

                            bool added = true;
                            while (added) {
                                added = false;
                                for (size_t j = i + 1; j < current_clusters.size(); ++j) {
                                    if (merged_flags[j]) continue;
                                    bool intersects = false;
                                    for (int idx : group) {
                                        if (!boxes[idx].IsOut(boxes[j])) {
                                            intersects = true;
                                            break;
                                        }
                                    }
                                    if (intersects) {
                                        group.push_back(j);
                                        merged_flags[j] = true;
                                        added = true;
                                    }
                                }
                            }

                            if (group.size() == 1) {
                                next_clusters.push_back(current_clusters[i]);
                            } else {
                                BRep_Builder bb; TopoDS_Compound comp; bb.MakeCompound(comp);
                                for (int idx : group) bb.Add(comp, current_clusters[idx].raw);
                                next_clusters.push_back({comp});
                            }
                        }
                        current_clusters = next_clusters;
                        auto t_recluster_end = std::chrono::high_resolution_clock::now();
                        sum_perf_modifier_recluster += std::chrono::duration<double, std::milli>(t_recluster_end - t_recluster_start).count();

                        {
                            BRep_Builder bb_mod; TopoDS_Compound comp_mod; bb_mod.MakeCompound(comp_mod);
                            for (auto& c : current_clusters) bb_mod.Add(comp_mod, c.raw);
                            try {
                                assign_uuids_to_new_faces(current_face_map, comp_mod, p_uuid + "_MOD");
                            } catch (Standard_Failure const& e) {
                                log_debug(std::string("[DRAFT_GLOBAL] assign_uuids_to_new_faces Standard_Failure: ") + e.GetMessageString());
                            } catch (const std::exception& e) {
                                log_debug(std::string("[DRAFT_GLOBAL] assign_uuids_to_new_faces std::exception: ") + e.what());
                            } catch (...) {
                                log_debug("[DRAFT_GLOBAL] assign_uuids_to_new_faces unknown exception");
                            }
                            uuid_to_shape[p_uuid] = comp_mod;
                        }
                        auto t_mod_end = std::chrono::high_resolution_clock::now();
                        sum_perf_bool_modifier += std::chrono::duration<double, std::milli>(t_mod_end - t_mod_start).count();
                        continue;
                    }

                    for (size_t c_idx_loop = 0; c_idx_loop < current_clusters.size(); ++c_idx_loop) {
                        ensure_cluster_index(current_clusters[c_idx_loop]);
                        ensure_cluster_bbox(current_clusters[c_idx_loop]);
                        TopoDS_Shape mod_c = current_clusters[c_idx_loop].fused;
                        try {
                            // Find which targets in target_lineages belong to this specific cluster
                            std::string sub_target_lineage = has_cached_assignment
                                ? assign_cache_it->second[c_idx_loop]
                                : computed_sub_target_lineages[c_idx_loop];

                            if (!sub_target_lineage.empty() || p_type == "SHELL" || p_type == "CLEANUP") {
                                auto t_mod_apply_start = std::chrono::high_resolution_clock::now();
                                OCC_CATCH_SIGNALS
                                if (p_type == "FILLET" || p_type == "CHAMFER" || p_type == "CLEANUP") {
                                    log_debug(std::string("[MOD_CLUSTER] ") + p_type + " sub_target_lineage=" + sub_target_lineage);
                                }
                                if (p_type == "FILLET") mod_c = apply_fillet(mod_c, sub_target_lineage, radii[i], &current_face_map, &p_edge_radii_map);
                                else if (p_type == "CHAMFER") mod_c = apply_chamfer(mod_c, sub_target_lineage, radii[i], &current_face_map);
                                else if (p_type == "FACE_OFFSET") mod_c = apply_face_offset(mod_c, sub_target_lineage, radii[i], &current_face_map);
                                else if (p_type == "FACE_INSET") mod_c = apply_face_inset(mod_c, sub_target_lineage, radii[i], extrude_heights[i], &current_face_map);
                                else if (p_type == "DRAFT") mod_c = apply_draft(mod_c, reference_lineages[i], sub_target_lineage, radii[i], &current_face_map, global_comp);
                                else if (p_type == "SHELL") mod_c = apply_shell(mod_c, sub_target_lineage, radii[i], &current_face_map);
                                else if (p_type == "CLEANUP") {
                                    ShapeUpgrade_UnifySameDomain unif_mod(mod_c, true, true, true);
                                    // OCCT の既定角度許容誤差は Precision::Angular() = 1e-12 rad
                                    // (約 6e-11 度)。ヘッダにある通り「この値より大きい角度で
                                    // 接続された形状は統合されない」ので、ブーリアン/オフセット/
                                    // フィレットを重ねた形状では、見た目に完全な一直線でも
                                    // 浮動小数点の誤差だけで統合が拒否される。実際に
                                    // 「面は結合されたのに、一直線に並ぶ2本の辺が1本にならない」
                                    // という報告があった (2026-08-01)。
                                    //
                                    // 1e-6 rad (約 0.00006 度) まで緩める。意図的な折れは
                                    // 最小でもドラフト角の 0.1 度 = 1.7e-3 rad なので3桁の開きがあり、
                                    // 消してはいけない角を巻き込む危険はない。
                                    // 線形側も同様に 1e-6 (1 マイクロメートル相当) へ。
                                    unif_mod.SetAngularTolerance(1e-6);
                                    unif_mod.SetLinearTolerance(1e-6);
                                    unif_mod.Build();
                                    mod_c = unif_mod.Shape();
                                    update_face_id_map_from_history(current_face_map, unif_mod.History());
                                }
                                auto t_mod_apply_end = std::chrono::high_resolution_clock::now();
                                sum_perf_modifier_apply += std::chrono::duration<double, std::milli>(t_mod_apply_end - t_mod_apply_start).count();
                            }
                        } catch (...) {}
                        new_clusters.push_back({mod_c});
                    }
                    if (!has_cached_assignment) {
                        stack->modifier_target_assignment_cache[assign_cache_key] = computed_sub_target_lineages;
                        if (stack->modifier_target_assignment_cache.size() > 256) {
                            log_debug("[MOD_TARGET_CACHE_CLEAR] size_limit");
                            stack->modifier_target_assignment_cache.clear();
                        }
                    }
                    auto t_target_assign_end = std::chrono::high_resolution_clock::now();
                    sum_perf_modifier_target_assign += std::chrono::duration<double, std::milli>(t_target_assign_end - t_target_assign_start).count();
                    current_clusters = new_clusters;

                    auto t_recluster_start = std::chrono::high_resolution_clock::now();
                    // Merge any clusters that now intersect after the modifier!
                    std::vector<ClusterData> next_clusters;
                    std::vector<bool> merged_flags(current_clusters.size(), false);
                    std::vector<Bnd_Box> boxes(current_clusters.size());
                    for (size_t i = 0; i < current_clusters.size(); ++i) {
                        ensure_cluster_bbox(current_clusters[i]);
                        boxes[i] = current_clusters[i].bbox;
                    }

                    for (size_t i = 0; i < current_clusters.size(); ++i) {
                        if (merged_flags[i]) continue;
                        std::vector<int> group = { (int)i };
                        merged_flags[i] = true;
                        
                        bool added = true;
                        while (added) {
                            added = false;
                            for (size_t j = i + 1; j < current_clusters.size(); ++j) {
                                if (merged_flags[j]) continue;
                                bool intersects = false;
                                for (int idx : group) {
                                    if (!boxes[idx].IsOut(boxes[j])) {
                                        intersects = true;
                                        break;
                                    }
                                }
                                if (intersects) {
                                    group.push_back(j);
                                    merged_flags[j] = true;
                                    added = true;
                                }
                            }
                        }
                        
                        if (group.size() == 1) {
                            next_clusters.push_back(current_clusters[i]);
                        } else {
                            BRep_Builder bb; TopoDS_Compound comp; bb.MakeCompound(comp);
                            for (int idx : group) bb.Add(comp, current_clusters[idx].raw);
                            next_clusters.push_back({comp});
                        }
                    }
                    current_clusters = next_clusters;
                    auto t_recluster_end = std::chrono::high_resolution_clock::now();
                    sum_perf_modifier_recluster += std::chrono::duration<double, std::milli>(t_recluster_end - t_recluster_start).count();

                    // Store the result of modifier in uuid_to_shape as a compound of all current clusters.
                    {
                        BRep_Builder bb_mod; TopoDS_Compound comp_mod; bb_mod.MakeCompound(comp_mod);
                        for(auto& c : current_clusters) bb_mod.Add(comp_mod, c.raw);
                        assign_uuids_to_new_faces(current_face_map, comp_mod, p_uuid + "_MOD");
                        uuid_to_shape[p_uuid] = comp_mod;
                    }
                    auto t_mod_end = std::chrono::high_resolution_clock::now();
                    sum_perf_bool_modifier += std::chrono::duration<double, std::milli>(t_mod_end - t_mod_start).count();
                }
            } else {
                if (p_type == "GROUP_START") {
                    log_debug("[GROUP_START] pushing parent clusters=" + std::to_string(current_clusters.size()) + " face_map_size=" + std::to_string(current_face_map.size()));
                    cluster_stack.push_back(current_clusters);
                    face_map_stack.push_back(current_face_map);
                    current_clusters.clear();
                    
                    BRep_Builder bb_start; TopoDS_Compound comp_start; bb_start.MakeCompound(comp_start);
                    uuid_to_shape[p_uuid] = comp_start;
                    
                    auto t_end_prim = std::chrono::high_resolution_clock::now();
                    sum_perf_prim += std::chrono::duration<double, std::milli>(t_end_prim - t_start_prim).count();
                } else if (p_type == "GROUP_END") {
                    BRep_Builder bb_group; TopoDS_Compound comp_group; bb_group.MakeCompound(comp_group);
                    for (auto& c : current_clusters) {
                        ensure_cluster_fused(c);
                        if (!c.fused.IsNull()) {
                            bb_group.Add(comp_group, c.fused);
                        }
                    }
                    TopoDS_Shape group_shape = comp_group;
                    std::map<std::string, TopoDS_Shape> child_group_face_map = current_face_map;
                    log_debug("[GROUP_END] child clusters=" + std::to_string(current_clusters.size()) + " child_face_map_size=" + std::to_string(child_group_face_map.size()));
                    
                    if (!cluster_stack.empty()) {
                        current_clusters = cluster_stack.back();
                        cluster_stack.pop_back();
                        current_face_map = face_map_stack.back();
                        face_map_stack.pop_back();
                        log_debug("[GROUP_END] restored parent clusters=" + std::to_string(current_clusters.size()) + " parent_face_map_size=" + std::to_string(current_face_map.size()));
                    } else {
                        current_clusters.clear();
                        current_face_map.clear();
                        log_debug("[GROUP_END] no parent stack, starting from empty parent context");
                    }

                    size_t merged_face_tokens = 0;
                    for (const auto& kv : child_group_face_map) {
                        if (current_face_map.count(kv.first) == 0 && !kv.second.IsNull()) {
                            current_face_map[kv.first] = kv.second;
                            merged_face_tokens++;
                        }
                    }
                    log_debug("[GROUP_END] merged child face tokens into parent: " + std::to_string(merged_face_tokens) + " total_parent_face_map_size=" + std::to_string(current_face_map.size()));
                    
                    if (!group_shape.IsNull()) {
                        if (current_clusters.empty() || p_op == "BASE") {
                            current_clusters.clear();
                            current_clusters.push_back({group_shape});
                            log_debug("[GROUP_END] group collapsed as BASE/current empty");
                        } else if (p_op == "ADD" || p_op == "SUBTRACT" || p_op == "SUB" || p_op == "INTERSECT" || p_op == "INT") {
                            std::vector<int> interacting_indices;
                            Bnd_Box prim_box; BRepBndLib::Add(group_shape, prim_box);
                            for (size_t c = 0; c < current_clusters.size(); ++c) {
                                ensure_cluster_bbox(current_clusters[c]);
                                if (!prim_box.IsOut(current_clusters[c].bbox)) interacting_indices.push_back(c);
                            }
                            log_debug("[GROUP_END] interacting_indices=" + std::to_string(interacting_indices.size()) + " op=" + p_op);
                            if (interacting_indices.empty()) {
                                if (p_op == "ADD") {
                                    current_clusters.push_back({group_shape});
                                    log_debug("[GROUP_END] appended group_shape as detached ADD cluster");
                                } else {
                                    log_debug("[GROUP_END] no interacting parent clusters for non-ADD op; group result will not affect parent");
                                }
                            } else {
                                BRep_Builder bb_base; TopoDS_Compound comp_base; bb_base.MakeCompound(comp_base);
                                for (int idx : interacting_indices) {
                                    bb_base.Add(comp_base, current_clusters[idx].raw);
                                }
                                TopoDS_Shape merged = apply_boolean(comp_base, group_shape, p_op, &current_face_map, false);
                                assign_uuids_to_new_faces(current_face_map, merged, p_uuid + "_BOOL");
                                log_debug("[GROUP_END] boolean merged group into parent for op=" + p_op);
                                std::vector<ClusterData> next_clusters;
                                for (size_t c = 0; c < current_clusters.size(); ++c) {
                                    if (std::find(interacting_indices.begin(), interacting_indices.end(), c) == interacting_indices.end()) {
                                        next_clusters.push_back(current_clusters[c]);
                                    }
                                }
                                next_clusters.push_back({merged});
                                current_clusters = next_clusters;
                            }
                        }
                    }
                    uuid_to_shape[p_uuid] = group_shape;
                    
                    auto t_end_prim = std::chrono::high_resolution_clock::now();
                    sum_perf_prim += std::chrono::duration<double, std::milli>(t_end_prim - t_start_prim).count();
                } else {
                    TopoDS_Shape prim;
                    if (!prim_params_dirty && stack->primitive_cache.count(p_uuid)) { 
                    prim = stack->primitive_cache[p_uuid]; 
                    if (p_type == "CURVE" || p_type == "SURFACE" || p_type == "POLYLINE") {
                        pts_offset += pt_counts[i] * 4;
                        seg_offset += segment_counts[i] * 17;
                    } 
                }
                else {
                    double sx = sizes[i*3+0], sy = sizes[i*3+1], sz = sizes[i*3+2]; int pc = pt_counts[i];
                    log_debug("[PRIM_CREATE] i=" + std::to_string(i) + " type=" + p_type + " sx=" + std::to_string(sx) + " sy=" + std::to_string(sy) + " sz=" + std::to_string(sz));
                    try {
                        if (p_type == "BOX") { prim = make_box(sx, sy, sz); log_debug("[PRIM_CREATE] BOX done, null=" + std::to_string(prim.IsNull())); }
                        else if (p_type == "STEP_PART") { prim = occ::get_step_shape(target_uuids[i]); }
                        else if (p_type == "SVG_PART") {
                            prim = occ::get_svg_shape(target_uuids[i]);
                            if (!prim.IsNull()) { gp_Trsf t_scale; t_scale.SetScale(gp_Pnt(0, 0, 0), sx); prim = BRepBuilderAPI_Transform(prim, t_scale, true).Shape(); }
                        }
                        else if (p_type == "FACE_REVOLVE" || p_type == "FACE_LOFT") {
                            TopoDS_Shape search_base;
                            if (current_clusters.empty()) search_base = TopoDS_Shape();
                            else if (current_clusters.size() == 1) {
                                ensure_cluster_fused(current_clusters[0]); search_base = current_clusters[0].fused;
                                if (!search_base.IsNull()) {
                                    try {
//                                         ShapeUpgrade_UnifySameDomain unif_search(search_base, true, !prevent_unify_faces, true);
//                                         unif_search.Build();
//                                         search_base = unif_search.Shape();
                                    } catch (...) {}
                                }
                            }
                            else {
                                // �検 迢ｬ遶九＠縺溘け繝ｩ繧ｹ繧ｿ繝ｼ縺斐→縺ｫ蛟句挨縺ｫ UnifySameDomain 繧帝←逕ｨ縺吶ｋ縺薙→縺ｧ縲√た繝ｪ繝・ラ髢薙ｒ縺ｾ縺溘＞縺�髱｢ID繧､繝ｳ繝・ャ繧ｯ繧ｹ縺ｮ蟠ｩ螢奇ｼ医す繝｣繝・ヵ繝ｫ・峨ｒ螳悟・縺ｫ髦ｲ縺撰ｼ・
                                BRep_Builder bb;
                                TopoDS_Compound comp;
                                bb.MakeCompound(comp);
                                for (auto& c : current_clusters) {
                                    ensure_cluster_fused(c); TopoDS_Shape unified_c = c.fused;
                                    if (!unified_c.IsNull()) {
                                        try {
//                                             ShapeUpgrade_UnifySameDomain unif_c(unified_c, true, !prevent_unify_faces, true);
//                                             unif_c.Build();
//                                             unified_c = unif_c.Shape();
                                        } catch (...) {}
                                    }
                                    bb.Add(comp, unified_c);
                                }
                                search_base = comp;
                            }

                            if (p_type == "FACE_LOFT") prim = apply_face_loft(search_base, target_lineages[i], &current_face_map);
                            else prim = apply_face_revolve(search_base, target_lineages[i], pattern_axes[i] ? pattern_axes[i] : "Z", distances[i], locs[i*3+0], locs[i*3+1], locs[i*3+2], rots[i*3+0], rots[i*3+1], rots[i*3+2], &current_face_map);
                        }
                        else if (p_type == "CYLINDER") prim = make_cylinder(sx, sy, sz);
                        else if (p_type == "SPHERE") prim = make_sphere(sx, sy, sz);
                        else if (p_type == "CONE") prim = make_cone(radii[i], radii2[i], sz);
                        else if (p_type == "TORUS") prim = make_torus(radii[i], minor_radii[i]);
                        else if (p_type == "SLOT") prim = make_slot(radii[i], sx);
                        else if (p_type == "VARIABLE_BOX") prim = make_variable_box(sx, sy, sz, radii[i], radii2[i], top_shapes[i], bot_shapes[i]);
                        else if (p_type == "POLYGON") prim = make_polygon(sides[i], radii[i]);
                        else if (p_type == "GEAR") prim = make_gear(sides[i], modules[i], pressure_angles[i]);
                        else if (p_type == "HELIX") prim = make_helix(radii[i], extrude_heights[i], distances[i]);
                        else if (p_type == "ARC") prim = make_arc(radii[i], a_starts[i], a_ends[i]);
                        else if (p_type == "SWEEP" || p_type == "LOFT") {
                            std::string t_str = target_lineages[i];
                            std::vector<std::string> t_uuids;
                            size_t pos = 0;
                            while ((pos = t_str.find('|')) != std::string::npos) {
                                t_uuids.push_back(t_str.substr(0, pos));
                                t_str.erase(0, pos + 1);
                            }
                            if (!t_str.empty()) t_uuids.push_back(t_str);

                            if (p_type == "SWEEP") {
                                if (t_uuids.size() >= 2) {
                                    TopoDS_Shape unif_result = result_shape;
                                    if (!unif_result.IsNull() && (t_uuids[0].rfind("Face:", 0) == 0 || t_uuids[1].rfind("Edge:", 0) == 0)) {
                                        try {
//                                             ShapeUpgrade_UnifySameDomain unif_sw(unif_result, true, !prevent_unify_faces, true);
//                                             unif_sw.Build();
//                                             unif_result = unif_sw.Shape();
                                        } catch (...) {}
                                    }
                                    
                                    TopoDS_Shape profile;
                                    if (t_uuids[0].rfind("Face:", 0) == 0) {
                                        profile = resolve_modifier_face_target(unif_result, t_uuids[0]);
                                    } else { profile = uuid_to_shape.count(t_uuids[0]) ? uuid_to_shape[t_uuids[0]] : TopoDS_Shape(); }
                                    
                                    TopoDS_Shape path;
                                    if (t_uuids[1].rfind("Edge:", 0) == 0) {
                                        TopTools_IndexedMapOfShape em;
                                        TopExp::MapShapes(unif_result, TopAbs_EDGE, em);
                                        path = find_edge_robust(t_uuids[1], em, &current_face_map);
                                        if (!path.IsNull()) {
                                            BRepBuilderAPI_MakeWire wire_maker(TopoDS::Edge(path));
                                            if (wire_maker.IsDone()) path = wire_maker.Wire();
                                        }
                                    } else { path = uuid_to_shape.count(t_uuids[1]) ? uuid_to_shape[t_uuids[1]] : TopoDS_Shape(); }

                                    std::string sweep_frame = sweep_frame_modes[i] ? sweep_frame_modes[i] : "AUTO";
                                    bool helix_axis_valid = false;
                                    gp_Pnt helix_axis_origin(0, 0, 0);
                                    gp_Dir helix_axis_dir(0, 0, 1);

                                    if (sweep_frame == "HELIX_AXIS") {
                                        const std::string& path_uuid = t_uuids[1];
                                        for (int j = 0; j < i; ++j) {
                                            if (path_uuid == uuids[j] && std::string(types[j]) == "HELIX") {
                                                helix_axis_origin = gp_Pnt(locs[j*3+0], locs[j*3+1], locs[j*3+2]);
                                                gp_Vec axis_vec(0, 0, 1);
                                                gp_Trsf axis_rot;
                                                gp_Quaternion axis_q(rots_quat[j*4+0], rots_quat[j*4+1], rots_quat[j*4+2], rots_quat[j*4+3]);
                                                axis_rot.SetRotation(axis_q);
                                                axis_vec.Transform(axis_rot);
                                                if (axis_vec.Magnitude() > 1e-9) { helix_axis_dir = gp_Dir(axis_vec); helix_axis_valid = true; }
                                                break;
                                            }
                                        }
                                    }
                                    prim = make_sweep(profile, path, sweep_frame, sweep_rolls[i], helix_axis_valid, helix_axis_origin, helix_axis_dir);
                                }
                            } else if (p_type == "LOFT") {
                                std::vector<TopoDS_Shape> profiles;
                                for (const auto& u : t_uuids) { if (uuid_to_shape.count(u)) profiles.push_back(uuid_to_shape[u]); }
                                prim = make_loft(profiles);
                            }
                        }
                        else if (p_type == "CURVE" || p_type == "SURFACE") {
                            int sc = segment_counts[i];
                            if (sc > 0) prim = make_curve_or_surface_from_segments(all_segments, seg_offset, sc, (p_type == "SURFACE"));
                            else prim = make_curve_or_surface(all_pts, pts_offset, pc, (p_type == "SURFACE"));
                            pts_offset += pc * 4; seg_offset += sc * 17;
                        } else if (p_type == "POLYLINE") {
                            prim = make_polyline(all_pts, pts_offset, pc, radii[i]);
                            pts_offset += pc * 4;
                        } else if (p_type == "MIRROR" || p_type == "ARRAY_LINEAR" || p_type == "ARRAY_CIRCULAR" || p_type == "REVOLVE" || p_type == "INSTANCE") {
                            bool is_collection_instance = false; TopoDS_Shape b; std::string target_uuid_str = target_uuids[i];
                            if (!target_uuid_str.empty() && std::all_of(target_uuid_str.begin(), target_uuid_str.end(), ::isdigit)) {
                                is_collection_instance = true;
                                try {
                                    uint64_t addr = std::stoull(target_uuid_str);
                                    CADStack* other_stack = reinterpret_cast<CADStack*>(addr);
                                    if (other_stack && !other_stack->current_shape.IsNull()) {
                                        b = other_stack->current_shape;
                                        double m_loc[3] = {0, 0, 0}; double m_rot[3] = {0, 0, 0}; bool found_master_t = false;
                                        for (const auto& pair : other_stack->transform_cache) {
                                            if (pair.second.op == "BASE") {
                                                m_loc[0] = pair.second.loc[0]; m_loc[1] = pair.second.loc[1]; m_loc[2] = pair.second.loc[2];
                                                found_master_t = true; break;
                                            }
                                        }
                                        if (!found_master_t && !other_stack->transform_cache.empty()) {
                                            auto it = other_stack->transform_cache.begin();
                                            m_loc[0] = it->second.loc[0]; m_loc[1] = it->second.loc[1]; m_loc[2] = it->second.loc[2];
                                            found_master_t = true;
                                        }
                                        if (found_master_t) {
                                            gp_Trsf t_master; gp_Quaternion q_master;
                                            t_master.SetTransformation(q_master, gp_Vec(m_loc[0], m_loc[1], m_loc[2]));
                                            b = BRepBuilderAPI_Transform(b, t_master.Inverted(), true).Shape();
                                        }
                                    }
                                } catch (...) {}
                            } else if (uuid_to_shape.count(target_uuid_str)) { b = uuid_to_shape[target_uuid_str]; }

                            if (!b.IsNull()) {
                                if (p_type == "MIRROR") prim = apply_mirror(b, pattern_axes[i], locs[i*3+0], locs[i*3+1], locs[i*3+2], rots[i*3+0], rots[i*3+1], rots[i*3+2]);
                                else if (p_type == "ARRAY_LINEAR") prim = apply_array_linear(b, pattern_axes[i], p_counts[i], distances[i]);
                                else if (p_type == "ARRAY_CIRCULAR") prim = apply_array_circular(b, pattern_axes[i], p_counts[i], distances[i], locs[i*3+0], locs[i*3+1], locs[i*3+2], rots[i*3+0], rots[i*3+1], rots[i*3+2]);
                                else if (p_type == "REVOLVE") prim = apply_revolve(b, pattern_axes[i], distances[i], locs[i*3+0], locs[i*3+1], locs[i*3+2], rots[i*3+0], rots[i*3+1], rots[i*3+2]);
                                else if (p_type == "INSTANCE") {
                                    prim = b;
                                    if (!is_collection_instance) {
                                        std::string master_uuid = target_uuids[i]; int master_idx = -1;
                                        for (int k = 0; k < n_prims; ++k) { if (std::string(uuids[k]) == master_uuid) { master_idx = k; break; } }
                                        if (master_idx != -1) {
                                            gp_Trsf t_rot; gp_Quaternion q_master(rots_quat[master_idx*4+0], rots_quat[master_idx*4+1], rots_quat[master_idx*4+2], rots_quat[master_idx*4+3]);
                                            t_rot.SetRotation(q_master);
                                            gp_Trsf t_loc; t_loc.SetTranslationPart(gp_Vec(locs[master_idx*3+0], locs[master_idx*3+1], locs[master_idx*3+2]));
                                            gp_Trsf t_master = t_loc * t_rot;
                                            prim = BRepBuilderAPI_Transform(prim, t_master.Inverted(), true).Shape();
                                        }
                                    }
                                }
                            }
                        }
                    } catch (...) {}
                    
                    if (!prim.IsNull() && (prim.ShapeType() == TopAbs_EDGE || prim.ShapeType() == TopAbs_WIRE || prim.ShapeType() == TopAbs_COMPOUND)) {
                        TopoDS_Shape base_wire = prim;
                        if (fill_closed[i] == 1 && (p_type == "CURVE" || p_type == "SURFACE" || p_type == "ARC" || p_type == "POLYLINE" || p_type == "SVG_PART")) {
                            if (prim.ShapeType() == TopAbs_COMPOUND) {
                                TopExp_Explorer exp(prim, TopAbs_WIRE); std::vector<TopoDS_Wire> wires;
                                for (; exp.More(); exp.Next()) wires.push_back(TopoDS::Wire(exp.Current()));
                                if (!wires.empty()) {
                                    std::vector<TopoDS_Wire> closed_wires;
                                    std::vector<TopoDS_Wire> open_wires;
                                    for (auto& w : wires) {
                                        bool is_closed = false;
                                        if (w.Closed()) is_closed = true;
                                        else {
                                            TopoDS_Vertex v1, v2; TopExp::Vertices(w, v1, v2);
                                            if (!v1.IsNull() && !v2.IsNull()) {
                                                if (BRep_Tool::Pnt(v1).Distance(BRep_Tool::Pnt(v2)) < 1e-4) is_closed = true;
                                            }
                                        }
                                        if (is_closed) closed_wires.push_back(w);
                                        else open_wires.push_back(w);
                                    }
                                    if (!closed_wires.empty()) {
                                        std::sort(closed_wires.begin(), closed_wires.end(), [](const TopoDS_Wire& a, const TopoDS_Wire& b) {
                                            Bnd_Box ba, bb; BRepBndLib::Add(a, ba); BRepBndLib::Add(b, bb); return ba.SquareExtent() > bb.SquareExtent();
                                        });
                                        BRepBuilderAPI_MakeFace face_maker(closed_wires[0], true);
                                        if (face_maker.IsDone()) {
                                            TopoDS_Shape current_face = face_maker.Face();
                                            ShapeFix_Face sff(TopoDS::Face(current_face)); sff.Perform(); current_face = sff.Face();
                                            for (size_t wi = 1; wi < closed_wires.size(); ++wi) {
                                                BRepBuilderAPI_MakeFace hole_maker(closed_wires[wi], true);
                                                if (hole_maker.IsDone()) {
                                                    TopoDS_Shape hole_face = hole_maker.Face();
                                                    ShapeFix_Face sff_hole(TopoDS::Face(hole_face)); sff_hole.Perform(); hole_face = sff_hole.Face();
                                                    current_face = apply_boolean(current_face, hole_face, "SUBTRACT", &current_face_map, false);
                                                }
                                            }
                                            if (!open_wires.empty()) {
                                                BRep_Builder bb; TopoDS_Compound final_comp; bb.MakeCompound(final_comp);
                                                bb.Add(final_comp, current_face);
                                                for (auto& ow : open_wires) bb.Add(final_comp, ow);
                                                prim = final_comp;
                                            } else {
                                                prim = current_face;
                                            }
                                        }
                                    }
                                }
                            } else {
                                TopoDS_Wire w; if (prim.ShapeType() == TopAbs_EDGE) w = BRepBuilderAPI_MakeWire(TopoDS::Edge(prim)).Wire(); else w = TopoDS::Wire(prim);
                                if (!w.IsNull()) { BRepBuilderAPI_MakeFace mf(w, true); if (mf.IsDone()) prim = mf.Shape(); }
                            }
                        }
                        if (use_pipe[i] == 1) {
                            if (base_wire.ShapeType() != TopAbs_COMPOUND) {
                                double r = std::max(0.01, pipe_radii[i]); TopoDS_Wire spine; if (base_wire.ShapeType() == TopAbs_EDGE) spine = BRepBuilderAPI_MakeWire(TopoDS::Edge(base_wire)).Wire(); else spine = TopoDS::Wire(base_wire);
                                if (!spine.IsNull()) {
                                    BRepAdaptor_CompCurve ad(spine, Standard_True);
                                    gp_Pnt p0; gp_Vec v0; ad.D1(ad.FirstParameter(), p0, v0); gp_Dir d0(0,0,1); if (v0.Magnitude()>1e-6) d0=gp_Dir(v0);
                                    BRepBuilderAPI_MakeEdge ce(gp_Circ(gp_Ax2(p0, d0), r)); if (ce.IsDone()) { BRepBuilderAPI_MakeFace mf(BRepBuilderAPI_MakeWire(ce.Edge()).Wire()); if (mf.IsDone()) { BRepOffsetAPI_MakePipe mp(spine, mf.Face()); if (mp.IsDone()) prim = mp.Shape(); } }
                                }
                            }
                        }
                    }

                    log_debug("[POST_TRY] i=" + std::to_string(i) + " prim.IsNull=" + std::to_string(prim.IsNull()));
                    double h = extrude_heights[i];
                    log_debug("[EXTRUDE] i=" + std::to_string(i) + " h=" + std::to_string(h));
                    if (std::abs(h) < 1e-5 && (p_type == "POLYGON" || p_type == "SLOT" || p_type == "SURFACE")) h = 1e-4;
                    // この汎用押し出しは「平面プロファイルを立体にする」ためのもの。
                    // 既に立体を返す型に適用してはいけない。VARIABLE_BOX は高さ h の
                    // ロフト済みソリッド、HELIX は make_helix が高さを織り込んだ螺旋
                    // (use_pipe ならパイプ化済み)で、そこへ MakePrism をかけると
                    // 形状生成が失敗する。失敗すると stack_results が空になり、
                    // generate_mesh が古いメッシュキャッシュを返すため、利用者からは
                    // 「高さを変えても何も起きない」ように見える(2026-08-01 に実測)。
                    const bool already_solid =
                        (p_type == "BOX" || p_type == "CYLINDER" || p_type == "SPHERE" ||
                         p_type == "CONE" || p_type == "TORUS" || p_type == "VARIABLE_BOX" ||
                         p_type == "HELIX" || p_type == "STEP_PART" || p_type == "INSTANCE");
                    if (!prim.IsNull() && std::abs(h) > 1e-6 && !already_solid) {
                        TopoDS_Face first_face;
                        TopExp_Explorer f_exp(prim, TopAbs_FACE);
                        if (f_exp.More()) first_face = TopoDS::Face(f_exp.Current());
                        else {
                            TopoDS_Wire w; if (prim.ShapeType() == TopAbs_EDGE) w = BRepBuilderAPI_MakeWire(TopoDS::Edge(prim)).Wire(); else if (prim.ShapeType() == TopAbs_WIRE) w = TopoDS::Wire(prim);
                            if (!w.IsNull()) { BRepBuilderAPI_MakeFace mf(w, true); if (mf.IsDone()) { first_face = mf.Face(); prim = first_face; } }
                        }
                        
                        if (!prim.IsNull()) {
                            gp_Vec extrude_vec(0, 0, h);
                            if (!first_face.IsNull() && (p_type == "CURVE" || p_type == "SURFACE" || p_type == "POLYLINE" || p_type == "SVG_PART")) {
                                try {
                                    Standard_Real u1, u2, v1, v2; BRepTools::UVBounds(first_face, u1, u2, v1, v2); BRepAdaptor_Surface surf(first_face, Standard_True);
                                    gp_Pnt p_mid; gp_Vec du, dv; surf.D1(0.5 * (u1 + u2), 0.5 * (v1 + v2), p_mid, du, dv); gp_Vec face_normal = du.Crossed(dv);
                                    if (face_normal.Magnitude() > 1e-9) { face_normal.Normalize(); extrude_vec = face_normal * h; }
                                } catch (...) {}
                            }
                            BRepPrimAPI_MakePrism m(prim, extrude_vec);
                            if (m.IsDone()) prim = m.Shape();
                        }
                    }

                    if (!is_p && prim_params_dirty && !prim.IsNull()) { stack->primitive_cache[p_uuid] = prim; stack->param_hashes[p_uuid] = p_geo_hash; }
                }
                if (!prim.IsNull()) {
                    if (!is_p) { 
                        if (p_type == "INSTANCE") {
                            gp_GTrsf gt_scale; gt_scale.SetVectorialPart(gp_Mat(sizes[i*3+0], 0, 0, 0, sizes[i*3+1], 0, 0, 0, sizes[i*3+2]));
                            gp_Trsf t_rot; gp_Quaternion q(rots_quat[i*4+0], rots_quat[i*4+1], rots_quat[i*4+2], rots_quat[i*4+3]); t_rot.SetRotation(q);
                            gp_Trsf t_loc; t_loc.SetTranslationPart(gp_Vec(locs[i*3+0], locs[i*3+1], locs[i*3+2]));
                            gp_GTrsf gt_final(t_loc * t_rot); gt_final.Multiply(gt_scale);
                            prim = BRepBuilderAPI_GTransform(prim, gt_final, true).Shape();
                        } else {
                            gp_Trsf t_rot; gp_Quaternion q(rots_quat[i*4+0], rots_quat[i*4+1], rots_quat[i*4+2], rots_quat[i*4+3]); t_rot.SetRotation(q);
                            gp_Trsf t_loc; t_loc.SetTranslationPart(gp_Vec(locs[i*3+0], locs[i*3+1], locs[i*3+2]));
                            prim = BRepBuilderAPI_Transform(prim, t_loc * t_rot, true).Shape(); 
                        }
                    }
                    if (!is_p && !prim.IsNull() && prim.ShapeType() == TopAbs_SOLID) {
                        GProp_GProps gprops;
                        BRepGProp::VolumeProperties(prim, gprops);
                        if (gprops.Mass() < 0.0) prim.Reverse();
                    }
                    log_debug("[POST_TRANSFORM] i=" + std::to_string(i) + " storing shape");
                    uuid_to_shape[p_uuid] = prim;
                    assign_uuids_to_new_faces(current_face_map, prim, p_uuid);
                    auto t_end_prim = std::chrono::high_resolution_clock::now();
                    sum_perf_prim += std::chrono::duration<double, std::milli>(t_end_prim - t_start_prim).count();
                    
                    auto t_start_bool = std::chrono::high_resolution_clock::now();
                    log_debug("[BOOL] i=" + std::to_string(i) + " first=" + std::to_string(first) + " op=" + p_op);
                    if (first || p_op == "BASE") { current_clusters.clear(); current_clusters.push_back({prim}); first = false; log_debug("[BOOL] BASE cluster created"); }
                    else if (p_op == "ADD" || p_op == "SUBTRACT" || p_op == "SUB" || p_op == "INTERSECT" || p_op == "INT") {
                        std::vector<int> interacting_indices;
                        Bnd_Box prim_box; BRepBndLib::Add(prim, prim_box);
                        for (size_t c = 0; c < current_clusters.size(); ++c) {
                            ensure_cluster_bbox(current_clusters[c]);
                            if (!prim_box.IsOut(current_clusters[c].bbox)) interacting_indices.push_back(c);
                        }
                        log_debug(
                            "[BOOL_CLUSTER] op=" + p_op +
                            " prim_idx=" + std::to_string(i) +
                            " cluster_count_before=" + std::to_string(current_clusters.size()) +
                            " interacting=" + std::to_string(interacting_indices.size())
                        );
                        if (interacting_indices.empty()) {
                            if (p_op == "ADD") {
                                current_clusters.push_back({prim});
                                log_debug("[BOOL_CLUSTER] add appended_as_new_cluster cluster_count_after=" + std::to_string(current_clusters.size()));
                            }
                        } else {
                            BRep_Builder bb; TopoDS_Compound comp_base; bb.MakeCompound(comp_base);
                            for (int idx : interacting_indices) {
                                bb.Add(comp_base, current_clusters[idx].raw);
                            }
                            TopoDS_Shape merged = apply_boolean(comp_base, prim, p_op, &current_face_map, false);
                            assign_uuids_to_new_faces(current_face_map, merged, p_uuid + "_BOOL");
                            std::vector<ClusterData> next_clusters;
                            for (size_t c = 0; c < current_clusters.size(); ++c) {
                                if (std::find(interacting_indices.begin(), interacting_indices.end(), c) == interacting_indices.end()) {
                                    next_clusters.push_back(current_clusters[c]);
                                }
                            }
                            next_clusters.push_back({merged});
                            current_clusters = next_clusters;
                            log_debug(
                                "[BOOL_CLUSTER] merged cluster_count_after=" + std::to_string(current_clusters.size()) +
                                " merged_shape_type=" + std::to_string((int)merged.ShapeType())
                            );
                        }
                    }
                    auto t_end_bool = std::chrono::high_resolution_clock::now();
                    sum_perf_bool_main += std::chrono::duration<double, std::milli>(t_end_bool - t_start_bool).count();
                }
            }
        }
            // Create a compound of current clusters to store in shape
            BRep_Builder bb_iter; TopoDS_Compound comp_iter; bb_iter.MakeCompound(comp_iter);
            for(auto& c : current_clusters) bb_iter.Add(comp_iter, c.raw);
            stack->stack_results.push_back({current_cum_hash, current_clusters, comp_iter, uuid_to_shape, TopoDS_Shape(), current_face_map});
        }
        
        BRep_Builder bb; TopoDS_Compound comp; bb.MakeCompound(comp);
        for(auto& c : current_clusters) bb.Add(comp, c.raw);
        result_shape = comp;
        
        if (result_shape.IsNull()) {
            bb.MakeCompound(comp);
            result_shape = comp;
        } else {
            if (!fast_mode) {
                try {
                    std::vector<ClusterData> unif_clusters;
                    for(auto& c : current_clusters) {
                        auto t_start_fuse = std::chrono::high_resolution_clock::now();
                        ensure_cluster_fused(c); 
                        auto t_end_fuse = std::chrono::high_resolution_clock::now();
                        sum_perf_bool_main += std::chrono::duration<double, std::milli>(t_end_fuse - t_start_fuse).count();

                        auto t_start_unify = std::chrono::high_resolution_clock::now();
                        TopoDS_Shape temp = c.fused;
//                         ShapeUpgrade_UnifySameDomain unif(temp, true, !prevent_unify_faces, true);
//                         unif.Build();
                         unif_clusters.push_back({temp});
                        auto t_end_unify = std::chrono::high_resolution_clock::now();
                        sum_perf_unify += std::chrono::duration<double, std::milli>(t_end_unify - t_start_unify).count();
                    }
                    
                    auto t_start_unify2 = std::chrono::high_resolution_clock::now();
                    BRep_Builder bb_f; TopoDS_Compound comp_f; bb_f.MakeCompound(comp_f);
                    for(auto& c : unif_clusters) bb_f.Add(comp_f, c.raw);
                    result_shape = comp_f;
                    auto t_end_unify2 = std::chrono::high_resolution_clock::now();
                    sum_perf_unify += std::chrono::duration<double, std::milli>(t_end_unify2 - t_start_unify2).count();
                } catch (...) {}
            } else {
                try {
                    auto t_start_unify2 = std::chrono::high_resolution_clock::now();
                    BRep_Builder bb_f; TopoDS_Compound comp_f; bb_f.MakeCompound(comp_f);
                    for(auto& c : current_clusters) bb_f.Add(comp_f, c.raw);
                    result_shape = comp_f;
                    auto t_end_unify2 = std::chrono::high_resolution_clock::now();
                    sum_perf_unify += std::chrono::duration<double, std::milli>(t_end_unify2 - t_start_unify2).count();
                } catch (...) {}
            }
        }
        
        if (!stack->stack_results.empty() && !fast_mode) {
            stack->stack_results.back().unified_shape = result_shape;
        }
        
        if (perf_out) {
            ModifierPerfBreakdown mod_perf = get_modifier_perf_breakdown();
            perf_out[0] = sum_perf_prim;
            perf_out[1] = sum_perf_bool_main;
            perf_out[2] = sum_perf_unify;
            perf_out[3] = sum_perf_bool_modifier;
            perf_out[4] = g_sum_perf_extrema;
            perf_out[5] = sum_perf_resume_restore;
            perf_out[6] = sum_perf_modifier_target_assign;
            perf_out[7] = sum_perf_modifier_apply;
            perf_out[8] = sum_perf_modifier_recluster;
            perf_out[9] = mod_perf.fillet_setup_ms;
            perf_out[10] = mod_perf.fillet_target_resolve_ms;
            perf_out[11] = mod_perf.fillet_add_ms;
            perf_out[12] = mod_perf.fillet_build_ms;
            perf_out[13] = mod_perf.fillet_history_ms;
            perf_out[14] = mod_perf.fillet_added_edges;
            perf_out[15] = mod_perf.fillet_contours;
            auto t_very_end = std::chrono::high_resolution_clock::now();
            perf_out[16] = std::chrono::duration<double, std::milli>(t_very_end - t_very_start).count();
            std::stringstream ss_perf;
            ss_perf << "DEBUG: C++ Internal Total Time: " << perf_out[16] << " ms";
            log_debug(ss_perf.str());
        }

        printf("result_shape is null? %d\n", result_shape.IsNull());
        stack->current_shape = result_shape;
        stack->last_deflection = deflection;
        stack->last_fast_mode = fast_mode;
        return true;
    } catch (...) { return false; }
}

static bool pick_edge_internal(const TopoDS_Shape& shape, const double* o, const double* d, double t, char* l, double* p, const std::map<std::string, TopoDS_Shape>* face_map = nullptr) {
    if (shape.IsNull()) return false;
    try {
        gp_Lin r(gp_Pnt(o[0], o[1], o[2]), gp_Dir(d[0], d[1], d[2]));
        double md = t, mcd = 1e10; bool fnd = false; std::string bl = ""; gp_Pnt bp;
        TopTools_IndexedMapOfShape ed; TopExp::MapShapes(shape, TopAbs_EDGE, ed);

        for (int i = 1; i <= ed.Extent(); ++i) {
            try {
                TopoDS_Edge e = TopoDS::Edge(ed.FindKey(i));
                if (e.IsNull()) continue;

                bool is_degen = BRep_Tool::Degenerated(e);
                GProp_GProps prop;
                BRepGProp::LinearProperties(e, prop);
                double edge_len = prop.Mass();

                BRepAdaptor_Curve bac;
                try {
                    bac.Initialize(e);
                } catch (...) {
                    continue;
                }

                double f = bac.FirstParameter();
                double n = bac.LastParameter();

                if (is_degen) continue;
                if (edge_len < 1e-4) continue;
                if (std::isnan(f) || std::isnan(n) || std::isinf(f) || std::isinf(n)) continue;
                if (std::abs(f) > 1e9 || std::abs(n) > 1e9) continue;
                if (n - f < 1e-5) continue;

                double length = std::abs(n - f);
                int num_samples = std::max(20, (int)(length / (t * 0.5)));
                if (num_samples > 2000) num_samples = 2000;
                for (int j = 0; j <= num_samples; ++j) {
                    double t_param = f + (n - f) * (double)j / num_samples;
                    gp_Pnt pt;
                    try {
                        pt = bac.Value(t_param);
                    } catch (...) {
                        continue;
                    }
                    
                    // 驛｢譎｢・ｽ・ｬ驛｢・ｧ繝ｻ・､驍ｵ・ｺ繝ｻ・ｮ髫俶誓・ｽ・ｷ髴難ｽ､繝ｻ・ｹ驍ｵ・ｺ闕ｵ譎｢・ｽ陋ｾ・ｨ・ｾ繝ｻ・ｲ鬮ｯ・ｦ隴ｴ・ｧ陝・ｿ髯ｷ・ｷ闔会ｽ｣郢晢ｽｻ驛｢譏ｶ繝ｻ邵ｺ閾･・ｹ譏ｴ繝ｻ邵ｺ莉｣繝ｻ陋ｹ・ｻ・取ｨ抵ｽｹ・ｧ繝ｻ・､驍ｵ・ｺ繝ｻ・ｮ髯ｷ鬘後＊陝・ｿ驍ｵ・ｺ繝ｻ・ｫ驍ｵ・ｺ郢ｧ繝ｻ・ｽ邇厄ｽｽ・､繝ｻ・ｹ驍ｵ・ｺ繝ｻ・ｮ驍ｵ・ｺ繝ｻ・ｿ鬯ｩ蛹・ｽｽ・ｸ髫ｰ螢ｽ・ｧ・ｫ陟弱・螯吶・・ｽ郢晢ｽｻ郢晢ｽｻ
                    gp_Vec v_pt(gp_Pnt(o[0], o[1], o[2]), pt);
                    double proj = v_pt.Dot(gp_Vec(d[0], d[1], d[2]));
                    if (proj < -0.1) continue;
                    
                    // 髴難ｽ､繝ｻ・ｹ pt 驍ｵ・ｺ繝ｻ・ｨ鬨ｾ・ｶ繝ｻ・ｴ鬩搾ｽｱ郢晢ｽｻr (origin, direction) 驍ｵ・ｺ繝ｻ・ｨ驍ｵ・ｺ繝ｻ・ｮ髫ｴ蟠｢ﾂ鬩墓得・ｽ・ｭ鬮ｴ閧ｴ霎ｨ陞ｻ・ｬ驛｢・ｧ陞ｳ螟ｲ・ｽ・ｨ髢ｧ・ｲ繝ｻ・ｮ郢晢ｽｻ
                    double v_sq = v_pt.SquareMagnitude();
                    double dist2 = v_sq - proj * proj;
                    if (dist2 < 0.0) dist2 = 0.0;
                    
                    if (dist2 < t * t) {
                        double dist = std::sqrt(dist2);
                        double dc = gp_Pnt(o[0], o[1], o[2]).Distance(pt);
                        if (!fnd || dist < md * 0.8 || (dist < md * 1.2 && dc < mcd)) {
                            md = dist; mcd = dc; bp = pt; fnd = true;
                            bl = "Edge:" + std::to_string(i);
                        }
                    }
                }
            } catch (...) { continue; }
        }

        if (fnd) {
            int idx = std::stoi(bl.substr(5));
            if (idx >= 1 && idx <= ed.Extent()) {
                TopoDS_Edge e = TopoDS::Edge(ed.FindKey(idx));
                gp_Pnt m; TopExp_Explorer exp(e, TopAbs_VERTEX);
                if (exp.More()) m = BRep_Tool::Pnt(TopoDS::Vertex(exp.Current())); else m = bp;
                std::string loop_suffix = "";
                gp_Pnt loop_center;
                double loop_diag = 0.0;
                int loop_edge_count = 0;
                if (describe_tracked_edge_loop(shape, e, loop_center, loop_diag, loop_edge_count)) {
                    char loop_buf[160];
                    snprintf(loop_buf, sizeof(loop_buf), "@Loop:%.3f;%.3f;%.3f;%.3f;%d", loop_center.X(), loop_center.Y(), loop_center.Z(), loop_diag, loop_edge_count);
                    loop_suffix = loop_buf;
                }
                
                std::string intersect_str = "";
                if (face_map) {
                    TopTools_IndexedDataMapOfShapeListOfShape edge_face_map;
                    TopExp::MapShapesAndAncestors(shape, TopAbs_EDGE, TopAbs_FACE, edge_face_map);
                    if (edge_face_map.Contains(e)) {
                        const TopTools_ListOfShape& faces = edge_face_map.FindFromKey(e);
                        std::vector<std::string> uuids;
                        for (TopTools_ListIteratorOfListOfShape it(faces); it.More(); it.Next()) {
                            for (const auto& pair : *face_map) {
                                bool found = false;
                                if (pair.second.ShapeType() == TopAbs_COMPOUND) {
                                    for (TopExp_Explorer exp(pair.second, TopAbs_FACE); exp.More(); exp.Next()) {
                                        if (exp.Current().IsSame(it.Value())) { found = true; break; }
                                    }
                                } else {
                                    if (pair.second.IsSame(it.Value())) found = true;
                                }
                                if (found) {
                                    uuids.push_back(pair.first);
                                    break;
                                }
                            }
                        }
                        if (uuids.size() == 2) {
                            // Sort to ensure consistent order
                            if (uuids[0] > uuids[1]) std::swap(uuids[0], uuids[1]);
                            intersect_str = "#FaceIntersect:" + uuids[0] + "," + uuids[1];
                        }
                    }
                }
                snprintf(l, 256, "Edge:%d@%.3f;%.3f;%.3f%s%s", idx, m.X(), m.Y(), m.Z(), loop_suffix.c_str(), intersect_str.c_str());

                p[0] = bp.X(); p[1] = bp.Y(); p[2] = bp.Z();
                return true;
            }
        }
    } catch (...) {}
    return false;
}bool pick_edge(void* stack_ptr, const double* o, const double* d, double t, char* l, double* p) {
    CADStack* stack = static_cast<CADStack*>(stack_ptr);
    if (!stack) return false;
    // std::lock_guard<std::mutex> lock(g_occ_mutex);
    std::map<std::string, TopoDS_Shape>* fm = nullptr;
    if (!stack->stack_results.empty()) fm = &stack->stack_results.back().face_id_map;
    return pick_edge_internal(stack->current_shape, o, d, t, l, p, fm);
}

bool pick_edge_from_stack(void* stack_ptr, int stack_idx, const double* o, const double* d, double t, char* l, double* p) {
    CADStack* stack = static_cast<CADStack*>(stack_ptr);
    if (!stack) return false;
    // std::lock_guard<std::mutex> lock(g_occ_mutex);
    if (stack_idx < 0 || stack_idx >= (int)stack->stack_results.size()) return false;
    if (stack->stack_results[stack_idx].unified_shape.IsNull()) {
        try {
            TopoDS_Shape fused = fuse_compound(stack->stack_results[stack_idx].shape);
//             ShapeUpgrade_UnifySameDomain unif(fused, true, true, true);
//             unif.Build();
             stack->stack_results[stack_idx].unified_shape = fused;
        } catch (...) {
            stack->stack_results[stack_idx].unified_shape = stack->stack_results[stack_idx].shape;
        }
    }
    return pick_edge_internal(stack->stack_results[stack_idx].unified_shape, o, d, t, l, p, &stack->stack_results[stack_idx].face_id_map);
}
static bool pick_face_internal(const TopoDS_Shape& shape, const double* o, const double* d, double t, char* l, double* p) {
    if (shape.IsNull()) return false;
    try {
        gp_Lin r(gp_Pnt(o[0], o[1], o[2]), gp_Dir(d[0], d[1], d[2]));
        
        bool exact_hit_found = false;
        double min_exact_dist = 1e10;
        std::string exact_bl = "";
        gp_Pnt exact_bp;

        bool fallback_hit_found = false;
        double min_fallback_dist = 1e10;
        double min_fallback_camera_dist = 1e10;
        std::string fallback_bl = "";
        gp_Pnt fallback_bp;

        TopTools_IndexedMapOfShape fa; TopExp::MapShapes(shape, TopAbs_FACE, fa);

        for (int i = 1; i <= fa.Extent(); ++i) {
            try {
                TopoDS_Face f = TopoDS::Face(fa.FindKey(i));
                if (f.IsNull()) continue;

                BRepIntCurveSurface_Inter in; in.Init(f, r, 1e-4);
                bool local_exact_fnd = false;
                while (in.More()) {
                    gp_Pnt pt = in.Pnt(); double dist_camera = gp_Pnt(o[0], o[1], o[2]).Distance(pt);
                    if (gp_Vec(gp_Pnt(o[0], o[1], o[2]), pt).Dot(gp_Vec(d[0], d[1], d[2])) > 0 && dist_camera < min_exact_dist) {
                        min_exact_dist = dist_camera; exact_bp = pt; exact_hit_found = true; exact_bl = "Face:" + std::to_string(i);
                        local_exact_fnd = true;
                    }
                    in.Next();
                }
                
                if (!local_exact_fnd && !exact_hit_found) {
                    double umin, umax, vmin, vmax;
                    BRepTools::UVBounds(f, umin, umax, vmin, vmax);
                    double len_u = std::abs(umax - umin);
                    double len_v = std::abs(vmax - vmin);
                    int num_samples_u = std::max(10, (int)(len_u / (t * 0.5)));
                    int num_samples_v = std::max(10, (int)(len_v / (t * 0.5)));
                    if (num_samples_u > 100) num_samples_u = 100;
                    if (num_samples_v > 100) num_samples_v = 100;
                    
                    BRepAdaptor_Surface surf(f);
                    for (int u = 0; u <= num_samples_u; ++u) {
                        for (int v = 0; v <= num_samples_v; ++v) {
                            double uu = umin + (umax - umin) * (double)u / num_samples_u;
                            double vv = vmin + (vmax - vmin) * (double)v / num_samples_v;
                            gp_Pnt pt;
                            try { pt = surf.Value(uu, vv); } catch (...) { continue; }
                            
                            gp_Vec v_pt(gp_Pnt(o[0], o[1], o[2]), pt);
                            double proj = v_pt.Dot(gp_Vec(d[0], d[1], d[2]));
                            if (proj < -0.1) continue;
                            
                            double dist2 = v_pt.SquareMagnitude() - proj * proj;
                            if (dist2 < 0.0) dist2 = 0.0;
                            
                            if (dist2 < t * t) {
                                double dist_ray = std::sqrt(dist2);
                                double dist_camera = gp_Pnt(o[0], o[1], o[2]).Distance(pt);
                                if (!fallback_hit_found || dist_ray < min_fallback_dist * 0.8 || (dist_ray < min_fallback_dist * 1.2 && dist_camera < min_fallback_camera_dist)) {
                                    min_fallback_dist = dist_ray; min_fallback_camera_dist = dist_camera;
                                    fallback_bp = pt; fallback_hit_found = true; fallback_bl = "Face:" + std::to_string(i);
                                }
                            }
                        }
                    }
                }
            } catch (...) { continue; }
        }
        
        bool fnd = exact_hit_found || fallback_hit_found;
        std::string bl = exact_hit_found ? exact_bl : fallback_bl;
        gp_Pnt bp = exact_hit_found ? exact_bp : fallback_bp;
        if (fnd) {
            int idx = std::stoi(bl.substr(5));
            if (idx >= 1 && idx <= fa.Extent()) {
                TopoDS_Face f = TopoDS::Face(fa.FindKey(idx));
                gp_Pnt c; 
                TopLoc_Location L;
                Handle(Geom_Surface) S = BRep_Tool::Surface(f, L);
                if (!S.IsNull()) {
                    double u1, u2, v1, v2; BRepTools::UVBounds(f, u1, u2, v1, v2);
                    S->D0((u1+u2)/2.0, (v1+v2)/2.0, c); c.Transform(L.Transformation());
                } else {
                    GProp_GProps gp; BRepGProp::SurfaceProperties(f, gp);
                    if (gp.Mass() > 1e-6) c = gp.CentreOfMass(); else c = bp;
                }
                gp_Vec normal(0, 0, 1);
                try {
                    BRepIntCurveSurface_Inter in;
                    gp_Lin r_norm(gp_Pnt(o[0], o[1], o[2]), gp_Dir(d[0], d[1], d[2]));
                    in.Init(f, r_norm, 1e-4);
                    double min_dist = 1e10;
                    while (in.More()) {
                        double u = in.U(), v = in.V();
                        gp_Pnt pt = in.Pnt();
                        double dist = pt.Distance(bp);
                        if (dist < min_dist) {
                            min_dist = dist;
                            BRepAdaptor_Surface surf(f);
                            gp_Pnt p_eval; gp_Vec du, dv;
                            surf.D1(u, v, p_eval, du, dv);
                            normal = du.Crossed(dv);
                            if (normal.SquareMagnitude() > 1e-9) { if (f.Orientation() == TopAbs_REVERSED) normal.Reverse(); normal.Normalize(); }
                        }
                        in.Next();
                    }
                } catch(...) {}
                // V8.1.4.1: embed the pick normal as "#N:nx;ny;nz" so downstream
                // face resolution (find_face_robust) can normal-gate the match and
                // avoid binding FACE_OFFSET to a neighbouring fillet strip. All
                // existing parsers stop at the '#'/coord and safely ignore it.
                snprintf(l, 256, "Face:%d@%.3f;%.3f;%.3f#N:%.4f;%.4f;%.4f", idx, c.X(), c.Y(), c.Z(), normal.X(), normal.Y(), normal.Z());
                p[0] = bp.X(); p[1] = bp.Y(); p[2] = bp.Z(); p[3] = normal.X(); p[4] = normal.Y(); p[5] = normal.Z();
                return true;
            }
        }
    } catch (...) {}
    return false;
}bool pick_face(void* stack_ptr, const double* o, const double* d, double t, char* l, double* p) {
    CADStack* stack = static_cast<CADStack*>(stack_ptr);
    if (!stack) return false;
    // std::lock_guard<std::mutex> lock(g_occ_mutex);
    return pick_face_internal(stack->current_shape, o, d, t, l, p);
}

bool pick_face_from_stack(void* stack_ptr, int stack_idx, const double* o, const double* d, double t, char* l, double* p) {
    CADStack* stack = static_cast<CADStack*>(stack_ptr);
    if (!stack) return false;
    // std::lock_guard<std::mutex> lock(g_occ_mutex);
    if (stack_idx < 0 || stack_idx >= (int)stack->stack_results.size()) return false;
    if (stack->stack_results[stack_idx].unified_shape.IsNull()) {
        try {
            TopoDS_Shape fused = fuse_compound(stack->stack_results[stack_idx].shape);
//             ShapeUpgrade_UnifySameDomain unif(fused, true, true, true);
//             unif.Build();
             stack->stack_results[stack_idx].unified_shape = fused;
        } catch (...) {
            stack->stack_results[stack_idx].unified_shape = stack->stack_results[stack_idx].shape;
        }
    }
    return pick_face_internal(stack->stack_results[stack_idx].unified_shape, o, d, t, l, p);
}
static bool pick_vertex_internal(const TopoDS_Shape& shape, const double* o, const double* d, double t, char* l, double* p) {
    if (shape.IsNull()) return false;
    try {
        gp_Lin ray(gp_Pnt(o[0], o[1], o[2]), gp_Dir(d[0], d[1], d[2]));
        TopTools_IndexedMapOfShape vm; TopExp::MapShapes(shape, TopAbs_VERTEX, vm);
        
        double min_dist = 1e10; gp_Pnt best_p; int best_idx = -1;
        for (int i = 1; i <= vm.Extent(); ++i) {
            TopoDS_Vertex v = TopoDS::Vertex(vm.FindKey(i));
            gp_Pnt pt = BRep_Tool::Pnt(v);
            double dist = ray.Distance(pt);
            if (dist < min_dist) {
                min_dist = dist; best_p = pt; best_idx = i;
            }
        }
        
        if (best_idx != -1 && min_dist < t * 10.0) { // 鬯ｯ繝ｻ・臥ｸｺ蟶ｷ・ｹ・ｧ繝ｻ・ｹ驛｢譎会ｽｿ・ｫ郢晢ｽ｣驛｢譎丞ｹｲ郢晢ｽｻ髯昴・・ｻ・｣繝ｻ・ｽ髯溷ｼｱ繝ｻ繝ｻ竏ｫ・ｸ・ｺ繝ｻ・ｮ髯具ｽｻ繝ｻ・､髯橸ｽｳ郢晢ｽｻ
            // 髣皮甥ﾂ・ｬ陜励ｉ・ｸ・ｺ陷ｷ・ｶ繝ｻ遏ｩ・ｫ・ｱ繝ｻ・｢驍ｵ・ｺ闕ｵ譎｢・ｽ闃ｽ・ｱ蠅薙・繝ｻ・ｷ陞｢・ｹ繝ｻ螳壽╂鬮｢ﾂ繝ｻ・ｾ郢晢ｽｻ
            gp_Vec normal(0, 0, 1);
            TopTools_IndexedMapOfShape fm; TopExp::MapShapes(shape, TopAbs_FACE, fm);
            for (int i = 1; i <= fm.Extent(); ++i) {
                TopoDS_Face f = TopoDS::Face(fm.FindKey(i));
                bool has_v = false;
                TopExp_Explorer ex(f, TopAbs_VERTEX);
                while(ex.More()){ if(ex.Current().IsSame(vm.FindKey(best_idx))){ has_v = true; break; } ex.Next(); }
                if (has_v) {
                    BRepAdaptor_Surface surf(f);
                    // 鬯ｯ繝ｻ・臥ｸｺ蟷・р陋滂ｽｩ繝ｻ・ｿ闔会ｽ｣郢晢ｽｻ髮主｢薙・繝ｻ・ｷ陞｢・ｹ繝ｻ螳夲ｽｬ證ｦ・ｽ・ｨ髯橸ｽｳ陞滂ｽｲ繝ｻ・ｼ髢ｧ・ｲ繝ｻ・ｰ繝ｻ・｡髫ｴ蝓手ｱｪ陜趣ｽｪ驍ｵ・ｺ繝ｻ・ｫ鬯ｩ・･隶主･・ｽｽ・ｿ郢晢ｽｻ陝・ｿ髯ｷ・ｷ闔会ｽ｣遶企・・ｸ・ｺ繝ｻ・ｩ郢晢ｽｻ郢晢ｽｻ
                    gp_Pnt c; GProp_GProps gp; BRepGProp::SurfaceProperties(f, gp);
                    if (gp.Mass() > 1e-6) c = gp.CentreOfMass(); else c = best_p;
                    // 髮弱・・ｽ・｣鬩墓慣・ｽ・ｺ驍ｵ・ｺ繝ｻ・ｫ驍ｵ・ｺ繝ｻ・ｯ鬯ｯ繝ｻ・臥ｸｺ蟶ｷ・ｸ・ｺ繝ｻ・ｫ驍ｵ・ｺ驗呻ｽｫ繝ｻ・ｽ驛｢・ｧ陋幢ｽｽV驍ｵ・ｺ隰疲ｻゑｽｽ・ｿ郢晢ｽｻ繝ｻ・ｦ遶丞｣ｺ蜻ｳ驍ｵ・ｺ陟募仰遶擾ｽｽ繝ｻ・ｸ・つ髫ｴ魃会ｽｽ・ｦ鬩阪・・ｽ・｡髫ｴ蝓手ｱｪ陜趣ｽｪ驍ｵ・ｺ繝ｻ・ｫ
                    gp_Vec du, dv; gp_Pnt eval_p;
                    surf.D1(0.5, 0.5, eval_p, du, dv); // 驍ｵ・ｺ繝ｻ・ｨ驛｢・ｧ驗呻ｽｫ遶包ｿｽ驍ｵ・ｺ陋ｹ・ｻ隨倥・・ｫ・ｱ繝ｻ・｢驍ｵ・ｺ繝ｻ・ｮ髣包ｽｳ繝ｻ・ｭ髯滂ｽ｢郢晢ｽｻ繝ｻ・ｻ陋滂ｽｩ繝ｻ・ｿ闔会ｽ｣郢晢ｽｻ髮主｢薙・繝ｻ・ｷ郢晢ｽｻ
                    normal = du.Crossed(dv);
                    if (normal.SquareMagnitude() > 1e-9) { if (f.Orientation() == TopAbs_REVERSED) normal.Reverse(); normal.Normalize(); }
                    break; 
                }
            }
            
            snprintf(l, 256, "Vertex:%d@%.3f;%.3f;%.3f", best_idx, best_p.X(), best_p.Y(), best_p.Z());
            p[0] = best_p.X(); p[1] = best_p.Y(); p[2] = best_p.Z();
            p[3] = normal.X(); p[4] = normal.Y(); p[5] = normal.Z();
            return true;
        }
    } catch(...) {}
    return false;
}bool pick_vertex_from_stack(void* stack_ptr, int stack_idx, const double* o, const double* d, double t, char* l, double* p) {
    CADStack* stack = static_cast<CADStack*>(stack_ptr);
    if (!stack) return false;
    // std::lock_guard<std::mutex> lock(g_occ_mutex);
    if (stack_idx < 0 || stack_idx >= (int)stack->stack_results.size()) return false;
    if (stack->stack_results[stack_idx].unified_shape.IsNull()) {
        try {
            TopoDS_Shape fused = fuse_compound(stack->stack_results[stack_idx].shape);
//             ShapeUpgrade_UnifySameDomain unif(fused, true, true, true);
//             unif.Build();
             stack->stack_results[stack_idx].unified_shape = fused;
        } catch (...) {
            stack->stack_results[stack_idx].unified_shape = stack->stack_results[stack_idx].shape;
        }
    }
    return pick_vertex_internal(stack->stack_results[stack_idx].unified_shape, o, d, t, l, p);
}
static bool pick_midpoint_internal(const TopoDS_Shape& shape, const double* o, const double* d, double t, char* l, double* p) {
    if (shape.IsNull()) return false;
    try {
        gp_Lin ray(gp_Pnt(o[0], o[1], o[2]), gp_Dir(d[0], d[1], d[2]));
        double min_dist = 1e10; gp_Pnt best_p; gp_Vec best_n(0,0,1); std::string best_lid = "";
        
        // 1. 鬮ｴ雜｣・ｽ・ｺ驍ｵ・ｺ繝ｻ・ｮ髣包ｽｳ繝ｻ・ｭ髴難ｽ､繝ｻ・ｹ驛｢・ｧ陷ｻ閧ｲ邊滄ｩ肴得・ｽ・｢
        TopTools_IndexedMapOfShape em; TopExp::MapShapes(shape, TopAbs_EDGE, em);
        for (int i = 1; i <= em.Extent(); ++i) {
            TopoDS_Edge e = TopoDS::Edge(em.FindKey(i));
            double f, n; Handle(Geom_Curve) c = BRep_Tool::Curve(e, f, n);
            if (!c.IsNull()) {
                gp_Pnt mid = c->Value((f + n) / 2.0);
                double dist = ray.Distance(mid);
                if (dist < min_dist) {
                    min_dist = dist; best_p = mid;
                    best_lid = "EdgeMid:" + std::to_string(i);
                    // 髮主｢薙・繝ｻ・ｷ陞｢・ｹ郢晢ｽｻ髣憺屮・ｽ・ｿ髯橸ｽｳ隲帑ｼ夲ｽｽ・ｸ驗呻ｽｫ・つ遶丞｣ｺ關ｽ驍ｵ・ｺ繝ｻ・ｮ鬮ｴ雜｣・ｽ・ｺ驛｢・ｧ髮区ｨ環・ｧ驛｢・ｧ・つ髫ｴ蟠｢ﾂ髯具ｽｻ隴擾ｽｴ郢晢ｽｻ鬯ｮ・ｱ繝ｻ・｢驍ｵ・ｺ闕ｵ譎｢・ｽ闃ｽ諢ｾ鬮｢ﾂ繝ｻ・ｾ郢晢ｽｻ
                    TopExp_Explorer ex_f(shape, TopAbs_FACE);
                    while(ex_f.More()){
                        TopoDS_Face face = TopoDS::Face(ex_f.Current());
                        TopExp_Explorer ex_e(face, TopAbs_EDGE);
                        bool found_e = false; while(ex_e.More()){ if(ex_e.Current().IsSame(e)){ found_e = true; break; } ex_e.Next(); }
                        if(found_e){
                            BRepAdaptor_Surface surf(face); gp_Pnt p_eval; gp_Vec du, dv; surf.D1(0.5, 0.5, p_eval, du, dv);
                            best_n = du.Crossed(dv); if (best_n.SquareMagnitude() > 1e-9) { if (face.Orientation() == TopAbs_REVERSED) best_n.Reverse(); best_n.Normalize(); }
                            break;
                        }
                        ex_f.Next();
                    }
                }
            }
        }
        
        // 2. 鬯ｮ・ｱ繝ｻ・｢驍ｵ・ｺ繝ｻ・ｮ髣包ｽｳ繝ｻ・ｭ髯滂ｽ｢郢晢ｽｻ繝ｻ・ｼ騾趣ｽｯ郤・ｽｾ髯滂ｽ｢郢晢ｽｻ繝ｻ・ｼ陝ｲ・ｨ繝ｻ螳夲ｽｬ證ｦ・ｽ・｢鬩肴得・ｽ・｢
        TopTools_IndexedMapOfShape fm; TopExp::MapShapes(shape, TopAbs_FACE, fm);
        for (int i = 1; i <= fm.Extent(); ++i) {
            TopoDS_Face f = TopoDS::Face(fm.FindKey(i));
            GProp_GProps gp; BRepGProp::SurfaceProperties(f, gp);
            if (gp.Mass() > 1e-6) {
                gp_Pnt center;
                TopLoc_Location L;
                Handle(Geom_Surface) S = BRep_Tool::Surface(f, L);
                if (!S.IsNull()) {
                    double u1, u2, v1, v2; BRepTools::UVBounds(f, u1, u2, v1, v2);
                    S->D0((u1+u2)/2.0, (v1+v2)/2.0, center); center.Transform(L.Transformation());
                } else {
                    center = gp.CentreOfMass();
                }
                double dist = ray.Distance(center);
                if (dist < min_dist) {
                    min_dist = dist; best_p = center;
                    best_lid = "FaceCenter:" + std::to_string(i);
                    BRepAdaptor_Surface surf(f); gp_Pnt p_eval; gp_Vec du, dv; surf.D1(0.5, 0.5, p_eval, du, dv);
                    best_n = du.Crossed(dv); if (best_n.SquareMagnitude() > 1e-9) { if (f.Orientation() == TopAbs_REVERSED) best_n.Reverse(); best_n.Normalize(); }
                }
            }
        }
        
        if (!best_lid.empty() && min_dist < t * 10.0) {
            snprintf(l, 256, "%s@%.3f;%.3f;%.3f", best_lid.c_str(), best_p.X(), best_p.Y(), best_p.Z());
            p[0] = best_p.X(); p[1] = best_p.Y(); p[2] = best_p.Z();
            p[3] = best_n.X(); p[4] = best_n.Y(); p[5] = best_n.Z();
            return true;
        }
    } catch(...) {}
    return false;
}

bool pick_midpoint_from_stack(void* stack_ptr, int stack_idx, const double* o, const double* d, double t, char* l, double* p) {
    CADStack* stack = static_cast<CADStack*>(stack_ptr);
    if (!stack) return false;
    // std::lock_guard<std::mutex> lock(g_occ_mutex);
    if (stack_idx < 0 || stack_idx >= (int)stack->stack_results.size()) return false;
    if (stack->stack_results[stack_idx].unified_shape.IsNull()) {
        try {
            TopoDS_Shape fused = fuse_compound(stack->stack_results[stack_idx].shape);
//             ShapeUpgrade_UnifySameDomain unif(fused, true, true, true);
//             unif.Build();
             stack->stack_results[stack_idx].unified_shape = fused;
        } catch (...) {
            stack->stack_results[stack_idx].unified_shape = stack->stack_results[stack_idx].shape;
        }
    }
    return pick_midpoint_internal(stack->stack_results[stack_idx].unified_shape, o, d, t, l, p);
}

int get_face_count(void* stack_ptr) {
    CADStack* stack = static_cast<CADStack*>(stack_ptr);
    if (!stack) return 0;
    // std::lock_guard<std::mutex> lock(g_occ_mutex);
    if (stack->current_shape.IsNull()) return 0;
    TopTools_IndexedMapOfShape fm; TopExp::MapShapes(stack->current_shape, TopAbs_FACE, fm);
    return fm.Extent();
}


int get_face_hash(void* stack_ptr, int i) {
    CADStack* stack = static_cast<CADStack*>(stack_ptr);
    if (!stack || stack->current_shape.IsNull()) return 0;
    TopTools_IndexedMapOfShape fm; TopExp::MapShapes(stack->current_shape, TopAbs_FACE, fm);
    if (i < 1 || i > fm.Extent()) return 0;
    TopoDS_Face f = TopoDS::Face(fm.FindKey(i));
    return (int)(std::hash<TopoDS_Shape>{}(f) & 0x7FFFFFFF);
}

int get_edge_hash(void* stack_ptr, int i) {
    CADStack* stack = static_cast<CADStack*>(stack_ptr);
    if (!stack || stack->current_shape.IsNull()) return 0;
    TopTools_IndexedMapOfShape em; TopExp::MapShapes(stack->current_shape, TopAbs_EDGE, em);
    if (i < 1 || i > em.Extent()) return 0;
    TopoDS_Edge e = TopoDS::Edge(em.FindKey(i));
    return (int)(std::hash<TopoDS_Shape>{}(e) & 0x7FFFFFFF);
}

#include "occ_mesh.hpp"



int get_edge_count(void* stack_ptr) {
    CADStack* stack = static_cast<CADStack*>(stack_ptr);
    if (!stack) return 0;
    // std::lock_guard<std::mutex> lock(g_occ_mutex);
    if (stack->current_shape.IsNull()) return 0;
    TopTools_IndexedMapOfShape re; TopExp::MapShapes(stack->current_shape, TopAbs_EDGE, re);
    return re.Extent();
}

void get_edge_points(void* stack_ptr, int i, double deflection, double angular_deflection, bool fast_mode, void* points_vec, void* counts_vec, void* lineages_out_vec, PushPointFn push_point, PushCountFn push_count, PushStringFn push_string) {
    CADStack* stack = static_cast<CADStack*>(stack_ptr);
    if (!stack) return;
    try {
        OCC_CATCH_SIGNALS
        TopTools_IndexedMapOfShape re; TopExp::MapShapes(stack->current_shape, TopAbs_EDGE, re);
        if (i < 1 || i > re.Extent()) return;
        TopoDS_Edge e = TopoDS::Edge(re.FindKey(i));
        
        if (e.IsNull() || BRep_Tool::Degenerated(e)) {
            return;
        }
        
        BRepAdaptor_Curve c;
        c.Initialize(e);
        double f_param = c.FirstParameter();
        double l_param = c.LastParameter();
        if (std::isnan(f_param) || std::isnan(l_param) || std::isinf(f_param) || std::isinf(l_param) || (l_param - f_param < 1e-7)) {
            return;
        }
        
        GCPnts_TangentialDeflection d(c, angular_deflection, deflection);
        if (d.NbPoints() < 2) return;
        
        push_count(counts_vec, d.NbPoints());
        for (int j = 1; j <= d.NbPoints(); ++j) {
            gp_Pnt p = d.Value(j);
            push_point(points_vec, (float)p.X(), (float)p.Y(), (float)p.Z());
        }
        
        char buf[256];
        gp_Pnt m;
        TopExp_Explorer exp(e, TopAbs_VERTEX);
        if (exp.More()) m = BRep_Tool::Pnt(TopoDS::Vertex(exp.Current()));
        else m = gp_Pnt(0,0,0);
        
        snprintf(buf, sizeof(buf), "Edge:%d@%.3f;%.3f;%.3f", i, m.X(), m.Y(), m.Z());
        push_string(lineages_out_vec, buf);
    } catch (Standard_Failure const&) {
    } catch (...) {
    }
}

namespace {
// 1本の辺のテッセレーション結果。並列ワーカーはインデックスごとの専用スロットにのみ書き込むため
// 追加のロックは不要（false sharing 対策で構造体は大きめのメンバを持つ）。
struct EdgeTessResult {
    bool valid = false;
    std::vector<float> points; // xyz flat
    std::string lineage;
};

void tessellate_edge_range(
    const TopTools_IndexedMapOfShape& re,
    int begin_idx, int end_idx, // [begin_idx, end_idx) 1-based
    double deflection, double angular_deflection,
    std::vector<EdgeTessResult>& results
) {
    for (int i = begin_idx; i < end_idx; ++i) {
        TopoDS_Edge e = TopoDS::Edge(re.FindKey(i));
        if (e.IsNull() || BRep_Tool::Degenerated(e)) continue;

        BRepAdaptor_Curve bac;
        bac.Initialize(e);
        double f_param = bac.FirstParameter();
        double l_param = bac.LastParameter();
        if (std::isnan(f_param) || std::isnan(l_param) || std::isinf(f_param) || std::isinf(l_param) || (l_param - f_param < 1e-7)) continue;

        GCPnts_TangentialDeflection td;
        try {
            td.Initialize(bac, angular_deflection, deflection, 0.001);
        } catch (...) {
            try {
                td.Initialize(bac, angular_deflection * 0.5, deflection * 0.5, 0.001);
            } catch (...) {
                try {
                    td.Initialize(bac, angular_deflection * 0.1, deflection * 0.1, 0.001);
                } catch (...) {
                    continue;
                }
            }
        }
        if (td.NbPoints() < 2) continue;

        EdgeTessResult& r = results[i - 1];
        r.points.reserve(td.NbPoints() * 3);
        for (int j = 1; j <= td.NbPoints(); ++j) {
            gp_Pnt p = td.Value(j);
            r.points.push_back((float)p.X());
            r.points.push_back((float)p.Y());
            r.points.push_back((float)p.Z());
        }

        char buf[256];
        gp_Pnt m;
        TopExp_Explorer exp(e, TopAbs_VERTEX);
        if (exp.More()) m = BRep_Tool::Pnt(TopoDS::Vertex(exp.Current()));
        else m = gp_Pnt(0, 0, 0);
        snprintf(buf, sizeof(buf), "Edge:%d@%.3f;%.3f;%.3f", i, m.X(), m.Y(), m.Z());
        r.lineage = buf;
        r.valid = true;
    }
}
} // anonymous namespace

void generate_full_edges(void* stack_ptr, double deflection, double angular_deflection, bool fast_mode, void* points_vec, void* counts_vec, void* lineages_out_vec, PushPointFn push_point, PushCountFn push_count, PushStringFn push_string) {
    CADStack* stack = static_cast<CADStack*>(stack_ptr);
    if (!stack || stack->current_shape.IsNull()) return;
    try {
        OCC_CATCH_SIGNALS
        TopTools_IndexedMapOfShape re; TopExp::MapShapes(stack->current_shape, TopAbs_EDGE, re);
        int n_edges = re.Extent();
        if (n_edges <= 0) return;

        std::vector<EdgeTessResult> results(n_edges);

        // 辺数が少ない場合はスレッド生成コストの方が高いのでシーケンシャル実行
        unsigned hw = std::thread::hardware_concurrency();
        unsigned n_threads = hw == 0 ? 1 : std::min<unsigned>(hw, 8);
        if (n_edges < 64) n_threads = 1;

        if (n_threads <= 1) {
            tessellate_edge_range(re, 1, n_edges + 1, deflection, angular_deflection, results);
        } else {
            std::vector<std::thread> workers;
            workers.reserve(n_threads);
            int chunk = (n_edges + n_threads - 1) / n_threads;
            for (unsigned t = 0; t < n_threads; ++t) {
                int begin_idx = 1 + t * chunk;
                int end_idx = std::min<int>(n_edges + 1, begin_idx + chunk);
                if (begin_idx >= end_idx) continue;
                workers.emplace_back(tessellate_edge_range, std::cref(re), begin_idx, end_idx,
                                      deflection, angular_deflection, std::ref(results));
            }
            for (auto& w : workers) w.join();
        }

        // 出力順序をシーケンシャル版と完全一致させるため、結果を元のインデックス順に結合
        for (int i = 1; i <= n_edges; ++i) {
            const EdgeTessResult& r = results[i - 1];
            if (!r.valid) continue;
            push_count(counts_vec, (int)(r.points.size() / 3));
            for (size_t k = 0; k < r.points.size(); k += 3) {
                push_point(points_vec, r.points[k], r.points[k + 1], r.points[k + 2]);
            }
            push_string(lineages_out_vec, r.lineage.c_str());
        }
    } catch (...) {}
}



// スタックの現在形状の質量特性と外形寸法を測る。
//
// out には 11 個の double を順に書く:
//   [0]     体積
//   [1]     表面積
//   [2..4]  重心 (x, y, z)
//   [5..10] バウンディングボックス (xmin, ymin, zmin, xmax, ymax, zmax)
//
// 体積は VolumeProperties、面積は SurfaceProperties。どちらも既にこのファイル
// 内で使っている呼び出しで、新しい幾何計算は無い。
//
// **面しか無い形状(ソリッドになっていないもの)では体積が 0 になる。** これは
// 誤りではなく、閉じていないシェルの体積は定義できないため。呼び出し側は
// 0 を「未計算」ではなく「ソリッドではない」と解釈すること。
bool measure_stack(void* stack_ptr, double* out) {
    if (!stack_ptr || !out) return false;
    CADStack* stack = static_cast<CADStack*>(stack_ptr);
    if (stack->current_shape.IsNull()) return false;

    try {
        GProp_GProps vprops;
        BRepGProp::VolumeProperties(stack->current_shape, vprops);
        // 面の向きが揃っていない形状では負の体積が返る。表示するのは大きさ
        // なので絶対値を取る (occ_core.cpp の他の箇所では、負値を検出して
        // 形状を Reverse する判定に使っている)。
        out[0] = std::abs(vprops.Mass());

        GProp_GProps sprops;
        BRepGProp::SurfaceProperties(stack->current_shape, sprops);
        out[1] = sprops.Mass();

        // 重心は体積基準。体積が無い(シェル)場合は面積基準の重心で代用する
        gp_Pnt com = (out[0] > 1e-12) ? vprops.CentreOfMass() : sprops.CentreOfMass();
        out[2] = com.X();
        out[3] = com.Y();
        out[4] = com.Z();

        // Add ではなく AddOptimal、しかも **useTriangulation = false** で呼ぶこと。
        // ここは3回測り直して詰めた場所なので、安易に既定値へ戻さないこと。
        //
        //   BRepBndLib::Add                     → 半径2の球が 4.1086/4.0940/4.1231
        //   AddOptimal (既定 useTriangulation=true) → 同上、まったく改善しない
        //   AddOptimal (useTriangulation=false)  → 4.0/4.0/4.0
        //
        // 犯人はテセレーションだった。既定では既存の三角形分割から箱を作り、
        // そこに deflection ぶんの余裕が乗る。**完全に対称な球なのに3軸の値が
        // 全部違う**のが目印で、これが出たらこのフラグを疑うこと。
        // false にすると厳密な幾何から求めるので遅いが、計測はボタンを押した
        // ときだけ走るので問題にならない。1〜3% ずれた数字を出す計測機能には
        // 存在価値が無い。
        //
        // SetGap(0.0) も要る。Bnd_Box::Get は設定された gap のぶん広げて返すので、
        // 箱を密着させても gap が残っていれば同じだけ膨らむ。
        Bnd_Box box;
        BRepBndLib::AddOptimal(stack->current_shape, box, Standard_False, Standard_False);
        if (box.IsVoid()) return false;
        box.SetGap(0.0);
        box.Get(out[5], out[6], out[7], out[8], out[9], out[10]);
        return true;
    } catch (...) {
        return false;
    }
}

// カーネルが**どの OCCT で建てられたか**を返す。
//
// ここは以前 "V8.1.3.3 (cache instrumentation pass)" というアドオン版数の
// 手書きリテラルだった。呼び出し元がどこにも無かったので誰にも気付かれず、
// 本体が 8.1.5.4 になるまで 12 版ぶん放置されていた。アドオンの版数は
// bl_info を単一ソースにして core_bridge.get_version() が導出しており、
// ここに二つ目の版数を置くと必ず食い違う。
//
// 代わりに、二重管理のしようがないもの — コンパイル時に効いていた OCCT の
// 版 — を返す。ユーザーから不具合報告が来たとき、掴んでいるカーネルが
// どの OCCT かはログから分かる必要がある(8.0.0 と 8.0.1 は API が同じで
// 挙動だけ違いうるので、バイナリを見ても区別がつかない)。
std::string get_version() { return std::string("OCCT ") + OCC_VERSION_COMPLETE; }

} // namespace occ_core



extern "C" {
    void test_occ_rotation_cpp();
}

void test_occ_rotation_cpp() {
    gp_Trsf t;
    gp_Quaternion q;
    // 90 degrees around X, 0 around Y, 0 around Z
    // Blender's (90, 0, 0)
    q.SetEulerAngles(gp_Extrinsic_XYZ, 90.0 * M_PI / 180.0, 0.0, 0.0);
    t.SetRotation(q);
    
    gp_Pnt p(0, 1, 0);
    p.Transform(t);
    printf("OCC gp_Extrinsic_XYZ(90, 0, 0) maps (0,1,0) to (%f, %f, %f)\n", p.X(), p.Y(), p.Z());
    
    q.SetEulerAngles(gp_Extrinsic_XYZ, 90.0 * M_PI / 180.0, 0.0, 90.0 * M_PI / 180.0);
    t.SetRotation(q);
    gp_Pnt p2(0, 1, 0);
    p2.Transform(t);
    printf("OCC gp_Extrinsic_XYZ(90, 0, 90) maps (0,1,0) to (%f, %f, %f)\n", p2.X(), p2.Y(), p2.Z());
    
    q.SetEulerAngles(gp_Extrinsic_XYZ, 90.0 * M_PI / 180.0, 0.0, 90.0 * M_PI / 180.0);
    t.SetRotation(q);
    gp_Pnt p3(0, 1, 0);
    p3.Transform(t);
    printf("OCC gp_Extrinsic_XYZ(90, 0, 90) maps (0,1,0) to (%f, %f, %f)\n", p3.X(), p3.Y(), p3.Z());
}


