#include <iostream>
#include <gp_Trsf.hxx>
#include <gp_Quaternion.hxx>
#include <gp_Vec.hxx>
#include <gp_Pnt.hxx>

int main() {
    gp_Quaternion q;
    q.SetEulerAngles(gp_Intrinsic_XYZ, 0, 0, -1.57079632679); // Rz(-90)
    gp_Vec loc(0, 0, 0.5);
    
    gp_Trsf t;
    t.SetTransformation(q, loc);
    
    gp_Pnt p(1, 0, 0);
    p.Transform(t);
    
    std::cout << "P transformed: " << p.X() << ", " << p.Y() << ", " << p.Z() << std::endl;
    return 0;
}
