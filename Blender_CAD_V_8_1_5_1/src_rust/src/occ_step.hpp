// 外部 CAD/メッシュ形式の入出力。名前は STEP だが、STL のような
// 「同じスタックを別の形式で吐く」処理も同居させている (書き出し前の倍率と
// 例外処理を共有できるため)。新しい形式を足すときもここでよい。
#pragma once
#include "occ_common.hpp"
#include <STEPControl_Reader.hxx>
#include <STEPControl_Writer.hxx>
#include <Interface_Static.hxx>
#include <StlAPI_Writer.hxx>
#include <BRepMesh_IncrementalMesh.hxx>
#include <BRepBuilderAPI_Copy.hxx>
#include <BRepTools.hxx>
#include <BRep_Tool.hxx>
#include <Poly_Triangulation.hxx>
#include <TopLoc_Location.hxx>

namespace occ {
    // Import STEP file. Returns a list of newly registered UUIDs.
    std::vector<std::string> import_step(const std::string& filepath, double scale = 1.0);
    
    // Export shapes corresponding to the given UUIDs to a STEP file.
    bool export_step(const std::vector<std::string>& uuids, const std::string& filepath);
    
    // Export the result of a CADStack to a STEP file.
    // scale は「1 Blender 単位を何 mm として書き出すか」。1.0 で従来どおり。
    bool export_stack_to_step(void* stack_ptr, const std::string& filepath, double scale = 1.0);

    // Export the result of a CADStack to an STL file.
    // scale は export_stack_to_step と同じ意味。
    // angular_deflection は**ラジアン**。三角形が1枚も出なければ false を返し、
    // 空のファイルは書かない。
    bool export_stack_to_stl(void* stack_ptr, const std::string& filepath, double scale = 1.0,
                             double linear_deflection = 0.1, double angular_deflection = 0.5,
                             bool ascii_mode = false);


    // Get a cached STEP shape by UUID
    TopoDS_Shape get_step_shape(const std::string& uuid);
}
