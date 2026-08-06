#include "occ_common.hpp"
#include "occ_sketch.hpp"
#include "occ_utils.hpp"
#include "occ_core.hpp"
namespace occ_core {
// occ_sketch.cpp

TopoDS_Shape make_curve_or_surface(const double* all_pts, int pts_offset, int pc, bool is_surface) {
    std::vector<std::vector<gp_Pnt>> loops;
    std::vector<gp_Pnt> current_loop;
    
    for (int j = 0; j < pc; ++j) {
        double x = all_pts[pts_offset + j*4+0];
        double y = all_pts[pts_offset + j*4+1];
        double z = all_pts[pts_offset + j*4+2];
        
        // 1e9以上は区切りと見なす
        if (x > 1e9 && y > 1e9 && z > 1e9) {
            if (current_loop.size() >= 2) {
                loops.push_back(current_loop);
            }
            current_loop.clear();
        } else {
            gp_Pnt p(x, y, z);
            if (current_loop.empty() || p.Distance(current_loop.back()) > 0.0001) {
                current_loop.push_back(p);
            }
        }
    }
    if (current_loop.size() >= 2) {
        loops.push_back(current_loop);
    }
    
    if (loops.empty()) return TopoDS_Shape();
    
    if (is_surface) {
        std::vector<TopoDS_Wire> wires;
        for (const auto& vp : loops) {
            if (vp.size() < 2) continue;
            bool is_closed = (vp.front().Distance(vp.back()) < 0.001);
            BRepBuilderAPI_MakePolygon mp;
            for (const auto& p : vp) mp.Add(p);
            if (is_closed) mp.Close();
            if (mp.IsDone()) {
                wires.push_back(mp.Wire());
            }
        }
        if (wires.empty()) return TopoDS_Shape();
        
        BRepBuilderAPI_MakeFace mf(wires[0], true);
        if (mf.IsDone()) {
            TopoDS_Face face = mf.Face();
            for (size_t k = 1; k < wires.size(); ++k) {
                BRep_Builder B;
                B.Add(face, wires[k]);
            }
            ShapeFix_Face sff(face);
            sff.FixOrientation();
            return sff.Face();
        }
        return wires[0];
    } else {
        // CURVE の場合
        const auto& vp = loops[0];
        if (vp.size() < 2) return TopoDS_Shape();
        bool is_closed = (vp.front().Distance(vp.back()) < 0.001);
        
        if (vp.size() == 2) {
            return BRepBuilderAPI_MakeEdge(vp[0], vp[1]).Shape();
        } else if (vp.size() > 2) {
            try {
                TColgp_Array1OfPnt pa(1, (int)vp.size());
                for (size_t j = 0; j < vp.size(); ++j) pa.SetValue((int)j + 1, vp[j]);
                GeomAPI_PointsToBSpline ap(pa);
                if (ap.IsDone()) {
                    TopoDS_Edge edge = BRepBuilderAPI_MakeEdge(ap.Curve()).Edge();
                    if (is_closed) {
                        BRepBuilderAPI_MakeWire mw(edge);
                        if (mw.IsDone()) return mw.Wire();
                    }
                    return edge;
                }
            } catch (...) {
                // fall through to polygon fallback
            }
        }
        
        BRepBuilderAPI_MakePolygon mp;
        for (const auto& p : vp) mp.Add(p);
        if (is_closed) mp.Close();
        if (mp.IsDone()) return mp.Wire();
    }
    return TopoDS_Shape();
}

TopoDS_Shape make_curve_or_surface_from_segments(const double* seg_data, int seg_offset, int sc, bool is_surface) {
    std::vector<TopoDS_Wire> wires;
    BRepBuilderAPI_MakeWire current_wire;
    bool has_edges = false;

    for (int j = 0; j < sc; ++j) {
        const double* sd = &seg_data[seg_offset + j * 17];
        double type_val = sd[0];
        
        if (type_val == 3.0) { // DELIMITER
            if (has_edges) {
                if (current_wire.IsDone()) wires.push_back(current_wire.Wire());
            }
            current_wire = BRepBuilderAPI_MakeWire();
            has_edges = false;
            continue;
        }
        
        gp_Pnt p_start(sd[1], sd[2], sd[3]);
        gp_Pnt p_end(sd[4], sd[5], sd[6]);
        gp_Pnt p_mid(sd[7], sd[8], sd[9]);
        gp_Pnt p_center(sd[10], sd[11], sd[12]);
        double radius = sd[13];
        gp_Dir normal(sd[14] < 1e9 ? sd[14] : 0, sd[15] < 1e9 ? sd[15] : 0, sd[16] < 1e9 ? sd[16] : 1);
        
        TopoDS_Edge edge;
        try {
            if (type_val == 0.0) { // LINE
                if (p_start.Distance(p_end) > 1e-6) {
                    edge = BRepBuilderAPI_MakeEdge(p_start, p_end).Edge();
                }
            } else if (type_val == 1.0) { // ARC
                if (p_start.Distance(p_end) > 1e-6 && p_start.Distance(p_mid) > 1e-6) {
                    GC_MakeArcOfCircle arc(p_start, p_mid, p_end);
                    if (arc.IsDone()) {
                        edge = BRepBuilderAPI_MakeEdge(arc.Value()).Edge();
                    }
                }
            } else if (type_val == 2.0) { // CIRCLE
                if (radius > 1e-6) {
                    gp_Ax2 ax(p_center, normal);
                    gp_Circ circ(ax, radius);
                    edge = BRepBuilderAPI_MakeEdge(circ).Edge();
                }
            }
            
            if (!edge.IsNull()) {
                current_wire.Add(edge);
                has_edges = true;
            }
        } catch(...) {
            // ignore failure for a single segment
        }
    }
    
    if (has_edges && current_wire.IsDone()) {
        wires.push_back(current_wire.Wire());
    }
    
    if (wires.empty()) return TopoDS_Shape();
    
    if (is_surface) {
        BRepBuilderAPI_MakeFace mf(wires[0], true);
        if (mf.IsDone()) {
            TopoDS_Face face = mf.Face();
            for (size_t k = 1; k < wires.size(); ++k) {
                BRep_Builder B;
                B.Add(face, wires[k]);
            }
            ShapeFix_Face sff(face);
            sff.FixOrientation();
            return sff.Face();
        }
        return wires[0];
    } else {
        return wires[0];
    }
}

TopoDS_Shape make_polyline(const double* all_pts, int pts_offset, int pc, double fillet_radius) {
    std::vector<gp_Pnt> points;
    std::vector<bool> point_use_fillet;
    for (int j = 0; j < pc; ++j) {
        double x = all_pts[pts_offset + j*4+0];
        double y = all_pts[pts_offset + j*4+1];
        double z = all_pts[pts_offset + j*4+2];
        double flag = all_pts[pts_offset + j*4+3];
        
        if (x > 1e9 && y > 1e9 && z > 1e9) {
            continue;
        }
        gp_Pnt p(x, y, z);
        if (points.empty() || p.Distance(points.back()) > 0.0001) {
            points.push_back(p);
            point_use_fillet.push_back(flag > 0.5);
        }
    }
    
    if (points.size() < 2) return TopoDS_Shape();
    bool is_closed = (points.front().Distance(points.back()) < 0.001);
    
    if (is_closed && points.size() > 2) {
        points.back() = points.front();
        point_use_fillet.back() = point_use_fillet.front();
    }
    
    int n = (int)points.size();
    if (n == 2) {
        return BRepBuilderAPI_MakeEdge(points[0], points[1]).Shape();
    }
    
    BRepBuilderAPI_MakeWire wire_builder;
    std::vector<gp_Pnt> T1(n);
    std::vector<gp_Pnt> T2(n);
    std::vector<bool> has_fillet(n, false);
    std::vector<TopoDS_Edge> arcs(n);
    
    int loop_end = is_closed ? n : n - 1;
    int loop_start = is_closed ? 0 : 1;
    
    for (int i = loop_start; i < loop_end; ++i) {
        if (!point_use_fillet[i]) {
            continue; // この頂点でのフィレットはスキップ（鋭角のままにする）
        }
        
        int prev_idx = (i - 1 + n) % n;
        int next_idx = (i + 1) % n;
        
        gp_Pnt P_prev = points[prev_idx];
        gp_Pnt P_curr = points[i];
        gp_Pnt P_next = points[next_idx];
        
        gp_Vec V1(P_curr, P_prev);
        gp_Vec V2(P_curr, P_next);
        
        double len1 = V1.Magnitude();
        double len2 = V2.Magnitude();
        
        if (len1 < 1e-4 || len2 < 1e-4) continue;
        
        V1.Normalize();
        V2.Normalize();
        
        double dot = V1.Dot(V2);
        if (dot > 0.999 || dot < -0.999) continue;
        
        double theta = std::acos(std::max(-1.0, std::min(1.0, dot)));
        double half_theta = theta * 0.5;
        
        double R = fillet_radius;
        if (R < 1e-4) continue;
        
        double d = R / std::tan(half_theta);
        double max_d = std::min(len1, len2) * 0.45;
        if (d > max_d) {
            d = max_d;
            R = d * std::tan(half_theta);
        }
        
        gp_Pnt pt_T1 = P_curr.Translated(V1 * d);
        gp_Pnt pt_T2 = P_curr.Translated(V2 * d);
        
        gp_Vec B = V1 + V2;
        if (B.Magnitude() < 1e-4) continue;
        B.Normalize();
        
        gp_Pnt C = P_curr.Translated(B * (R / std::sin(half_theta)));
        gp_Pnt M = C.Translated(-B * R);
        
        try {
            GC_MakeArcOfCircle arc_maker(pt_T1, M, pt_T2);
            if (arc_maker.IsDone()) {
                arcs[i] = BRepBuilderAPI_MakeEdge(arc_maker.Value()).Edge();
                T1[i] = pt_T1;
                T2[i] = pt_T2;
                has_fillet[i] = true;
            }
        } catch (...) {
        }
    }
    
    try {
        for (int i = 0; i < n - 1; ++i) {
            gp_Pnt start_p = points[i];
            gp_Pnt end_p = points[i+1];
            
            if (has_fillet[i]) {
                start_p = T2[i];
            }
            if (has_fillet[i+1]) {
                end_p = T1[i+1];
            }
            
            if (start_p.Distance(end_p) > 1e-4) {
                TopoDS_Edge line_edge = BRepBuilderAPI_MakeEdge(start_p, end_p).Edge();
                wire_builder.Add(line_edge);
            }
            
            if (i + 1 < n - 1 && has_fillet[i+1] && !arcs[i+1].IsNull()) {
                wire_builder.Add(arcs[i+1]);
            }
        }
        
        if (is_closed) {
            gp_Pnt start_p = points[n-1];
            gp_Pnt end_p = points[0];
            
            if (has_fillet[n-1]) {
                start_p = T2[n-1];
            }
            if (has_fillet[0]) {
                end_p = T1[0];
            }
            
            if (start_p.Distance(end_p) > 1e-4) {
                TopoDS_Edge line_edge = BRepBuilderAPI_MakeEdge(start_p, end_p).Edge();
                wire_builder.Add(line_edge);
            }
            if (has_fillet[0] && !arcs[0].IsNull()) {
                wire_builder.Add(arcs[0]);
            }
        }
    } catch (...) {
        BRepBuilderAPI_MakePolygon fallback_mp;
        for (const auto& p : points) fallback_mp.Add(p);
        if (is_closed) fallback_mp.Close();
        return fallback_mp.Wire();
    }
    
    if (wire_builder.IsDone()) {
        return wire_builder.Wire();
    }
    
    BRepBuilderAPI_MakePolygon fallback_mp;
    for (const auto& p : points) fallback_mp.Add(p);
    if (is_closed) fallback_mp.Close();
    return fallback_mp.Wire();
}

}
