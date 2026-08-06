#include <gp_Quaternion.hxx>
#include <gp_Trsf.hxx>

extern "C" {
    void test_occ() {
        gp_Quaternion q;
        q.SetEulerAngles(gp_Intrinsic_XYZ, 0.0, 0.0, 0.0);
    }
}
