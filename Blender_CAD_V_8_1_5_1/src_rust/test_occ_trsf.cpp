#include <gp_Trsf.hxx>
#include <gp_Quaternion.hxx>
#include <gp_Vec.hxx>
#include <gp_Pnt.hxx>
#include <iostream>

int main() {
    gp_Quaternion q(0.70710678, 0, 0, 0.70710678); // X=90 deg. X,Y,Z,W
    gp_Trsf t;
    t.SetTransformation(q, gp_Vec(0,0,0));
    
    gp_Pnt p(0, 1, 0); // Y axis point
    p.Transform(t);
    std::cout << "P transformed: " << p.X() << ", " << p.Y() << ", " << p.Z() << std::endl;

    gp_Trsf t2;
    t2.SetRotation(q);
    gp_Pnt p2(0, 1, 0);
    p2.Transform(t2);
    std::cout << "P2 transformed: " << p2.X() << ", " << p2.Y() << ", " << p2.Z() << std::endl;
    return 0;
}
