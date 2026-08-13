#pragma once
#include "occ_common.hpp"
#include <STEPControl_Reader.hxx>
#include <STEPControl_Writer.hxx>
#include <Interface_Static.hxx>

namespace occ {
    // Import STEP file. Returns a list of newly registered UUIDs.
    std::vector<std::string> import_step(const std::string& filepath, double scale = 1.0);
    
    // Export shapes corresponding to the given UUIDs to a STEP file.
    bool export_step(const std::vector<std::string>& uuids, const std::string& filepath);
    
    // Export the result of a CADStack to a STEP file.
    // scale は「1 Blender 単位を何 mm として書き出すか」。1.0 で従来どおり。
    bool export_stack_to_step(void* stack_ptr, const std::string& filepath, double scale = 1.0);
    
    // Get a cached STEP shape by UUID
    TopoDS_Shape get_step_shape(const std::string& uuid);
}
