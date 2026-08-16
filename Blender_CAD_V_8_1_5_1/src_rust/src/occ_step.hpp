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
// XCAF: STEP に名前とアセンブリ構造を載せるための一式。
// STEPControl_Writer は形状しか書けないので、名前を出すにはこちらを通す。
#include <STEPCAFControl_Writer.hxx>
#include <XCAFApp_Application.hxx>
#include <XCAFDoc_DocumentTool.hxx>
#include <XCAFDoc_ShapeTool.hxx>
#include <TDocStd_Document.hxx>
#include <TDataStd_Name.hxx>
#include <TDF_Label.hxx>
#include <TDF_LabelSequence.hxx>
#include <TCollection_ExtendedString.hxx>
#include <TopoDS_Compound.hxx>
#include <BRep_Builder.hxx>
#include <TopoDS_Iterator.hxx>
// IGES: 幾何のみの書き出し。IGESControl_Controller::Init() を先に呼ぶこと。
#include <IGESControl_Writer.hxx>
#include <IGESControl_Controller.hxx>
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

    // Export one or more CADStacks to a STEP file **with names**, and with an
    // assembly structure when more than one is given.
    //
    // stack_ptrs と names は同じ長さでなければならない。形状を持たないスタックは
    // 読み飛ばす。1つも残らなければ false。
    // scale は export_stack_to_step と同じ意味。
    bool export_parts_to_step(const std::vector<void*>& stack_ptrs,
                              const std::vector<std::string>& names,
                              const std::string& filepath,
                              double scale,
                              const std::string& assembly_name);

    // Export the result of a CADStack to an IGES file.
    // scale は export_stack_to_step と同じ意味。
    //
    // **幾何のみ。** 名前もアセンブリ構造も入らない。IGES の実体参照は
    // 相手の実装差が大きく、名前を載せても読めない側が多いため、
    // STEP のような XCAF 経路は用意していない。名前が要るなら STEP を使うこと。
    bool export_stack_to_iges(void* stack_ptr, const std::string& filepath,
                              double scale = 1.0, bool brep_mode = true);

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
