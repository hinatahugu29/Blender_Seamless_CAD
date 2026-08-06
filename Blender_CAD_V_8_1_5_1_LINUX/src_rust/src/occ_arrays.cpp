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

TopoDS_Shape apply_revolve(const TopoDS_Shape& b, const std::string& axis, double angle_deg, double x, double y, double z, double rx, double ry, double rz) {
    double a = angle_deg * 3.141592653589793 / 180.0; if (std::abs(a) < 1e-6) a = 2.0 * 3.141592653589793; gp_Dir d(0,0,1); std::string ax = axis; if (ax == "X") d = gp_Dir(1,0,0); else if (ax == "Y") d = gp_Dir(0,1,0);
    gp_Trsf r; gp_Quaternion q; q.SetEulerAngles(gp_Extrinsic_XYZ, rx, ry, rz); r.SetRotation(q); d.Transform(r);
    BRepPrimAPI_MakeRevol rv(b, gp_Ax1(gp_Pnt(x, y, z), d), a); if (rv.IsDone()) return rv.Shape();
    return TopoDS_Shape();
}

}
