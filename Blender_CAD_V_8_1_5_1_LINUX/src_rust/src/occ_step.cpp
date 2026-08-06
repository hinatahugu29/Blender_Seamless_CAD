#include "occ_step.hpp"
#include "occ_utils.hpp"
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <BRepBuilderAPI_GTransform.hxx>
#include <gp_GTrsf.hxx>
#include <gp_Mat.hxx>
#include <map>
#include <mutex>
#include <atomic>

namespace occ {

static std::map<std::string, TopoDS_Shape> g_step_cache;
static std::mutex g_step_mutex;
static std::atomic<uint64_t> g_step_counter(0);

TopoDS_Shape get_step_shape(const std::string& uuid) {
    std::lock_guard<std::mutex> lock(g_step_mutex);
    auto it = g_step_cache.find(uuid);
    if (it != g_step_cache.end()) {
        return it->second;
    }
    return TopoDS_Shape();
}

std::vector<std::string> import_step(const std::string& filepath, double scale) {
    std::vector<std::string> new_uuids;
    
    STEPControl_Reader reader;
    IFSelect_ReturnStatus status = reader.ReadFile(filepath.c_str());
    
    if (status != IFSelect_RetDone) {
        occ_core::log_debug("import_step: Failed to read STEP file: " + filepath);
        return new_uuids;
    }
    
    reader.TransferRoots();
    TopoDS_Shape result = reader.OneShape();
    
    std::vector<TopoDS_Shape> parts;
    
    TopExp_Explorer exp(result, TopAbs_SOLID);
    while (exp.More()) {
        parts.push_back(exp.Current());
        exp.Next();
    }
    
    if (parts.empty()) {
        exp.Init(result, TopAbs_SHELL);
        while (exp.More()) {
            parts.push_back(exp.Current());
            exp.Next();
        }
    }
    
    if (parts.empty()) {
        exp.Init(result, TopAbs_FACE);
        while (exp.More()) {
            parts.push_back(exp.Current());
            exp.Next();
        }
    }
    
    if (parts.empty() && !result.IsNull()) {
        parts.push_back(result);
    }
    
    const double safe_scale = std::max(scale, 1e-6);
    const bool apply_scale = std::abs(safe_scale - 1.0) > 1e-9;

    std::lock_guard<std::mutex> lock(g_step_mutex);
    for (const auto& part : parts) {
        std::string new_uuid = "step_part_" + std::to_string(++g_step_counter);
        TopoDS_Shape final_part = part;
        if (apply_scale && !part.IsNull()) {
            gp_GTrsf gt_scale;
            gt_scale.SetVectorialPart(gp_Mat(
                safe_scale, 0, 0,
                0, safe_scale, 0,
                0, 0, safe_scale
            ));
            final_part = BRepBuilderAPI_GTransform(part, gt_scale, true).Shape();
        }
        g_step_cache[new_uuid] = final_part;
        new_uuids.push_back(new_uuid);
    }
    
    return new_uuids;
}

bool export_step(const std::vector<std::string>& uuids, const std::string& filepath) {
    STEPControl_Writer writer;
    Interface_Static::SetIVal("write.step.schema", 4);
    
    bool has_shapes = false;
    for (const auto& uuid : uuids) {
        TopoDS_Shape shape = get_step_shape(uuid);
        if (!shape.IsNull()) {
            writer.Transfer(shape, STEPControl_AsIs);
            has_shapes = true;
        } else {
            occ_core::log_debug("export_step: Shape not found for UUID " + uuid);
        }
    }
    
    if (!has_shapes) {
        occ_core::log_debug("export_step: No valid shapes to export");
        return false;
    }
    
    IFSelect_ReturnStatus status = writer.Write(filepath.c_str());
    if (status != IFSelect_RetDone) {
        occ_core::log_debug("export_step: Failed to write STEP file: " + filepath);
        return false;
    }
    
    return true;
}

bool export_stack_to_step(void* stack_ptr, const std::string& filepath) {
    if (!stack_ptr) return false;
    occ_core::CADStack* stack = static_cast<occ_core::CADStack*>(stack_ptr);
    if (stack->current_shape.IsNull()) return false;
    
    STEPControl_Writer writer;
    Interface_Static::SetIVal("write.step.schema", 4);
    writer.Transfer(stack->current_shape, STEPControl_AsIs);
    IFSelect_ReturnStatus status = writer.Write(filepath.c_str());
    return status == IFSelect_RetDone;
}

} // namespace occ
