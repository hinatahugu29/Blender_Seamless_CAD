#pragma once
#include <TopoDS_Shape.hxx>
#include <TopoDS_Wire.hxx>
#include <string>

namespace occ_core {

    TopoDS_Shape make_box(double sx, double sy, double sz);
    TopoDS_Shape make_cylinder(double sx, double sy, double sz);
    TopoDS_Shape make_sphere(double sx, double sy, double sz);
    TopoDS_Shape make_cone(double r1, double r2, double sz);
    TopoDS_Shape make_torus(double r1, double minor_r);
    TopoDS_Shape make_slot(double r, double sx);
    TopoDS_Shape make_variable_box(double tw, double th, double h, double bw, double bh, const std::string& top_shape, const std::string& bot_shape);
    TopoDS_Shape make_polygon(int sides, double radius);
    TopoDS_Shape make_gear(int sides, double module, double pressure_angle_deg);
    TopoDS_Shape make_arc(double radius, double a_start, double a_end);
    TopoDS_Shape make_sweep(
        const TopoDS_Shape& profile,
        const TopoDS_Shape& path,
        const std::string& frame_mode = "AUTO",
        double sweep_roll_degrees = 0.0,
        bool helix_axis_valid = false,
        const gp_Pnt& helix_axis_origin = gp_Pnt(0, 0, 0),
        const gp_Dir& helix_axis_dir = gp_Dir(0, 0, 1)
    );
    TopoDS_Shape make_loft(const std::vector<TopoDS_Shape>& profiles);
    TopoDS_Shape make_helix(double radius, double height, double turns);

}
