
#include "occ_common.hpp"
#include "occ_booleans.hpp"
#include "occ_utils.hpp"
#include <BRepAlgoAPI_Fuse.hxx>
#include <BRepAlgoAPI_Cut.hxx>
#include <BRepAlgoAPI_Common.hxx>
#include <BRep_Builder.hxx>
#include <TopoDS_Compound.hxx>
#include <ShapeUpgrade_UnifySameDomain.hxx>
#include <TopTools_ListOfShape.hxx>
#include <Bnd_Box.hxx>
#include <BRepBndLib.hxx>

namespace occ_core {
    static int count_subshapes(const TopoDS_Shape& shape, TopAbs_ShapeEnum type) {
        if (shape.IsNull()) return 0;
        TopTools_IndexedMapOfShape map;
        TopExp::MapShapes(shape, type, map);
        return map.Extent();
    }

    static std::string shape_type_name(const TopoDS_Shape& shape) {
        if (shape.IsNull()) return "NULL";
        switch (shape.ShapeType()) {
            case TopAbs_COMPOUND: return "COMPOUND";
            case TopAbs_COMPSOLID: return "COMPSOLID";
            case TopAbs_SOLID: return "SOLID";
            case TopAbs_SHELL: return "SHELL";
            case TopAbs_FACE: return "FACE";
            case TopAbs_WIRE: return "WIRE";
            case TopAbs_EDGE: return "EDGE";
            case TopAbs_VERTEX: return "VERTEX";
            default: return "OTHER";
        }
    }

    TopoDS_Shape apply_boolean_batch(const TopoDS_Shape& base_shape, const TopTools_ListOfShape& tool_shapes, const std::string& p_op, std::map<std::string, TopoDS_Shape>* face_map, bool base_is_fused) {
        if (base_shape.IsNull()) {
            if (tool_shapes.IsEmpty()) return base_shape;
            if (p_op == "ADD") {
                BRep_Builder bb; TopoDS_Compound comp; bb.MakeCompound(comp);
                for (TopTools_ListIteratorOfListOfShape it(tool_shapes); it.More(); it.Next()) {
                    bb.Add(comp, it.Value());
                }
                return comp;
            }
            return base_shape;
        }
        if (tool_shapes.IsEmpty()) return base_shape;

        Bnd_Box base_box;
        BRepBndLib::Add(base_shape, base_box);

        TopTools_ListOfShape intersecting_tools;
        TopTools_ListOfShape non_intersecting_tools;

        for (TopTools_ListIteratorOfListOfShape it(tool_shapes); it.More(); it.Next()) {
            const TopoDS_Shape& t_shape = it.Value();
            if (t_shape.IsNull()) continue;
            Bnd_Box t_box;
            BRepBndLib::Add(t_shape, t_box);
            if (base_box.IsOut(t_box)) {
                non_intersecting_tools.Append(t_shape);
            } else {
                intersecting_tools.Append(t_shape);
            }
        }

        // 全く干渉しない場合の早期リターン
        if (intersecting_tools.IsEmpty()) {
            if (p_op == "SUB" || p_op == "SUBTRACT") {
                return base_shape;
            } else if (p_op == "INT" || p_op == "INTERSECT") {
                BRep_Builder bb; TopoDS_Compound comp; bb.MakeCompound(comp);
                return comp;
            } else if (p_op == "ADD") {
                BRep_Builder bb; TopoDS_Compound comp; bb.MakeCompound(comp);
                bb.Add(comp, base_shape);
                for (TopTools_ListIteratorOfListOfShape it(non_intersecting_tools); it.More(); it.Next()) {
                    bb.Add(comp, it.Value());
                }
                return comp;
            }
        }

        TopoDS_Shape result = base_shape;
        try {
            BRepAlgoAPI_BooleanOperation* b = nullptr;
            TopTools_ListOfShape args; args.Append(base_shape);
            
            if (p_op == "ADD") b = new BRepAlgoAPI_Fuse(); 
            else if (p_op == "SUB" || p_op == "SUBTRACT") b = new BRepAlgoAPI_Cut(); 
            else if (p_op == "INT" || p_op == "INTERSECT") b = new BRepAlgoAPI_Common();
            
            if (b) {
                b->SetArguments(args);
                b->SetTools(intersecting_tools);
                b->SetRunParallel(Standard_True);
                b->SetNonDestructive(Standard_True);
                b->SetFuzzyValue(1e-4); 
                b->Build();
                if (b->IsDone()) {
                    result = b->Shape();
                    if (face_map) {
                        update_face_id_map_from_history(*face_map, b->History());
                        purge_unused_faces(*face_map, result);
                    }
                }
                else if (p_op == "ADD") {
                    BRep_Builder bb; TopoDS_Compound comp; bb.MakeCompound(comp);
                    bb.Add(comp, base_shape);
                    for (TopTools_ListIteratorOfListOfShape it(intersecting_tools); it.More(); it.Next()) {
                        bb.Add(comp, it.Value());
                    }
                    result = comp;
                }
                delete b;
            }
        } catch (...) {
            if (p_op == "ADD") {
                BRep_Builder bb; TopoDS_Compound comp; bb.MakeCompound(comp);
                bb.Add(comp, base_shape);
                for (TopTools_ListIteratorOfListOfShape it(intersecting_tools); it.More(); it.Next()) {
                    bb.Add(comp, it.Value());
                }
                result = comp;
            }
        }

        // ADDの場合、干渉しなかったツールを後から Compound にまとめる
        if (p_op == "ADD" && !non_intersecting_tools.IsEmpty()) {
            BRep_Builder bb; TopoDS_Compound comp; bb.MakeCompound(comp);
            bb.Add(comp, result);
            for (TopTools_ListIteratorOfListOfShape it(non_intersecting_tools); it.More(); it.Next()) {
                bb.Add(comp, it.Value());
            }
            result = comp;
        }

        return result;
    }

    TopoDS_Shape fuse_compound(const TopoDS_Shape& shape, std::map<std::string, TopoDS_Shape>* face_map) {
        if (shape.IsNull()) return shape;
        
        TopTools_ListOfShape solids;
        TopTools_ListOfShape shells_faces;
        TopTools_ListOfShape wires_edges;
        
        TopExp_Explorer exp_s(shape, TopAbs_SOLID);
        while (exp_s.More()) {
            solids.Append(exp_s.Current());
            exp_s.Next();
        }
        
        TopExp_Explorer exp_sh(shape, TopAbs_SHELL, TopAbs_SOLID);
        while (exp_sh.More()) {
            shells_faces.Append(exp_sh.Current());
            exp_sh.Next();
        }
        
        TopExp_Explorer exp_f(shape, TopAbs_FACE, TopAbs_SHELL);
        while (exp_f.More()) {
            shells_faces.Append(exp_f.Current());
            exp_f.Next();
        }
        
        // Collect standalone wires and edges that are not part of faces
        TopExp_Explorer exp_w(shape, TopAbs_WIRE, TopAbs_FACE);
        while (exp_w.More()) {
            wires_edges.Append(exp_w.Current());
            exp_w.Next();
        }
        TopExp_Explorer exp_e(shape, TopAbs_EDGE, TopAbs_WIRE);
        while (exp_e.More()) {
            wires_edges.Append(exp_e.Current());
            exp_e.Next();
        }
        
        TopoDS_Shape fused_solids;
        if (solids.Extent() <= 1) {
            if (solids.Extent() == 1) {
                fused_solids = solids.First();
            }
        } else {
            TopTools_ListIteratorOfListOfShape it(solids);
            TopoDS_Shape base = it.Value();
            it.Next();
            TopTools_ListOfShape tools;
            while (it.More()) {
                tools.Append(it.Value());
                it.Next();
            }
            fused_solids = apply_boolean_batch(base, tools, "ADD", face_map);
        }

        TopoDS_Shape fused_shells;
        if (shells_faces.Extent() <= 1) {
            if (shells_faces.Extent() == 1) {
                fused_shells = shells_faces.First();
            }
        } else {
            TopTools_ListIteratorOfListOfShape it(shells_faces);
            TopoDS_Shape base = it.Value();
            it.Next();
            TopTools_ListOfShape tools;
            while (it.More()) {
                tools.Append(it.Value());
                it.Next();
            }
            fused_shells = apply_boolean_batch(base, tools, "ADD", face_map);
        }
        
        if (wires_edges.IsEmpty() && fused_shells.IsNull() && !fused_solids.IsNull()) {
            return fused_solids;
        }
        
        BRep_Builder bb;
        TopoDS_Compound comp;
        bb.MakeCompound(comp);
        bool has_element = false;
        
        if (!fused_solids.IsNull()) {
            bb.Add(comp, fused_solids);
            has_element = true;
        }
        if (!fused_shells.IsNull()) {
            bb.Add(comp, fused_shells);
            has_element = true;
        }
        TopTools_ListIteratorOfListOfShape it_w(wires_edges);
        while (it_w.More()) {
            bb.Add(comp, it_w.Value());
            has_element = true;
            it_w.Next();
        }
        
        if (has_element) {
            return comp;
        }
        return shape;
    }

    TopoDS_Shape apply_boolean(const TopoDS_Shape& base_shape, const TopoDS_Shape& tool_shape, const std::string& p_op, std::map<std::string, TopoDS_Shape>* face_map, bool base_is_fused) {
        if (base_shape.IsNull()) {
            if (p_op == "ADD" && !tool_shape.IsNull()) return tool_shape;
            return base_shape;
        }
        if (tool_shape.IsNull()) return base_shape;

        TopoDS_Shape fused_base = base_is_fused ? base_shape : fuse_compound(base_shape);
        
        // BBox干渉チェックによる最適化
        Bnd_Box base_box;
        BRepBndLib::Add(fused_base, base_box);
        Bnd_Box tool_box;
        BRepBndLib::Add(tool_shape, tool_box);

        if (base_box.IsOut(tool_box)) {
            if (p_op == "ADD") {
                BRep_Builder bb; TopoDS_Compound comp; bb.MakeCompound(comp);
                bb.Add(comp, fused_base);
                bb.Add(comp, tool_shape);
                log_debug(
                    "[ADD_BOOLEAN] non_intersecting_compound base_type=" + shape_type_name(fused_base) +
                    " tool_type=" + shape_type_name(tool_shape) +
                    " base_solids=" + std::to_string(count_subshapes(fused_base, TopAbs_SOLID)) +
                    " tool_solids=" + std::to_string(count_subshapes(tool_shape, TopAbs_SOLID))
                );
                return comp;
            } else if (p_op == "SUB" || p_op == "SUBTRACT") {
                return fused_base;
            } else if (p_op == "INT" || p_op == "INTERSECT") {
                BRep_Builder bb; TopoDS_Compound comp; bb.MakeCompound(comp);
                return comp;
            }
        }

        TopoDS_Shape result = fused_base;
        try {
            BRepAlgoAPI_BooleanOperation* b = nullptr;
            if (p_op == "ADD") b = new BRepAlgoAPI_Fuse(fused_base, tool_shape);
            else if (p_op == "SUB" || p_op == "SUBTRACT") b = new BRepAlgoAPI_Cut(fused_base, tool_shape); 
            else if (p_op == "INT" || p_op == "INTERSECT") b = new BRepAlgoAPI_Common(fused_base, tool_shape);
            
            if (b) {
                b->SetRunParallel(Standard_True);
                b->SetNonDestructive(Standard_True);
                // b->SetGlue(BOPAlgo_GlueShift); // Enable for benchmark testing if coplanar
                b->SetFuzzyValue(1e-4); 
                b->Build();
                if (b->IsDone()) {
                    result = b->Shape();
                    if (p_op == "ADD") {
                        log_debug(
                            "[ADD_BOOLEAN] built result_type=" + shape_type_name(result) +
                            " result_solids=" + std::to_string(count_subshapes(result, TopAbs_SOLID)) +
                            " result_faces=" + std::to_string(count_subshapes(result, TopAbs_FACE))
                        );
                    }
                    if (face_map) {
                        update_face_id_map_from_history(*face_map, b->History());
                        purge_unused_faces(*face_map, result);
                    }
                }
                else if (p_op == "ADD") {
                    BRep_Builder bb; TopoDS_Compound comp; bb.MakeCompound(comp);
                    bb.Add(comp, base_shape); bb.Add(comp, tool_shape); result = comp;
                }
                delete b;
            }
        } catch (...) {
            if (p_op == "ADD") {
                BRep_Builder bb; TopoDS_Compound comp; bb.MakeCompound(comp);
                bb.Add(comp, base_shape); bb.Add(comp, tool_shape); result = comp;
            }
        }
        return result;
    }
}
