#include "occ_common.hpp"
#include "occ_modifiers.hpp"
#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <TopTools_MapOfShape.hxx>
#include "occ_utils.hpp"
#include <BRepTools_WireExplorer.hxx>
#include <ShapeAnalysis_FreeBounds.hxx>
#include <TopTools_HSequenceOfShape.hxx>
#include <Bnd_Box.hxx>
#include <BRepBndLib.hxx>
#include <BRepClass3d_SolidClassifier.hxx>
#include <TopExp.hxx>
#include <chrono>
#include <unordered_map>
#include "occ_core.hpp"
namespace occ_core {
// occ_modifiers.cpp

static std::unordered_map<std::string, std::vector<TopoDS_Edge>> g_semantic_edge_history;
static std::unordered_map<std::string, std::vector<TopoDS_Face>> g_face_history;
static std::unordered_map<std::string, std::vector<int>> g_modifier_edge_resolution_cache;
static ModifierPerfBreakdown g_modifier_perf_breakdown;
struct OpeningLoopDescriptor {
    gp_Pnt centroid;
    double bbox_diag = 0.0;
    int edge_count = 0;
    double min_seed_dist = 1e100;
    std::vector<TopoDS_Edge> edges;
};
struct ShellOpeningLoopRecord {
    gp_Pnt seed_point;
    OpeningLoopDescriptor loop;
};
static std::vector<ShellOpeningLoopRecord> g_shell_opening_loops;
static std::vector<TopoDS_Edge> find_best_opening_loop_edges(const TopoDS_Shape& shape, const std::string& token, double* out_min_dist = nullptr);

void reset_modifier_tracking() {
    g_semantic_edge_history.clear();
    g_face_history.clear();
    g_shell_opening_loops.clear();
    g_modifier_edge_resolution_cache.clear();
}

void reset_modifier_perf_breakdown() {
    g_modifier_perf_breakdown = ModifierPerfBreakdown{};
}

ModifierPerfBreakdown get_modifier_perf_breakdown() {
    return g_modifier_perf_breakdown;
}

static void append_unique_edge(std::vector<TopoDS_Edge>& edges, const TopoDS_Edge& candidate) {
    if (candidate.IsNull() || BRep_Tool::Degenerated(candidate)) return;
    for (const auto& existing : edges) {
        if (existing.IsSame(candidate)) return;
    }
    edges.push_back(candidate);
}

static bool loop_contains_edge(const OpeningLoopDescriptor& loop, const TopoDS_Edge& edge) {
    if (edge.IsNull()) return false;
    for (const auto& candidate : loop.edges) {
        if (!candidate.IsNull() && candidate.IsSame(edge)) return true;
    }
    return false;
}

static gp_Pnt edge_representative_point(const TopoDS_Edge& edge) {
    if (edge.IsNull()) return gp_Pnt(0, 0, 0);
    try {
        Standard_Real first = 0.0;
        Standard_Real last = 0.0;
        Handle(Geom_Curve) curve = BRep_Tool::Curve(edge, first, last);
        if (!curve.IsNull()) {
            return curve->Value(0.5 * (first + last));
        }
    } catch (...) {}

    TopExp_Explorer exp(edge, TopAbs_VERTEX);
    if (exp.More()) {
        return BRep_Tool::Pnt(TopoDS::Vertex(exp.Current()));
    }
    return gp_Pnt(0, 0, 0);
}

static bool loop_geometrically_matches_edge(const OpeningLoopDescriptor& loop, const TopoDS_Edge& edge, double tol = 5.0e-3) {
    if (edge.IsNull() || loop.edges.empty()) return false;
    gp_Pnt probe = edge_representative_point(edge);
    for (const auto& candidate : loop.edges) {
        if (candidate.IsNull()) continue;
        if (safe_edge_point_distance(candidate, probe) <= tol) {
            return true;
        }
    }
    return false;
}

static void append_unique_face(std::vector<TopoDS_Face>& faces, const TopoDS_Face& candidate) {
    if (candidate.IsNull()) return;
    for (const auto& existing : faces) {
        if (existing.IsSame(candidate)) return;
    }
    faces.push_back(candidate);
}

static std::vector<TopoDS_Edge> resolve_semantic_history_edges(const std::string& token) {
    auto it = g_semantic_edge_history.find(token);
    if (it == g_semantic_edge_history.end()) return {};
    return it->second;
}

bool describe_tracked_edge_loop(const TopoDS_Shape& shape, const TopoDS_Edge& edge, gp_Pnt& out_centroid, double& out_bbox_diag, int& out_edge_count) {
    (void)shape;
    if (edge.IsNull()) return false;

    for (const auto& rec : g_shell_opening_loops) {
        if (loop_contains_edge(rec.loop, edge) || loop_geometrically_matches_edge(rec.loop, edge)) {
            out_centroid = rec.loop.centroid;
            out_bbox_diag = rec.loop.bbox_diag;
            out_edge_count = rec.loop.edge_count;
            return true;
        }
    }

    for (const auto& entry : g_semantic_edge_history) {
        OpeningLoopDescriptor loop;
        for (const auto& candidate : entry.second) append_unique_edge(loop.edges, candidate);
        if (loop.edges.empty()) continue;
        if (!loop_contains_edge(loop, edge) && !loop_geometrically_matches_edge(loop, edge)) continue;

        Bnd_Box box;
        for (const auto& candidate : loop.edges) {
            BRepBndLib::Add(candidate, box);
        }
        loop.edge_count = static_cast<int>(loop.edges.size());
        if (!box.IsVoid()) {
            double xmin, ymin, zmin, xmax, ymax, zmax;
            box.Get(xmin, ymin, zmin, xmax, ymax, zmax);
            loop.centroid = gp_Pnt(0.5 * (xmin + xmax), 0.5 * (ymin + ymax), 0.5 * (zmin + zmax));
            loop.bbox_diag = gp_Pnt(xmin, ymin, zmin).Distance(gp_Pnt(xmax, ymax, zmax));
        } else {
            loop.centroid = gp_Pnt(0, 0, 0);
            loop.bbox_diag = 0.0;
        }

        out_centroid = loop.centroid;
        out_bbox_diag = loop.bbox_diag;
        out_edge_count = loop.edge_count;
        return true;
    }

    static int miss_log_count = 0;
    if (miss_log_count < 20) {
        log_debug(
            "[TRACK_LOOP] Miss: shell_loops=" + std::to_string(g_shell_opening_loops.size()) +
            " semantic_histories=" + std::to_string(g_semantic_edge_history.size())
        );
        miss_log_count++;
    }
    return false;
}

static bool parse_face_seed_point(const std::string& lid, gp_Pnt& out_point) {
    if (lid.find("Face:") != 0) return false;
    size_t at_pos = lid.rfind("@");
    if (at_pos == std::string::npos) return false;
    double x = 0.0, y = 0.0, z = 0.0;
    if (sscanf(lid.c_str() + at_pos + 1, "%lf;%lf;%lf", &x, &y, &z) == 3) {
        out_point = gp_Pnt(x, y, z);
        return true;
    }
    return false;
}

static std::vector<TopoDS_Face> resolve_face_history_targets(const std::string& token) {
    auto it = g_face_history.find(token);
    if (it == g_face_history.end()) return {};
    return it->second;
}

static std::vector<TopoDS_Face> find_nearest_faces_to_point(const TopoDS_Shape& shape, const gp_Pnt& target_point, double dist_limit = 5e-2) {
    std::vector<TopoDS_Face> resolved;
    TopTools_IndexedMapOfShape fm;
    TopExp::MapShapes(shape, TopAbs_FACE, fm);
    double best_dist = 1e100;
    for (int i = 1; i <= fm.Extent(); ++i) {
        TopoDS_Face face = TopoDS::Face(fm.FindKey(i));
        double d = safe_face_point_distance(face, target_point);
        if (d + 1e-9 < best_dist) {
            best_dist = d;
            resolved.clear();
            append_unique_face(resolved, face);
        }
    }
    if (best_dist > dist_limit) resolved.clear();
    return resolved;
}

static std::vector<TopoDS_Face> resolve_faces_for_token(const TopoDS_Shape& shape, const std::string& token, const TopTools_IndexedMapOfShape& face_map) {
    std::vector<TopoDS_Face> resolved;
    TopoDS_Face direct = find_face_robust(token, face_map);
    if (!direct.IsNull()) {
        append_unique_face(resolved, direct);
        return resolved;
    }

    std::vector<TopoDS_Face> hist = resolve_face_history_targets(token);
    for (const auto& f : hist) append_unique_face(resolved, f);
    if (!resolved.empty()) return resolved;

    gp_Pnt seed_point;
    if (parse_face_seed_point(token, seed_point)) {
        return find_nearest_faces_to_point(shape, seed_point);
    }
    return resolved;
}

static void register_face_history_for_token(const std::string& token, const TopoDS_Shape& shape) {
    gp_Pnt seed_point;
    if (!parse_face_seed_point(token, seed_point)) return;
    std::vector<TopoDS_Face> nearest = find_nearest_faces_to_point(shape, seed_point, 2.0);
    if (!nearest.empty()) {
        g_face_history[token] = nearest;
    }
}

TopoDS_Face resolve_modifier_face_target(const TopoDS_Shape& shape, const std::string& token) {
    if (shape.IsNull() || token.empty()) return TopoDS_Face();
    TopTools_IndexedMapOfShape fm;
    TopExp::MapShapes(shape, TopAbs_FACE, fm);
    std::vector<TopoDS_Face> resolved = resolve_faces_for_token(shape, token, fm);
    return resolved.empty() ? TopoDS_Face() : resolved.front();
}

static bool parse_first_coord_segment(const std::string& token, gp_Pnt& out_point) {
    size_t at_pos = token.find("@");
    if (at_pos == std::string::npos) return false;
    size_t next_at = token.find("@", at_pos + 1);
    std::string coord_text = token.substr(at_pos + 1, next_at == std::string::npos ? std::string::npos : (next_at - at_pos - 1));
    double x = 0.0, y = 0.0, z = 0.0;
    if (sscanf(coord_text.c_str(), "%lf;%lf;%lf", &x, &y, &z) == 3) {
        out_point = gp_Pnt(x, y, z);
        return true;
    }
    return false;
}

static bool parse_semloop_descriptor(const std::string& token, gp_Pnt& centroid, double& bbox_diag, int& edge_count) {
    if (token.rfind("SemLoop", 0) != 0) return false;
    if (!parse_first_coord_segment(token, centroid)) return false;
    bbox_diag = 0.0;
    edge_count = 0;
    size_t second_at = token.find("@", token.find("@") + 1);
    if (second_at == std::string::npos) return true;
    double d = 0.0;
    int n = 0;
    if (sscanf(token.c_str() + second_at + 1, "%lf;%d", &d, &n) >= 1) {
        bbox_diag = d;
        edge_count = n;
    }
    return true;
}

static std::vector<OpeningLoopDescriptor> collect_opening_loops(const TopoDS_Shape& shape) {
    std::vector<OpeningLoopDescriptor> loops;
    TopTools_IndexedMapOfShape edge_map;
    TopExp::MapShapes(shape, TopAbs_EDGE, edge_map);
    if (edge_map.Extent() == 0) return loops;

    TopTools_IndexedDataMapOfShapeListOfShape edge_to_faces_map;
    TopExp::MapShapesAndAncestors(shape, TopAbs_EDGE, TopAbs_FACE, edge_to_faces_map);

    Handle(TopTools_HSequenceOfShape) free_edges = new TopTools_HSequenceOfShape();
    for (int i = 1; i <= edge_map.Extent(); ++i) {
        TopoDS_Edge edge = TopoDS::Edge(edge_map.FindKey(i));
        if (edge.IsNull() || BRep_Tool::Degenerated(edge)) continue;
        int face_count = edge_to_faces_map.Contains(edge) ? edge_to_faces_map.FindFromKey(edge).Extent() : 0;
        if (face_count <= 1) free_edges->Append(edge);
    }
    if (free_edges->Length() == 0) return loops;

    Handle(TopTools_HSequenceOfShape) wires = new TopTools_HSequenceOfShape();
    ShapeAnalysis_FreeBounds::ConnectEdgesToWires(free_edges, 1.0e-3, false, wires);
    for (int w_idx = 1; w_idx <= wires->Length(); ++w_idx) {
        TopoDS_Wire wire = TopoDS::Wire(wires->Value(w_idx));
        if (wire.IsNull()) continue;

        OpeningLoopDescriptor desc;
        Bnd_Box box;
        for (BRepTools_WireExplorer exp(wire); exp.More(); exp.Next()) {
            TopoDS_Edge edge = exp.Current();
            if (edge.IsNull() || BRep_Tool::Degenerated(edge)) continue;
            desc.edges.push_back(edge);
            BRepBndLib::Add(edge, box);
        }
        if (desc.edges.empty()) continue;

        desc.edge_count = static_cast<int>(desc.edges.size());
        if (!box.IsVoid()) {
            double xmin, ymin, zmin, xmax, ymax, zmax;
            box.Get(xmin, ymin, zmin, xmax, ymax, zmax);
            desc.centroid = gp_Pnt(0.5 * (xmin + xmax), 0.5 * (ymin + ymax), 0.5 * (zmin + zmax));
            desc.bbox_diag = gp_Pnt(xmin, ymin, zmin).Distance(gp_Pnt(xmax, ymax, zmax));
        } else {
            desc.centroid = gp_Pnt(0, 0, 0);
        }
        loops.push_back(desc);
    }
    return loops;
}

static std::vector<OpeningLoopDescriptor> collect_face_wire_loops(const TopoDS_Shape& shape) {
    std::vector<OpeningLoopDescriptor> loops;
    TopTools_MapOfShape seen_wires;
    for (TopExp_Explorer face_exp(shape, TopAbs_FACE); face_exp.More(); face_exp.Next()) {
        TopoDS_Face face = TopoDS::Face(face_exp.Current());
        if (face.IsNull()) continue;
        for (TopExp_Explorer wire_exp(face, TopAbs_WIRE); wire_exp.More(); wire_exp.Next()) {
            TopoDS_Wire wire = TopoDS::Wire(wire_exp.Current());
            if (wire.IsNull() || seen_wires.Contains(wire)) continue;
            seen_wires.Add(wire);

            OpeningLoopDescriptor desc;
            Bnd_Box box;
            for (BRepTools_WireExplorer edge_exp(wire); edge_exp.More(); edge_exp.Next()) {
                TopoDS_Edge edge = edge_exp.Current();
                if (edge.IsNull() || BRep_Tool::Degenerated(edge)) continue;
                append_unique_edge(desc.edges, edge);
                BRepBndLib::Add(edge, box);
            }
            if (desc.edges.size() < 2) continue;

            desc.edge_count = static_cast<int>(desc.edges.size());
            if (!box.IsVoid()) {
                double xmin, ymin, zmin, xmax, ymax, zmax;
                box.Get(xmin, ymin, zmin, xmax, ymax, zmax);
                desc.centroid = gp_Pnt(0.5 * (xmin + xmax), 0.5 * (ymin + ymax), 0.5 * (zmin + zmax));
                desc.bbox_diag = gp_Pnt(xmin, ymin, zmin).Distance(gp_Pnt(xmax, ymax, zmax));
            } else {
                desc.centroid = gp_Pnt(0, 0, 0);
                desc.bbox_diag = 0.0;
            }
            loops.push_back(desc);
        }
    }
    return loops;
}

static std::vector<TopoDS_Edge> resolve_shell_history_edges(const std::string& token, double* out_min_dist = nullptr) {
    gp_Pnt centroid;
    double token_diag = 0.0;
    int token_edge_count = 0;
    bool has_sem_desc = parse_semloop_descriptor(token, centroid, token_diag, token_edge_count);
    gp_Pnt fallback_point;
    bool has_fallback_point = parse_first_coord_segment(token, fallback_point);

    double best_score = 1e100;
    std::vector<TopoDS_Edge> resolved;
    for (const auto& rec : g_shell_opening_loops) {
        double score = 1e100;
        if (has_sem_desc) {
            double centroid_d = rec.loop.centroid.Distance(centroid);
            double diag_d = std::abs(rec.loop.bbox_diag - token_diag);
            double count_d = std::abs(rec.loop.edge_count - token_edge_count);
            score = centroid_d + diag_d * 0.35 + count_d * 0.05;
        } else if (has_fallback_point) {
            score = rec.seed_point.Distance(fallback_point);
        }
        if (score < best_score) {
            best_score = score;
            resolved = rec.loop.edges;
        }
    }
    if (out_min_dist) *out_min_dist = best_score;
    return resolved;
}

static gp_Pnt face_seed_point(const TopoDS_Face& face) {
    if (face.IsNull()) return gp_Pnt(0, 0, 0);
    try {
        BRepAdaptor_Surface surf(face);
        Standard_Real u = 0.5 * (surf.FirstUParameter() + surf.LastUParameter());
        Standard_Real v = 0.5 * (surf.FirstVParameter() + surf.LastVParameter());
        return surf.Value(u, v);
    } catch (...) {
        return gp_Pnt(0, 0, 0);
    }
}

static std::vector<TopoDS_Edge> collect_face_boundary_edges(const TopoDS_Face& face) {
    std::vector<TopoDS_Edge> edges;
    if (face.IsNull()) return edges;
    for (TopExp_Explorer exp(face, TopAbs_EDGE); exp.More(); exp.Next()) {
        append_unique_edge(edges, TopoDS::Edge(exp.Current()));
    }
    return edges;
}

// 定義は下(register_shell_opening_history の後)にあるが、
// collect_shell_opening_loop_from_builder から先に呼ばれる。
// テンプレート内の非依存名は定義時点で解決される必要があり、GCC/Clang は
// ここに宣言が無いと実体化時に「declared later in the translation unit」で
// 落ちる。MSVC は遅延解決するので Windows では通っていた。
template <typename BuilderT>
static std::vector<TopoDS_Edge> collect_history_edges_from_builder(
    BuilderT& builder,
    const std::vector<TopoDS_Edge>& source_edges
);

template <typename BuilderT>
static OpeningLoopDescriptor collect_shell_opening_loop_from_builder(
    BuilderT& builder,
    const TopoDS_Face& removed_face,
    const gp_Pnt& seed
) {
    OpeningLoopDescriptor loop;
    if (removed_face.IsNull()) return loop;

    std::vector<TopoDS_Edge> source_edges = collect_face_boundary_edges(removed_face);
    loop.edges = collect_history_edges_from_builder(builder, source_edges);
    if (loop.edges.empty()) return loop;

    Bnd_Box box;
    loop.edge_count = static_cast<int>(loop.edges.size());
    loop.min_seed_dist = 1e100;
    for (const auto& edge : loop.edges) {
        if (edge.IsNull()) continue;
        BRepBndLib::Add(edge, box);
        loop.min_seed_dist = std::min(loop.min_seed_dist, safe_edge_point_distance(edge, seed));
    }
    if (!box.IsVoid()) {
        double xmin, ymin, zmin, xmax, ymax, zmax;
        box.Get(xmin, ymin, zmin, xmax, ymax, zmax);
        loop.centroid = gp_Pnt(0.5 * (xmin + xmax), 0.5 * (ymin + ymax), 0.5 * (zmin + zmax));
        loop.bbox_diag = gp_Pnt(xmin, ymin, zmin).Distance(gp_Pnt(xmax, ymax, zmax));
    }
    return loop;
}

template <typename BuilderT>
static void register_shell_opening_history(
    BuilderT& builder,
    const TopTools_ListOfShape& removed_faces
) {
    int added = 0;
    int scanned = 0;
    for (TopTools_ListIteratorOfListOfShape it(removed_faces); it.More(); it.Next()) {
        if (it.Value().ShapeType() != TopAbs_FACE) continue;
        scanned++;
        TopoDS_Face face = TopoDS::Face(it.Value());
        gp_Pnt seed = face_seed_point(face);
        OpeningLoopDescriptor loop = collect_shell_opening_loop_from_builder(builder, face, seed);
        if (!loop.edges.empty()) {
            g_shell_opening_loops.push_back({seed, loop});
            added++;
            log_debug(
                "[SHELL_TRACK] Registered opening loop: edges=" + std::to_string(loop.edge_count) +
                " diag=" + std::to_string(loop.bbox_diag) +
                " centroid=(" + std::to_string(loop.centroid.X()) + "," +
                std::to_string(loop.centroid.Y()) + "," +
                std::to_string(loop.centroid.Z()) + ")" +
                " seed=(" + std::to_string(seed.X()) + "," +
                std::to_string(seed.Y()) + "," +
                std::to_string(seed.Z()) + ")"
            );
        } else {
            log_debug(
                "[SHELL_TRACK] Failed to register opening loop for removed face seed=(" +
                std::to_string(seed.X()) + "," +
                std::to_string(seed.Y()) + "," +
                std::to_string(seed.Z()) + ")"
            );
        }
    }
    log_debug(
        "[SHELL_TRACK] register_shell_opening_history done: removed_faces=" +
        std::to_string(scanned) + " added=" + std::to_string(added) +
        " total_loops=" + std::to_string(g_shell_opening_loops.size())
    );
}

template <typename BuilderT>
static std::vector<TopoDS_Edge> collect_history_edges_from_builder(BuilderT& builder, const std::vector<TopoDS_Edge>& source_edges) {
    std::vector<TopoDS_Edge> resolved;
    for (const auto& src_edge : source_edges) {
        if (src_edge.IsNull()) continue;

        const TopTools_ListOfShape& modified = builder.Modified(src_edge);
        for (TopTools_ListIteratorOfListOfShape it(modified); it.More(); it.Next()) {
            if (it.Value().ShapeType() == TopAbs_EDGE) {
                append_unique_edge(resolved, TopoDS::Edge(it.Value()));
            }
        }

        const TopTools_ListOfShape& generated = builder.Generated(src_edge);
        for (TopTools_ListIteratorOfListOfShape it(generated); it.More(); it.Next()) {
            if (it.Value().ShapeType() == TopAbs_EDGE) {
                append_unique_edge(resolved, TopoDS::Edge(it.Value()));
            }
        }
    }
    return resolved;
}

static bool parse_seed_point_from_target(const std::string& lid, gp_Pnt& out_point) {
    if (lid.rfind("SemLoop", 0) == 0) {
        return parse_first_coord_segment(lid, out_point);
    }

    if (lid.find("Edge:") != 0) return false;
    return parse_first_coord_segment(lid, out_point);
}

static std::vector<gp_Pnt> collect_semantic_loop_seeds(const std::string& target_lineage) {
    std::vector<gp_Pnt> seeds;
    std::string t = target_lineage;
    while (t.length() > 0) {
        size_t end = t.find("|");
        std::string lid = t.substr(0, end);
        gp_Pnt seed;
        if (lid.rfind("SemLoop:OPENING@", 0) == 0 && parse_seed_point_from_target(lid, seed)) {
            seeds.push_back(seed);
        }
        if (end == std::string::npos) break;
        t = t.substr(end + 1);
    }
    return seeds;
}

static bool target_lineage_has_semantic_loop(const std::string& target_lineage) {
    std::string t = target_lineage;
    while (t.length() > 0) {
        size_t end = t.find("|");
        std::string lid = t.substr(0, end);
        if (lid.rfind("SemLoop", 0) == 0) {
            return true;
        }
        if (end == std::string::npos) break;
        t = t.substr(end + 1);
    }
    return false;
}

static bool target_lineage_has_raw_edges(const std::string& target_lineage) {
    std::string t = target_lineage;
    while (t.length() > 0) {
        size_t end = t.find("|");
        std::string lid = t.substr(0, end);
        if (lid.find("Edge:") == 0) {
            return true;
        }
        if (end == std::string::npos) break;
        t = t.substr(end + 1);
    }
    return false;
}

static bool edge_token_is_shadowed_by_semloop(const std::string& lid, const std::vector<gp_Pnt>& semloop_seeds, double tol = 2.5e-3) {
    if (semloop_seeds.empty() || lid.find("Edge:") != 0) return false;
    gp_Pnt edge_seed;
    if (!parse_seed_point_from_target(lid, edge_seed)) return false;
    for (const auto& seed : semloop_seeds) {
        if (edge_seed.Distance(seed) <= tol) return true;
    }
    return false;
}

static std::string build_modifier_shape_signature(const TopoDS_Shape& shape, const TopTools_IndexedMapOfShape& edge_map, const TopTools_IndexedMapOfShape& face_map) {
    Bnd_Box box;
    BRepBndLib::Add(shape, box);
    Standard_Real xmin = 0.0, ymin = 0.0, zmin = 0.0, xmax = 0.0, ymax = 0.0, zmax = 0.0;
    if (!box.IsVoid()) {
        box.Get(xmin, ymin, zmin, xmax, ymax, zmax);
    }
    std::ostringstream ss;
    ss.setf(std::ios::fixed);
    ss.precision(4);
    ss << "E" << edge_map.Extent()
       << "|F" << face_map.Extent()
       << "|B" << xmin << "," << ymin << "," << zmin << "," << xmax << "," << ymax << "," << zmax;
    return ss.str();
}

static std::vector<TopoDS_Edge> resolve_cached_edges(
    const std::string& cache_key,
    const std::string& token,
    const TopTools_IndexedMapOfShape& edge_map
) {
    auto it = g_modifier_edge_resolution_cache.find(cache_key);
    if (it == g_modifier_edge_resolution_cache.end()) return {};

    std::vector<TopoDS_Edge> cached_edges;
    cached_edges.reserve(it->second.size());
    for (int idx : it->second) {
        if (idx < 1 || idx > edge_map.Extent()) return {};
        TopoDS_Edge edge = TopoDS::Edge(edge_map.FindKey(idx));
        if (edge.IsNull() || BRep_Tool::Degenerated(edge)) return {};
        cached_edges.push_back(edge);
    }
    if (cached_edges.empty()) return {};

    gp_Pnt seed_point;
    if (parse_seed_point_from_target(token, seed_point)) {
        double best_dist = 1e100;
        for (const auto& edge : cached_edges) {
            best_dist = std::min(best_dist, safe_edge_point_distance(edge, seed_point));
        }
        double tol = (token.rfind("SemLoop", 0) == 0) ? 1.5e-1 : 5.0e-2;
        if (best_dist > tol) {
            return {};
        }
    }

    return cached_edges;
}

static void store_cached_edges(
    const std::string& cache_key,
    const std::vector<TopoDS_Edge>& edges,
    const TopTools_IndexedMapOfShape& edge_map
) {
    if (edges.empty()) return;
    std::vector<int> indices;
    indices.reserve(edges.size());
    for (const auto& edge : edges) {
        int idx = edge_map.FindIndex(edge);
        if (idx < 1) return;
        indices.push_back(idx);
    }
    g_modifier_edge_resolution_cache[cache_key] = std::move(indices);
}

static std::vector<TopoDS_Edge> find_best_opening_loop_edges(const TopoDS_Shape& shape, const std::string& token, double* out_min_dist) {
    std::vector<OpeningLoopDescriptor> loops = collect_opening_loops(shape);
    gp_Pnt centroid;
    double token_diag = 0.0;
    int token_edge_count = 0;
    bool has_sem_desc = parse_semloop_descriptor(token, centroid, token_diag, token_edge_count);
    gp_Pnt fallback_point;
    bool has_fallback_point = parse_seed_point_from_target(token, fallback_point);

    double best_score = 1e100;
    std::vector<TopoDS_Edge> resolved_edges;
    for (auto& loop : loops) {
        double seed_min_dist = 1e100;
        if (has_fallback_point) {
            for (const auto& edge : loop.edges) {
                seed_min_dist = std::min(seed_min_dist, safe_edge_point_distance(edge, fallback_point));
            }
        }

        double score = seed_min_dist;
        if (has_sem_desc) {
            double centroid_d = loop.centroid.Distance(centroid);
            double diag_d = std::abs(loop.bbox_diag - token_diag);
            double count_d = std::abs(loop.edge_count - token_edge_count);
            score = centroid_d + diag_d * 0.35 + count_d * 0.05 + seed_min_dist * 0.2;
        }

        if (score < best_score) {
            best_score = score;
            resolved_edges = loop.edges;
        }
    }

    if (out_min_dist) *out_min_dist = best_score;
    return resolved_edges;
}

static std::vector<TopoDS_Edge> find_best_face_wire_loop_edges(const TopoDS_Shape& shape, const std::string& token, double* out_min_dist = nullptr) {
    std::vector<OpeningLoopDescriptor> loops = collect_face_wire_loops(shape);
    gp_Pnt centroid;
    double token_diag = 0.0;
    int token_edge_count = 0;
    bool has_sem_desc = parse_semloop_descriptor(token, centroid, token_diag, token_edge_count);
    gp_Pnt fallback_point;
    bool has_fallback_point = parse_seed_point_from_target(token, fallback_point);

    double best_score = 1e100;
    std::vector<TopoDS_Edge> resolved_edges;
    for (auto& loop : loops) {
        double seed_min_dist = 1e100;
        if (has_fallback_point) {
            for (const auto& edge : loop.edges) {
                seed_min_dist = std::min(seed_min_dist, safe_edge_point_distance(edge, fallback_point));
            }
        }

        double score = seed_min_dist;
        if (has_sem_desc) {
            double centroid_d = loop.centroid.Distance(centroid);
            double diag_d = std::abs(loop.bbox_diag - token_diag);
            double count_d = std::abs(loop.edge_count - token_edge_count);
            score = centroid_d + diag_d * 0.35 + count_d * 0.10 + seed_min_dist * 0.15;
        }

        if (score < best_score) {
            best_score = score;
            resolved_edges = loop.edges;
        }
    }

    if (out_min_dist) *out_min_dist = best_score;
    return resolved_edges;
}

std::map<std::string, double> parse_edge_radii_joined(const char* joined) {
    std::map<std::string, double> out;
    if (!joined || !*joined) return out;
    std::string s(joined);
    size_t pos = 0;
    while (pos < s.length()) {
        size_t bar = s.find('|', pos);
        std::string pair = s.substr(pos, bar == std::string::npos ? std::string::npos : bar - pos);
        size_t eq = pair.rfind('=');
        if (eq != std::string::npos) {
            std::string token = pair.substr(0, eq);
            try {
                double r = std::stod(pair.substr(eq + 1));
                if (!token.empty()) out[token] = r;
            } catch (...) {}
        }
        if (bar == std::string::npos) break;
        pos = bar + 1;
    }
    return out;
}

namespace {
    // トークンの "@" より前(Edge:N など)を取り出す。座標付きトークンの
    // 微小なドリフトを無視してベース識別子だけで一致判定するため。
    std::string edge_token_base(const std::string& token) {
        size_t at = token.find('@');
        return at == std::string::npos ? token : token.substr(0, at);
    }

    // owner_token に対応する個別半径を edge_radii_map から探す。完全一致を優先し、
    // 無ければベース部分(座標を除いたエッジ識別子)で一致するエントリを使う。
    // 見つからなければ fallback_radius (= primitiveのradius) を返す。
    double lookup_edge_radius(const std::string* owner_token, const std::map<std::string, double>* edge_radii_map, double fallback_radius) {
        if (!owner_token || !edge_radii_map || edge_radii_map->empty()) return fallback_radius;
        auto exact = edge_radii_map->find(*owner_token);
        if (exact != edge_radii_map->end() && exact->second >= 0.0) return exact->second;
        const std::string base = edge_token_base(*owner_token);
        for (const auto& kv : *edge_radii_map) {
            if (kv.second < 0.0) continue;
            if (edge_token_base(kv.first) == base) return kv.second;
        }
        return fallback_radius;
    }
}

TopoDS_Shape apply_fillet(const TopoDS_Shape& result_shape, const std::string& target_lineage, double radius, std::map<std::string, TopoDS_Shape>* face_map, const std::map<std::string, double>* edge_radii_map) {
    if (result_shape.IsNull()) return result_shape;
    if (radius < 1e-6 || target_lineage.empty()) return result_shape;
    try {
        OCC_CATCH_SIGNALS
        auto t_setup_start = std::chrono::high_resolution_clock::now();
        TopTools_IndexedMapOfShape em; TopExp::MapShapes(result_shape, TopAbs_EDGE, em);
        TopTools_IndexedMapOfShape fm; TopExp::MapShapes(result_shape, TopAbs_FACE, fm);
        
        TopTools_IndexedDataMapOfShapeListOfShape edgeToFacesMap;
        TopExp::MapShapesAndAncestors(result_shape, TopAbs_EDGE, TopAbs_FACE, edgeToFacesMap);

        BRepFilletAPI_MakeFillet f(result_shape);
        TopTools_MapOfShape added_edges;
        std::unordered_map<std::string, std::vector<TopoDS_Edge>> token_source_edges;
        std::vector<gp_Pnt> semloop_seeds = collect_semantic_loop_seeds(target_lineage);
        const bool has_semantic_loops = target_lineage_has_semantic_loop(target_lineage);
        const bool has_raw_edges = target_lineage_has_raw_edges(target_lineage);
        const std::string shape_signature = build_modifier_shape_signature(result_shape, em, fm);
        int raw_edge_hits = 0;
        int added_edge_count = 0;
        auto t_setup_end = std::chrono::high_resolution_clock::now();
        g_modifier_perf_breakdown.fillet_setup_ms += std::chrono::duration<double, std::milli>(t_setup_end - t_setup_start).count();
        // is_semantic_loop: SemLoopトークン経由の追加かどうか(raw_edge_hits集計とfallback再試行判定に使う)。
        // owner_tokenはV8.1.5で可変フィレットの個別半径ルックアップ用にraw Edge:呼び出しにも渡すようになったため、
        // 「raw edgeかどうか」の判定は owner_token の有無ではなくこのフラグで行う。
        auto try_add_edge = [&](TopoDS_Edge e, const std::string* owner_token = nullptr, bool is_semantic_loop = false) {
            if (!e.IsNull() && !BRep_Tool::Degenerated(e) && !added_edges.Contains(e)) {
                GProp_GProps prop; BRepGProp::LinearProperties(e, prop);
                double len = prop.Mass();
                // V8.1.5: 可変フィレット - owner_tokenに個別半径があればそれを使う
                double edge_radius = lookup_edge_radius(owner_token, edge_radii_map, radius);
                if (len > 1e-5 && len > edge_radius * 0.5) {
                    try {
                        OCC_CATCH_SIGNALS
                        auto t_add_start = std::chrono::high_resolution_clock::now();
                        f.Add(edge_radius, e);
                        auto t_add_end = std::chrono::high_resolution_clock::now();
                        g_modifier_perf_breakdown.fillet_add_ms += std::chrono::duration<double, std::milli>(t_add_end - t_add_start).count();
                        added_edges.Add(e);
                        added_edge_count++;
                        if (!is_semantic_loop) raw_edge_hits++;
                        if (owner_token) append_unique_edge(token_source_edges[*owner_token], e);
                    } catch (...) {}
                }
            }
        };
        if (has_semantic_loops) {
            log_debug("[APPLY_FILLET] Semantic loop targets present; raw edges kept as fallback");
        }

        std::string t = target_lineage;
        while (t.length() > 0) {
            auto t_resolve_start = std::chrono::high_resolution_clock::now();
            size_t end = t.find("|"); std::string lid = t.substr(0, end);
            const std::string cache_key = std::string("FILLET|") + shape_signature + "|" + lid;

            if (lid.find("Edge:") == 0) {
                if (edge_token_is_shadowed_by_semloop(lid, semloop_seeds)) {
                    log_debug(std::string("[APPLY_FILLET] Shadowed raw edge by SemLoop: ") + lid);
                    if (end == std::string::npos) break;
                    t = t.substr(end + 1);
                    continue;
                }
                std::vector<TopoDS_Edge> cached_edges = resolve_cached_edges(cache_key, lid, em);
                if (!cached_edges.empty()) {
                    for (const auto& cached_edge : cached_edges) {
                        try_add_edge(cached_edge, &lid);
                    }
                } else {
                    std::vector<TopoDS_Edge> resolved_edges;
                    TopoDS_Edge found = find_edge_robust(lid, em, face_map);
                    if (!found.IsNull()) {
                        resolved_edges.push_back(found);
                    } else {
                        gp_Pnt seed_point;
                        if (parse_seed_point_from_target(lid, seed_point)) {
                            double loop_dist = 1e100;
                            resolved_edges = find_best_opening_loop_edges(result_shape, lid, &loop_dist);
                            if (!resolved_edges.empty() && loop_dist < 5e-2) {
                                log_debug(std::string("[APPLY_FILLET] Recovered as opening loop from seed: ") + lid);
                            } else {
                                resolved_edges.clear();
                                log_debug(std::string("[APPLY_FILLET] Edge NOT FOUND: ") + lid);
                            }
                        } else {
                            log_debug(std::string("[APPLY_FILLET] Edge NOT FOUND: ") + lid);
                        }
                    }
                    if (!resolved_edges.empty()) {
                        store_cached_edges(cache_key, resolved_edges, em);
                        for (const auto& resolved_edge : resolved_edges) {
                            try_add_edge(resolved_edge, &lid);
                        }
                    }
                }
            }
            else if (lid.rfind("SemLoop", 0) == 0) {
                if (has_raw_edges && lid.rfind("SemLoop:EDGESET@", 0) == 0) {
                    if (end == std::string::npos) break;
                    t = t.substr(end + 1);
                    continue;
                }
                std::vector<TopoDS_Edge> cached_edges = resolve_cached_edges(cache_key, lid, em);
                if (!cached_edges.empty()) {
                    for (const auto& loop_edge : cached_edges) {
                        try_add_edge(loop_edge, &lid, true);
                    }
                } else {
                    std::vector<TopoDS_Edge> loop_edges = resolve_semantic_history_edges(lid);
                    if (loop_edges.empty()) {
                        gp_Pnt seed_point;
                        if (parse_seed_point_from_target(lid, seed_point)) {
                            double shell_hist_dist = 1e100;
                            loop_edges = resolve_shell_history_edges(lid, &shell_hist_dist);
                            if (loop_edges.empty() || shell_hist_dist > 5e-2) {
                                double face_loop_dist = 1e100;
                                loop_edges = find_best_face_wire_loop_edges(result_shape, lid, &face_loop_dist);
                                if (loop_edges.empty() || face_loop_dist > 1.5e-1) {
                                    loop_edges = find_best_opening_loop_edges(result_shape, lid);
                                } else {
                                    log_debug(std::string("[APPLY_FILLET] Recovered as face wire loop from semantic token: ") + lid);
                                }
                            }
                        }
                    }
                    if (!loop_edges.empty()) {
                        store_cached_edges(cache_key, loop_edges, em);
                    }
                    for (const auto& loop_edge : loop_edges) {
                        try_add_edge(loop_edge, &lid, true);
                    }
                }
            }
            else if (lid.find("Face:") == 0) {
                TopoDS_Face face = find_face_robust(lid, fm); 
                if (!face.IsNull()) { 
                    TopExp_Explorer ex(face, TopAbs_EDGE); 
                    while (ex.More()) { try_add_edge(TopoDS::Edge(ex.Current())); ex.Next(); } 
                } 
            }
            auto t_resolve_end = std::chrono::high_resolution_clock::now();
            g_modifier_perf_breakdown.fillet_target_resolve_ms += std::chrono::duration<double, std::milli>(t_resolve_end - t_resolve_start).count();
            if (end == std::string::npos) break; t = t.substr(end + 1);
        }
        if (has_raw_edges && raw_edge_hits == 0 && f.NbContours() == 0) {
            log_debug("[APPLY_FILLET] Raw edges failed; retrying semantic loop fallback");
            std::string retry = target_lineage;
            while (retry.length() > 0) {
                auto t_resolve_start = std::chrono::high_resolution_clock::now();
                size_t end = retry.find("|");
                std::string lid = retry.substr(0, end);
                if (lid.rfind("SemLoop", 0) == 0) {
                    const std::string cache_key = std::string("FILLET|") + shape_signature + "|" + lid;
                    std::vector<TopoDS_Edge> history_edges = resolve_semantic_history_edges(lid);
                    if (!history_edges.empty()) {
                        store_cached_edges(cache_key, history_edges, em);
                        for (const auto& loop_edge : history_edges) {
                            try_add_edge(loop_edge, &lid, true);
                        }
                    } else {
                        gp_Pnt seed_point;
                        if (parse_seed_point_from_target(lid, seed_point)) {
                            double shell_hist_dist = 1e100;
                            std::vector<TopoDS_Edge> loop_edges = resolve_shell_history_edges(lid, &shell_hist_dist);
                            if (loop_edges.empty() || shell_hist_dist > 5e-2) {
                                double face_loop_dist = 1e100;
                                loop_edges = find_best_face_wire_loop_edges(result_shape, lid, &face_loop_dist);
                                if (loop_edges.empty() || face_loop_dist > 1.5e-1) {
                                    loop_edges = find_best_opening_loop_edges(result_shape, lid);
                                } else {
                                log_debug(std::string("[APPLY_FILLET] Recovered as face wire loop from semantic token: ") + lid);
                            }
                        }
                        if (!loop_edges.empty()) {
                            store_cached_edges(cache_key, loop_edges, em);
                        }
                        for (const auto& loop_edge : loop_edges) {
                            try_add_edge(loop_edge, &lid, true);
                        }
                        }
                    }
                }
                auto t_resolve_end = std::chrono::high_resolution_clock::now();
                g_modifier_perf_breakdown.fillet_target_resolve_ms += std::chrono::duration<double, std::milli>(t_resolve_end - t_resolve_start).count();
                if (end == std::string::npos) break;
                retry = retry.substr(end + 1);
            }
        }
        g_modifier_perf_breakdown.fillet_added_edges += static_cast<double>(added_edge_count);
        g_modifier_perf_breakdown.fillet_contours += static_cast<double>(f.NbContours());
        if (f.NbContours() > 0) {
            auto t_build_start = std::chrono::high_resolution_clock::now();
            f.Build();
            auto t_build_end = std::chrono::high_resolution_clock::now();
            g_modifier_perf_breakdown.fillet_build_ms += std::chrono::duration<double, std::milli>(t_build_end - t_build_start).count();
            if (f.IsDone()) {
                TopoDS_Shape out_shape = f.Shape();
                auto t_history_start = std::chrono::high_resolution_clock::now();
                for (const auto& entry : token_source_edges) {
                    if (entry.first.rfind("SemLoop", 0) != 0) continue;
                    std::vector<TopoDS_Edge> resolved = collect_history_edges_from_builder(f, entry.second);
                    if (resolved.empty()) {
                        gp_Pnt seed_point;
                        if (parse_seed_point_from_target(entry.first, seed_point)) {
                            double face_loop_dist = 1e100;
                            resolved = find_best_face_wire_loop_edges(out_shape, entry.first, &face_loop_dist);
                            if (resolved.empty() || face_loop_dist > 1.5e-1) {
                                resolved = find_best_opening_loop_edges(out_shape, entry.first);
                            }
                        }
                    }
                    if (!resolved.empty()) {
                        g_semantic_edge_history[entry.first] = resolved;
                    }
                }
                if (face_map) update_face_id_map_from_builder(*face_map, f);
                auto t_history_end = std::chrono::high_resolution_clock::now();
                g_modifier_perf_breakdown.fillet_history_ms += std::chrono::duration<double, std::milli>(t_history_end - t_history_start).count();
                return out_shape;
            }
        }
    } catch (...) {
        log_debug("[APPLY_FILLET] Exception caught");
    }
    return result_shape;
}

TopoDS_Shape apply_chamfer(const TopoDS_Shape& result_shape, const std::string& target_lineage, double radius, std::map<std::string, TopoDS_Shape>* face_map) {
    if (result_shape.IsNull()) return result_shape;
    if (radius < 1e-6 || target_lineage.empty()) return result_shape;
    try {
        OCC_CATCH_SIGNALS
        TopTools_IndexedMapOfShape em; TopExp::MapShapes(result_shape, TopAbs_EDGE, em);
        TopTools_IndexedMapOfShape fm; TopExp::MapShapes(result_shape, TopAbs_FACE, fm);
        
        TopTools_IndexedDataMapOfShapeListOfShape edgeToFacesMap;
        TopExp::MapShapesAndAncestors(result_shape, TopAbs_EDGE, TopAbs_FACE, edgeToFacesMap);

        BRepFilletAPI_MakeChamfer f(result_shape);
        TopTools_MapOfShape added_edges;
        std::unordered_map<std::string, std::vector<TopoDS_Edge>> token_source_edges;
        std::vector<gp_Pnt> semloop_seeds = collect_semantic_loop_seeds(target_lineage);
        const bool has_semantic_loops = target_lineage_has_semantic_loop(target_lineage);
        const bool has_raw_edges = target_lineage_has_raw_edges(target_lineage);
        const std::string shape_signature = build_modifier_shape_signature(result_shape, em, fm);
        int raw_edge_hits = 0;
        auto try_add_edge = [&](TopoDS_Edge e, const std::string* owner_token = nullptr) {
            if (!e.IsNull() && !BRep_Tool::Degenerated(e) && !added_edges.Contains(e)) {
                GProp_GProps prop; BRepGProp::LinearProperties(e, prop);
                double len = prop.Mass();
                if (len > 1e-5 && len > radius * 0.5) {
                    try {
                        OCC_CATCH_SIGNALS
                        f.Add(radius, e);
                        added_edges.Add(e);
                        if (!owner_token) raw_edge_hits++;
                        if (owner_token) append_unique_edge(token_source_edges[*owner_token], e);
                    } catch (...) {}
                }
            }
        };
        if (has_semantic_loops) {
            log_debug("[APPLY_CHAMFER] Semantic loop targets present; raw edges kept as fallback");
        }

        std::string t = target_lineage;
        while (t.length() > 0) {
            size_t end = t.find("|"); std::string lid = t.substr(0, end);
            const std::string cache_key = std::string("CHAMFER|") + shape_signature + "|" + lid;

            if (lid.find("Edge:") == 0) {
                if (edge_token_is_shadowed_by_semloop(lid, semloop_seeds)) {
                    log_debug(std::string("[APPLY_CHAMFER] Shadowed raw edge by SemLoop: ") + lid);
                    if (end == std::string::npos) break;
                    t = t.substr(end + 1);
                    continue;
                }
                std::vector<TopoDS_Edge> cached_edges = resolve_cached_edges(cache_key, lid, em);
                if (!cached_edges.empty()) {
                    for (const auto& cached_edge : cached_edges) {
                        try_add_edge(cached_edge);
                    }
                } else {
                    std::vector<TopoDS_Edge> resolved_edges;
                    TopoDS_Edge found = find_edge_robust(lid, em, face_map);
                    if (!found.IsNull()) {
                        resolved_edges.push_back(found);
                    } else {
                        gp_Pnt seed_point;
                        if (parse_seed_point_from_target(lid, seed_point)) {
                            double loop_dist = 1e100;
                            resolved_edges = find_best_opening_loop_edges(result_shape, lid, &loop_dist);
                            if (!resolved_edges.empty() && loop_dist < 5e-2) {
                                log_debug(std::string("[APPLY_CHAMFER] Recovered as opening loop from seed: ") + lid);
                            } else {
                                resolved_edges.clear();
                                log_debug(std::string("[APPLY_CHAMFER] Edge NOT FOUND: ") + lid);
                            }
                        } else {
                            log_debug(std::string("[APPLY_CHAMFER] Edge NOT FOUND: ") + lid);
                        }
                    }
                    if (!resolved_edges.empty()) {
                        store_cached_edges(cache_key, resolved_edges, em);
                        for (const auto& resolved_edge : resolved_edges) {
                            try_add_edge(resolved_edge);
                        }
                    }
                }
            }
            else if (lid.rfind("SemLoop", 0) == 0) {
                if (has_raw_edges && lid.rfind("SemLoop:EDGESET@", 0) == 0) {
                    if (end == std::string::npos) break;
                    t = t.substr(end + 1);
                    continue;
                }
                std::vector<TopoDS_Edge> cached_edges = resolve_cached_edges(cache_key, lid, em);
                if (!cached_edges.empty()) {
                    for (const auto& loop_edge : cached_edges) {
                        try_add_edge(loop_edge, &lid);
                    }
                } else {
                    std::vector<TopoDS_Edge> loop_edges = resolve_semantic_history_edges(lid);
                    if (loop_edges.empty()) {
                        gp_Pnt seed_point;
                        if (parse_seed_point_from_target(lid, seed_point)) {
                            double shell_hist_dist = 1e100;
                            loop_edges = resolve_shell_history_edges(lid, &shell_hist_dist);
                            if (loop_edges.empty() || shell_hist_dist > 5e-2) {
                                double face_loop_dist = 1e100;
                                loop_edges = find_best_face_wire_loop_edges(result_shape, lid, &face_loop_dist);
                                if (loop_edges.empty() || face_loop_dist > 1.5e-1) {
                                    loop_edges = find_best_opening_loop_edges(result_shape, lid);
                                } else {
                                    log_debug(std::string("[APPLY_CHAMFER] Recovered as face wire loop from semantic token: ") + lid);
                                }
                            }
                        }
                    }
                    if (!loop_edges.empty()) {
                        store_cached_edges(cache_key, loop_edges, em);
                    }
                    for (const auto& loop_edge : loop_edges) {
                        try_add_edge(loop_edge, &lid);
                    }
                }
            }
            else if (lid.find("Face:") == 0) { 
                TopoDS_Face face = find_face_robust(lid, fm); 
                if (!face.IsNull()) { 
                    TopExp_Explorer ex(face, TopAbs_EDGE); 
                    while (ex.More()) { try_add_edge(TopoDS::Edge(ex.Current())); ex.Next(); } 
                } 
            }
            if (end == std::string::npos) break; t = t.substr(end + 1);
        }
        if (has_raw_edges && raw_edge_hits == 0 && f.NbContours() == 0) {
            log_debug("[APPLY_CHAMFER] Raw edges failed; retrying semantic loop fallback");
            std::string retry = target_lineage;
            while (retry.length() > 0) {
                size_t end = retry.find("|");
                std::string lid = retry.substr(0, end);
                if (lid.rfind("SemLoop", 0) == 0) {
                    const std::string cache_key = std::string("CHAMFER|") + shape_signature + "|" + lid;
                    std::vector<TopoDS_Edge> history_edges = resolve_semantic_history_edges(lid);
                    if (!history_edges.empty()) {
                        store_cached_edges(cache_key, history_edges, em);
                        for (const auto& loop_edge : history_edges) {
                            try_add_edge(loop_edge, &lid);
                        }
                    } else {
                        gp_Pnt seed_point;
                        if (parse_seed_point_from_target(lid, seed_point)) {
                            double shell_hist_dist = 1e100;
                            std::vector<TopoDS_Edge> loop_edges = resolve_shell_history_edges(lid, &shell_hist_dist);
                            if (loop_edges.empty() || shell_hist_dist > 5e-2) {
                                double face_loop_dist = 1e100;
                                loop_edges = find_best_face_wire_loop_edges(result_shape, lid, &face_loop_dist);
                                if (loop_edges.empty() || face_loop_dist > 1.5e-1) {
                                    loop_edges = find_best_opening_loop_edges(result_shape, lid);
                                } else {
                                log_debug(std::string("[APPLY_CHAMFER] Recovered as face wire loop from semantic token: ") + lid);
                            }
                        }
                        if (!loop_edges.empty()) {
                            store_cached_edges(cache_key, loop_edges, em);
                        }
                        for (const auto& loop_edge : loop_edges) {
                            try_add_edge(loop_edge, &lid);
                        }
                        }
                    }
                }
                if (end == std::string::npos) break;
                retry = retry.substr(end + 1);
            }
        }
        if (f.NbContours() > 0) {
            f.Build();
            if (f.IsDone()) {
                TopoDS_Shape out_shape = f.Shape();
                for (const auto& entry : token_source_edges) {
                    if (entry.first.rfind("SemLoop", 0) != 0) continue;
                    std::vector<TopoDS_Edge> resolved = collect_history_edges_from_builder(f, entry.second);
                    if (resolved.empty()) {
                        gp_Pnt seed_point;
                        if (parse_seed_point_from_target(entry.first, seed_point)) {
                            double face_loop_dist = 1e100;
                            resolved = find_best_face_wire_loop_edges(out_shape, entry.first, &face_loop_dist);
                            if (resolved.empty() || face_loop_dist > 1.5e-1) {
                                resolved = find_best_opening_loop_edges(out_shape, entry.first);
                            }
                        }
                    }
                    if (!resolved.empty()) {
                        g_semantic_edge_history[entry.first] = resolved;
                    }
                }
                if (face_map) update_face_id_map_from_builder(*face_map, f);
                return out_shape;
            }
        }
    } catch (...) {
        log_debug("[APPLY_CHAMFER] Exception caught");
    }
    return result_shape;
}

TopoDS_Shape apply_face_offset(const TopoDS_Shape& result_shape, const std::string& target_lineage, double radius, std::map<std::string, TopoDS_Shape>* face_map) {
    if (result_shape.IsNull()) return result_shape;
    if (std::abs(radius) < 1e-9) {
        log_debug("[FACE_OFFSET] radius is zero, skipping");
        return result_shape;
    }
    log_debug("[FACE_OFFSET] Starting: target_lineage=" + target_lineage + " radius=" + std::to_string(radius));
    TopoDS_Shape out_shape = result_shape;
    std::string t = target_lineage; TopTools_IndexedMapOfShape fm; TopExp::MapShapes(out_shape, TopAbs_FACE, fm); size_t pos = 0;
    log_debug("[FACE_OFFSET] Total faces in shape: " + std::to_string(fm.Extent()));
    int face_processed = 0;
    while ((pos = t.find("Face:")) != std::string::npos) {
        size_t end = t.find("|", pos); std::string lid = t.substr(pos, (end == std::string::npos) ? std::string::npos : end - pos);
        log_debug("[FACE_OFFSET] Searching for face: " + lid);
        std::vector<TopoDS_Face> target_faces = resolve_faces_for_token(out_shape, lid, fm);
        if (!target_faces.empty()) {
            TopoDS_Face f = target_faces.front();
            BRepAdaptor_Surface s(f); double u = (s.FirstUParameter() + s.LastUParameter()) / 2.0, v = (s.FirstVParameter() + s.LastVParameter()) / 2.0;
            gp_Pnt p; gp_Vec du, dv; s.D1(u, v, p, du, dv); gp_Vec n = du.Crossed(dv);
            if (n.SquareMagnitude() > 1e-9) { 
                if (f.Orientation() == TopAbs_REVERSED) n.Reverse(); 
                n.Normalize(); 
                log_debug("[FACE_OFFSET] Face found, normal=(" + std::to_string(n.X()) + "," + std::to_string(n.Y()) + "," + std::to_string(n.Z()) + ") at point=(" + std::to_string(p.X()) + "," + std::to_string(p.Y()) + "," + std::to_string(p.Z()) + ")");
                try {
                    if (out_shape.ShapeType() == TopAbs_SOLID || out_shape.ShapeType() == TopAbs_COMPSOLID) {
                        BRepClass3d_SolidClassifier classifier(out_shape);
                        classifier.Perform(p.Translated(n * 1e-4), 1e-6);
                        if (classifier.State() == TopAbs_IN) {
                            n.Reverse();
                            log_debug("[FACE_OFFSET] Reversed normal via SolidClassifier");
                        }
                    }

                    // gp_Vec shift_vec = (radius > 0) ? -n * 0.001 : n * 0.001;
                    // double new_radius = (radius > 0) ? radius + 0.001 : radius - 0.001;
                    // gp_Trsf shift_trsf; shift_trsf.SetTranslation(shift_vec);
                    // BRepBuilderAPI_Transform xform(f, shift_trsf, true);
                    // TopoDS_Face shifted_f = TopoDS::Face(xform.Shape());
                    BRepPrimAPI_MakePrism m(f, n * radius);
                TopoDS_Shape m_shape = m.Shape();
                if (!m_shape.IsNull() && m_shape.ShapeType() == TopAbs_SOLID) {
                    GProp_GProps gprops;
                    BRepGProp::VolumeProperties(m_shape, gprops);
                    if (gprops.Mass() < 0.0) m_shape.Reverse();
                }
                    if (m.IsDone()) {
                        if (face_map) {
                            TopoDS_Shape top_face = m.LastShape();
                            if (!top_face.IsNull()) (*face_map)[lid + "_TOP"] = top_face;
                            int side_idx = 0;
                            for (TopExp_Explorer ex_e(f, TopAbs_EDGE); ex_e.More(); ex_e.Next()) {
                                const TopTools_ListOfShape& gen = m.Generated(ex_e.Current());
                                if (!gen.IsEmpty()) {
                                    TopoDS_Shape side_face = gen.First();
                                    if (!side_face.IsNull()) {
                                        (*face_map)[lid + "_SIDE_" + std::to_string(side_idx)] = side_face;
                                        side_idx++;
                                    }
                                }
                            }
                        }
                        if (radius > 0) {
                            BRepAlgoAPI_Fuse op(out_shape, m_shape);
                            op.SetRunParallel(Standard_True);
                            op.SetFuzzyValue(1e-5);
                            op.Build();
                            if (op.IsDone()) {
                                out_shape = op.Shape();
                                if (face_map) update_face_id_map_from_history(*face_map, op.History());
                            }
                        } else {
                            BRepAlgoAPI_Cut op(out_shape, m_shape);
                            op.SetRunParallel(Standard_True);
                            op.SetFuzzyValue(1e-5);
                            op.Build();
                            if (op.IsDone()) {
                                out_shape = op.Shape();
                                if (face_map) update_face_id_map_from_history(*face_map, op.History());
                            }
                        }
                        TopExp::MapShapes(out_shape, TopAbs_FACE, fm);
                        register_face_history_for_token(lid, out_shape);
                        face_processed++;
                        log_debug("[FACE_OFFSET] MakePrism + Boolean succeeded");
                    } else {
                        log_debug("[FACE_OFFSET] MakePrism failed (not done)");
                    }
                } catch (Standard_Failure const& e) {
                    log_debug(std::string("[FACE_OFFSET] MakePrism/Boolean exception: ") + e.GetMessageString());
                } catch (...) {
                    log_debug("[FACE_OFFSET] MakePrism/Boolean unknown exception");
                }
            } else {
                log_debug("[FACE_OFFSET] Normal vector is degenerate, skipping face");
            }
        } else {
            log_debug("[FACE_OFFSET] Face NOT found for: " + lid);
        }
        if (end == std::string::npos) break; t = t.substr(end + 1);
    }
    log_debug("[FACE_OFFSET] Completed: " + std::to_string(face_processed) + " faces processed");
    return out_shape;
}

TopoDS_Shape apply_face_inset(const TopoDS_Shape& result_shape, const std::string& target_lineage, double inset_dist, double extrude_dist, std::map<std::string, TopoDS_Shape>* face_map) {
    if (result_shape.IsNull()) return result_shape;
    if (inset_dist < 1e-6) return result_shape;
    TopoDS_Shape out_shape = result_shape;
    std::string t = target_lineage; TopTools_IndexedMapOfShape fm; TopExp::MapShapes(out_shape, TopAbs_FACE, fm); size_t pos = 0;
    while ((pos = t.find("Face:")) != std::string::npos) {
        size_t end = t.find("|", pos); std::string lid = t.substr(pos, (end == std::string::npos) ? std::string::npos : end - pos);
        std::vector<TopoDS_Face> target_faces = resolve_faces_for_token(out_shape, lid, fm);
        if (!target_faces.empty()) {
            TopoDS_Face f = target_faces.front();
            // --- Step 1: オフセットされた内側ワイヤーを取得 ---
            std::vector<TopoDS_Wire> inner_wires;
            bool offset_success = false;
            
            // 方法A: BRepOffsetAPI_MakeOffset（面を渡す方式のみ。AddWireは呼ばない）
            try {
                OCC_CATCH_SIGNALS
                BRepOffsetAPI_MakeOffset makeOffset(f, GeomAbs_Arc);
                makeOffset.Perform(-inset_dist);
                
                if (makeOffset.IsDone()) {
                    TopoDS_Shape offset_result = makeOffset.Shape();
                    // オフセット結果からワイヤーを取得
                    for (TopExp_Explorer fexp(offset_result, TopAbs_FACE); fexp.More(); fexp.Next()) {
                        TopoDS_Face offset_face = TopoDS::Face(fexp.Current());
                        for (TopExp_Explorer wexp(offset_face, TopAbs_WIRE); wexp.More(); wexp.Next()) {
                            TopoDS_Wire wire = TopoDS::Wire(wexp.Current());
                            if (!wire.IsNull()) inner_wires.push_back(wire);
                        }
                    }
                    TopExp_Explorer wcheck(offset_result, TopAbs_WIRE);
                    while (inner_wires.empty() && wcheck.More()) {
                        TopoDS_Wire wire = TopoDS::Wire(wcheck.Current());
                        if (!wire.IsNull()) inner_wires.push_back(wire);
                        wcheck.Next();
                    }
                    if (!inner_wires.empty()) {
                        offset_success = true;
                    } else {
                        // Wireがない場合、Edgeからワイヤーを構築
                        TopExp_Explorer echeck(offset_result, TopAbs_EDGE);
                        if (echeck.More()) {
                            BRepBuilderAPI_MakeWire mw;
                            while (echeck.More()) {
                                mw.Add(TopoDS::Edge(echeck.Current()));
                                echeck.Next();
                            }
                            if (mw.IsDone()) {
                                inner_wires.push_back(mw.Wire());
                                offset_success = true;
                            }
                        }
                    }
                }
            } catch (Standard_Failure const& e) {
                log_debug(std::string("[FACE_INSET] MakeOffset failed: ") + e.GetMessageString());
            } catch (...) {
                log_debug("[FACE_INSET] MakeOffset unknown exception");
            }
            
            // 方法B: フォールバック - 面の中心基準でスケーリング
            TopoDS_Face inner_f;
            if (offset_success) {
                BRepBuilderAPI_MakeFace mkFace(BRep_Tool::Surface(f), inner_wires.front(), true);
                for (size_t wire_idx = 1; wire_idx < inner_wires.size(); ++wire_idx) {
                    mkFace.Add(inner_wires[wire_idx]);
                }
                if (mkFace.IsDone()) {
                    inner_f = mkFace.Face();
                }
            } else {
                try {
                    OCC_CATCH_SIGNALS
                    GProp_GProps gp_props;
                    BRepGProp::SurfaceProperties(f, gp_props);
                    gp_Pnt center = gp_props.CentreOfMass();
                    double R = std::sqrt(gp_props.Mass() / 3.141592653589793);
                    double scale = std::max(0.001, (R - inset_dist) / R);

                    gp_Trsf trsf;
                    trsf.SetScale(center, scale);
                    BRepBuilderAPI_Transform xform(f, trsf);
                    if (xform.IsDone()) {
                        TopoDS_Shape scaled_face = xform.Shape();
                        TopExp_Explorer wexp(scaled_face, TopAbs_WIRE);
                        while(wexp.More()) {
                            inner_wires.push_back(TopoDS::Wire(wexp.Current()));
                            wexp.Next();
                        }
                        if (!inner_wires.empty()) {
                            offset_success = true;
                            
                            BRepBuilderAPI_MakeFace mkFaceFallback(BRep_Tool::Surface(f), inner_wires.front(), true);
                            for (size_t wire_idx = 1; wire_idx < inner_wires.size(); ++wire_idx) {
                                mkFaceFallback.Add(inner_wires[wire_idx]);
                            }
                            if (mkFaceFallback.IsDone()) {
                                inner_f = mkFaceFallback.Face();
                            }
                        }
                    }
                } catch (...) {}
            }

                        if (extrude_dist != 0.0) {
                try {
                    OCC_CATCH_SIGNALS
                    if (!inner_f.IsNull()) {
                        inner_f.Orientation(f.Orientation());
                        BRepAdaptor_Surface s(inner_f); double u = (s.FirstUParameter() + s.LastUParameter()) / 2.0, v = (s.FirstVParameter() + s.LastVParameter()) / 2.0;
                        gp_Pnt p; gp_Vec du, dv; s.D1(u, v, p, du, dv); gp_Vec n = du.Crossed(dv);
                        if (n.SquareMagnitude() > 1e-9) {
                            if (inner_f.Orientation() == TopAbs_REVERSED) n.Reverse();
                            n.Normalize();
                            if (out_shape.ShapeType() == TopAbs_SOLID || out_shape.ShapeType() == TopAbs_COMPSOLID) {
                                BRepClass3d_SolidClassifier classifier(out_shape);
                                classifier.Perform(p.Translated(n * 1e-4), 1e-6);
                                if (classifier.State() == TopAbs_IN) {
                                    n.Reverse();
                                }
                            }
                            gp_Vec shift_vec = (extrude_dist > 0) ? -n * 0.001 : n * 0.001;
                            double new_extrude_dist = (extrude_dist > 0) ? extrude_dist + 0.001 : extrude_dist - 0.001;
                            gp_Trsf shift_trsf; shift_trsf.SetTranslation(shift_vec);
                            BRepBuilderAPI_Transform xform(inner_f, shift_trsf, true);
                            TopoDS_Face shifted_inner_f = TopoDS::Face(xform.Shape());
                            BRepPrimAPI_MakePrism m(shifted_inner_f, n * new_extrude_dist);
                            if (m.IsDone()) {
                                if (face_map) {
                                    TopoDS_Shape top_face = m.LastShape();
                                    if (!top_face.IsNull()) (*face_map)[lid + "_INSET_TOP"] = top_face;
                                    int side_idx = 0;
                                    for (TopExp_Explorer ex_e(shifted_inner_f, TopAbs_EDGE); ex_e.More(); ex_e.Next()) {
                                        const TopTools_ListOfShape& gen = m.Generated(ex_e.Current());
                                        if (!gen.IsEmpty()) {
                                            TopoDS_Shape side_face = gen.First();
                                            if (!side_face.IsNull()) {
                                                (*face_map)[lid + "_INSET_SIDE_" + std::to_string(side_idx)] = side_face;
                                                side_idx++;
                                            }
                                        }
                                    }
                                }
                                TopoDS_Shape m_shape = m.Shape();
                                if (!m_shape.IsNull() && m_shape.ShapeType() == TopAbs_SOLID) {
                                    GProp_GProps gprops;
                                    BRepGProp::VolumeProperties(m_shape, gprops);
                                    if (gprops.Mass() < 0.0) m_shape.Reverse();
                                }
                                if (extrude_dist > 0) {
                                    BRepAlgoAPI_Fuse op(out_shape, m_shape);
                                    op.SetRunParallel(Standard_True);
                                    op.SetFuzzyValue(1e-5);
                                    op.Build();
                                    if (op.IsDone()) {
                                        out_shape = op.Shape();
                                        if (face_map) update_face_id_map_from_history(*face_map, op.History());
                                    }
                                } else {
                                    BRepAlgoAPI_Cut op(out_shape, m_shape);
                                    op.SetRunParallel(Standard_True);
                                    op.SetFuzzyValue(1e-5);
                                    op.Build();
                                    if (op.IsDone()) {
                                        out_shape = op.Shape();
                                        if (face_map) update_face_id_map_from_history(*face_map, op.History());
                                    }
                                }
                                TopExp::MapShapes(out_shape, TopAbs_FACE, fm);
                                register_face_history_for_token(lid, out_shape);
                            }
                        }
                    }
                } catch (Standard_Failure const& e) {
                    log_debug(std::string("[FACE_INSET] Extrude failed: ") + e.GetMessageString());
                } catch (...) {
                    log_debug("[FACE_INSET] Extrude unknown exception");
                }
            } else {
                try {
                    OCC_CATCH_SIGNALS
                    BRepFeat_SplitShape splitter(out_shape);
                    if (inner_wires.empty() && !inner_f.IsNull()) {
                        for (TopExp_Explorer wexp(inner_f, TopAbs_WIRE); wexp.More(); wexp.Next()) {
                            splitter.Add(TopoDS::Wire(wexp.Current()), f);
                        }
                    } else {
                        for (const auto& inner_wire : inner_wires) {
                            splitter.Add(inner_wire, f);
                        }
                    }
                    splitter.Build();
                    if (splitter.IsDone()) {
                        out_shape = splitter.Shape();
                        TopExp::MapShapes(out_shape, TopAbs_FACE, fm);
                        register_face_history_for_token(lid, out_shape);
                    }
                } catch (Standard_Failure const& e) {
                    log_debug(std::string("[FACE_INSET] SplitShape failed: ") + e.GetMessageString());
                } catch (...) {
                    log_debug("[FACE_INSET] SplitShape unknown exception");
                }
            }
        }
        if (end == std::string::npos) break; t = t.substr(end + 1);
    }
    return out_shape;
}


TopoDS_Shape apply_draft(const TopoDS_Shape& result_shape, const std::string& ref_lineage, const std::string& target_lineage, double radius_angle, std::map<std::string, TopoDS_Shape>* face_map, const TopoDS_Shape& global_shape) {
    if (result_shape.IsNull()) return result_shape;
    log_debug(
        std::string("[apply_draft] Called. ref_lineage=") + ref_lineage +
        " target_lineage=" + target_lineage +
        " angle=" + std::to_string(radius_angle)
    );

    std::vector<TopoDS_Face> ref_faces;
    if (face_map && face_map->count(ref_lineage)) {
        TopoDS_Shape s = (*face_map)[ref_lineage];
        if (!s.IsNull() && s.ShapeType() == TopAbs_FACE) {
            ref_faces.push_back(TopoDS::Face(s));
        }
    }
    if (ref_faces.empty()) {
        TopTools_IndexedMapOfShape fm; TopExp::MapShapes(result_shape, TopAbs_FACE, fm);
        ref_faces = resolve_faces_for_token(result_shape, ref_lineage, fm);
    }
    if (ref_faces.empty() && !global_shape.IsNull()) {
        TopTools_IndexedMapOfShape gfm; TopExp::MapShapes(global_shape, TopAbs_FACE, gfm);
        ref_faces = resolve_faces_for_token(global_shape, ref_lineage, gfm);
    }
    log_debug(
        std::string("[apply_draft] Neutral face resolved count=") +
        std::to_string(static_cast<int>(ref_faces.size()))
    );
    TopoDS_Face nf = ref_faces.empty() ? TopoDS_Face() : ref_faces.front();
    if (nf.IsNull()) {
        log_debug("[apply_draft] Early exit: neutral face not resolved");
        return result_shape;
    }

    BRepAdaptor_Surface s(nf);
    if (s.GetType() != GeomAbs_Plane) {
        log_debug("[apply_draft] Early exit: neutral face is not planar");
        return result_shape;
    }

    gp_Pln pl = s.Plane();
    gp_Dir d = pl.Axis().Direction();
    if (nf.Orientation() == TopAbs_REVERSED) d.Reverse();
    
    double rad = radius_angle * 3.14159 / 180.0;
    if (std::abs(radius_angle) <= 0.001) {
        log_debug("[apply_draft] Early exit: angle too small");
        return result_shape;
    }

    bool is_compound = (result_shape.ShapeType() == TopAbs_COMPOUND);
    TopTools_IndexedMapOfShape whole_fm; TopExp::MapShapes(result_shape, TopAbs_FACE, whole_fm);
    
    std::vector<TopoDS_Face> all_target_faces;
    std::string t = target_lineage;
    std::vector<std::string> target_tokens;
    while (t.length() > 0) {
        size_t end = t.find("|");
        std::string lid = t.substr(0, end);
        std::vector<TopoDS_Face> target_faces = resolve_faces_for_token(result_shape, lid, whole_fm);
        log_debug(
            std::string("[apply_draft] target token resolved: token=") + lid +
            " count=" + std::to_string(static_cast<int>(target_faces.size()))
        );
        for (const auto& f : target_faces) {
            if (!f.IsNull()) {
                all_target_faces.push_back(f);
                target_tokens.push_back(lid);
            }
        }
        if (end == std::string::npos) break;
        t = t.substr(end + 1);
    }
    if (all_target_faces.empty()) {
        log_debug("[apply_draft] Early exit: no target faces resolved from target_lineage");
        return result_shape;
    }
    log_debug(
        std::string("[apply_draft] Total target faces resolved: ") +
        std::to_string(static_cast<int>(all_target_faces.size())) +
        " is_compound=" + std::to_string(is_compound ? 1 : 0)
    );

    if (is_compound) {
        BRep_Builder bb;
        TopoDS_Compound comp_out;
        bb.MakeCompound(comp_out);
        
        bool modified_any = false;
        TopoDS_Iterator it(result_shape);
        while (it.More()) {
            TopoDS_Shape child = it.Value();
            
            TopTools_IndexedMapOfShape child_fm;
            TopExp::MapShapes(child, TopAbs_FACE, child_fm);
            
            std::vector<TopoDS_Face> child_targets;
            std::vector<std::string> child_touched_tokens;
            for (size_t k = 0; k < all_target_faces.size(); ++k) {
                if (child_fm.Contains(all_target_faces[k])) {
                    child_targets.push_back(all_target_faces[k]);
                    child_touched_tokens.push_back(target_tokens[k]);
                }
            }
            
            if (!child_targets.empty()) {
                BRepOffsetAPI_DraftAngle dr(child);
                int add_count = 0;
                for (const auto& tf : child_targets) {
                    dr.Add(tf, d, rad, pl);
                    if (dr.AddDone()) add_count++;
                }
                log_debug(
                    std::string("[apply_draft] Compound Child: targets=") +
                    std::to_string(static_cast<int>(child_targets.size())) +
                    " add_done_count=" + std::to_string(add_count)
                );
                
                if (add_count > 0) {
                    dr.Build();
                    log_debug(
                        std::string("[apply_draft] Compound Child dr.Build done. IsDone=") +
                        std::to_string(dr.IsDone() ? 1 : 0)
                    );
                    if (dr.IsDone()) {
                        try {
                            TopoDS_Shape drafted_child = dr.Shape();
                            bb.Add(comp_out, drafted_child);
                            modified_any = true;
                            
                            try {
                                if (face_map) update_face_id_map_from_builder(*face_map, dr);
                            } catch (Standard_Failure const& e) {
                                log_debug(std::string("[apply_draft] Compound child face_map update Standard_Failure: ") + e.GetMessageString());
                            } catch (...) {
                                log_debug("[apply_draft] Compound child face_map update threw; continuing with drafted result");
                            }
                            try {
                                register_face_history_for_token(ref_lineage, drafted_child);
                                for (const auto& token : child_touched_tokens) register_face_history_for_token(token, drafted_child);
                            } catch (Standard_Failure const& e) {
                                log_debug(std::string("[apply_draft] Compound child face history Standard_Failure: ") + e.GetMessageString());
                            } catch (...) {
                                log_debug("[apply_draft] Compound child face history registration threw; continuing with drafted result");
                            }
                            
                            it.Next();
                            continue;
                        } catch (Standard_Failure const& e) {
                            log_debug(std::string("[apply_draft] Compound child post-build Standard_Failure: ") + e.GetMessageString());
                        } catch (const std::exception& e) {
                            log_debug(std::string("[apply_draft] Compound child post-build std::exception: ") + e.what());
                        } catch (...) {
                            log_debug("[apply_draft] Compound child post-build unknown exception");
                        }
                    }
                    log_debug("[apply_draft] Compound child build returned not done despite add_count>0");
                } else {
                    log_debug("[apply_draft] Compound child had add_count=0");
                }
            } else {
                log_debug("[apply_draft] Compound child had no matching targets; child passed through untouched");
            }
            
            bb.Add(comp_out, child);
            it.Next();
        }
        
        if (modified_any) {
            return comp_out;
        }
        log_debug("[apply_draft] Compound exit without modifications; returning original shape");
    } else {
        BRepOffsetAPI_DraftAngle dr(result_shape);
        int count = 0;
        for (const auto& tf : all_target_faces) {
            dr.Add(tf, d, rad, pl);
            if (dr.AddDone()) count++;
        }
        log_debug(
            std::string("[apply_draft] Single Shape: add_done_count=") +
            std::to_string(count)
        );
        if (count > 0) {
            dr.Build();
            log_debug(
                std::string("[apply_draft] Single Shape dr.Build done. IsDone=") +
                std::to_string(dr.IsDone() ? 1 : 0)
            );
            if (dr.IsDone()) {
                try {
                    TopoDS_Shape out_shape = dr.Shape();
                    log_debug(
                        std::string("[apply_draft] Single shape dr.Shape acquired. is_null=") +
                        std::to_string(out_shape.IsNull() ? 1 : 0)
                    );
                    try {
                        if (face_map) update_face_id_map_from_builder(*face_map, dr);
                    } catch (Standard_Failure const& e) {
                        log_debug(std::string("[apply_draft] Single shape face_map Standard_Failure: ") + e.GetMessageString());
                    } catch (...) {
                        log_debug("[apply_draft] Single shape face_map update threw; continuing with drafted result");
                    }
                    try {
                        register_face_history_for_token(ref_lineage, out_shape);
                        for (const auto& token : target_tokens) register_face_history_for_token(token, out_shape);
                    } catch (Standard_Failure const& e) {
                        log_debug(std::string("[apply_draft] Single shape face history Standard_Failure: ") + e.GetMessageString());
                    } catch (...) {
                        log_debug("[apply_draft] Single shape face history registration threw; continuing with drafted result");
                    }
                    return out_shape;
                } catch (Standard_Failure const& e) {
                    log_debug(std::string("[apply_draft] Single shape post-build Standard_Failure: ") + e.GetMessageString());
                } catch (const std::exception& e) {
                    log_debug(std::string("[apply_draft] Single shape post-build std::exception: ") + e.what());
                } catch (...) {
                    log_debug("[apply_draft] Single shape post-build unknown exception");
                }
            }
            log_debug("[apply_draft] Single shape build returned not done despite add_count>0");
        } else {
            log_debug("[apply_draft] Single shape had add_count=0");
        }
        log_debug("[apply_draft] Single shape exit without modifications");
    }

    return result_shape;
}

TopoDS_Shape apply_shell(const TopoDS_Shape& result_shape, const std::string& target_lineage, double thickness, std::map<std::string, TopoDS_Shape>* face_map) {
    if (result_shape.IsNull()) return result_shape;
    if (std::abs(thickness) > 1e-6) {
        TopTools_IndexedMapOfShape fm; TopExp::MapShapes(result_shape, TopAbs_FACE, fm);
        TopTools_ListOfShape rem;
        std::vector<std::pair<std::string, TopoDS_Face>> rem_with_lid;
        std::string t = target_lineage;
            while (t.length() > 0) {
                size_t end = t.find("|");
                std::string lid = t.substr(0, end);
                std::vector<TopoDS_Face> target_faces = resolve_faces_for_token(result_shape, lid, fm);
                for (const auto& f : target_faces) {
                    if (!f.IsNull()) {
                        rem.Append(f);
                        rem_with_lid.push_back({lid, f});
                    }
                }
                if (end == std::string::npos) break;
                t = t.substr(end + 1);
            }
            
            if (rem.Extent() > 0) {
                try {
                    OCC_CATCH_SIGNALS
                    BRepOffsetAPI_MakeThickSolid s; 
                    s.MakeThickSolidByJoin(result_shape, rem, -thickness, 1e-3); 
                    if (s.IsDone()) {
                        TopoDS_Shape out_shape = s.Shape();
                        if (face_map) {
                            for (const auto& pair : rem_with_lid) {
                                std::string lid = pair.first;
                                TopoDS_Face rem_face = pair.second;
                                int edge_idx = 0;
                                for (TopExp_Explorer ex_e(rem_face, TopAbs_EDGE); ex_e.More(); ex_e.Next()) {
                                    const TopTools_ListOfShape& gen = s.Generated(ex_e.Current());
                                    if (!gen.IsEmpty()) {
                                        TopoDS_Shape side_face = gen.First();
                                        if (!side_face.IsNull()) {
                                            (*face_map)[lid + "_SHELLSIDE_" + std::to_string(edge_idx)] = side_face;
                                        }
                                    }
                                    edge_idx++;
                                }
                            }
                            update_face_id_map_from_builder(*face_map, s);
                        }
                        register_shell_opening_history(s, rem);
                        return out_shape;
                }
            } catch (Standard_Failure const& e) {
                log_debug(std::string("[SHELL] Exception: ") + e.GetMessageString());
            } catch (...) {
                log_debug("[SHELL] Unknown exception");
            }
        } else {
            try {
                OCC_CATCH_SIGNALS
                BRepOffsetAPI_MakeThickSolid s; 
                s.MakeThickSolidByJoin(result_shape, rem, -thickness, 1e-3); 
                if (s.IsDone()) {
                    TopoDS_Shape inner_solid = s.Shape();
                    BRepAlgoAPI_Cut cut_op(result_shape, inner_solid);
                    cut_op.SetRunParallel(Standard_True);
                    cut_op.Build();
                    if (cut_op.IsDone()) {
                        TopoDS_Shape hollow_shape = cut_op.Shape();
                        if (face_map) update_face_id_map_from_history(*face_map, cut_op.History());
                        return hollow_shape;
                    }
                }
            } catch (Standard_Failure const& e) {
                log_debug(std::string("[SHELL] Hollow Exception: ") + e.GetMessageString());
            } catch (...) {
                log_debug("[SHELL] Hollow Unknown exception");
            }
        }
    }
    return result_shape;
}

TopoDS_Shape apply_face_loft(const TopoDS_Shape& result_shape, const std::string& target_lineage, std::map<std::string, TopoDS_Shape>* face_map) {
    if (result_shape.IsNull()) return TopoDS_Shape();
    if (target_lineage.empty()) return TopoDS_Shape();
    
    try {
        OCC_CATCH_SIGNALS
        TopTools_IndexedMapOfShape fm;
        TopExp::MapShapes(result_shape, TopAbs_FACE, fm);
        
        std::string t = target_lineage;
        std::vector<std::string> face_ids;
        size_t end = 0;
        while ((end = t.find("|")) != std::string::npos) {
            std::string id = t.substr(0, end);
            if (!id.empty()) face_ids.push_back(id);
            t = t.substr(end + 1);
        }
        if (!t.empty()) {
            face_ids.push_back(t);
        }
        
        if (face_ids.size() < 2) {
            log_debug("[FACE_LOFT] Less than 2 faces specified.");
            return TopoDS_Shape();
        }
        
        std::vector<TopoDS_Face> selected_faces;
        for (const auto& fid : face_ids) {
            TopoDS_Face f = resolve_modifier_face_target(result_shape, fid);
            if (!f.IsNull()) selected_faces.push_back(f);
        }
        
        if (selected_faces.size() < 2) {
            log_debug("[FACE_LOFT] Less than 2 valid faces found.");
            return TopoDS_Shape();
        }
        
        // Group faces into connected components
        std::vector<std::vector<TopoDS_Face>> groups;
        std::vector<bool> visited(selected_faces.size(), false);
        for (size_t i = 0; i < selected_faces.size(); ++i) {
            if (visited[i]) continue;
            std::vector<TopoDS_Face> current_group;
            std::vector<size_t> queue = {i};
            visited[i] = true;
            
            while (!queue.empty()) {
                size_t curr = queue.front();
                queue.erase(queue.begin());
                current_group.push_back(selected_faces[curr]);
                
                TopTools_IndexedMapOfShape curr_verts;
                TopExp::MapShapes(selected_faces[curr], TopAbs_VERTEX, curr_verts);
                
                for (size_t j = 0; j < selected_faces.size(); ++j) {
                    if (visited[j]) continue;
                    TopTools_IndexedMapOfShape j_verts;
                    TopExp::MapShapes(selected_faces[j], TopAbs_VERTEX, j_verts);
                    
                    bool shared = false;
                    for (int v1 = 1; v1 <= curr_verts.Extent(); ++v1) {
                        for (int v2 = 1; v2 <= j_verts.Extent(); ++v2) {
                            if (curr_verts.FindKey(v1).IsSame(j_verts.FindKey(v2))) {
                                shared = true; break;
                            }
                        }
                        if (shared) break;
                    }
                    if (shared) { visited[j] = true; queue.push_back(j); }
                }
            }
            groups.push_back(current_group);
        }
        
        if (groups.size() < 2) {
            log_debug("[FACE_LOFT] Faces do not form at least 2 disconnected groups.");
            return TopoDS_Shape();
        }
        
        auto get_outer_wire = [](const std::vector<TopoDS_Face>& group) -> TopoDS_Wire {
            TopTools_IndexedMapOfShape all_edges;
            std::vector<int> edge_counts;
            for (const auto& f : group) {
                TopExp_Explorer exp(f, TopAbs_EDGE);
                while (exp.More()) {
                    TopoDS_Edge e = TopoDS::Edge(exp.Current());
                    int idx = all_edges.FindIndex(e);
                    if (idx == 0) { idx = all_edges.Add(e); edge_counts.push_back(1); }
                    else { edge_counts[idx - 1]++; }
                    exp.Next();
                }
            }
            
            Handle(TopTools_HSequenceOfShape) edges_seq = new TopTools_HSequenceOfShape();
            for (int i = 1; i <= all_edges.Extent(); ++i) {
                if (edge_counts[i - 1] == 1) {
                    TopoDS_Edge e = TopoDS::Edge(all_edges.FindKey(i));
                    if (!BRep_Tool::Degenerated(e)) edges_seq->Append(e);
                }
            }
            
            Handle(TopTools_HSequenceOfShape) wires_seq = new TopTools_HSequenceOfShape();
            ShapeAnalysis_FreeBounds::ConnectEdgesToWires(edges_seq, 1e-4, false, wires_seq);
            
            TopoDS_Wire best_wire;
            double max_diag = -1.0;
            for (int i = 1; i <= wires_seq->Length(); ++i) {
                TopoDS_Wire w = TopoDS::Wire(wires_seq->Value(i));
                Bnd_Box box;
                BRepBndLib::Add(w, box);
                if (!box.IsVoid()) {
                    double xmin, ymin, zmin, xmax, ymax, zmax;
                    box.Get(xmin, ymin, zmin, xmax, ymax, zmax);
                    double diag = gp_Pnt(xmin, ymin, zmin).Distance(gp_Pnt(xmax, ymax, zmax));
                    if (diag > max_diag) {
                        max_diag = diag;
                        best_wire = w;
                    }
                }
            }
            
            if (!best_wire.IsNull()) return best_wire;
            if (group.size() == 1) return BRepTools::OuterWire(group[0]);
            return TopoDS_Wire();
        };
        
        TopoDS_Wire w1 = get_outer_wire(groups[0]);
        TopoDS_Wire w2 = get_outer_wire(groups[1]);
        if (!w2.IsNull()) w2.Reverse();
        
        auto align_wire = [](const TopoDS_Wire& ref_w, const TopoDS_Wire& target_w) -> TopoDS_Wire {
            if (ref_w.IsNull() || target_w.IsNull()) return target_w;
            
            // Get first vertex of ref_w
            TopExp_Explorer exp1(ref_w, TopAbs_VERTEX);
            if (!exp1.More()) return target_w;
            TopoDS_Vertex v_ref = TopoDS::Vertex(exp1.Current());
            gp_Pnt p_ref = BRep_Tool::Pnt(v_ref);
            
            // Collect edges of target_w in order
            BRepTools_WireExplorer wexp(target_w);
            std::vector<TopoDS_Edge> ordered_edges;
            double min_dist = 1e10;
            int best_start_idx = 0;
            
            int i = 0;
            while (wexp.More()) {
                TopoDS_Edge e = wexp.Current();
                ordered_edges.push_back(e);
                TopoDS_Vertex v1 = wexp.CurrentVertex();
                gp_Pnt p1 = BRep_Tool::Pnt(v1);
                double d = p1.Distance(p_ref);
                if (d < min_dist) {
                    min_dist = d;
                    best_start_idx = i;
                }
                wexp.Next();
                i++;
            }
            
            if (ordered_edges.empty()) return target_w;
            
            BRepBuilderAPI_MakeWire new_wire;
            for (size_t j = 0; j < ordered_edges.size(); ++j) {
                new_wire.Add(ordered_edges[(best_start_idx + j) % ordered_edges.size()]);
            }
            if (new_wire.IsDone()) return new_wire.Wire();
            return target_w;
        };
        w2 = align_wire(w1, w2);
        
        if (w1.IsNull() || w2.IsNull()) {
            log_debug("[FACE_LOFT] Failed to extract outer wires from groups.");
            return TopoDS_Shape();
        }
        
        BRepOffsetAPI_ThruSections loft(Standard_True, Standard_True);
        loft.AddWire(w1);
        loft.AddWire(w2);
        loft.Build();
        
        if (loft.IsDone()) {
            TopoDS_Shape loft_shape = loft.Shape();
            if (!loft_shape.IsNull()) {
                if (face_map) update_face_id_map_from_builder(*face_map, loft);
                return loft_shape;
            }
        } else {
            log_debug("[FACE_LOFT] ThruSections loft failed.");
        }
    } catch (Standard_Failure const& e) {
        log_debug(std::string("[FACE_LOFT] Standard_Failure caught: ") + e.GetMessageString());
    } catch (...) {
        log_debug("[FACE_LOFT] Unknown exception caught");
    }
    return TopoDS_Shape();
}


TopoDS_Shape apply_face_revolve(const TopoDS_Shape& result_shape, const std::string& target_lineage, const std::string& axis, double angle_deg, double x, double y, double z, double rx, double ry, double rz, std::map<std::string, TopoDS_Shape>* face_map) {
    if (result_shape.IsNull() || target_lineage.empty()) return TopoDS_Shape();
    try {
        OCC_CATCH_SIGNALS
        TopTools_IndexedMapOfShape fm;
        TopExp::MapShapes(result_shape, TopAbs_FACE, fm);
        
        double a = angle_deg * 3.141592653589793 / 180.0;
        if (std::abs(a) < 1e-6) a = 2.0 * 3.141592653589793;
        gp_Dir d(0,0,1);
        std::string ax = axis;
        if (ax == "X") d = gp_Dir(1,0,0);
        else if (ax == "Y") d = gp_Dir(0,1,0);
        
        gp_Trsf r; gp_Quaternion q;
        q.SetEulerAngles(gp_Extrinsic_XYZ, rx, ry, rz);
        r.SetRotation(q);
        d.Transform(r);
        
        BRep_Builder builder;
        TopoDS_Compound comp;
        builder.MakeCompound(comp);
        bool has_any = false;

        std::stringstream ss(target_lineage);
        std::string lid;
        while (std::getline(ss, lid, '|')) {
            if (lid.empty()) continue;
            TopoDS_Face f = resolve_modifier_face_target(result_shape, lid);
            if (!f.IsNull()) {
                BRepPrimAPI_MakeRevol rv(f, gp_Ax1(gp_Pnt(x, y, z), d), a);
                if (rv.IsDone()) {
                    TopoDS_Shape rev_shape = rv.Shape();
                    if (!rev_shape.IsNull()) {
                        builder.Add(comp, rev_shape);
                        if (face_map) update_face_id_map_from_builder(*face_map, rv);
                        has_any = true;
                    }
                }
            }
        }
        
        if (has_any) {
            return comp;
        }

    } catch (Standard_Failure const& e) {
        log_debug(std::string("[FACE_REVOLVE] Standard_Failure: ") + e.GetMessageString());
    } catch (...) {
        log_debug("[FACE_REVOLVE] Unknown exception");
    }
    return TopoDS_Shape();
}
}
