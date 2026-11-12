// occ_quad.cpp — Quad Bake P0: topology extraction for a seam-exact bake mesh.
//
// The kernel does NOT triangulate here. It hands Python everything a face fill
// needs, with every boundary point shared by index:
//   * verts    — CAD vertices first, then each edge's interior samples. An edge
//                is discretised ONCE, so the two faces on either side of it use
//                the very same vertex indices (no position-based welding).
//   * faces    — per CAD face: surface kind, orientation, UV metric scale, the
//                boundary loops as (vertex index, u, v) read from the edge's
//                pcurve on THAT face, and interior (Steiner) points already
//                evaluated on the surface.
// Python (operators/quad_bake.py) fills each face: a hole-free plane becomes one
// n-gon, everything else a constrained Delaunay triangulation in UV.
//
// Span law per edge (absolute chord tolerance `tol`, model units):
//   line   -> 1
//   circle -> ceil(theta / (2 acos(1 - tol/R))), at least 2 (a full ring snaps
//             to 4/8/12/16/24/32/48/64 when within 35%)
//   other  -> flattening integral sum sqrt(phi*l / (8 tol)) over a dense sample

#include "occ_common.hpp"
#include "occ_core.hpp"
#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepTools.hxx>
#include <BRepTools_WireExplorer.hxx>
#include <BRepTopAdaptor_FClass2d.hxx>
#include <BRep_Tool.hxx>
#include <GCPnts_TangentialDeflection.hxx>
#include <GCPnts_UniformAbscissa.hxx>
#include <Geom2d_Curve.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopoDS.hxx>
#include <gp_Circ.hxx>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdio>
#include <string>
#include <vector>

namespace occ_core {

namespace {

const int kMaxSpans = 512;

struct EdgeSamples {
    bool ok = false;
    bool degenerated = false;
    std::vector<double> params;  // ascending curve parameters, size n+1
    std::vector<int> vids;       // global vertex index per param
};

void jnum(std::string& out, double v) {
    if (!std::isfinite(v)) v = 0.0;
    char buf[40];
    snprintf(buf, sizeof(buf), "%.10g", v);
    out += buf;
}

int snap_ring(int n) {
    static const int pref[] = {4, 8, 12, 16, 24, 32, 48, 64};
    int best = n;
    double bestd = 1e300;
    for (int c : pref) {
        if (c < n * 0.65 - 1e-9 || c > n * 1.35 + 1e-9) continue;
        double d = std::fabs(c - n);
        if (d < bestd - 1e-9 || (std::fabs(d - bestd) <= 1e-9 && c < best)) { bestd = d; best = c; }
    }
    if (n > 64) best = ((n + 15) / 16) * 16;
    return best;
}

int arc_spans(double theta, double R, double tol) {
    theta = std::fabs(theta);
    if (theta <= 0.0 || R <= 0.0) return 1;
    double ratio = 1.0 - tol / R;
    int n = 2;
    if (ratio > -1.0) {
        double denom = 2.0 * std::acos(std::min(ratio, 1.0));
        if (denom > 1e-12) n = std::max(2, (int)std::ceil(theta / denom - 1e-9));
    }
    if (std::fabs(theta - 6.283185307179586) < 1e-6) n = std::max(4, snap_ring(n));
    return std::min(n, kMaxSpans);
}

int free_curve_spans(const BRepAdaptor_Curve& c, double tol) {
    std::vector<gp_Pnt> P;
    try {
        GCPnts_TangentialDeflection td(c, 0.05, std::max(tol * 0.05, 1e-9), 3);
        for (int i = 1; i <= td.NbPoints(); ++i) P.push_back(td.Value(i));
    } catch (...) {}
    if (P.size() < 3) return 1;
    double total = 0.0;
    for (size_t i = 1; i + 1 < P.size(); ++i) {
        gp_Vec v1(P[i - 1], P[i]), v2(P[i], P[i + 1]);
        double l1 = v1.Magnitude(), l2 = v2.Magnitude();
        if (l1 < 1e-12 || l2 < 1e-12) continue;
        double phi = v1.Angle(v2);
        total += std::sqrt(phi * 0.5 * (l1 + l2) / (8.0 * tol));
    }
    int n = std::max(1, (int)std::ceil(total - 1e-9));
    return std::min(n, kMaxSpans);
}

int edge_spans(const TopoDS_Edge& e, double tol) {
    BRepAdaptor_Curve c(e);
    switch (c.GetType()) {
        case GeomAbs_Line:
            return 1;
        case GeomAbs_Circle: {
            double R = c.Circle().Radius();
            return arc_spans(c.LastParameter() - c.FirstParameter(), R, tol);
        }
        default:
            return free_curve_spans(c, tol);
    }
}

const char* surface_kind(GeomAbs_SurfaceType t) {
    switch (t) {
        case GeomAbs_Plane: return "plane";
        case GeomAbs_Cylinder: return "cylinder";
        case GeomAbs_Cone: return "cone";
        case GeomAbs_Sphere: return "sphere";
        case GeomAbs_Torus: return "torus";
        case GeomAbs_BezierSurface: return "bezier";
        case GeomAbs_BSplineSurface: return "bspline";
        case GeomAbs_SurfaceOfRevolution: return "revolution";
        case GeomAbs_SurfaceOfExtrusion: return "extrusion";
        case GeomAbs_OffsetSurface: return "offset";
        default: return "other";
    }
}

struct LoopPt { int vid; double u, v; };

// Walk one wire of `face` in connection order; each edge contributes its samples
// (minus the last, which is the next edge's first) with (u,v) from its pcurve on
// this face. Returns false when a pcurve is missing.
bool walk_wire(const TopoDS_Wire& w, const TopoDS_Face& face, const TopTools_IndexedMapOfShape& em,
               const std::vector<EdgeSamples>& es, std::vector<LoopPt>& out) {
    for (BRepTools_WireExplorer wx(w, face); wx.More(); wx.Next()) {
        TopoDS_Edge e = wx.Current();
        int ei = em.FindIndex(e);
        if (ei < 1 || !es[ei].ok) return false;
        const EdgeSamples& s = es[ei];
        double f2, l2;
        Handle(Geom2d_Curve) pc = BRep_Tool::CurveOnSurface(e, face, f2, l2);
        if (pc.IsNull()) return false;
        int n = (int)s.params.size();
        bool rev = (e.Orientation() == TopAbs_REVERSED);
        for (int k = 0; k < n - 1; ++k) {
            int idx = rev ? (n - 1 - k) : k;
            gp_Pnt2d uv = pc->Value(s.params[idx]);
            out.push_back({s.vids[idx], uv.X(), uv.Y()});
        }
    }
    return true;
}

}  // namespace

std::string quad_topology_json(void* stack_ptr, double tol) {
    CADStack* stack = static_cast<CADStack*>(stack_ptr);
    if (!stack || stack->current_shape.IsNull()) return std::string();
    if (!(tol > 0.0)) tol = 0.01;
    const TopoDS_Shape& shape = stack->current_shape;

    TopTools_IndexedMapOfShape vm, em, fm;
    TopExp::MapShapes(shape, TopAbs_VERTEX, vm);
    TopExp::MapShapes(shape, TopAbs_EDGE, em);
    TopExp::MapShapes(shape, TopAbs_FACE, fm);

    std::vector<gp_Pnt> verts;
    verts.reserve(vm.Extent() * 4);
    for (int i = 1; i <= vm.Extent(); ++i) verts.push_back(BRep_Tool::Pnt(TopoDS::Vertex(vm.FindKey(i))));

    // ── edges: discretise ONCE ────────────────────────────────────────────
    std::vector<EdgeSamples> es(em.Extent() + 1);
    int n_edge_fail = 0;
    for (int i = 1; i <= em.Extent(); ++i) {
        TopoDS_Edge e = TopoDS::Edge(em.FindKey(i));
        EdgeSamples& s = es[i];
        try {
            TopoDS_Vertex v0 = TopExp::FirstVertex(e, Standard_False);
            TopoDS_Vertex v1 = TopExp::LastVertex(e, Standard_False);
            if (v0.IsNull() || v1.IsNull()) { ++n_edge_fail; continue; }
            int i0 = vm.FindIndex(v0) - 1, i1 = vm.FindIndex(v1) - 1;
            double f, l;
            BRep_Tool::Range(e, f, l);
            if (BRep_Tool::Degenerated(e)) {
                s.degenerated = true;
                s.params = {f, l};
                s.vids = {i0, i0};
                s.ok = true;
                continue;
            }
            int n = edge_spans(e, tol);
            BRepAdaptor_Curve c(e);
            s.params.push_back(f);
            if (n > 1) {
                GCPnts_UniformAbscissa ua(c, n + 1, f, l);
                if (ua.IsDone() && ua.NbPoints() == n + 1) {
                    for (int k = 2; k <= n; ++k) s.params.push_back(ua.Parameter(k));
                } else {
                    for (int k = 1; k < n; ++k) s.params.push_back(f + (l - f) * k / n);
                }
            }
            s.params.push_back(l);
            s.vids.push_back(i0);
            for (size_t k = 1; k + 1 < s.params.size(); ++k) {
                s.vids.push_back((int)verts.size());
                verts.push_back(c.Value(s.params[k]));
            }
            s.vids.push_back(i1);
            s.ok = true;
        } catch (...) {
            ++n_edge_fail;
        }
    }

    std::string out;
    out.reserve(1 << 20);
    out += "{\"version\":1,\"tol\":";
    jnum(out, tol);
    out += ",\"faces\":[";

    // ── faces ─────────────────────────────────────────────────────────────
    bool first_face = true;
    for (int fi = 1; fi <= fm.Extent(); ++fi) {
        TopoDS_Face face = TopoDS::Face(fm.FindKey(fi));
        // Work on the FORWARD face so pcurves/wire order are in surface terms;
        // the original orientation is reported as "rev".
        bool rev = (face.Orientation() == TopAbs_REVERSED);
        TopoDS_Face ff = TopoDS::Face(face.Oriented(TopAbs_FORWARD));
        std::string why;
        std::vector<std::vector<LoopPt>> loops;
        try {
            TopoDS_Wire outer = BRepTools::OuterWire(ff);
            if (outer.IsNull()) why = "no outer wire";
            else {
                loops.emplace_back();
                if (!walk_wire(outer, ff, em, es, loops.back())) why = "missing pcurve";
                for (TopExp_Explorer wx(ff, TopAbs_WIRE); why.empty() && wx.More(); wx.Next()) {
                    TopoDS_Wire w = TopoDS::Wire(wx.Current());
                    if (w.IsSame(outer)) continue;
                    loops.emplace_back();
                    if (!walk_wire(w, ff, em, es, loops.back())) why = "missing pcurve";
                }
            }
        } catch (...) {
            why = "wire walk failed";
        }

        BRepAdaptor_Surface sa(ff, Standard_True);
        GeomAbs_SurfaceType st = sa.GetType();

        // UV metric scale at the centre: |dS/du|, |dS/dv|.
        double su = 1.0, sv = 1.0;
        double umin = 0, umax = 0, vmin = 0, vmax = 0;
        try {
            BRepTools::UVBounds(ff, umin, umax, vmin, vmax);
            gp_Pnt p; gp_Vec du, dv;
            sa.D1(0.5 * (umin + umax), 0.5 * (vmin + vmax), p, du, dv);
            su = du.Magnitude(); sv = dv.Magnitude();
            if (!(su > 1e-12)) su = 1.0;
            if (!(sv > 1e-12)) sv = 1.0;
        } catch (...) {}

        // Interior (Steiner) points for curved faces: a UV grid with the
        // boundary's own 3D step, kept away from the boundary by half a step.
        std::vector<std::array<double, 5>> steiner;
        if (why.empty() && st != GeomAbs_Plane && !loops.empty()) {
            std::vector<double> seglen;
            std::vector<std::array<double, 4>> segs;  // scaled UV segments
            for (auto& L : loops) {
                for (size_t k = 0; k < L.size(); ++k) {
                    const LoopPt& a = L[k];
                    const LoopPt& b = L[(k + 1) % L.size()];
                    double len3 = verts[a.vid].Distance(verts[b.vid]);
                    if (len3 > 1e-12) seglen.push_back(len3);
                    segs.push_back({a.u * su, a.v * sv, b.u * su, b.v * sv});
                }
            }
            double h = 0.0;
            if (!seglen.empty()) {
                std::sort(seglen.begin(), seglen.end());
                h = seglen[seglen.size() / 2];
            }
            // A curved face also obeys the chord law across its interior.
            double rmin = 0.0;
            if (st == GeomAbs_Cylinder) rmin = sa.Cylinder().Radius();
            else if (st == GeomAbs_Sphere) rmin = sa.Sphere().Radius();
            else if (st == GeomAbs_Torus) rmin = sa.Torus().MinorRadius();
            if (rmin > tol) h = (h > 0.0) ? std::min(h, 2.0 * std::sqrt(2.0 * rmin * tol)) : 2.0 * std::sqrt(2.0 * rmin * tol);
            double U0 = umin * su, U1 = umax * su, V0 = vmin * sv, V1 = vmax * sv;
            if (h > 1e-12) {
                int nu = (int)std::floor((U1 - U0) / h), nv = (int)std::floor((V1 - V0) / h);
                if (nu >= 1 && nv >= 1 && (long long)nu * nv <= 200000) {
                    BRepTopAdaptor_FClass2d cls(ff, Precision::PConfusion());
                    double ou = 0.5 * ((U1 - U0) - nu * h), ov = 0.5 * ((V1 - V0) - nv * h);
                    double keep2 = (0.5 * h) * (0.5 * h);
                    for (int a = 0; a <= nu; ++a) {
                        for (int b = 0; b <= nv; ++b) {
                            double X = U0 + ou + a * h, Y = V0 + ov + b * h;
                            double u = X / su, v = Y / sv;
                            if (cls.Perform(gp_Pnt2d(u, v)) != TopAbs_IN) continue;
                            bool near = false;
                            for (auto& sg : segs) {
                                double dx = sg[2] - sg[0], dy = sg[3] - sg[1];
                                double L2 = dx * dx + dy * dy;
                                double t = L2 > 0 ? ((X - sg[0]) * dx + (Y - sg[1]) * dy) / L2 : 0.0;
                                t = std::max(0.0, std::min(1.0, t));
                                double ex = sg[0] + t * dx - X, ey = sg[1] + t * dy - Y;
                                if (ex * ex + ey * ey < keep2) { near = true; break; }
                            }
                            if (near) continue;
                            gp_Pnt p = sa.Value(u, v);
                            steiner.push_back({u, v, p.X(), p.Y(), p.Z()});
                        }
                    }
                }
            }
        }

        // centre for the legacy "Face:%d@x;y;z" id
        gp_Pnt c(0, 0, 0);
        try { c = sa.Value(0.5 * (umin + umax), 0.5 * (vmin + vmax)); } catch (...) {}

        if (!first_face) out += ",";
        first_face = false;
        out += "{\"i\":" + std::to_string(fi) + ",\"kind\":\"" + surface_kind(st) + "\",\"rev\":";
        out += rev ? "true" : "false";
        out += ",\"su\":"; jnum(out, su);
        out += ",\"sv\":"; jnum(out, sv);
        out += ",\"c\":["; jnum(out, c.X()); out += ","; jnum(out, c.Y()); out += ","; jnum(out, c.Z()); out += "]";
        if (!why.empty()) {
            out += ",\"error\":\"" + why + "\",\"loops\":[],\"steiner\":[]}";
            continue;
        }
        out += ",\"loops\":[";
        for (size_t li = 0; li < loops.size(); ++li) {
            if (li) out += ",";
            out += "[";
            for (size_t k = 0; k < loops[li].size(); ++k) {
                if (k) out += ",";
                out += "[" + std::to_string(loops[li][k].vid) + ",";
                jnum(out, loops[li][k].u); out += ",";
                jnum(out, loops[li][k].v); out += "]";
            }
            out += "]";
        }
        out += "],\"steiner\":[";
        for (size_t k = 0; k < steiner.size(); ++k) {
            if (k) out += ",";
            out += "[";
            for (int q = 0; q < 5; ++q) { if (q) out += ","; jnum(out, steiner[k][q]); }
            out += "]";
        }
        out += "]}";
    }

    out += "],\"verts\":[";
    for (size_t k = 0; k < verts.size(); ++k) {
        if (k) out += ",";
        jnum(out, verts[k].X()); out += ",";
        jnum(out, verts[k].Y()); out += ",";
        jnum(out, verts[k].Z());
    }
    out += "],\"n_cad_verts\":" + std::to_string(vm.Extent());
    out += ",\"n_edges\":" + std::to_string(em.Extent());
    out += ",\"n_edge_fail\":" + std::to_string(n_edge_fail) + "}";
    return out;
}

void quad_topology(void* stack_ptr, double tol, void* str_vec, PushStringFn ps) {
    try {
        std::string s = quad_topology_json(stack_ptr, tol);
        if (!s.empty()) ps(str_vec, s.c_str());
    } catch (...) {}
}

}  // namespace occ_core
