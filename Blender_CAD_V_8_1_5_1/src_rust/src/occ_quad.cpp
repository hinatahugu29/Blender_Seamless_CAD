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
#include <GCPnts_AbscissaPoint.hxx>
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

// A full ring snaps UP to the next preferred count (4/8/12/16/24/32/48/64,
// then multiples of 16) when that is within +35% of the law; it never goes
// below the law, which would break the chord tolerance (a torus tube of
// r = 0.2 at tol 0.01 needs 10 spans: rounding down to 8 lost 11% volume).
int snap_ring(int n) {
    static const int pref[] = {4, 8, 12, 16, 24, 32, 48, 64};
    for (int c : pref)
        if (c >= n) return (c <= n * 1.35 + 1e-9) ? c : n;
    int c = ((n + 15) / 16) * 16;
    return (c <= n * 1.35 + 1e-9) ? c : n;
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

int polyline_spans(const std::vector<gp_Pnt>& P, double tol) {
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

int free_curve_spans(const BRepAdaptor_Curve& c, double tol) {
    std::vector<gp_Pnt> P;
    try {
        GCPnts_TangentialDeflection td(c, 0.05, std::max(tol * 0.05, 1e-9), 3);
        for (int i = 1; i <= td.NbPoints(); ++i) P.push_back(td.Value(i));
    } catch (...) {}
    return polyline_spans(P, tol);
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

// A ruled wall: a cylinder / cone face with ONE wire made of two rims joined
// by exactly two RULINGS (straight generators: u = const in the pcurve — the
// seam of a full wall, or a side line of a partial one). rim_a / rim_b are the
// edge indices of the two rims; first_a is the position (in wire order) of
// rim A's first edge, which Python turns into a loop index.
struct RuledFace {
    bool ok = false;
    std::vector<int> rim_a, rim_b, order;
    int first_a = -1;
};

RuledFace analyse_ruled(const TopoDS_Face& ff, const TopTools_IndexedMapOfShape& em) {
    RuledFace r;
    BRepAdaptor_Surface sa(ff, Standard_False);
    if (sa.GetType() != GeomAbs_Cylinder && sa.GetType() != GeomAbs_Cone) return r;
    int nw = 0;
    for (TopExp_Explorer wx(ff, TopAbs_WIRE); wx.More(); wx.Next()) ++nw;
    if (nw != 1) return r;
    TopoDS_Wire w = BRepTools::OuterWire(ff);
    if (w.IsNull()) return r;
    std::vector<int> eids;
    std::vector<bool> ruling;
    for (BRepTools_WireExplorer wx(w, ff); wx.More(); wx.Next()) {
        TopoDS_Edge e = wx.Current();
        if (BRep_Tool::Degenerated(e)) return r;      // a cone apex: not P1
        int ei = em.FindIndex(e);
        if (ei < 1) return r;
        double f, l;
        Handle(Geom2d_Curve) pc = BRep_Tool::CurveOnSurface(e, ff, f, l);
        if (pc.IsNull()) return r;
        gp_Pnt2d p0 = pc->Value(f), p1 = pc->Value(l);
        bool is_rule = false;
        if (BRepAdaptor_Curve(e).GetType() == GeomAbs_Line)
            is_rule = std::fabs(p1.X() - p0.X()) < 1e-7 && std::fabs(p1.Y() - p0.Y()) > 1e-9;
        eids.push_back(ei);
        ruling.push_back(is_rule);
    }
    int n = (int)eids.size(), nr = 0;
    for (bool b : ruling) nr += b ? 1 : 0;
    if (nr != 2 || n < 4) return r;
    // rotate so that position 0 is a ruling; then the two runs between rulings
    int r0 = 0;
    while (!ruling[r0]) ++r0;
    std::vector<int> run1, run2;
    int pos1 = -1;
    bool second = false;
    for (int k = 1; k < n; ++k) {
        int p = (r0 + k) % n;
        if (ruling[p]) { second = true; continue; }
        if (!second) { if (run1.empty()) pos1 = p; run1.push_back(eids[p]); }
        else run2.push_back(eids[p]);
    }
    if (run1.empty() || run2.empty()) return r;
    r.rim_a = run1;
    r.rim_b = run2;
    r.first_a = pos1;
    r.order = eids;
    r.ok = true;
    return r;
}

// A four-sided curved face: ONE wire whose UV boundary turns by more than 30
// degrees at exactly four junctions (a pole's degenerate edge counts as a
// side). sides[k] are the edge indices of side k in wire order; first is the
// wire position of side 0's first edge. mid_uv[k] is the UV midpoint of side k,
// used to measure the surface across the face when both opposite sides are
// poles (a sphere).
struct CoonsFace {
    bool ok = false;
    std::vector<int> sides[4];
    std::vector<int> order;
    int first = -1;
    gp_Pnt2d mid_uv[4];
};

CoonsFace analyse_coons(const TopoDS_Face& ff, const TopTools_IndexedMapOfShape& em, double su, double sv) {
    CoonsFace r;
    BRepAdaptor_Surface sa(ff, Standard_False);
    if (sa.GetType() == GeomAbs_Plane) return r;
    int nw = 0;
    for (TopExp_Explorer wx(ff, TopAbs_WIRE); wx.More(); wx.Next()) ++nw;
    if (nw != 1) return r;
    TopoDS_Wire w = BRepTools::OuterWire(ff);
    if (w.IsNull()) return r;
    std::vector<int> eids;
    std::vector<gp_Vec2d> t0, t1;           // UV tangent at start / end (walk direction)
    std::vector<gp_Pnt2d> mid;
    for (BRepTools_WireExplorer wx(w, ff); wx.More(); wx.Next()) {
        TopoDS_Edge e = wx.Current();
        int ei = em.FindIndex(e);
        if (ei < 1) return r;
        double f, l;
        Handle(Geom2d_Curve) pc = BRep_Tool::CurveOnSurface(e, ff, f, l);
        if (pc.IsNull()) return r;
        bool rv = (e.Orientation() == TopAbs_REVERSED);
        gp_Pnt2d p; gp_Vec2d da, db;
        pc->D1(f, p, da);
        pc->D1(l, p, db);
        if (rv) { gp_Vec2d tmp = da; da = -db; db = -tmp; }
        da.SetCoord(da.X() * su, da.Y() * sv);
        db.SetCoord(db.X() * su, db.Y() * sv);
        if (da.Magnitude() < 1e-14 || db.Magnitude() < 1e-14) return r;
        eids.push_back(ei);
        t0.push_back(da);
        t1.push_back(db);
        mid.push_back(pc->Value(0.5 * (f + l)));
    }
    int n = (int)eids.size();
    if (n < 4) return r;
    std::vector<int> corner;              // a corner BEFORE edge k
    for (int k = 0; k < n; ++k) {
        const gp_Vec2d& a = t1[(k + n - 1) % n];
        const gp_Vec2d& b = t0[k];
        double ang = std::fabs(a.Angle(b));
        if (ang > 30.0 * 3.14159265358979 / 180.0) corner.push_back(k);
    }
    if (corner.size() != 4) return r;
    for (int sd = 0; sd < 4; ++sd) {
        int a = corner[sd], b = corner[(sd + 1) % 4];
        int k = a;
        do { r.sides[sd].push_back(eids[k]); k = (k + 1) % n; } while (k != b);
        int m = (int)r.sides[sd].size();
        r.mid_uv[sd] = mid[(a + m / 2) % n];
    }
    r.first = corner[0];
    r.order = eids;
    r.ok = true;
    return r;
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

    // ── span law per edge ─────────────────────────────────────────────────
    std::vector<int> nspan(em.Extent() + 1, 1);
    std::vector<double> elen(em.Extent() + 1, 0.0);
    std::vector<char> degen(em.Extent() + 1, 0);
    for (int i = 1; i <= em.Extent(); ++i) {
        TopoDS_Edge e = TopoDS::Edge(em.FindKey(i));
        try {
            if (BRep_Tool::Degenerated(e)) { nspan[i] = 1; degen[i] = 1; continue; }
            nspan[i] = edge_spans(e, tol);
            BRepAdaptor_Curve c(e);
            elen[i] = GCPnts_AbscissaPoint::Length(c);
        } catch (...) {}
    }

    // ── P1: ruled walls (cylinder / cone) and their HARD rim equality ─────
    std::vector<RuledFace> ruled(fm.Extent() + 1);
    for (int fi = 1; fi <= fm.Extent(); ++fi) {
        TopoDS_Face ff = TopoDS::Face(fm.FindKey(fi).Oriented(TopAbs_FORWARD));
        try { ruled[fi] = analyse_ruled(ff, em); } catch (...) { ruled[fi] = RuledFace(); }
    }
    // ── holed planes: straight edges take the holes' density ─────────────────
    // A plate with a bolt hole has 1-span sides; the hole ring has many. A fill
    // between a 16-point ring and four bare corners can only fan long slivers.
    // So a straight edge of a holed plane is cut at the holes' own step
    // (length / step, at most 64). The extra points are shared with the face on
    // the other side like any edge sample, so the seam stays welded. Rulings of
    // a ruled wall are left alone — that wall needs them at 1 span.
    {
        std::vector<char> is_ruling(em.Extent() + 1, 0);
        for (int fi = 1; fi <= fm.Extent(); ++fi) {
            const RuledFace& r = ruled[fi];
            if (!r.ok) continue;
            for (int ei : r.order) {
                bool rim = std::find(r.rim_a.begin(), r.rim_a.end(), ei) != r.rim_a.end()
                        || std::find(r.rim_b.begin(), r.rim_b.end(), ei) != r.rim_b.end();
                if (!rim) is_ruling[ei] = 1;
            }
        }
        for (int fi = 1; fi <= fm.Extent(); ++fi) {
            TopoDS_Face ff = TopoDS::Face(fm.FindKey(fi).Oriented(TopAbs_FORWARD));
            try {
                if (BRepAdaptor_Surface(ff, Standard_False).GetType() != GeomAbs_Plane) continue;
                TopoDS_Wire outer = BRepTools::OuterWire(ff);
                if (outer.IsNull()) continue;
                double hl = 0.0; int hn = 0;
                std::vector<int> lines;
                int nw = 0;
                for (TopExp_Explorer wx(ff, TopAbs_WIRE); wx.More(); wx.Next()) {
                    ++nw;
                    TopoDS_Wire w = TopoDS::Wire(wx.Current());
                    bool inner = !w.IsSame(outer);
                    for (TopExp_Explorer ex(w, TopAbs_EDGE); ex.More(); ex.Next()) {
                        int ei = em.FindIndex(ex.Current());
                        if (ei < 1 || degen[ei]) continue;
                        bool is_line = BRepAdaptor_Curve(TopoDS::Edge(ex.Current())).GetType() == GeomAbs_Line;
                        if (is_line) lines.push_back(ei);
                        else if (inner) { hl += elen[ei]; hn += nspan[ei]; }
                    }
                }
                if (nw < 2 || hn == 0) continue;
                double step = hl / hn;
                if (!(step > 1e-9)) continue;
                for (int ei : lines) {
                    if (is_ruling[ei]) continue;
                    int want = (int)std::lround(elen[ei] / step);
                    want = std::max(1, std::min(64, want));
                    if (want > nspan[ei]) nspan[ei] = want;
                }
            } catch (...) {}
        }
    }

    // ── P2: four-sided curved faces (Coons) ─────────────────────────────────
    std::vector<CoonsFace> coons(fm.Extent() + 1);
    for (int fi = 1; fi <= fm.Extent(); ++fi) {
        if (ruled[fi].ok) continue;
        TopoDS_Face ff = TopoDS::Face(fm.FindKey(fi).Oriented(TopAbs_FORWARD));
        try {
            BRepAdaptor_Surface sa(ff, Standard_True);
            double u0, u1, v0, v1;
            BRepTools::UVBounds(ff, u0, u1, v0, v1);
            gp_Pnt p; gp_Vec du, dv;
            sa.D1(0.5 * (u0 + u1), 0.5 * (v0 + v1), p, du, dv);
            double su = du.Magnitude() > 1e-12 ? du.Magnitude() : 1.0;
            double sv = dv.Magnitude() > 1e-12 ? dv.Magnitude() : 1.0;
            coons[fi] = analyse_coons(ff, em, su, sv);
            if (!coons[fi].ok) continue;
            // a pair of POLE sides (a sphere): their count is the surface's own
            // demand along the midline between the two other sides
            for (int pr = 0; pr < 2; ++pr) {
                auto all_degen = [&](const std::vector<int>& sd) {
                    for (int ei : sd) if (!degen[ei]) return false;
                    return true;
                };
                if (!all_degen(coons[fi].sides[pr]) || !all_degen(coons[fi].sides[pr + 2])) continue;
                gp_Pnt2d a = coons[fi].mid_uv[pr + 1], b = coons[fi].mid_uv[(pr + 3) % 4];
                std::vector<gp_Pnt> P;
                for (int k = 0; k <= 128; ++k) {
                    double t = k / 128.0;
                    P.push_back(sa.Value(a.X() + t * (b.X() - a.X()), a.Y() + t * (b.Y() - a.Y())));
                }
                int nm = std::max(4, polyline_spans(P, tol));
                if (std::fabs(b.X() - a.X()) > 6.28 || std::fabs(b.Y() - a.Y()) > 6.28) nm = std::max(4, snap_ring(nm));
                nspan[coons[fi].sides[pr][0]] = nm;
                nspan[coons[fi].sides[pr + 2][0]] = nm;
            }
        } catch (...) { coons[fi] = CoonsFace(); }
    }

    // A rim may be shared by several walls (a stack of tubes), so iterate:
    // the lower rim RISES to the higher one (never goes down) until stable.
    // Coons sides follow the same rule, but SOFTLY: a pole side takes its
    // opposite's count, and two real sides meet only when the lower one need
    // not rise by more than max(2, half of the higher) -- otherwise the face
    // stays unsatisfied and falls back to the triangulation.
    for (int round = 0; round < 32; ++round) {
        bool moved = false;
        for (int fi = 1; fi <= fm.Extent(); ++fi) {
            const CoonsFace& cf = coons[fi];
            if (!cf.ok) continue;
            for (int pr = 0; pr < 2; ++pr) {
                const std::vector<int>& A = cf.sides[pr];
                const std::vector<int>& B = cf.sides[pr + 2];
                int sa = 0, sb = 0;
                bool da = true, db = true;
                for (int ei : A) { sa += nspan[ei]; da = da && degen[ei]; }
                for (int ei : B) { sb += nspan[ei]; db = db && degen[ei]; }
                if (sa == sb) continue;
                if (da != db) {
                    const std::vector<int>& pole = da ? A : B;
                    int target = da ? sb : sa;
                    int other = 0;
                    for (size_t k = 1; k < pole.size(); ++k) other += nspan[pole[k]];
                    nspan[pole[0]] = std::max(1, target - other);
                    moved = true;
                    continue;
                }
                int hi = std::max(sa, sb), lo = std::min(sa, sb);
                if (hi - lo > std::max(2, hi / 2)) continue;
                const std::vector<int>& low = (sa < sb) ? A : B;
                int best = low[0];
                for (int ei : low) if (elen[ei] > elen[best] + 1e-12) best = ei;
                nspan[best] = std::min(kMaxSpans, nspan[best] + (hi - lo));
                moved = true;
            }
        }
        for (int fi = 1; fi <= fm.Extent(); ++fi) {
            const RuledFace& r = ruled[fi];
            if (!r.ok) continue;
            int sa = 0, sb = 0;
            for (int ei : r.rim_a) sa += nspan[ei];
            for (int ei : r.rim_b) sb += nspan[ei];
            if (sa == sb) continue;
            const std::vector<int>& low = (sa < sb) ? r.rim_a : r.rim_b;
            int need = std::abs(sa - sb);
            // add to the longest edge of the lower rim (deterministic: first max)
            int best = low[0];
            for (int ei : low) if (elen[ei] > elen[best] + 1e-12) best = ei;
            nspan[best] = std::min(kMaxSpans, nspan[best] + need);
            moved = true;
        }
        if (!moved) break;
    }

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
                int nd = std::max(1, nspan[i]);
                for (int k = 0; k <= nd; ++k) {
                    s.params.push_back(f + (l - f) * k / nd);
                    s.vids.push_back(i0);
                }
                s.ok = true;
                continue;
            }
            int n = nspan[i];
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
        if (why.empty() && coons[fi].ok && loops.size() == 1) {
            const CoonsFace& cf = coons[fi];
            int cnt[4] = {0, 0, 0, 0};
            for (int sd = 0; sd < 4; ++sd)
                for (int ei : cf.sides[sd]) cnt[sd] += (int)es[ei].params.size() - 1;
            int nn = cnt[0], mm = cnt[1];
            const std::vector<LoopPt>& L = loops[0];
            int M = (int)L.size();
            if (cnt[2] == nn && cnt[3] == mm && nn >= 1 && mm >= 1 && M == 2 * (nn + mm)) {
                int rs = 0;
                for (int k = 0; k < cf.first; ++k) rs += (int)es[cf.order[k]].params.size() - 1;
                auto at = [&](int k) -> const LoopPt& { return L[((rs + k) % M + M) % M]; };
                // boundary in UV, grid G[i][j]: i along side 0, j along side 1
                auto B0 = [&](int i) { return at(i); };                       // (i, 0)
                auto B1 = [&](int j) { return at(nn + j); };                  // (nn, j)
                auto B2 = [&](int i) { return at(nn + mm + (nn - i)); };      // (i, mm)
                auto B3 = [&](int j) { return at(2 * nn + mm + (mm - j)); };  // (0, j)
                double area = 0.0;
                for (int k = 0; k < M; ++k) {
                    const LoopPt& a = L[k]; const LoopPt& b = L[(k + 1) % M];
                    area += (a.u * su) * (b.v * sv) - (b.u * su) * (a.v * sv);
                }
                std::vector<double> gu((nn + 1) * (mm + 1)), gv((nn + 1) * (mm + 1));
                for (int i = 0; i <= nn; ++i) {
                    for (int j = 0; j <= mm; ++j) {
                        double s_ = (double)i / nn, t_ = (double)j / mm;
                        double u, v;
                        if (j == 0) { u = B0(i).u; v = B0(i).v; }
                        else if (j == mm) { u = B2(i).u; v = B2(i).v; }
                        else if (i == 0) { u = B3(j).u; v = B3(j).v; }
                        else if (i == nn) { u = B1(j).u; v = B1(j).v; }
                        else {
                            u = (1 - t_) * B0(i).u + t_ * B2(i).u + (1 - s_) * B3(j).u + s_ * B1(j).u
                              - ((1 - s_) * (1 - t_) * B0(0).u + s_ * (1 - t_) * B0(nn).u
                                 + (1 - s_) * t_ * B2(0).u + s_ * t_ * B2(nn).u);
                            v = (1 - t_) * B0(i).v + t_ * B2(i).v + (1 - s_) * B3(j).v + s_ * B1(j).v
                              - ((1 - s_) * (1 - t_) * B0(0).v + s_ * (1 - t_) * B0(nn).v
                                 + (1 - s_) * t_ * B2(0).v + s_ * t_ * B2(nn).v);
                        }
                        gu[i * (mm + 1) + j] = u;
                        gv[i * (mm + 1) + j] = v;
                    }
                }
                // quality gate: every UV cell keeps the loop's winding
                bool good = true;
                for (int i = 0; i < nn && good; ++i) {
                    for (int j = 0; j < mm && good; ++j) {
                        int c[4] = {i * (mm + 1) + j, (i + 1) * (mm + 1) + j,
                                    (i + 1) * (mm + 1) + j + 1, i * (mm + 1) + j + 1};
                        double a2 = 0.0;
                        for (int q = 0; q < 4; ++q) {
                            int x = c[q], y = c[(q + 1) % 4];
                            a2 += (gu[x] * su) * (gv[y] * sv) - (gu[y] * su) * (gv[x] * sv);
                        }
                        // a cell on a pole side collapses to a triangle: zero is fine
                        if (a2 * area < -1e-18) good = false;
                    }
                }
                if (good) {
                    out += ",\"coons\":{\"n\":" + std::to_string(nn) + ",\"m\":" + std::to_string(mm)
                         + ",\"start\":" + std::to_string(rs) + ",\"pts\":[";
                    bool fp = true;
                    for (int i = 1; i < nn; ++i) {
                        for (int j = 1; j < mm; ++j) {
                            gp_Pnt q = sa.Value(gu[i * (mm + 1) + j], gv[i * (mm + 1) + j]);
                            if (!fp) out += ",";
                            fp = false;
                            jnum(out, q.X()); out += ","; jnum(out, q.Y()); out += ","; jnum(out, q.Z());
                        }
                    }
                    out += "],\"uv\":[";   // the same interior points in (u, v)
                    fp = true;
                    for (int i = 1; i < nn; ++i) {
                        for (int j = 1; j < mm; ++j) {
                            if (!fp) out += ",";
                            fp = false;
                            jnum(out, gu[i * (mm + 1) + j]); out += ","; jnum(out, gv[i * (mm + 1) + j]);
                        }
                    }
                    out += "]}";
                }
            }
        }
        if (why.empty() && ruled[fi].ok) {
            // loop index where rim A starts = points contributed by the edges
            // before it in wire order (an edge of n spans gives n points)
            int rs = 0;
            for (int k = 0; k < ruled[fi].first_a; ++k) rs += (int)es[ruled[fi].order[k]].params.size() - 1;
            out += ",\"ruled\":" + std::to_string(rs);
        }
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
