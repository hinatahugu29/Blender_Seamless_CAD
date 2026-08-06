#include "occ_common.hpp"
#include "occ_utils.hpp"
#include <iostream>
#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRep_Tool.hxx>
#include <BRepGProp.hxx>
#include <GProp_GProps.hxx>
#include <BRepTools.hxx>
#include <Geom_Surface.hxx>
#include <BRepExtrema_DistShapeShape.hxx>
#include <BRepBuilderAPI_MakeVertex.hxx>
#include <ShapeUpgrade_ShapeDivideClosed.hxx>
#include <BRepBndLib.hxx>
#include <Bnd_Box.hxx>

namespace occ_core {
    double bbox_distance_sq(const Bnd_Box& box, const gp_Pnt& p) {
        if (box.IsVoid()) return 1e10;
        Standard_Real xmin, ymin, zmin, xmax, ymax, zmax;
        box.Get(xmin, ymin, zmin, xmax, ymax, zmax);
        double dx = std::max({0.0, xmin - p.X(), p.X() - xmax});
        double dy = std::max({0.0, ymin - p.Y(), p.Y() - ymax});
        double dz = std::max({0.0, zmin - p.Z(), p.Z() - zmax});
        return dx*dx + dy*dy + dz*dz;
    }
    bool g_debug_logging_enabled = true;
    double g_sum_perf_extrema = 0.0;

    void log_debug(const std::string& msg) {
        if (!g_debug_logging_enabled) return;
        std::cerr << "[CAD_DEBUG] " << msg << std::endl;
    }

    double safe_edge_point_distance(const TopoDS_Edge& e, const gp_Pnt& target_p) {
        if (e.IsNull() || BRep_Tool::Degenerated(e)) return 1e10;
        try {
            auto t_start = std::chrono::high_resolution_clock::now();
            BRepExtrema_DistShapeShape dist(BRepBuilderAPI_MakeVertex(target_p), e);
            dist.Perform();
            auto t_end = std::chrono::high_resolution_clock::now();
            g_sum_perf_extrema += std::chrono::duration<double, std::milli>(t_end - t_start).count();
            if (dist.IsDone()) return dist.Value();
            return 1e10;
        } catch (...) { return 1e10; }
    }

    double safe_edge_length(const TopoDS_Edge& e) {
        if (e.IsNull() || BRep_Tool::Degenerated(e)) return 0.0;
        try {
            GProp_GProps prop;
            BRepGProp::LinearProperties(e, prop);
            return prop.Mass();
        } catch (...) { return 0.0; }
    }

    gp_Pnt safe_edge_midpoint(const TopoDS_Edge& e) {
        if (e.IsNull() || BRep_Tool::Degenerated(e)) return gp_Pnt(0,0,0);
        try {
            Standard_Real first, last;
            Handle(Geom_Curve) curve = BRep_Tool::Curve(e, first, last);
            if (!curve.IsNull()) {
                return curve->Value((first + last) / 2.0);
            }
        } catch (...) {}
        return gp_Pnt(0,0,0);
    }

    TopoDS_Edge find_edge_robust(const std::string& lid, const TopTools_IndexedMapOfShape& edge_map, const std::map<std::string, TopoDS_Shape>* face_map) {
        if (lid.find("Edge:") != 0) return TopoDS_Edge();
        size_t at_pos = lid.find("@");
        size_t hash_pos = lid.find("#");
        int idx = 0; 
        try { 
            size_t end_idx = (at_pos != std::string::npos) ? at_pos : ((hash_pos != std::string::npos) ? hash_pos : std::string::npos);
            idx = std::stoi(lid.substr(5, (end_idx == std::string::npos) ? std::string::npos : end_idx - 5)); 
        } catch(...) {}

        double x1 = 0, y1 = 0, z1 = 0, x2 = 0, y2 = 0, z2 = 0; 
        int index = -1;
        bool has_coord = false;
        bool has_p2 = false;
        gp_Pnt target_p1, target_p2;

        if (at_pos != std::string::npos) {
            std::string coord_part = lid.substr(at_pos + 1);
            if (hash_pos != std::string::npos && hash_pos > at_pos) {
                coord_part = lid.substr(at_pos + 1, hash_pos - at_pos - 1);
            }
            int parsed = sscanf((std::to_string(idx) + "@" + coord_part).c_str(), "%d@%lf;%lf;%lf@%lf;%lf;%lf", &index, &x1, &y1, &z1, &x2, &y2, &z2);
            if (parsed >= 4) {
                has_coord = true;
                target_p1 = gp_Pnt(x1, y1, z1);
                if (parsed == 7) {
                    has_p2 = true;
                    target_p2 = gp_Pnt(x2, y2, z2);
                }
            }
        }

    if (face_map) {
        size_t fi_pos = lid.find("FaceIntersect:");
        if (fi_pos != std::string::npos) {
            std::string uuids = lid.substr(fi_pos + 14);
            size_t comma = uuids.find(",");
            if (comma != std::string::npos) {
                std::string u1 = uuids.substr(0, comma);
                std::string u2 = uuids.substr(comma + 1);
                size_t bar = u2.find("|");
                if (bar != std::string::npos) u2 = u2.substr(0, bar);

                auto it1 = face_map->find(u1);
                auto it2 = face_map->find(u2);
                if (it1 != face_map->end() && it2 != face_map->end()) {
                    TopoDS_Shape f1 = it1->second;
                    TopoDS_Shape f2 = it2->second;
                    TopTools_MapOfShape f1_edges;
                    for (TopExp_Explorer ex1(f1, TopAbs_EDGE); ex1.More(); ex1.Next()) {
                        f1_edges.Add(ex1.Current());
                    }
                    TopoDS_Edge best_shared;
                    double best_score = 1e10; // score is distance if coord exists, else -length
                    for (TopExp_Explorer ex2(f2, TopAbs_EDGE); ex2.More(); ex2.Next()) {
                        if (f1_edges.Contains(ex2.Current())) {
                            TopoDS_Edge shared_edge = TopoDS::Edge(ex2.Current());
                            for (int i = 1; i <= edge_map.Extent(); ++i) {
                                if (edge_map.FindKey(i).IsSame(shared_edge)) {
                                    TopoDS_Edge mapped_edge = TopoDS::Edge(edge_map.FindKey(i));
                                    double score;
                                    if (has_coord) {
                                        double d1 = safe_edge_point_distance(mapped_edge, target_p1);
                                        double d2 = has_p2 ? safe_edge_point_distance(mapped_edge, target_p2) : 1e10;
                                        score = std::min(d1, d2);
                                    } else {
                                        GProp_GProps prop;
                                        BRepGProp::LinearProperties(mapped_edge, prop);
                                        score = -prop.Mass();
                                    }
                                    if (score < best_score) {
                                        best_score = score;
                                        best_shared = mapped_edge;
                                    }
                                }
                            }
                        }
                    }
                    if (!best_shared.IsNull()) return best_shared;
                }
            }
        }
    }

        if (!has_coord) {
            if (idx >= 1 && idx <= edge_map.Extent()) return TopoDS::Edge(edge_map.FindKey(idx));
            return TopoDS_Edge();
        }

        if (index >= 1 && index <= edge_map.Extent()) {
            TopoDS_Edge e = TopoDS::Edge(edge_map.FindKey(index));
            double d1 = safe_edge_point_distance(e, target_p1);
            double d2 = has_p2 ? safe_edge_point_distance(e, target_p2) : 1e10;
            if (std::min(d1, d2) < 5e-3) return e;  // 5mm: Unify後E座標ずれに対忁E
        }
        TopoDS_Edge best_e; double min_d = 1e10;
        std::vector<std::pair<double, TopoDS_Edge>> candidates;
        for (int i = 1; i <= edge_map.Extent(); ++i) {
            TopoDS_Edge e = TopoDS::Edge(edge_map.FindKey(i));
            Bnd_Box box; BRepBndLib::Add(e, box);
            double d1_sq = bbox_distance_sq(box, target_p1);
            double d2_sq = has_p2 ? bbox_distance_sq(box, target_p2) : 1e10;
            if (std::min(d1_sq, d2_sq) > 1.0) continue;
            
            gp_Pnt mid = safe_edge_midpoint(e);
            double mid_dist = std::min(mid.Distance(target_p1), has_p2 ? mid.Distance(target_p2) : 1e10);
            candidates.push_back({mid_dist, e});
        }
        std::sort(candidates.begin(), candidates.end(), [](const auto& a, const auto& b){ return a.first < b.first; });
        for (size_t i = 0; i < std::min((size_t)3, candidates.size()); ++i) {
            TopoDS_Edge e = candidates[i].second;
            double d1 = safe_edge_point_distance(e, target_p1);
            double d2 = has_p2 ? safe_edge_point_distance(e, target_p2) : 1e10;
            double d = std::min(d1, d2);
            if (d < min_d) { min_d = d; best_e = e; }
        }
        if (min_d < 5e-2) return best_e;
        return TopoDS_Edge();
    }

    double safe_face_point_distance(const TopoDS_Face& f, const gp_Pnt& target_p) {
        if (f.IsNull()) return 1e10;
        try {
            auto t_start = std::chrono::high_resolution_clock::now();
            BRepExtrema_DistShapeShape dist(BRepBuilderAPI_MakeVertex(target_p), f);
            dist.Perform();
            auto t_end = std::chrono::high_resolution_clock::now();
            g_sum_perf_extrema += std::chrono::duration<double, std::milli>(t_end - t_start).count();
            if (dist.IsDone()) return dist.Value();
            return 1e10;
        } catch (...) { return 1e10; }
    }

    TopoDS_Face find_face_robust(const std::string& lid, const TopTools_IndexedMapOfShape& face_map) {
        if (lid.find("Face:") != 0) return TopoDS_Face();
        size_t at_pos = lid.find("@");
        int idx = 0; try { idx = std::stoi(lid.substr(5, (at_pos == std::string::npos) ? std::string::npos : at_pos - 5)); } catch(...) {}
        if (at_pos == std::string::npos) {
            if (idx >= 1 && idx <= face_map.Extent()) return TopoDS::Face(face_map.FindKey(idx));
            return TopoDS_Face();
        }
        double x, y, z; int index = -1;
        std::string coord_part = lid.substr(lid.find(":") + 1);
        if (sscanf(coord_part.c_str(), "%d@%lf;%lf;%lf", &index, &x, &y, &z) != 4) return TopoDS_Face();
        gp_Pnt target_p(x, y, z);
        if (index >= 1 && index <= face_map.Extent()) {
            TopoDS_Face f = TopoDS::Face(face_map.FindKey(index));
            if (safe_face_point_distance(f, target_p) < 5e-3) return f;  // 5mm: Unify後の座標ずれに対応
        }

        // V8.1.4.1: normal-gated robust match. Newly picked face tokens embed the
        // pick normal as "#N:nx;ny;nz". On fillet-dense geometry the legacy
        // nearest-surface match (tol 0.5) could bind FACE_OFFSET to a neighbouring
        // 45-deg fillet strip that merely passes within 0.5 of the stored seed
        // point. When a normal is present, restrict candidates to faces whose
        // normal aligns with it (|dot| >= 0.85) and take the nearest centroid;
        // this rejects the fillet face decisively. Old tokens (no #N) are
        // untouched and fall through to the legacy path below.
        {
            gp_Vec want_n; bool has_n = false;
            size_t np = lid.find("#N:");
            if (np != std::string::npos) {
                double nx = 0, ny = 0, nz = 0;
                if (sscanf(lid.c_str() + np + 3, "%lf;%lf;%lf", &nx, &ny, &nz) == 3) {
                    want_n = gp_Vec(nx, ny, nz);
                    if (want_n.SquareMagnitude() > 1e-9) { want_n.Normalize(); has_n = true; }
                }
            }
            if (has_n) {
                TopoDS_Face best_nf; double best_nd = 1e10;
                for (int i = 1; i <= face_map.Extent(); ++i) {
                    TopoDS_Face f = TopoDS::Face(face_map.FindKey(i));
                    Bnd_Box box; BRepBndLib::Add(f, box);
                    if (bbox_distance_sq(box, target_p) > 1.0) continue;
                    try {
                        GProp_GProps gp_props;
                        BRepGProp::SurfaceProperties(f, gp_props);
                        double dc = gp_props.CentreOfMass().Distance(target_p);
                        if (dc >= best_nd) continue;
                        BRepAdaptor_Surface s(f);
                        double u = (s.FirstUParameter() + s.LastUParameter()) / 2.0;
                        double v = (s.FirstVParameter() + s.LastVParameter()) / 2.0;
                        gp_Pnt pp; gp_Vec du, dv; s.D1(u, v, pp, du, dv);
                        gp_Vec fn = du.Crossed(dv);
                        if (fn.SquareMagnitude() < 1e-9) continue;
                        fn.Normalize();
                        if (std::abs(fn.Dot(want_n)) < 0.85) continue; // normal must align
                        best_nd = dc; best_nf = f;
                    } catch (...) {}
                }
                if (!best_nf.IsNull() && best_nd < 5e-1) {
                    log_debug("[find_face_robust] normal-gated match centroid_dist=" + std::to_string(best_nd));
                    return best_nf;
                }
                log_debug("[find_face_robust] normal-gated match failed; legacy fallback for lid=" + lid);
            }
        }

        std::vector<std::pair<double, TopoDS_Face>> candidates;
        for (int i = 1; i <= face_map.Extent(); ++i) {
            TopoDS_Face f = TopoDS::Face(face_map.FindKey(i));
            Bnd_Box box; BRepBndLib::Add(f, box);
            if (bbox_distance_sq(box, target_p) > 1.0) continue;
            try {
                GProp_GProps gp_props;
                BRepGProp::SurfaceProperties(f, gp_props);
                double d = gp_props.CentreOfMass().Distance(target_p);
                candidates.push_back({d, f});
            } catch (...) {}
        }
        std::sort(candidates.begin(), candidates.end(), [](const auto& a, const auto& b){ return a.first < b.first; });
        TopoDS_Face best_f; double min_d = 1e10;
        for (size_t i = 0; i < std::min((size_t)3, candidates.size()); ++i) {
            TopoDS_Face f = candidates[i].second;
            double d = safe_face_point_distance(f, target_p);
            if (d < min_d) { min_d = d; best_f = f; }
        }
        if (min_d < 5e-1) return best_f;
        if (!candidates.empty() && candidates[0].first < 5e-1) {
            log_debug("[find_face_robust] Centroid fallback matched: centroid_dist=" + std::to_string(candidates[0].first));
            return candidates[0].second;
        }
        log_debug("[find_face_robust] No face matched for lid=" + lid + " min_dist=" + std::to_string(min_d));
        return TopoDS_Face();
    }

    TopoDS_Shape apply_divide_closed(const TopoDS_Shape& shape) {
        if (shape.IsNull()) return shape;
        try {
            ShapeUpgrade_ShapeDivideClosed divider(shape);
            divider.Perform();
            if (divider.Status(ShapeExtend_DONE)) {
                return divider.Result();
            }
        } catch (...) {}
        return shape;
    }
}
