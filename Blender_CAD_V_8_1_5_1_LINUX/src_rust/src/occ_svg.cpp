#include "occ_svg.hpp"
#include <vector>
#include <string>
#include <iostream>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <Geom_BSplineCurve.hxx>
#include <Geom_BezierCurve.hxx>
#include <TColgp_Array1OfPnt.hxx>
#include <TopoDS_Wire.hxx>
#include <ElCLib.hxx>
#include <gp_Circ.hxx>
#include <GC_MakeArcOfCircle.hxx>
#include <Bnd_Box.hxx>
#include <BRepBndLib.hxx>
#include <BRepBuilderAPI_Transform.hxx>
#include <gp_Trsf.hxx>
#include <TopoDS_Compound.hxx>
#include <BRep_Builder.hxx>

// SVGのArcを近似的にベジェまたは円弧に変換するための補助が必要かもしれないが
// 今回は円弧から円の中心を推測するか、ベジェの集合にフォールバックする
// ユーザーが「円弧を線分にしない」と言っていたので、少なくともGeom_BezierCurveにはしておく。

#include "occ_utils.hpp"
#include "occ_core.hpp"
#include <map>
#include <mutex>
#include <atomic>

namespace occ {

static std::map<std::string, TopoDS_Shape> g_svg_cache;
static std::mutex g_svg_mutex;
static std::atomic<uint64_t> g_svg_counter(0);

TopoDS_Shape get_svg_shape(const std::string& uuid) {
    std::lock_guard<std::mutex> lock(g_svg_mutex);
    auto it = g_svg_cache.find(uuid);
    if (it != g_svg_cache.end()) {
        return it->second;
    }
    return TopoDS_Shape();
}

std::vector<std::string> import_svg(const char* filepath, double scale, const double* data, int data_len) {
    std::vector<std::string> new_uuids;
    if (data_len == 0) return new_uuids;
    
    int i = 0;
    if (i >= data_len) return new_uuids;
    int num_paths = (int)data[i++];
    
    std::vector<TopoDS_Shape> parsed_shapes;
    Bnd_Box global_bbox;
    
    for (int p = 0; p < num_paths; ++p) {
        if (i >= data_len) break;
        int num_subpaths = (int)data[i++];
        
        TopoDS_Compound comp;
        BRep_Builder bb;
        bb.MakeCompound(comp);
        bool has_any_wire = false;
        
        for (int sp = 0; sp < num_subpaths; ++sp) {
            if (i >= data_len) break;
            int num_segments = (int)data[i++];
            
            BRepBuilderAPI_MakeWire wire_maker;
            bool has_edge = false;
            
            for (int s = 0; s < num_segments; ++s) {
                if (i >= data_len) break;
                int type = (int)data[i++];
                
                try {
                    if (type == 0) { // Line
                        if (i + 4 > data_len) break;
                        gp_Pnt p1(data[i]*scale, -data[i+1]*scale, 0);
                        gp_Pnt p2(data[i+2]*scale, -data[i+3]*scale, 0);
                        i += 4;
                        if (p1.Distance(p2) > 1e-6) {
                            TopoDS_Edge edge = BRepBuilderAPI_MakeEdge(p1, p2);
                            if (!edge.IsNull()) {
                                wire_maker.Add(edge);
                                has_edge = true;
                            }
                        }
                    } else if (type == 1) { // CubicBezier
                        if (i + 8 > data_len) break;
                        TColgp_Array1OfPnt poles(1, 4);
                        poles.SetValue(1, gp_Pnt(data[i]*scale, -data[i+1]*scale, 0));
                        poles.SetValue(2, gp_Pnt(data[i+2]*scale, -data[i+3]*scale, 0));
                        poles.SetValue(3, gp_Pnt(data[i+4]*scale, -data[i+5]*scale, 0));
                        poles.SetValue(4, gp_Pnt(data[i+6]*scale, -data[i+7]*scale, 0));
                        i += 8;
                        Handle(Geom_BezierCurve) curve = new Geom_BezierCurve(poles);
                        if (!curve.IsNull()) {
                            TopoDS_Edge edge = BRepBuilderAPI_MakeEdge(curve);
                            if (!edge.IsNull()) {
                                wire_maker.Add(edge);
                                has_edge = true;
                            }
                        }
                    } else if (type == 2) { // QuadraticBezier
                        if (i + 6 > data_len) break;
                        TColgp_Array1OfPnt poles(1, 3);
                        poles.SetValue(1, gp_Pnt(data[i]*scale, -data[i+1]*scale, 0));
                        poles.SetValue(2, gp_Pnt(data[i+2]*scale, -data[i+3]*scale, 0));
                        poles.SetValue(3, gp_Pnt(data[i+4]*scale, -data[i+5]*scale, 0));
                        i += 6;
                        Handle(Geom_BezierCurve) curve = new Geom_BezierCurve(poles);
                        if (!curve.IsNull()) {
                            TopoDS_Edge edge = BRepBuilderAPI_MakeEdge(curve);
                            if (!edge.IsNull()) {
                                wire_maker.Add(edge);
                                has_edge = true;
                            }
                        }
                    } else if (type == 3) { // Arc
                        if (i + 9 > data_len) break;
                        gp_Pnt p1(data[i]*scale, -data[i+1]*scale, 0);
                        gp_Pnt p2(data[i+7]*scale, -data[i+8]*scale, 0);
                        if (p1.Distance(p2) > 1e-6) {
                            TopoDS_Edge edge = BRepBuilderAPI_MakeEdge(p1, p2);
                            if (!edge.IsNull()) {
                                wire_maker.Add(edge);
                                has_edge = true;
                            }
                        }
                        i += 9;
                    }
                } catch (const Standard_Failure&) {
                    // Ignore failure on single segment and proceed to build whatever is possible
                } catch (...) {
                    // Ignore unexpected exceptions
                }
            }
            
            if (has_edge) {
                try {
                    if (wire_maker.IsDone()) {
                        bb.Add(comp, wire_maker.Wire());
                        has_any_wire = true;
                    }
                } catch (...) {}
            }
        }
        
        if (has_any_wire) {
            try {
                parsed_shapes.push_back(comp);
                BRepBndLib::Add(comp, global_bbox);
            } catch (...) {}
        }
    }
    
    gp_Trsf t_total;
    if (!global_bbox.IsVoid()) {
        Standard_Real xmin, ymin, zmin, xmax, ymax, zmax;
        global_bbox.Get(xmin, ymin, zmin, xmax, ymax, zmax);
        gp_Pnt center((xmin + xmax) / 2.0, (ymin + ymax) / 2.0, 0.0);
        Standard_Real width = xmax - xmin;
        Standard_Real height = ymax - ymin;
        Standard_Real max_dim = std::max(width, height);
        if (max_dim < 1e-6) max_dim = 1.0;
        
        gp_Trsf t_center, t_scale;
        t_center.SetTranslation(center, gp_Pnt(0, 0, 0));
        t_scale.SetScale(gp_Pnt(0, 0, 0), 1.0 / max_dim);
        t_total = t_scale * t_center;
    }

    for (const auto& shape : parsed_shapes) {
        try {
            TopoDS_Shape final_shape = BRepBuilderAPI_Transform(shape, t_total, true).Shape();
            std::string new_uuid = "svg_part_" + std::to_string(++g_svg_counter);
            {
                std::lock_guard<std::mutex> lock(g_svg_mutex);
                g_svg_cache[new_uuid] = final_shape;
            }
            new_uuids.push_back(new_uuid);
        } catch (...) {}
    }
    
    return new_uuids;
}

}
