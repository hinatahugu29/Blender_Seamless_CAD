#include "occ_common.hpp"
#include "occ_mesh.hpp"
#include "occ_utils.hpp"
#include "occ_core.hpp"
#include <map>
#include <tuple>
#include <cmath>
#include <vector>
namespace occ_core {
// occ_mesh.cpp

void get_face_mesh(void* stack_ptr, int i, double deflection, void* verts_vec, void* tris_vec, void* f_ids_vec, void* f_t_counts_vec, PushPointFn pp, PushCountFn pc, PushStringFn ps) {
    CADStack* stack = static_cast<CADStack*>(stack_ptr);
    if (!stack) return;
    // std::lock_guard<std::mutex> lock(g_occ_mutex);
    TopTools_IndexedMapOfShape fm; TopExp::MapShapes(stack->current_shape, TopAbs_FACE, fm);
    if (i < 1 || i > fm.Extent()) return;
    TopoDS_Face f = TopoDS::Face(fm.FindKey(i));
    TopLoc_Location lo; Handle(Poly_Triangulation) tr = BRep_Tool::Triangulation(f, lo);
    if (tr.IsNull()) {
        return;
    }

    gp_Pnt c; 
    TopLoc_Location L_surf; Handle(Geom_Surface) S = BRep_Tool::Surface(f, L_surf);
    if (!S.IsNull()) {
        double u1, u2, v1, v2; BRepTools::UVBounds(f, u1, u2, v1, v2);
        S->D0((u1+u2)/2.0, (v1+v2)/2.0, c); c.Transform(L_surf.Transformation());
    } else {
        GProp_GProps gp; BRepGProp::SurfaceProperties(f, gp);
        if (gp.Mass() > 1e-6) c = gp.CentreOfMass(); else { TopExp_Explorer ev(f, TopAbs_VERTEX); if (ev.More()) c = BRep_Tool::Pnt(TopoDS::Vertex(ev.Current())); else c = gp_Pnt(0,0,0); }
    }
    char buf[256]; snprintf(buf, sizeof(buf), "Face:%d@%.3f;%.3f;%.3f", i, c.X(), c.Y(), c.Z()); ps(f_ids_vec, buf);
    
    pc(f_t_counts_vec, tr->NbTriangles() * 3);
    gp_Trsf tf = lo.Transformation();
    for (int j = 1; j <= tr->NbNodes(); ++j) { gp_Pnt pt = tr->Node(j).Transformed(tf); pp(verts_vec, (float)pt.X(), (float)pt.Y(), (float)pt.Z()); }
    for (int j = 1; j <= tr->NbTriangles(); ++j) {
        int n1, n2, n3;
        tr->Triangle(j).Get(n1, n2, n3);
        if (f.Orientation() == TopAbs_REVERSED) {
            pc(tris_vec, n3 - 1); pc(tris_vec, n2 - 1); pc(tris_vec, n1 - 1);
        }
    }
}

void generate_full_mesh(void* stack_ptr, double deflection, double angular_deflection, bool fast_mode, void* verts_vec, void* tris_vec, void* f_ids_vec, void* f_t_counts_vec, PushPointFn pp, PushCountFn pc, PushStringFn ps) {
    CADStack* stack = static_cast<CADStack*>(stack_ptr);
    if (!stack || stack->current_shape.IsNull()) return;

    try {
        BRepTools::Clean(stack->current_shape);
        BRepMesh_IncrementalMesh mesh(stack->current_shape, deflection, Standard_False, angular_deflection, Standard_True);
        
        TopTools_IndexedMapOfShape fm; TopExp::MapShapes(stack->current_shape, TopAbs_FACE, fm);

        if (fast_mode) {
            int vertex_offset = 0;
            for (int i = 1; i <= fm.Extent(); ++i) {
                TopoDS_Face f = TopoDS::Face(fm.FindKey(i));
                TopLoc_Location lo; Handle(Poly_Triangulation) tr = BRep_Tool::Triangulation(f, lo);
                
                if (tr.IsNull()) {
                    // Fallback for complex surfaces (e.g., Torus/Sphere fragments) that failed standard meshing
                    try {
                        BRepMesh_IncrementalMesh fallback_mesh(f, deflection * 0.5, Standard_True, angular_deflection * 0.5, Standard_False);
                        tr = BRep_Tool::Triangulation(f, lo);
                    } catch (...) {}
                }

                if (tr.IsNull()) {
                    try {
                        BRepMesh_IncrementalMesh fallback_mesh2(f, deflection * 0.1, Standard_True, angular_deflection * 0.1, Standard_False);
                        tr = BRep_Tool::Triangulation(f, lo);
                    } catch (...) {}
                }

                if (tr.IsNull() || tr->NbNodes() == 0) continue;

                gp_Trsf tf = lo.Transformation();
                gp_Pnt c;
                if (tr->NbNodes() > 0) {
                    c = tr->Node(1).Transformed(tf);
                } else {
                    TopLoc_Location L_surf; Handle(Geom_Surface) S = BRep_Tool::Surface(f, L_surf);
                    if (!S.IsNull()) {
                        double u1, u2, v1, v2; BRepTools::UVBounds(f, u1, u2, v1, v2);
                        S->D0((u1+u2)/2.0, (v1+v2)/2.0, c); c.Transform(L_surf.Transformation());
                    } else {
                        GProp_GProps gp; BRepGProp::SurfaceProperties(f, gp);
                        if (gp.Mass() > 1e-6) c = gp.CentreOfMass(); else { TopExp_Explorer ev(f, TopAbs_VERTEX); if (ev.More()) c = BRep_Tool::Pnt(TopoDS::Vertex(ev.Current())); else c = gp_Pnt(0,0,0); }
                    }
                }

                char buf[256]; snprintf(buf, sizeof(buf), "Face:%d@%.3f;%.3f;%.3f", i, c.X(), c.Y(), c.Z());
                ps(f_ids_vec, buf);
                pc(f_t_counts_vec, tr->NbTriangles() * 3);

                for (int j = 1; j <= tr->NbNodes(); ++j) {
                    gp_Pnt pt = tr->Node(j).Transformed(tf);
                    pp(verts_vec, (float)pt.X(), (float)pt.Y(), (float)pt.Z());
                }

                for (int j = 1; j <= tr->NbTriangles(); ++j) {
                    int n1, n2, n3;
                    tr->Triangle(j).Get(n1, n2, n3);
                    if (f.Orientation() == TopAbs_REVERSED) {
                        pc(tris_vec, vertex_offset + n3 - 1); pc(tris_vec, vertex_offset + n2 - 1); pc(tris_vec, vertex_offset + n1 - 1);
                    } else {
                        pc(tris_vec, vertex_offset + n1 - 1); pc(tris_vec, vertex_offset + n2 - 1); pc(tris_vec, vertex_offset + n3 - 1);
                    }
                }

                vertex_offset += tr->NbNodes();
            }
            return;
        }

        std::map<std::tuple<int, int, int>, int> vertex_map;
        std::vector<gp_Pnt> unique_verts;
        double precision = 10000.0;
        
        for (int i = 1; i <= fm.Extent(); ++i) {
            TopoDS_Face f = TopoDS::Face(fm.FindKey(i));
            TopLoc_Location lo; Handle(Poly_Triangulation) tr = BRep_Tool::Triangulation(f, lo);
            
            if (tr.IsNull()) {
                // Fallback for complex surfaces (e.g., Torus/Sphere fragments) that failed standard meshing
                try {
                    BRepMesh_IncrementalMesh fallback_mesh(f, deflection * 0.5, Standard_True, angular_deflection * 0.5, Standard_False);
                    tr = BRep_Tool::Triangulation(f, lo);
                } catch (...) {}
            }

            if (tr.IsNull()) {
                // If still null, try one more time with extreme settings
                try {
                    BRepMesh_IncrementalMesh fallback_mesh2(f, deflection * 0.1, Standard_True, angular_deflection * 0.1, Standard_False);
                    tr = BRep_Tool::Triangulation(f, lo);
                } catch (...) {}
            }

            if (tr.IsNull()) continue;

            gp_Pnt c; 
            TopLoc_Location L_surf; Handle(Geom_Surface) S = BRep_Tool::Surface(f, L_surf);
            if (!S.IsNull()) {
                double u1, u2, v1, v2; BRepTools::UVBounds(f, u1, u2, v1, v2);
                S->D0((u1+u2)/2.0, (v1+v2)/2.0, c); c.Transform(L_surf.Transformation());
            } else {
                GProp_GProps gp; BRepGProp::SurfaceProperties(f, gp);
                if (gp.Mass() > 1e-6) c = gp.CentreOfMass(); else { TopExp_Explorer ev(f, TopAbs_VERTEX); if (ev.More()) c = BRep_Tool::Pnt(TopoDS::Vertex(ev.Current())); else c = gp_Pnt(0,0,0); }
            }
            char buf[256]; snprintf(buf, sizeof(buf), "Face:%d@%.3f;%.3f;%.3f", i, c.X(), c.Y(), c.Z()); 
            ps(f_ids_vec, buf);
            
            pc(f_t_counts_vec, tr->NbTriangles() * 3);
            gp_Trsf tf = lo.Transformation();
            
            std::vector<int> index_remap;
            index_remap.reserve(tr->NbNodes() + 1);
            index_remap.push_back(0); // 1-based indexing padding
            
            for (int j = 1; j <= tr->NbNodes(); ++j) { 
                gp_Pnt pt = tr->Node(j).Transformed(tf); 
                int kx = (int)std::round(pt.X() * precision);
                int ky = (int)std::round(pt.Y() * precision);
                int kz = (int)std::round(pt.Z() * precision);
                auto key = std::make_tuple(kx, ky, kz);
                
                auto it = vertex_map.find(key);
                if (it == vertex_map.end()) {
                    int new_idx = (int)unique_verts.size();
                    unique_verts.push_back(pt);
                    vertex_map[key] = new_idx;
                    index_remap.push_back(new_idx);
                } else {
                    index_remap.push_back(it->second);
                }
            }
            
            for (int j = 1; j <= tr->NbTriangles(); ++j) {
                int n1, n2, n3;
                tr->Triangle(j).Get(n1, n2, n3);
                if (f.Orientation() == TopAbs_REVERSED) {
                    pc(tris_vec, index_remap[n3]); pc(tris_vec, index_remap[n2]); pc(tris_vec, index_remap[n1]);
                } else {
                    pc(tris_vec, index_remap[n1]); pc(tris_vec, index_remap[n2]); pc(tris_vec, index_remap[n3]);
                }
            }
        }
        
        for (const auto& pt : unique_verts) {
            pp(verts_vec, (float)pt.X(), (float)pt.Y(), (float)pt.Z());
        }
    } catch (...) {}
}

// Tessellate an arbitrary shape into a single welded (verts, tris) mesh.
// Reuses the standard BRepMesh path; vertices are globally deduplicated so the
// output is suitable as CSG input.
static void mesh_shape_welded(const TopoDS_Shape& shape, double deflection, double angular_deflection,
    void* verts_vec, void* tris_vec, PushPointFn pp, PushCountFn pc) {
    if (shape.IsNull()) return;
    try {
        BRepTools::Clean(shape);
        BRepMesh_IncrementalMesh mesh(shape, deflection, Standard_False, angular_deflection, Standard_True);

        std::map<std::tuple<int, int, int>, int> vertex_map;
        std::vector<gp_Pnt> unique_verts;
        double precision = 10000.0;

        TopTools_IndexedMapOfShape fm; TopExp::MapShapes(shape, TopAbs_FACE, fm);
        for (int i = 1; i <= fm.Extent(); ++i) {
            TopoDS_Face f = TopoDS::Face(fm.FindKey(i));
            TopLoc_Location lo; Handle(Poly_Triangulation) tr = BRep_Tool::Triangulation(f, lo);
            if (tr.IsNull()) continue;
            gp_Trsf tf = lo.Transformation();
            std::vector<int> index_remap;
            index_remap.reserve(tr->NbNodes() + 1);
            index_remap.push_back(0);
            for (int j = 1; j <= tr->NbNodes(); ++j) {
                gp_Pnt pt = tr->Node(j).Transformed(tf);
                int kx = (int)std::round(pt.X() * precision);
                int ky = (int)std::round(pt.Y() * precision);
                int kz = (int)std::round(pt.Z() * precision);
                auto key = std::make_tuple(kx, ky, kz);
                auto it = vertex_map.find(key);
                if (it == vertex_map.end()) {
                    int new_idx = (int)unique_verts.size();
                    unique_verts.push_back(pt);
                    vertex_map[key] = new_idx;
                    index_remap.push_back(new_idx);
                } else {
                    index_remap.push_back(it->second);
                }
            }
            for (int j = 1; j <= tr->NbTriangles(); ++j) {
                int n1, n2, n3;
                tr->Triangle(j).Get(n1, n2, n3);
                if (f.Orientation() == TopAbs_REVERSED) {
                    pc(tris_vec, index_remap[n3]); pc(tris_vec, index_remap[n2]); pc(tris_vec, index_remap[n1]);
                } else {
                    pc(tris_vec, index_remap[n1]); pc(tris_vec, index_remap[n2]); pc(tris_vec, index_remap[n3]);
                }
            }
        }
        for (const auto& pt : unique_verts) {
            pp(verts_vec, (float)pt.X(), (float)pt.Y(), (float)pt.Z());
        }
    } catch (...) {}
}

bool tessellate_preview_meshes(void* stack_ptr, int tool_index, const char* tool_uuid,
    double deflection, double angular_deflection,
    void* base_v, void* base_t, void* tool_v, void* tool_t,
    PushPointFn pp, PushCountFn pc) {
    CADStack* stack = static_cast<CADStack*>(stack_ptr);
    if (!stack) return false;
    try {
        // BASE = compound of the clusters just before the tool (result before the tool).
        int base_idx = tool_index - 1;
        if (base_idx < 0 || base_idx >= (int)stack->stack_results.size()) return false;
        BRep_Builder bb; TopoDS_Compound comp; bb.MakeCompound(comp);
        bool any = false;
        for (auto& c : stack->stack_results[base_idx].clusters) {
            if (!c.raw.IsNull()) { bb.Add(comp, c.raw); any = true; }
        }
        if (!any) return false;
        mesh_shape_welded(comp, deflection, angular_deflection, base_v, base_t, pp, pc);

        // TOOL = world-space tool shape at drag start (uuid_to_shape from last result).
        if (stack->stack_results.empty()) return false;
        std::string uuid_str(tool_uuid ? tool_uuid : "");
        const auto& u2s = stack->stack_results.back().uuid_to_shape;
        auto it = u2s.find(uuid_str);
        if (it == u2s.end() || it->second.IsNull()) return false;
        mesh_shape_welded(it->second, deflection, angular_deflection, tool_v, tool_t, pp, pc);
        return true;
    } catch (...) {
        return false;
    }
}

void generate_mesh(void* stack_ptr, double d, double ang_d, void* vv, void* tv, void* fiv, void* ftv, void* nv, PushPointFn pp, PushCountFn pc, PushStringFn ps) {
    CADStack* stack = static_cast<CADStack*>(stack_ptr);
    if (!stack) return;
    // std::lock_guard<std::mutex> lock(g_occ_mutex);
    if (stack->current_shape.IsNull()) return;
    BRepTools::Clean(stack->current_shape); // Restored for fundamental avoidance of cache corruption on Cone/Torus
    BRepMesh_IncrementalMesh(stack->current_shape, d, Standard_False, ang_d, Standard_True);
}

void make_variable_box_mesh(
    double tw, double th, 
    double bw, double bh, 
    double h, 
    double deflection,
    void* verts_vec, void* tris_vec, void* normals_vec,
    PushPointFn push_point, PushCountFn push_count
) {
    // std::lock_guard<std::mutex> lock(g_occ_mutex);
    try {
        if (std::abs(h) < 1e-6) h = 0.001;
        if (tw < 1e-6) tw = 0.001; if (th < 1e-6) th = 0.001;
        if (bw < 1e-6) bw = 0.001; if (bh < 1e-6) bh = 0.001;

        auto make_rect = [&](double w, double h_val, double z) {
            BRepBuilderAPI_MakeWire wire;
            gp_Pnt p1(-w/2, -h_val/2, z), p2(w/2, -h_val/2, z), p3(w/2, h_val/2, z), p4(-w/2, h_val/2, z);
            wire.Add(BRepBuilderAPI_MakeEdge(p1, p2).Edge());
            wire.Add(BRepBuilderAPI_MakeEdge(p2, p3).Edge());
            wire.Add(BRepBuilderAPI_MakeEdge(p3, p4).Edge());
            wire.Add(BRepBuilderAPI_MakeEdge(p4, p1).Edge());
            return wire.Wire();
        };

        TopoDS_Wire w1 = make_rect(tw, th, h/2);
        TopoDS_Wire w2 = make_rect(bw, bh, -h/2);

        BRepOffsetAPI_ThruSections loft(Standard_True, Standard_True);
        loft.AddWire(w1);
        loft.AddWire(w2);
        loft.Build();

        if (loft.IsDone()) {
            TopoDS_Shape shape = loft.Shape();
            BRepMesh_IncrementalMesh(shape, deflection);
            
            TopExp_Explorer ex(shape, TopAbs_FACE);
            int global_tris_count = 0;
            while (ex.More()) {
                TopoDS_Face f = TopoDS::Face(ex.Current());
                TopLoc_Location lo;
                Handle(Poly_Triangulation) tr = BRep_Tool::Triangulation(f, lo);
                if (!tr.IsNull()) {
                    gp_Trsf tf = lo.Transformation();
                    int node_offset = global_tris_count; // This is not correct for nodes, nodes are face-local
                    // Wait, generate_mesh usually handles this. Let's just collect all nodes and adjust tris.
                    // Actually, for a single preview shape, we can just push everything.
                    
                    // Simple mesh collection
                    int start_node_idx = 0; // We need to track total nodes pushed so far for index offsetting
                    // I'll use a simpler approach for the preview: just one combined mesh
                }
                ex.Next();
            }
            
            // Re-implementing a simple mesh collector here
            std::vector<gp_Pnt> all_nodes;
            std::vector<int> all_tris;
            TopExp_Explorer ex2(shape, TopAbs_FACE);
            while (ex2.More()) {
                TopoDS_Face f = TopoDS::Face(ex2.Current());
                TopLoc_Location lo;
                Handle(Poly_Triangulation) tr = BRep_Tool::Triangulation(f, lo);
                if (!tr.IsNull()) {
                    gp_Trsf tf = lo.Transformation();
                    int base = (int)all_nodes.size();
                    for (int j = 1; j <= tr->NbNodes(); ++j) {
                        all_nodes.push_back(tr->Node(j).Transformed(tf));
                    }
                    for (int j = 1; j <= tr->NbTriangles(); ++j) {
                        int n1, n2, n3;
                        tr->Triangle(j).Get(n1, n2, n3);
                        if (f.Orientation() == TopAbs_REVERSED) {
                            all_tris.push_back(base + n3 - 1);
                            all_tris.push_back(base + n2 - 1);
                            all_tris.push_back(base + n1 - 1);
                        } else {
                            all_tris.push_back(base + n1 - 1);
                            all_tris.push_back(base + n2 - 1);
                            all_tris.push_back(base + n3 - 1);
                        }
                    }
                }
                ex2.Next();
            }
            
            for (const auto& p : all_nodes) push_point(verts_vec, (float)p.X(), (float)p.Y(), (float)p.Z());
            for (int tri : all_tris) push_count(tris_vec, tri);
        }
    } catch (...) {}
}

}
