#include <iostream>
#include <gp_Quaternion.hxx>
#include <gp_Trsf.hxx>
#include <gp_Pnt.hxx>

int main() {
    // 90 deg around X is Q = (sin(45), 0, 0, cos(45))
    // Let's test with W=0.707, X=0.707
    gp_Quaternion q(0.707106, 0.0, 0.0, 0.707106); // If signature is X, Y, Z, W
    gp_Trsf t;
    t.SetRotation(q);
    
    gp_Pnt p(0, 1, 0); // Y axis
    p.Transform(t);
    
    std::cout << "P': " << p.X() << ", " << p.Y() << ", " << p.Z() << std::endl;
    return 0;
}
