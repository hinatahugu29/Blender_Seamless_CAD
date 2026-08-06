#include <Geom_CylindricalSurface.hxx>
#include <Geom2d_Line.hxx>
#include <Geom2d_TrimmedCurve.hxx>
#include <Bnd_Box.hxx>
#include <BRepBndLib.hxx>
#include <gp_Ax1.hxx>
#include <gp_Ax3.hxx>
#include "occ_common.hpp"
#include "occ_primitives.hpp"
#include "occ_utils.hpp"
#include "occ_core.hpp"
namespace occ_core {
// occ_primitives.cpp

TopoDS_Shape make_box(double sx, double sy, double sz) {
    if (sx > 1e-6 && sy > 1e-6 && sz > 1e-6) {
        return BRepPrimAPI_MakeBox(gp_Pnt(-sx/2, -sy/2, -sz/2), sx, sy, sz).Shape();
    }
    return TopoDS_Shape();
}

TopoDS_Shape make_cylinder(double sx, double sy, double sz) {
    TopoDS_Shape prim;
    if (sx > 1e-6 && sz > 1e-6) {
        prim = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0,0,-sz/2), gp_Dir(0,0,1)), sx, sz).Shape(); 
        if (std::abs(sx - sy) > 1e-6 && sx > 1e-6) {
            gp_GTrsf gt; gt.SetVectorialPart(gp_Mat(1, 0, 0, 0, sy/sx, 0, 0, 0, 1));
            prim = BRepBuilderAPI_GTransform(prim, gt, true).Shape();
        }
    }
    return prim;
}

TopoDS_Shape make_sphere(double sx, double sy, double sz) {
    TopoDS_Shape prim;
    if (sx > 1e-6) {
        prim = BRepPrimAPI_MakeSphere(sx).Shape();
        if ((std::abs(sx - sy) > 1e-6 || std::abs(sx - sz) > 1e-6) && sx > 1e-6) {
            gp_GTrsf gt; gt.SetVectorialPart(gp_Mat(1, 0, 0, 0, sy/sx, 0, 0, 0, sz/sx));
            prim = BRepBuilderAPI_GTransform(prim, gt, true).Shape();
        }
    }
    return prim;
}

TopoDS_Shape make_cone(double r1, double r2, double sz) {
    return BRepPrimAPI_MakeCone(gp_Ax2(gp_Pnt(0,0,-sz/2), gp_Dir(0,0,1)), std::max(0.001, r1), std::max(0.0, r2), std::max(0.001, sz)).Shape();
}

TopoDS_Shape make_torus(double r1, double minor_r) {
    return BRepPrimAPI_MakeTorus(gp_Ax2(gp_Pnt(0,0,0), gp_Dir(0,0,1)), std::max(0.01, r1), std::max(0.01, minor_r)).Shape();
}

TopoDS_Shape make_slot(double r, double sx) {
    double rad = std::max(0.001, r), L = std::max(0.001, sx);
    gp_Pnt p1(-L/2, 0, 0), p2(L/2, 0, 0); gp_Ax2 ax1(p1, gp_Dir(0,0,1), gp_Dir(0,1,0)), ax2(p2, gp_Dir(0,0,1), gp_Dir(0,-1,0));
    GC_MakeArcOfCircle arc1(gp_Circ(ax1, rad), 0, 3.141592653589793, true), arc2(gp_Circ(ax2, rad), 0, 3.141592653589793, true);
    if (arc1.IsDone() && arc2.IsDone()) {
        BRepBuilderAPI_MakeWire w; w.Add(BRepBuilderAPI_MakeEdge(arc1.Value()).Edge()); w.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(-L/2, rad, 0), gp_Pnt(L/2, rad, 0)).Edge());
        w.Add(BRepBuilderAPI_MakeEdge(arc2.Value()).Edge()); w.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(L/2, -rad, 0), gp_Pnt(-L/2, -rad, 0)).Edge());
        if (w.IsDone()) { BRepBuilderAPI_MakeFace f(w.Wire(), true); if (f.IsDone()) return f.Shape(); }
    }
    return TopoDS_Shape();
}

TopoDS_Shape make_variable_box(double tw, double th, double h, double bw, double bh, const std::string& top_shape, const std::string& bot_shape) {
    double top_w = std::max(0.001, tw), top_h = std::max(0.001, th), height = std::max(0.001, h);
    double bot_w = std::max(0.001, bw), bot_h = std::max(0.001, bh);
    
    auto make_profile = [&](std::string shape, double w_v, double h_v, double z) {
        BRepBuilderAPI_MakeWire wire;
        if (shape == "CIRCLE") {
            gp_Ax2 ax(gp_Pnt(0, 0, z), gp_Dir(0, 0, 1));
            wire.Add(BRepBuilderAPI_MakeEdge(gp_Circ(ax, w_v)).Edge());
        } else {
            gp_Pnt p1(-w_v/2, -h_v/2, z), p2(w_v/2, -h_v/2, z), p3(w_v/2, h_v/2, z), p4(-w_v/2, h_v/2, z);
            wire.Add(BRepBuilderAPI_MakeEdge(p1, p2).Edge()); wire.Add(BRepBuilderAPI_MakeEdge(p2, p3).Edge()); 
            wire.Add(BRepBuilderAPI_MakeEdge(p3, p4).Edge()); wire.Add(BRepBuilderAPI_MakeEdge(p4, p1).Edge());
        }
        return wire.Wire();
    };

    TopoDS_Wire w1 = make_profile(top_shape, top_w, top_h, height/2);
    TopoDS_Wire w2 = make_profile(bot_shape, bot_w, bot_h, -height/2);
    BRepOffsetAPI_ThruSections loft(Standard_True, Standard_True);
    loft.AddWire(w1); loft.AddWire(w2); loft.Build();
    if (loft.IsDone()) return loft.Shape();
    return TopoDS_Shape();
}

TopoDS_Shape make_polygon(int sides, double radius) {
    int n = std::max(3, sides); double r = std::max(0.01, radius); BRepBuilderAPI_MakeWire w;
    for (int j = 0; j < n; ++j) { double a1 = j*2*3.141592653589793/n, a2 = (j+1)*2*3.141592653589793/n; w.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(r*cos(a1), r*sin(a1), 0), gp_Pnt(r*cos(a2), r*sin(a2), 0)).Edge()); }
    if (w.IsDone()) { BRepBuilderAPI_MakeFace f(w.Wire(), true); if (f.IsDone()) return f.Shape(); }
    return TopoDS_Shape();
}

TopoDS_Shape make_gear(int sides, double module, double pressure_angle_deg) {
    double m = std::max(0.01, module);
    double alpha_p = pressure_angle_deg * 3.14159265358979323846 / 180.0;
    int z = std::max(3, sides);
    double r_p = (m * z) / 2.0;
    double r_a = r_p + m;
    double r_d = r_p - 1.25 * m;
    double r_b = r_p * std::cos(alpha_p);
    double step = 2.0 * 3.14159265358979323846 / z;
    
    BRepBuilderAPI_MakeWire w;
    for (int j = 0; j < z; ++j) {
        double base_angle = j * step;
        auto get_inv = [&](double r) {
            double cos_a = r_b / r;
            if (cos_a > 1.0) cos_a = 1.0;
            double a = std::acos(cos_a);
            return std::tan(a) - a;
        };
        double inv_p = std::tan(alpha_p) - alpha_p;
        auto get_half_thick = [&](double r) {
            return (3.14159265358979323846 / (2.0 * z)) + inv_p - get_inv(r);
        };

        int samples = 5;
        std::vector<gp_Pnt> left, right;
        for (int k = 0; k <= samples; ++k) {
            double r = r_d + (r_a - r_d) * (double)k / samples;
            double ht = get_half_thick(std::max(r, r_b));
            left.push_back(gp_Pnt(r * std::cos(base_angle - ht), r * std::sin(base_angle - ht), 0));
            right.push_back(gp_Pnt(r * std::cos(base_angle + ht), r * std::sin(base_angle + ht), 0));
        }
        for (int k = 0; k < samples; ++k) w.Add(BRepBuilderAPI_MakeEdge(left[k], left[k+1]).Edge());
        w.Add(BRepBuilderAPI_MakeEdge(left.back(), right.back()).Edge());
        for (int k = samples; k > 0; --k) w.Add(BRepBuilderAPI_MakeEdge(right[k], right[k-1]).Edge());
        
        double next_base_angle = (j + 1) * step;
        double ht_d = get_half_thick(std::max(r_d, r_b));
        w.Add(BRepBuilderAPI_MakeEdge(right[0], gp_Pnt(r_d * std::cos(next_base_angle - ht_d), r_d * std::sin(next_base_angle - ht_d), 0)).Edge());
    }
    if (w.IsDone()) { BRepBuilderAPI_MakeFace f(w.Wire(), true); if (f.IsDone()) return f.Shape(); }
    return TopoDS_Shape();
}

TopoDS_Shape make_arc(double radius, double a_start, double a_end) {
    double r = std::max(0.01, radius), a1 = a_start * 3.141592653589793 / 180.0, a2 = a_end * 3.141592653589793 / 180.0; gp_Circ c(gp_Ax2(gp_Pnt(0,0,0), gp_Dir(0,0,1)), r);
    if (std::abs(a_end - a_start) >= 359.99) return BRepBuilderAPI_MakeEdge(c).Shape(); 
    else { GC_MakeArcOfCircle ar(c, a1, a2, true); if (ar.IsDone()) return BRepBuilderAPI_MakeEdge(ar.Value()).Shape(); }
    return TopoDS_Shape();
}
TopoDS_Shape cap_shell(const TopoDS_Shape& shape) {
    if (shape.ShapeType() == TopAbs_SOLID) return shape;
    if (shape.ShapeType() != TopAbs_SHELL && shape.ShapeType() != TopAbs_FACE) return shape;

    // Try to sew everything and make a solid
    BRepBuilderAPI_Sewing sewer;
    sewer.Add(shape);
    
    // Find all free edges (boundary edges)
    TopTools_IndexedDataMapOfShapeListOfShape edgeFaceMap;
    TopExp::MapShapesAndAncestors(shape, TopAbs_EDGE, TopAbs_FACE, edgeFaceMap);
    
    TopTools_ListOfShape freeEdges;
    for (int i = 1; i <= edgeFaceMap.Extent(); ++i) {
        if (edgeFaceMap(i).Extent() == 1) { // Edge belongs to only one face -> it's a free boundary
            freeEdges.Append(edgeFaceMap.FindKey(i));
        }
    }
    
    if (!freeEdges.IsEmpty()) {
        BRepBuilderAPI_MakeWire mkWire;
        for (TopTools_ListIteratorOfListOfShape it(freeEdges); it.More(); it.Next()) {
            mkWire.Add(TopoDS::Edge(it.Value()));
        }
        if (mkWire.IsDone()) {
            // This wire might actually be multiple closed wires (one for each open end)
            TopExp_Explorer wireExp(mkWire.Wire(), TopAbs_WIRE);
            while (wireExp.More()) {
                TopoDS_Wire w = TopoDS::Wire(wireExp.Current());
                BRepBuilderAPI_MakeFace mkFace(w, true); // true = planar
                if (mkFace.IsDone()) {
                    sewer.Add(mkFace.Face());
                }
                wireExp.Next();
            }
        }
    }
    
    sewer.Perform();
    TopoDS_Shape sewed = sewer.SewedShape();
    
    TopExp_Explorer shellExp(sewed, TopAbs_SHELL);
    if (shellExp.More()) {
        BRepBuilderAPI_MakeSolid mkSolid;
        while (shellExp.More()) {
            TopoDS_Shell sh = TopoDS::Shell(shellExp.Current());
            ShapeFix_Shell fixer(sh);
            fixer.Perform();
            mkSolid.Add(fixer.Shell());
            shellExp.Next();
        }
        if (mkSolid.IsDone()) {
            return mkSolid.Solid();
        }
    }
    if (sewed.ShapeType() == TopAbs_SOLID) return sewed;
    return shape;
}
TopoDS_Shape make_sweep(
    const TopoDS_Shape& profile,
    const TopoDS_Shape& path,
    const std::string& frame_mode,
    double sweep_roll_degrees,
    bool helix_axis_valid,
    const gp_Pnt& helix_axis_origin,
    const gp_Dir& helix_axis_dir
) {
    if (profile.IsNull() || path.IsNull()) return TopoDS_Shape();
    log_debug("make_sweep: Start sweep.");
    
    // 1. Convert path to wire
    TopoDS_Wire path_wire;
    if (path.ShapeType() == TopAbs_WIRE) {
        path_wire = TopoDS::Wire(path);
    } else if (path.ShapeType() == TopAbs_EDGE) {
        BRepBuilderAPI_MakeWire wireMaker(TopoDS::Edge(path));
        if (wireMaker.IsDone()) path_wire = wireMaker.Wire();
    }
    
    if (path_wire.IsNull()) {
        log_debug("make_sweep: Path is not a valid wire or edge.");
        return TopoDS_Shape();
    }

    // 2. Extract wire from profile (MakePipeShell.Add() requires Wire, NOT Face!)
    TopoDS_Wire profile_wire;
    bool profile_is_face = false;
    
    if (profile.ShapeType() == TopAbs_FACE) {
        profile_is_face = true;
        // Extract the outer wire from the face
        TopExp_Explorer wireExp(profile, TopAbs_WIRE);
        if (wireExp.More()) {
            profile_wire = TopoDS::Wire(wireExp.Current());
            log_debug("make_sweep: Extracted outer wire from FACE profile.");
        }
    } else if (profile.ShapeType() == TopAbs_WIRE) {
        profile_wire = TopoDS::Wire(profile);
        // Check if the wire is closed - if so, we can make a solid
        profile_is_face = true; // closed wire can also produce solid
        log_debug("make_sweep: Profile is already a WIRE.");
    } else if (profile.ShapeType() == TopAbs_EDGE) {
        BRepBuilderAPI_MakeWire mw(TopoDS::Edge(profile));
        if (mw.IsDone()) {
            profile_wire = mw.Wire();
            log_debug("make_sweep: Converted EDGE profile to WIRE.");
        }
    }
    
    if (profile_wire.IsNull()) {
        log_debug("make_sweep: Could not extract wire from profile. Falling back to MakePipe.");
        // Fallback: use simple MakePipe which accepts any shape
        BRepOffsetAPI_MakePipe pipe(path_wire, profile);
        if (pipe.IsDone()) return pipe.Shape();
        return TopoDS_Shape();
    }

    auto build_pipe_shell = [&]() -> TopoDS_Shape {
        BRepOffsetAPI_MakePipeShell pipeShell(path_wire);
        pipeShell.SetMode(Standard_False); // CorrectedFrenet to avoid twisting
        pipeShell.Add(profile_wire);
        pipeShell.Build();
        
        if (!pipeShell.IsDone()) {
            log_debug("make_sweep: MakePipeShell failed. Falling back to MakePipe.");
            BRepOffsetAPI_MakePipe pipe(path_wire, profile);
            if (pipe.IsDone()) return pipe.Shape();
            return TopoDS_Shape();
        }
        
        if (profile_is_face) {
            if (pipeShell.MakeSolid()) {
                log_debug("make_sweep: MakeSolid succeeded!");
            } else {
                log_debug("make_sweep: MakeSolid failed. Will try manual capping.");
            }
        }
        
        TopoDS_Shape result = pipeShell.Shape();
        if (profile_is_face && result.ShapeType() != TopAbs_SOLID) {
            try {
                log_debug("make_sweep: Result is not a solid. Performing manual capping...");
                TopoDS_Shape firstS = pipeShell.FirstShape();
                TopoDS_Shape lastS = pipeShell.LastShape();
                
                BRepBuilderAPI_Sewing sewer;
                sewer.Add(result);
                
                bool capped_any = false;
                if (!firstS.IsNull() && (firstS.ShapeType() == TopAbs_WIRE || firstS.ShapeType() == TopAbs_EDGE)) {
                    TopoDS_Wire w = (firstS.ShapeType() == TopAbs_EDGE) ? BRepBuilderAPI_MakeWire(TopoDS::Edge(firstS)).Wire() : TopoDS::Wire(firstS);
                    if (!w.IsNull()) {
                        BRepBuilderAPI_MakeFace mf(w, Standard_True);
                        if (mf.IsDone()) {
                            sewer.Add(mf.Face());
                            capped_any = true;
                            log_debug("make_sweep: Capped start face.");
                        }
                    }
                }
                if (!lastS.IsNull() && (lastS.ShapeType() == TopAbs_WIRE || lastS.ShapeType() == TopAbs_EDGE)) {
                    TopoDS_Wire w = (lastS.ShapeType() == TopAbs_EDGE) ? BRepBuilderAPI_MakeWire(TopoDS::Edge(lastS)).Wire() : TopoDS::Wire(lastS);
                    if (!w.IsNull()) {
                        BRepBuilderAPI_MakeFace mf(w, Standard_True);
                        if (mf.IsDone()) {
                            sewer.Add(mf.Face());
                            capped_any = true;
                            log_debug("make_sweep: Capped end face.");
                        }
                    }
                }
                
                if (capped_any) {
                    sewer.Perform();
                    TopoDS_Shape sewed = sewer.SewedShape();
                    
                    TopExp_Explorer shellExp(sewed, TopAbs_SHELL);
                    if (shellExp.More()) {
                        BRepBuilderAPI_MakeSolid mkSolid;
                        while (shellExp.More()) {
                            TopoDS_Shell sh = TopoDS::Shell(shellExp.Current());
                            ShapeFix_Shell fixer(sh);
                            fixer.Perform();
                            mkSolid.Add(fixer.Shell());
                            shellExp.Next();
                        }
                        if (mkSolid.IsDone()) {
                            result = mkSolid.Solid();
                            log_debug("make_sweep: Manual capping and Solid creation succeeded!");
                        }
                    } else if (sewed.ShapeType() == TopAbs_SOLID) {
                        result = sewed;
                        log_debug("make_sweep: Sewing directly produced a Solid!");
                    }
                }
            } catch (const std::exception& e) {
                std::stringstream ss;
                ss << "make_sweep: Exception during manual capping: " << e.what();
                log_debug(ss.str());
            } catch (...) {
                log_debug("make_sweep: Unknown exception during manual capping.");
            }
        }
        return result;
    };

    auto build_helix_axis_sweep = [&]() -> TopoDS_Shape {
        if (!helix_axis_valid) {
            log_debug("make_sweep: HELIX_AXIS requested but helix axis is unavailable.");
            return TopoDS_Shape();
        }

        GProp_GProps path_props;
        BRepGProp::LinearProperties(path_wire, path_props);
        double path_length = path_props.Mass();
        int sample_count = std::max(48, std::min(320, (int)std::ceil(std::max(path_length, 0.1) / 0.05)));

        BRepAdaptor_CompCurve curve(path_wire, Standard_True);
        double u0 = curve.FirstParameter();
        double u1 = curve.LastParameter();
        if (!(u1 > u0)) {
            log_debug("make_sweep: Invalid path parameter range for HELIX_AXIS.");
            return TopoDS_Shape();
        }

        gp_Vec axis_vec(helix_axis_dir);
        double prev_angle = 0.0;
        double unwrapped_angle = 0.0;
        bool has_prev_angle = false;
        bool start_frame_ready = false;
        gp_Ax3 start_frame;
        gp_Vec basis_x;
        gp_Vec basis_y;

        BRepOffsetAPI_ThruSections loft(profile_is_face, Standard_True);
        loft.CheckCompatibility(Standard_False);

        for (int s = 0; s <= sample_count; ++s) {
            double t = (double)s / (double)sample_count;
            double u = u0 + (u1 - u0) * t;

            gp_Pnt point;
            gp_Vec tangent;
            curve.D1(u, point, tangent);
            if (tangent.Magnitude() <= 1e-9) {
                continue;
            }
            tangent.Normalize();

            gp_Vec axis_to_point(helix_axis_origin, point);
            gp_Vec radial = axis_to_point - axis_vec.Multiplied(axis_to_point.Dot(axis_vec));

            if (radial.Magnitude() <= 1e-9) {
                if (!start_frame_ready) {
                    radial = tangent.Crossed(axis_vec);
                } else {
                    radial = basis_x;
                }
            }
            if (radial.Magnitude() <= 1e-9) {
                continue;
            }
            radial.Normalize();

            if (!start_frame_ready) {
                basis_x = radial;
                basis_y = axis_vec.Crossed(basis_x);
                if (basis_y.Magnitude() <= 1e-9) {
                    basis_y = tangent.Crossed(basis_x);
                }
                if (basis_y.Magnitude() <= 1e-9) {
                    continue;
                }
                basis_y.Normalize();
            }

            double angle = std::atan2(radial.Dot(basis_y), radial.Dot(basis_x));
            if (!has_prev_angle) {
                prev_angle = angle;
                unwrapped_angle = angle;
                has_prev_angle = true;
            } else {
                double delta = angle - prev_angle;
                while (delta > M_PI) delta -= 2.0 * M_PI;
                while (delta < -M_PI) delta += 2.0 * M_PI;
                unwrapped_angle += delta;
                prev_angle = angle;
            }

            double roll_turns = unwrapped_angle / (2.0 * M_PI);
            double roll_angle = sweep_roll_degrees * M_PI / 180.0 * roll_turns;

            gp_Vec frame_x = radial;
            if (std::abs(roll_angle) > 1e-12) {
                gp_Trsf roll_tf;
                roll_tf.SetRotation(gp_Ax1(point, gp_Dir(tangent)), roll_angle);
                frame_x.Transform(roll_tf);
            }
            if (frame_x.Magnitude() <= 1e-9) {
                continue;
            }
            frame_x.Normalize();

            gp_Ax3 current_frame(point, gp_Dir(tangent), gp_Dir(frame_x));
            if (!start_frame_ready) {
                start_frame = current_frame;
                start_frame_ready = true;
            }

            gp_Trsf delta_tf;
            delta_tf.SetDisplacement(start_frame, current_frame);

            TopoDS_Shape section_shape = BRepBuilderAPI_Transform(profile_wire, delta_tf, true).Shape();
            TopoDS_Wire section_wire;
            if (section_shape.ShapeType() == TopAbs_WIRE) {
                section_wire = TopoDS::Wire(section_shape);
            } else {
                TopExp_Explorer wireExp(section_shape, TopAbs_WIRE);
                if (wireExp.More()) {
                    section_wire = TopoDS::Wire(wireExp.Current());
                }
            }

            if (!section_wire.IsNull()) {
                loft.AddWire(section_wire);
            }
        }

        if (!start_frame_ready) {
            log_debug("make_sweep: HELIX_AXIS could not build a valid start frame.");
            return TopoDS_Shape();
        }

        loft.Build();
        if (!loft.IsDone()) {
            log_debug("make_sweep: HELIX_AXIS loft failed.");
            return TopoDS_Shape();
        }

        TopoDS_Shape result = loft.Shape();
        if (profile_is_face && result.ShapeType() != TopAbs_SOLID) {
            result = cap_shell(result);
        }
        return result;
    };

    auto build_helix_axis_pipe_shell = [&]() -> TopoDS_Shape {
        if (!helix_axis_valid) {
            return TopoDS_Shape();
        }

        GProp_GProps path_props;
        BRepGProp::LinearProperties(path_wire, path_props);
        double path_length = path_props.Mass();
        int sample_count = std::max(64, std::min(384, (int)std::ceil(std::max(path_length, 0.1) / 0.04)));

        BRepAdaptor_CompCurve curve(path_wire, Standard_True);
        double u0 = curve.FirstParameter();
        double u1 = curve.LastParameter();
        if (!(u1 > u0)) {
            return TopoDS_Shape();
        }

        gp_Vec axis_vec(helix_axis_dir);
        axis_vec.Normalize();

        Bnd_Box profile_bbox;
        BRepBndLib::Add(profile_wire, profile_bbox, false);
        Standard_Real xmin = 0.0, ymin = 0.0, zmin = 0.0, xmax = 0.0, ymax = 0.0, zmax = 0.0;
        profile_bbox.Get(xmin, ymin, zmin, xmax, ymax, zmax);
        double profile_span = std::max({std::abs(xmax - xmin), std::abs(ymax - ymin), std::abs(zmax - zmin), 1e-3});
        double guide_distance = std::max(profile_span * 2.0, 0.05);

        double prev_angle = 0.0;
        double unwrapped_angle = 0.0;
        bool has_prev_angle = false;
        gp_Vec basis_x;
        gp_Vec basis_y;
        bool basis_ready = false;

        TColgp_Array1OfPnt guide_pts(1, sample_count + 1);
        int valid_pts = 0;

        for (int s = 0; s <= sample_count; ++s) {
            double t = (double)s / (double)sample_count;
            double u = u0 + (u1 - u0) * t;

            gp_Pnt point;
            gp_Vec tangent;
            curve.D1(u, point, tangent);
            if (tangent.Magnitude() <= 1e-9) {
                continue;
            }
            tangent.Normalize();

            gp_Vec axis_to_point(helix_axis_origin, point);
            gp_Vec radial = axis_to_point - axis_vec.Multiplied(axis_to_point.Dot(axis_vec));
            if (radial.Magnitude() <= 1e-9) {
                if (basis_ready) {
                    radial = basis_x;
                } else {
                    radial = tangent.Crossed(axis_vec);
                }
            }
            if (radial.Magnitude() <= 1e-9) {
                continue;
            }
            radial.Normalize();

            if (!basis_ready) {
                basis_x = radial;
                basis_y = axis_vec.Crossed(basis_x);
                if (basis_y.Magnitude() <= 1e-9) {
                    basis_y = tangent.Crossed(basis_x);
                }
                if (basis_y.Magnitude() <= 1e-9) {
                    continue;
                }
                basis_y.Normalize();
                basis_ready = true;
            }

            double angle = std::atan2(radial.Dot(basis_y), radial.Dot(basis_x));
            if (!has_prev_angle) {
                prev_angle = angle;
                unwrapped_angle = angle;
                has_prev_angle = true;
            } else {
                double delta = angle - prev_angle;
                while (delta > M_PI) delta -= 2.0 * M_PI;
                while (delta < -M_PI) delta += 2.0 * M_PI;
                unwrapped_angle += delta;
                prev_angle = angle;
            }

            double roll_turns = unwrapped_angle / (2.0 * M_PI);
            double roll_angle = sweep_roll_degrees * M_PI / 180.0 * roll_turns;

            gp_Vec guide_normal = radial;
            if (std::abs(roll_angle) > 1e-12) {
                gp_Trsf roll_tf;
                roll_tf.SetRotation(gp_Ax1(point, gp_Dir(tangent)), roll_angle);
                guide_normal.Transform(roll_tf);
            }
            if (guide_normal.Magnitude() <= 1e-9) {
                continue;
            }
            guide_normal.Normalize();

            gp_Pnt guide_point = point.Translated(guide_normal.Multiplied(guide_distance));
            guide_pts.SetValue(valid_pts + 1, guide_point);
            valid_pts++;
        }

        if (valid_pts < 4) {
            log_debug("make_sweep: HELIX_AXIS guide spine has too few valid points.");
            return TopoDS_Shape();
        }

        TColgp_Array1OfPnt fit_pts(1, valid_pts);
        for (int i = 1; i <= valid_pts; ++i) {
            fit_pts.SetValue(i, guide_pts.Value(i));
        }

        TopoDS_Wire aux_wire;
        GeomAPI_PointsToBSpline guide_builder(fit_pts);
        Handle(Geom_BSplineCurve) guide_curve = guide_builder.Curve();
        if (!guide_curve.IsNull()) {
            BRepBuilderAPI_MakeEdge guide_edge(guide_curve);
            if (guide_edge.IsDone()) {
                BRepBuilderAPI_MakeWire guide_wire(guide_edge.Edge());
                if (guide_wire.IsDone()) {
                    aux_wire = guide_wire.Wire();
                }
            }
        }

        if (aux_wire.IsNull()) {
            BRepBuilderAPI_MakeWire guide_poly;
            for (int i = 1; i < valid_pts; ++i) {
                BRepBuilderAPI_MakeEdge seg(fit_pts.Value(i), fit_pts.Value(i + 1));
                if (seg.IsDone()) {
                    guide_poly.Add(seg.Edge());
                }
            }
            if (guide_poly.IsDone()) {
                aux_wire = guide_poly.Wire();
            }
        }

        if (aux_wire.IsNull()) {
            log_debug("make_sweep: HELIX_AXIS failed to construct auxiliary spine.");
            return TopoDS_Shape();
        }

        BRepOffsetAPI_MakePipeShell pipeShell(path_wire);
        pipeShell.SetMode(aux_wire, Standard_True, BRepFill_NoContact);
        pipeShell.Add(profile_wire, Standard_False, Standard_True);
        pipeShell.Build();

        if (!pipeShell.IsDone()) {
            std::stringstream ss;
            ss << "make_sweep: HELIX_AXIS guide pipe failed. status=" << (int)pipeShell.GetStatus();
            log_debug(ss.str());
            return TopoDS_Shape();
        }

        if (profile_is_face) {
            pipeShell.MakeSolid();
        }

        TopoDS_Shape result = pipeShell.Shape();
        if (profile_is_face && result.ShapeType() != TopAbs_SOLID) {
            result = cap_shell(result);
        }
        return result;
    };

    // 3. Build sweep
    if (frame_mode == "HELIX_AXIS") {
        TopoDS_Shape helix_sweep = build_helix_axis_pipe_shell();
        if (!helix_sweep.IsNull()) {
            return helix_sweep;
        }
        log_debug("make_sweep: HELIX_AXIS guide pipe fallback to section loft.");

        helix_sweep = build_helix_axis_sweep();
        if (!helix_sweep.IsNull()) {
            return helix_sweep;
        }
        log_debug("make_sweep: HELIX_AXIS fallback to corrected Frenet pipe shell.");
    }

    TopoDS_Shape result = build_pipe_shell();
    
    {
        std::stringstream ss;
        ss << "make_sweep: Final shape type = " << result.ShapeType() 
           << " (0=COMPOUND, 2=SOLID, 3=SHELL, 4=FACE, 6=WIRE, 7=EDGE)";
        log_debug(ss.str());
    }
    
    return result;
}

TopoDS_Shape make_loft(const std::vector<TopoDS_Shape>& profiles) {
    if (profiles.size() < 2) return TopoDS_Shape();
    
    BRepOffsetAPI_ThruSections loft(Standard_True, Standard_True);
    for (const auto& shape : profiles) {
        if (shape.IsNull()) continue;
        if (shape.ShapeType() == TopAbs_WIRE) {
            loft.AddWire(TopoDS::Wire(shape));
        } else if (shape.ShapeType() == TopAbs_EDGE) {
            BRepBuilderAPI_MakeWire mw(TopoDS::Edge(shape));
            if (mw.IsDone()) loft.AddWire(mw.Wire());
        } else if (shape.ShapeType() == TopAbs_FACE) {
            TopExp_Explorer exp(shape, TopAbs_WIRE);
            if (exp.More()) loft.AddWire(TopoDS::Wire(exp.Current()));
        }
    }
    loft.Build();
    if (loft.IsDone()) {
        return loft.Shape();
    }
    return TopoDS_Shape();
}

}

TopoDS_Shape occ_core::make_helix(double radius, double height, double turns) {
    if (radius <= 1e-5 || turns <= 1e-5) {
        BRep_Builder bb;
        TopoDS_Compound comp;
        bb.MakeCompound(comp);
        return comp;
    }
    try {
        int n_pts = (int)std::ceil(turns * 96.0);
        if (n_pts < 64) n_pts = 64;

        TColgp_Array1OfPnt pts(1, n_pts + 1);
        for (int i = 0; i <= n_pts; ++i) {
            double t = (double)i / (double)n_pts;
            double ang = t * turns * 2.0 * M_PI;
            double z = t * height;
            pts.SetValue(i + 1, gp_Pnt(radius * std::cos(ang), radius * std::sin(ang), z));
        }

        GeomAPI_PointsToBSpline bspline_builder(pts);
        Handle(Geom_BSplineCurve) curve = bspline_builder.Curve();
        if (!curve.IsNull()) {
            BRepBuilderAPI_MakeEdge me(curve);
            if (me.IsDone()) {
                return me.Edge();
            }
        }

        BRepBuilderAPI_MakeWire mw;
        gp_Pnt prev_pt;
        bool has_prev = false;
        for (int i = 1; i <= pts.Length(); ++i) {
            gp_Pnt pt = pts.Value(i);
            if (has_prev) {
                BRepBuilderAPI_MakeEdge me(prev_pt, pt);
                if (me.IsDone()) {
                    mw.Add(me.Edge());
                }
            }
            prev_pt = pt;
            has_prev = true;
        }
        if (mw.IsDone()) {
            return mw.Wire();
        }
    } catch(...) {}
    
    BRep_Builder bb;
    TopoDS_Compound comp;
    bb.MakeCompound(comp);
    return comp;
}
