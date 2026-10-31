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


// ---------------------------------------------------------------------------
// 既存形状のスケッチ平面への投影 (フェーズ2.1 第1段階)
//
// 投影は BRepProj_Projection ではなく、平面への**正射影**を自前で行う。
// 欲しいのは「真上から見た輪郭」であって円筒面への投影ではないので、
// 曲線の種類を見て 2D の線・円・円弧へ落とす方が結果が素直になる。
//
// 返すのは平面ローカルの 2D 座標。原点・X軸・法線は呼び出し側(スケッチの
// 基準行列)が渡す。Y軸は法線×X軸で導くので、呼び出し側と必ず一致する。
//
// **第1段階は一度きりの取り込み。** 上流が変わっても再投影しない。
// 投影元の lineage を覚えてもいない(覚えるのは第2段階の仕事)。
// ---------------------------------------------------------------------------

static void project_pnt_2d(const gp_Pnt& p, const gp_Pnt& origin,
                           const gp_Dir& ax, const gp_Dir& ay,
                           double& out_x, double& out_y) {
    gp_Vec v(origin, p);
    out_x = v.Dot(gp_Vec(ax));
    out_y = v.Dot(gp_Vec(ay));
}

// 1本の辺を 2D エンティティの記述へ落として out へ積む。
// 書式は呼び出し側(api/sketch.rs)がそのまま JSON にする前提の平坦な数値列:
//   LINE   : 0, x1, y1, x2, y2
//   CIRCLE : 1, cx, cy, r
//   ARC    : 2, cx, cy, sx, sy, ex, ey, mx, my
//   POLY   : 3, 点数, x1, y1, x2, y2, ...
static void project_edge_2d(const TopoDS_Edge& e, const gp_Pnt& origin,
                            const gp_Dir& az, const gp_Dir& ax, const gp_Dir& ay,
                            std::vector<double>& out) {
    if (e.IsNull()) return;
    BRepAdaptor_Curve crv(e);
    const double f = crv.FirstParameter();
    const double l = crv.LastParameter();

    if (crv.GetType() == GeomAbs_Line) {
        double x1, y1, x2, y2;
        project_pnt_2d(crv.Value(f), origin, ax, ay, x1, y1);
        project_pnt_2d(crv.Value(l), origin, ax, ay, x2, y2);
        out.push_back(0.0);
        out.push_back(x1); out.push_back(y1);
        out.push_back(x2); out.push_back(y2);
        return;
    }

    if (crv.GetType() == GeomAbs_Circle) {
        const gp_Circ c = crv.Circle();
        // 円の載る平面がスケッチ平面と平行な時だけ、円は円のまま落ちる。
        // 傾いていれば楕円になるので、その場合は折れ線へ退避する。
        if (std::abs(c.Axis().Direction().Dot(az)) > 1.0 - 1e-7) {
            double cx, cy;
            project_pnt_2d(c.Location(), origin, ax, ay, cx, cy);
            if (BRep_Tool::IsClosed(e) || std::abs((l - f) - 2.0 * M_PI) < 1e-7) {
                out.push_back(1.0);
                out.push_back(cx); out.push_back(cy);
                out.push_back(c.Radius());
            } else {
                double sx, sy, ex, ey, mx, my;
                project_pnt_2d(crv.Value(f), origin, ax, ay, sx, sy);
                project_pnt_2d(crv.Value(l), origin, ax, ay, ex, ey);
                project_pnt_2d(crv.Value(0.5 * (f + l)), origin, ax, ay, mx, my);
                out.push_back(2.0);
                out.push_back(cx); out.push_back(cy);
                out.push_back(sx); out.push_back(sy);
                out.push_back(ex); out.push_back(ey);
                out.push_back(mx); out.push_back(my);
            }
            return;
        }
    }

    // それ以外(楕円・スプライン・傾いた円)は折れ線で近似する。
    // 第1段階は凍結した取り込みなので、ここで精度を決め打ちしてよい。
    std::vector<gp_Pnt> pts;
    try {
        GCPnts_UniformDeflection sampler(crv, 0.05, f, l);
        if (sampler.IsDone() && sampler.NbPoints() >= 2) {
            for (int i = 1; i <= sampler.NbPoints(); ++i) pts.push_back(sampler.Value(i));
        }
    } catch (...) {
        pts.clear();
    }
    if (pts.size() < 2) {
        const int n = 16;
        pts.clear();
        for (int i = 0; i <= n; ++i) pts.push_back(crv.Value(f + (l - f) * (double)i / (double)n));
    }

    out.push_back(3.0);
    out.push_back((double)pts.size());
    for (size_t i = 0; i < pts.size(); ++i) {
        double x, y;
        project_pnt_2d(pts[i], origin, ax, ay, x, y);
        out.push_back(x); out.push_back(y);
    }
}

bool project_to_sketch_plane(void* stack_ptr, const char* lineage, bool is_face,
                             const double* plane_origin, const double* plane_x, const double* plane_z,
                             std::vector<double>& out) {
    out.clear();
    if (!stack_ptr || !lineage || !plane_origin || !plane_x || !plane_z) return false;
    CADStack* stack = static_cast<CADStack*>(stack_ptr);
    if (stack->current_shape.IsNull()) return false;

    const std::string lid(lineage);
    if (lid.empty()) return false;

    try {
        const gp_Pnt origin(plane_origin[0], plane_origin[1], plane_origin[2]);
        gp_Dir az(plane_z[0], plane_z[1], plane_z[2]);
        gp_Dir ax(plane_x[0], plane_x[1], plane_x[2]);
        // Y軸は右手系で導く。呼び出し側(スケッチの基準行列)と同じ取り方。
        const gp_Dir ay(gp_Vec(az).Crossed(gp_Vec(ax)));

        if (is_face) {
            TopTools_IndexedMapOfShape fm;
            TopExp::MapShapes(stack->current_shape, TopAbs_FACE, fm);
            TopoDS_Face f = find_face_robust(lid, fm);
            if (f.IsNull()) return true;   // 解決できず = 空で返す
            for (TopExp_Explorer ex(f, TopAbs_EDGE); ex.More(); ex.Next()) {
                project_edge_2d(TopoDS::Edge(ex.Current()), origin, az, ax, ay, out);
            }
        } else {
            TopTools_IndexedMapOfShape em;
            TopExp::MapShapes(stack->current_shape, TopAbs_EDGE, em);
            TopoDS_Edge e = find_edge_robust(lid, em, nullptr);
            if (e.IsNull()) return true;
            project_edge_2d(e, origin, az, ax, ay, out);
        }
        return true;
    } catch (...) {
        out.clear();
        return false;
    }
}


// Rust から呼ぶための固定長バッファ版。measure_entity と同じ形に揃えてある。
// 返り値は書き込んだ double の個数。バッファに収まらなければ -2、
// 失敗は -1。呼び出し側は -2 を「投影結果が大きすぎる」として扱う。
int project_to_sketch_plane_buf(void* stack_ptr, const char* lineage, bool is_face,
                                const double* plane_origin, const double* plane_x, const double* plane_z,
                                double* out_buf, int buf_len) {
    std::vector<double> tmp;
    if (!project_to_sketch_plane(stack_ptr, lineage, is_face, plane_origin, plane_x, plane_z, tmp)) return -1;
    if (!out_buf || buf_len < 0) return -1;
    if ((int)tmp.size() > buf_len) return -2;
    for (size_t i = 0; i < tmp.size(); ++i) out_buf[i] = tmp[i];
    return (int)tmp.size();
}

}
