#pragma once

#define _CRT_SECURE_NO_WARNINGS
#include <Standard_DefineAlloc.hxx>
#include <Standard_Handle.hxx>
#include <gp_Pnt.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Shape.hxx>
#include <TopoDS_Vertex.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Face.hxx>
#include <BRepAdaptor_Curve.hxx>
#include <TopoDS_Wire.hxx>
#include <TopoDS_Shell.hxx>
#include <TopoDS_Solid.hxx>
#include <TopoDS_Compound.hxx>
#include <TopTools_ShapeMapHasher.hxx>
#include <TopTools_MapOfShape.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopTools_DataMapOfShapeShape.hxx>
#include <TopTools_DataMapOfShapeInteger.hxx>
#include <TopTools_ListOfShape.hxx>
#include <BRep_Builder.hxx>
#include <ShapeFix_Face.hxx>
#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <TopTools_DataMapOfShapeListOfShape.hxx>
#include "occ_core.hpp"
#include <TopExp.hxx>
#include <iostream>
#include <string>
#include <fstream>
#include <sstream>
#include <map>
#include <cmath>
#include <cstring>
#include <algorithm>
#include <vector>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <BRepPrimAPI_MakeSphere.hxx>
#include <BRepPrimAPI_MakeCone.hxx>
#include <BRepPrimAPI_MakeTorus.hxx>
#include <BRepPrimAPI_MakeRevol.hxx>
#include <BRepPrimAPI_MakePrism.hxx>
#include <BRepAlgoAPI_Cut.hxx>
#include <BRepAlgoAPI_Fuse.hxx>
#include <BRepAlgoAPI_Common.hxx>
#include <BRepBuilderAPI_Transform.hxx>
#include <BRepBuilderAPI_GTransform.hxx>
#include <BRepBuilderAPI_MakeVertex.hxx>
#include <BRepGProp.hxx>
#include <GProp_GProps.hxx>
#include <ShapeUpgrade_UnifySameDomain.hxx>
#include <BRepIntCurveSurface_Inter.hxx>
#include <IntCurveSurface_HInter.hxx>
#include <GeomAdaptor_Curve.hxx>
#include <Geom_Line.hxx>
#include <TopAbs_ShapeEnum.hxx>
#include <TopExp_Explorer.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <GCPnts_UniformDeflection.hxx>
#include <GCPnts_UniformAbscissa.hxx>
#include <GCPnts_TangentialDeflection.hxx>
#include <gp_Trsf.hxx>
#include <gp_Vec.hxx>
#include <gp_GTrsf.hxx>
#include <gp_Lin.hxx>
#include <gp_Dir.hxx>
#include <BRepExtrema_DistShapeShape.hxx>
#include <BRep_Tool.hxx>
#include <Geom_Curve.hxx>
#include <GeomAPI_ProjectPointOnCurve.hxx>
#include <BRepFilletAPI_MakeFillet.hxx>
#include <BRepFilletAPI_MakeChamfer.hxx>
#include <BRepMesh_IncrementalMesh.hxx>
#include <BRepTools.hxx>
#include <Geom_Surface.hxx>
#include <Poly_Triangulation.hxx>
#include <Poly_Triangle.hxx>
#include <Standard_ErrorHandler.hxx>
#include <Standard_Failure.hxx>
#include <TCollection_AsciiString.hxx>
#include <GeomAPI_PointsToBSpline.hxx>
#include <Geom_BSplineCurve.hxx>
#include <TColgp_Array1OfPnt.hxx>
#include <BRepAdaptor_CompCurve.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakePolygon.hxx>
#include <BRepOffsetAPI_MakePipe.hxx>
#include <BRepOffsetAPI_MakePipeShell.hxx>
#include <BRepBuilderAPI_Sewing.hxx>
#include <BRepBuilderAPI_MakeSolid.hxx>
#include <ShapeFix_Shell.hxx>
#include <BRepOffsetAPI_DraftAngle.hxx>
#include <BRepOffsetAPI_MakeThickSolid.hxx>
#include <BRepOffsetAPI_MakeOffset.hxx>
#include <BRepFeat_SplitShape.hxx>
#include <gp_Circ.hxx>
#include <gp_Ax2.hxx>
#include <Extrema_ExtCC.hxx>
#include <Extrema_POnCurv.hxx>
#include <GC_MakeArcOfCircle.hxx>
#include <gp_Quaternion.hxx>
#include <gp_EulerSequence.hxx>
#include <BRepOffsetAPI_ThruSections.hxx>
#include <mutex>
#include <BRepBuilderAPI_MakeShape.hxx>
#include <BRepTools_History.hxx>

inline void assign_uuids_to_new_faces(std::map<std::string, TopoDS_Shape>& face_map, const TopoDS_Shape& shape, const std::string& prefix) {
    if (shape.IsNull()) return;
    TopTools_IndexedMapOfShape fm;
    TopExp::MapShapes(shape, TopAbs_FACE, fm);
    
    TopTools_MapOfShape existing_faces;
    for (const auto& pair : face_map) {
        existing_faces.Add(pair.second);
    }

    for (int i = 1; i <= fm.Extent(); ++i) {
        TopoDS_Shape f = fm.FindKey(i);
        if (!existing_faces.Contains(f)) {
            std::string new_uuid = prefix + "_F" + std::to_string(i);
            face_map[new_uuid] = f;
        }
    }
}

inline void update_face_id_map_from_builder(std::map<std::string, TopoDS_Shape>& face_map, BRepBuilderAPI_MakeShape& builder) {
    for (auto it = face_map.begin(); it != face_map.end();) {
        if (builder.IsDeleted(it->second)) {
            it = face_map.erase(it);
        } else {
            const TopTools_ListOfShape& modified = builder.Modified(it->second);
            if (!modified.IsEmpty()) {
                it->second = modified.First();
                ++it;
            } else {
                const TopTools_ListOfShape& generated = builder.Generated(it->second);
                if (!generated.IsEmpty()) {
                    it->second = generated.First();
                    ++it;
                } else {
                    ++it;
                }
            }
        }
    }
}

inline void update_face_id_map_from_history(std::map<std::string, TopoDS_Shape>& face_map, Handle(BRepTools_History) history) {
    if (history.IsNull()) return;
    for (auto it = face_map.begin(); it != face_map.end();) {
        if (history->IsRemoved(it->second)) {
            it = face_map.erase(it);
        } else {
            const TopTools_ListOfShape& modified = history->Modified(it->second);
            if (!modified.IsEmpty()) {
                if (modified.Extent() == 1) {
                    it->second = modified.First();
                } else {
                    BRep_Builder bb; TopoDS_Compound comp; bb.MakeCompound(comp);
                    for (TopTools_ListIteratorOfListOfShape list_it(modified); list_it.More(); list_it.Next()) {
                        bb.Add(comp, list_it.Value());
                    }
                    it->second = comp;
                }
                ++it;
            } else {
                const TopTools_ListOfShape& generated = history->Generated(it->second);
                if (!generated.IsEmpty()) {
                    if (generated.Extent() == 1) {
                        it->second = generated.First();
                    } else {
                        BRep_Builder bb; TopoDS_Compound comp; bb.MakeCompound(comp);
                        for (TopTools_ListIteratorOfListOfShape list_it(generated); list_it.More(); list_it.Next()) {
                            bb.Add(comp, list_it.Value());
                        }
                        it->second = comp;
                    }
                    ++it;
                } else {
                    ++it;
                }
            }
        }
    }
}

inline void purge_unused_faces(std::map<std::string, TopoDS_Shape>& face_map, const TopoDS_Shape& current_shape) {
    if (current_shape.IsNull()) return;
    TopTools_IndexedMapOfShape fm;
    TopExp::MapShapes(current_shape, TopAbs_FACE, fm);
    TopTools_MapOfShape active_faces;
    for (int i = 1; i <= fm.Extent(); ++i) {
        active_faces.Add(fm.FindKey(i));
    }

    for (auto it = face_map.begin(); it != face_map.end();) {
        bool in_use = false;
        if (it->second.ShapeType() == TopAbs_FACE) {
            in_use = active_faces.Contains(it->second);
        } else if (it->second.ShapeType() == TopAbs_COMPOUND || it->second.ShapeType() == TopAbs_SHELL || it->second.ShapeType() == TopAbs_SOLID) {
            TopTools_IndexedMapOfShape sub_fm;
            TopExp::MapShapes(it->second, TopAbs_FACE, sub_fm);
            for (int i = 1; i <= sub_fm.Extent(); ++i) {
                if (active_faces.Contains(sub_fm.FindKey(i))) {
                    in_use = true;
                    break;
                }
            }
        } else {
            in_use = true; // フェイス以外が含まれる場合は安全のため残す
        }
        
        if (!in_use) {
            it = face_map.erase(it);
        } else {
            ++it;
        }
    }
}
