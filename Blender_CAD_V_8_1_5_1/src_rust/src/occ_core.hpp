#pragma once

#include <vector>
#include <string>
#include <cstdint>
#include <TopoDS_Shape.hxx>

typedef void (*PushPointFn)(void*, float, float, float);
typedef void (*PushCountFn)(void*, int);
typedef void (*PushStringFn)(void*, const char*);

#include <map>

#include <Bnd_Box.hxx>
#include <gp_Pnt.hxx>

namespace occ_core {

#include <unordered_map>

struct VoxelGrid {
    double voxel_size = 0.5;
    std::unordered_map<int64_t, std::vector<size_t>> cells;
    
    void clear() { cells.clear(); }
    
    int64_t get_id(double px, double py, double pz) const {
        int64_t x = static_cast<int64_t>(std::floor(px / voxel_size));
        int64_t y = static_cast<int64_t>(std::floor(py / voxel_size));
        int64_t z = static_cast<int64_t>(std::floor(pz / voxel_size));
        return x ^ (y * 73856093) ^ (z * 19349663);
    }
    
    void add(const gp_Pnt& p, size_t idx) {
        cells[get_id(p.X(), p.Y(), p.Z())].push_back(idx);
    }

    void add_bbox(const Bnd_Box& box, size_t idx) {
        if (box.IsVoid()) return;
        Standard_Real xmin = 0.0, ymin = 0.0, zmin = 0.0, xmax = 0.0, ymax = 0.0, zmax = 0.0;
        box.Get(xmin, ymin, zmin, xmax, ymax, zmax);
        
        int64_t min_x = static_cast<int64_t>(std::floor(xmin / voxel_size));
        int64_t max_x = static_cast<int64_t>(std::floor(xmax / voxel_size));
        int64_t min_y = static_cast<int64_t>(std::floor(ymin / voxel_size));
        int64_t max_y = static_cast<int64_t>(std::floor(ymax / voxel_size));
        int64_t min_z = static_cast<int64_t>(std::floor(zmin / voxel_size));
        int64_t max_z = static_cast<int64_t>(std::floor(zmax / voxel_size));
        
        // 巨大な無限平面やバウンディングボックスの肥大化対策（安全装置）
        if ((max_x - min_x + 1) * (max_y - min_y + 1) * (max_z - min_z + 1) > 1000) {
            add(gp_Pnt((xmin + xmax) * 0.5, (ymin + ymax) * 0.5, (zmin + zmax) * 0.5), idx);
            return;
        }

        for (int64_t x = min_x; x <= max_x; ++x) {
            for (int64_t y = min_y; y <= max_y; ++y) {
                for (int64_t z = min_z; z <= max_z; ++z) {
                    int64_t id = x ^ (y * 73856093) ^ (z * 19349663);
                    cells[id].push_back(idx);
                }
            }
        }
    }
    
    std::vector<size_t> get_candidates(const gp_Pnt& p, double r) const {
        std::vector<size_t> res;
        int64_t min_x = static_cast<int64_t>(std::floor((p.X() - r) / voxel_size));
        int64_t max_x = static_cast<int64_t>(std::floor((p.X() + r) / voxel_size));
        int64_t min_y = static_cast<int64_t>(std::floor((p.Y() - r) / voxel_size));
        int64_t max_y = static_cast<int64_t>(std::floor((p.Y() + r) / voxel_size));
        int64_t min_z = static_cast<int64_t>(std::floor((p.Z() - r) / voxel_size));
        int64_t max_z = static_cast<int64_t>(std::floor((p.Z() + r) / voxel_size));
        
        for (int64_t x = min_x; x <= max_x; ++x) {
            for (int64_t y = min_y; y <= max_y; ++y) {
                for (int64_t z = min_z; z <= max_z; ++z) {
                    int64_t id = x ^ (y * 73856093) ^ (z * 19349663);
                    auto it = cells.find(id);
                    if (it != cells.end()) {
                        res.insert(res.end(), it->second.begin(), it->second.end());
                    }
                }
            }
        }
        std::sort(res.begin(), res.end());
        res.erase(std::unique(res.begin(), res.end()), res.end());
        return res;
    }
};

struct ClusterData {
    TopoDS_Shape raw;
    TopoDS_Shape fused;
    Bnd_Box bbox;
    std::vector<TopoDS_Face> faces;
    std::vector<gp_Pnt> face_centroids;
    std::vector<TopoDS_Edge> edges;
    std::vector<gp_Pnt> edge_midpoints;
    VoxelGrid edge_grid;
    VoxelGrid face_grid;
    bool is_fused_valid = false;
    bool is_bbox_valid = false;
    bool is_index_valid = false;
};

struct CachedResult {
    uint64_t cumulative_hash;
    std::vector<ClusterData> clusters;
    TopoDS_Shape shape;
    std::map<std::string, TopoDS_Shape> uuid_to_shape;
    TopoDS_Shape unified_shape;
    std::map<std::string, TopoDS_Shape> face_id_map; // V8.1.0: topological naming tracking
};

struct TransformCache {
    std::string op;
    double loc[3];
    double rot[3];
};

class CADStack {
public:
    TopoDS_Shape current_shape;
    std::map<std::string, uint64_t> param_hashes;
    std::map<std::string, TopoDS_Shape> primitive_cache;
    std::vector<CachedResult> stack_results;
    std::map<std::string, TransformCache> transform_cache;
    std::unordered_map<std::string, std::vector<std::string>> modifier_target_assignment_cache;
    std::unordered_map<std::string, int> modifier_target_cluster_cache;
    double last_deflection = -1.0;
    bool last_fast_mode = false;
};
    void set_debug_logging(bool enabled);

    void* create_cad_stack();
    void delete_cad_stack(void* stack_ptr);

    bool update_geometry(
        void* stack_ptr,
        int n_prims,
        const char** types,
        const char** ops,
        const char** uuids,
        const double* locs,
        const double* rots,
        const double* rots_quat,
        const double* sizes,
        const double* radii,
        const double* pipe_radii,
        const double* a_starts,
        const double* a_ends,
        const char** target_lineages,
        const char** reference_lineages,
        const int* fill_closed,
        const int* use_pipe,
        const double* extrude_heights,
        const double* radii2,
        const double* minor_radii,
        const int* sides,
        const double* modules,
        const double* pressure_angles,
        const char** target_uuids,
        const int* counts,
        const double* distances,
        const char** pattern_axes,
        const char** top_shapes,
        const char** bot_shapes,
        const double* all_pts,
        const int* pt_counts,
        const double* all_segments,
        const int* segment_counts,
        const uint64_t* hashes,
        const uint64_t* geo_hashes,
        // V8.1.5: 可変フィレット - primitive毎の "token=radius|..." 個別半径上書き文字列
        const char** edge_radii_joined,
        double fillet_radius,
        double deflection,
        const char** f_lineages,
        int n_lineages,
        void* points_vec,
        void* counts_vec,
        void* lineages_out_vec,
        PushPointFn push_point,
        PushCountFn push_count,
        PushStringFn push_string,
        bool fast_mode,
        double* perf_out
    );

    void update_cad_geometry(
        const std::string& json_str, 
        const std::vector<std::string>& lineages, 
        double fillet_radius, 
        double deflection,
        double angular_deflection,
        void* v_ptr, void* c_ptr, void* l_ptr,
        PushPointFn push_point, PushCountFn push_count, PushStringFn push_string
    );

    void generate_full_mesh(void* stack_ptr, double deflection, double angular_deflection, bool fast_mode, void* verts_vec, void* tris_vec, void* f_ids_vec, void* f_t_counts_vec, PushPointFn push_point, PushCountFn push_count, PushStringFn push_string);
    // Interactive CSG preview: tessellate the base (clusters before the tool at
    // tool_index) and the tool (uuid_to_shape, world-space at drag start) into two
    // welded meshes. Read-only; reuses the standard BRepMesh path. Returns true if
    // both meshes were produced.
    bool tessellate_preview_meshes(void* stack_ptr, int tool_index, const char* tool_uuid,
        double deflection, double angular_deflection,
        void* base_v, void* base_t, void* tool_v, void* tool_t,
        PushPointFn push_point, PushCountFn push_count);
    int get_face_count(void* stack_ptr);
    int get_face_hash(void* stack_ptr, int i);
    int get_edge_hash(void* stack_ptr, int i);
    void get_face_mesh(void* stack_ptr, int i, double deflection, void* verts_vec, void* tris_vec, void* f_ids_vec, void* f_t_counts_vec, PushPointFn push_point, PushCountFn push_count, PushStringFn push_string);

bool pick_edge(
    void* stack_ptr,
    const double* ray_o,
    const double* ray_d,
    double tolerance,
    char* out_lid,
    double* out_p
);

bool pick_face(
    void* stack_ptr,
    const double* ray_o,
    const double* ray_d,
    double tolerance,
    char* out_lid,
    double* out_p
);

bool pick_edge_from_stack(void* stack_ptr, int stack_idx, const double* o, const double* d, double t, char* l, double* p);
bool pick_face_from_stack(void* stack_ptr, int stack_idx, const double* o, const double* d, double t, char* l, double* p);
bool pick_vertex_from_stack(void* stack_ptr, int stack_idx, const double* o, const double* d, double t, char* l, double* p);
bool pick_midpoint_from_stack(void* stack_ptr, int stack_idx, const double* o, const double* d, double t, char* l, double* p);

    int get_edge_count(void* stack_ptr);
    void get_edge_points(void* stack_ptr, int i, double deflection, double angular_deflection, bool fast_mode, void* points_vec, void* counts_vec, void* lineages_out_vec, PushPointFn push_point, PushCountFn push_count, PushStringFn push_string);
    void generate_full_edges(void* stack_ptr, double deflection, double angular_deflection, bool fast_mode, void* points_vec, void* counts_vec, void* lineages_out_vec, PushPointFn push_point, PushCountFn push_count, PushStringFn push_string);
void make_variable_box_mesh(
    double top_w, double top_h, 
    double bottom_w, double bottom_h, 
    double height, 
    double deflection,
    void* verts_vec, void* tris_vec, void* normals_vec,
    PushPointFn push_point, PushCountFn push_count
);

// スタックの質量特性と外形寸法。out は 11 個の double
// [体積, 表面積, 重心xyz, bbox(xmin,ymin,zmin,xmax,ymax,zmax)]
bool measure_stack(void* stack_ptr, double* out);

std::string get_version();

} // namespace occ_core
