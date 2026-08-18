#include "occ_common.hpp"
#include "occ_arrays.hpp"
#include "occ_utils.hpp"
#include "occ_core.hpp"
namespace occ_core {
// occ_arrays.cpp
#include <TopoDS_Compound.hxx>
#include <BRep_Builder.hxx>

TopoDS_Shape apply_mirror(const TopoDS_Shape& b, const std::string& axis, double x, double y, double z, double rx, double ry, double rz) {
    gp_Dir d(0,0,1); std::string ax = axis; if (ax == "X") d = gp_Dir(1,0,0); else if (ax == "Y") d = gp_Dir(0,1,0);
    gp_Trsf r; gp_Quaternion q; q.SetEulerAngles(gp_Extrinsic_XYZ, rx, ry, rz); r.SetRotation(q); d.Transform(r);
    gp_Trsf t; if (ax == "POINT") t.SetMirror(gp_Pnt(x, y, z)); else t.SetMirror(gp_Ax2(gp_Pnt(x, y, z), d));
    
    BRepBuilderAPI_Transform tr(b, t, Standard_False); // Copy=False for instancing
    if (tr.IsDone()) {
        TopoDS_Compound comp;
        BRep_Builder builder;
        builder.MakeCompound(comp);
        builder.Add(comp, b);
        builder.Add(comp, tr.Shape());
        return comp;
    }
    return b;
}

TopoDS_Shape apply_array_linear(const TopoDS_Shape& b, const std::string& axis, int count, double distance) {
    int n = count; double dist = distance; gp_Vec st(dist, 0, 0); std::string ax = axis; if (ax == "Y") st = gp_Vec(0, dist, 0); else if (ax == "Z") st = gp_Vec(0, 0, dist);
    
    TopoDS_Compound comp;
    BRep_Builder builder;
    builder.MakeCompound(comp);
    
    builder.Add(comp, b);

    for (int j = 1; j < n; ++j) { 
        gp_Trsf t; 
        t.SetTranslation(st * j); 
        BRepBuilderAPI_Transform tr(b, t, Standard_False); // Copy=False
        builder.Add(comp, tr.Shape());
    } 
    return comp;
}

TopoDS_Shape apply_array_circular(const TopoDS_Shape& b, const std::string& axis, int count, double angle_deg, double x, double y, double z, double rx, double ry, double rz) {
    int n = count; double ang = angle_deg * 3.141592653589793 / 180.0; gp_Dir d(0,0,1); std::string ax = axis; if (ax == "X") d = gp_Dir(1,0,0); else if (ax == "Y") d = gp_Dir(0,1,0);
    gp_Trsf r; gp_Quaternion q; q.SetEulerAngles(gp_Extrinsic_XYZ, rx, ry, rz); r.SetRotation(q); d.Transform(r);
    gp_Ax1 ra(gp_Pnt(x, y, z), d); 
    
    TopoDS_Compound comp;
    BRep_Builder builder;
    builder.MakeCompound(comp);
    
    builder.Add(comp, b);

    for (int j = 1; j < n; ++j) { 
        gp_Trsf t; 
        t.SetRotation(ra, (ang/n)*j); 
        BRepBuilderAPI_Transform tr(b, t, Standard_False); // Copy=False
        builder.Add(comp, tr.Shape());
    } 
    return comp;
}

// REVOLVE が回せる「プロファイル」を取り出す。
//
// BRepPrimAPI_MakeRevol は次元2までの形状しか回せない。ところが REVOLVE の
// ターゲットは uuid_to_shape 経由で渡ってくる **押し出し済み** の形状で、
// POLYGON / SLOT / SURFACE は occ_core.cpp の
//   if (|h| < 1e-5 && (POLYGON|SLOT|SURFACE)) h = 1e-4;
// によって必ず厚み 1e-4 の薄いソリッドにされている。つまりスケッチから作った
// 閉じたプロファイルを Rev に渡すと、常にソリッドが来て MakeRevol が成立せず、
// 「ターゲットの UUID は入るのに何も起きない」という症状になっていた
// (2026-08-18 の利用者報告)。
//
// そこでソリッド/シェルを渡されたら、面積が最大の平面フェイスをプロファイルとして
// 取り出す。薄い押し出しの場合これは元のプロファイル面そのもの(上下のキャップ)
// なので、利用者の意図どおりの回転体になる。
static TopoDS_Shape extract_revolvable_profile(const TopoDS_Shape& b) {
    if (b.IsNull()) return b;
    TopAbs_ShapeEnum st = b.ShapeType();
    if (st != TopAbs_SOLID && st != TopAbs_SHELL && st != TopAbs_COMPSOLID) return b;

    TopoDS_Face best; double best_area = 0.0;
    for (TopExp_Explorer exp(b, TopAbs_FACE); exp.More(); exp.Next()) {
        const TopoDS_Face& f = TopoDS::Face(exp.Current());
        // Geom_Plane への IsKind ではなく Adaptor で判定する。トリム面に包まれた
        // 平面を取りこぼさないため。
        BRepAdaptor_Surface ad(f, Standard_True);
        if (ad.GetType() != GeomAbs_Plane) continue;
        GProp_GProps gp_area;
        BRepGProp::SurfaceProperties(f, gp_area);
        double area = gp_area.Mass();
        if (area > best_area) { best_area = area; best = f; }
    }
    if (best.IsNull()) return TopoDS_Shape();
    log_debug("[REVOLVE] target was a solid; revolving its largest planar face (area=" + std::to_string(best_area) + ")");
    return best;
}

TopoDS_Shape apply_revolve(const TopoDS_Shape& b, const std::string& axis, double angle_deg, double x, double y, double z, double rx, double ry, double rz) {
    double a = angle_deg * 3.141592653589793 / 180.0; if (std::abs(a) < 1e-6) a = 2.0 * 3.141592653589793; gp_Dir d(0,0,1); std::string ax = axis; if (ax == "X") d = gp_Dir(1,0,0); else if (ax == "Y") d = gp_Dir(0,1,0);
    gp_Trsf r; gp_Quaternion q; q.SetEulerAngles(gp_Extrinsic_XYZ, rx, ry, rz); r.SetRotation(q); d.Transform(r);
    // 例外を握るのは apply_face_revolve に合わせた形。MakeRevol は回せない形状を
    // 渡されると IsDone() が false になるのではなく送出してくることがあり、
    // 素通しするとサーバごと落ちる。
    try {
        OCC_CATCH_SIGNALS
        TopoDS_Shape profile = extract_revolvable_profile(b);
        if (profile.IsNull()) return TopoDS_Shape();
        BRepPrimAPI_MakeRevol rv(profile, gp_Ax1(gp_Pnt(x, y, z), d), a); if (rv.IsDone()) return rv.Shape();
    } catch (Standard_Failure const& e) {
        log_debug(std::string("[REVOLVE] Standard_Failure: ") + e.GetMessageString());
    } catch (...) {
        log_debug("[REVOLVE] Unknown exception");
    }
    return TopoDS_Shape();
}

}
