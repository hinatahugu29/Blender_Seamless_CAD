#include <iostream>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <BRepOffsetAPI_MakeOffset.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Face.hxx>
#include <TopoDS_Wire.hxx>
#include <GeomAbs_JoinType.hxx>
#include <BRepTools.hxx>

int main() {
    BRepPrimAPI_MakeCylinder mkCyl(10.0, 20.0);
    TopoDS_Shape cyl = mkCyl.Shape();
    
    TopExp_Explorer ex(cyl, TopAbs_FACE);
    int face_count = 0;
    while(ex.More()) {
        TopoDS_Face f = TopoDS::Face(ex.Current());
        face_count++;
        
        BRepOffsetAPI_MakeOffset makeOffset(f, GeomAbs_Arc);
        TopExp_Explorer wexp(f, TopAbs_WIRE);
        while (wexp.More()) {
            makeOffset.AddWire(TopoDS::Wire(wexp.Current()));
            wexp.Next();
        }
        makeOffset.Perform(-1.0); // Inset by 1
        
        if (makeOffset.IsDone()) {
            std::cout << "Face " << face_count << ": MakeOffset SUCCESS" << std::endl;
        } else {
            std::cout << "Face " << face_count << ": MakeOffset FAILED" << std::endl;
        }
        ex.Next();
    }
    return 0;
}
