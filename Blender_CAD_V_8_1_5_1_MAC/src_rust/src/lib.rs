#![recursion_limit = "2048"]

use cpp::cpp;

pub mod api;
pub use api::core::*;
pub use api::geometry::*;
pub use api::mesh::*;
pub use api::picking::*;
pub use api::sketch::*;
pub use api::utils::*;

#[path = "renderer.rs"]
pub(crate) mod renderer;

#[path = "csg.rs"]
pub mod csg;

cpp!{{
    #include <Standard_DefineAlloc.hxx>
    #include <Standard_Handle.hxx>
    #include <gp_Pnt.hxx>
    #include <TopoDS.hxx>
    #include <TopoDS_Shape.hxx>
    #include <TopoDS_Vertex.hxx>
    #include <TopoDS_Edge.hxx>
    #include <TopoDS_Face.hxx>
    #include <TopoDS_Wire.hxx>
    #include <TopoDS_Shell.hxx>
    #include <TopoDS_Solid.hxx>
    #include <TopoDS_Compound.hxx>
    #include <TopTools_ShapeMapHasher.hxx>
    #include <TopTools_MapOfShape.hxx>
    #include <TopTools_IndexedMapOfShape.hxx>
    #include <TopTools_DataMapOfShapeShape.hxx>
    #include <TopTools_DataMapOfShapeInteger.hxx>
    #include <TopTools_ListOfShape.hxx>
    #include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
    #include <TopTools_DataMapOfShapeListOfShape.hxx>
    #include "occ_core.cpp"
    #include "occ_step.cpp"
    #include "occ_svg.cpp"
}}

extern "C" fn rust_push_point(vec_ptr: *mut Vec<f32>, x: f32, y: f32, z: f32) {
    let vec = unsafe { &mut *vec_ptr };
    vec.push(x); vec.push(y); vec.push(z);
}

extern "C" fn rust_push_count(vec_ptr: *mut Vec<i32>, count: i32) {
    let vec = unsafe { &mut *vec_ptr };
    vec.push(count);
}

extern "C" fn rust_push_string(vec_ptr: *mut Vec<String>, s: *const std::ffi::c_char) {
    let vec = unsafe { &mut *vec_ptr };
    let c_str = unsafe { std::ffi::CStr::from_ptr(s) };
    vec.push(c_str.to_string_lossy().into_owned());
}

pub struct PrimitiveJson {
    p_type: String,
    operation: String,
    uuid: String,
    location: [f64; 3],
    rotation: [f64; 3],
    rotation_quat: Option<[f64; 4]>,
    size: [f64; 3],
    radius: f64,
    fill_closed: bool,
    sweep_path_uuid: String,
    sweep_profile_uuid: String,
    sweep_frame_mode: String,
    sweep_roll_degrees: f64,
    loft_uuids: Vec<String>,
    points: Option<Vec<[f64; 3]>>,
    segments: Option<Vec<SegmentData>>,
}

#[derive(serde::Deserialize, Clone)]
pub struct SegmentData {
    #[serde(rename = "type")]
    pub s_type: String,
    pub start: Option<[f64; 3]>,
    pub end: Option<[f64; 3]>,
    pub mid: Option<[f64; 3]>,
    pub center: Option<[f64; 3]>,
    pub radius: Option<f64>,
    pub normal: Option<[f64; 3]>,
}

#[derive(serde::Deserialize)]
pub struct PrimitiveInput {
    #[serde(rename = "type")]
    p_type: String,
    operation: String,
    uuid: String,
    location: [f64; 3],
    rotation: [f64; 3],
    rotation_quat: Option<[f64; 4]>,
    size: [f64; 3],
    radius: f64,
    fill_closed: bool,
    use_pipe: bool,
    pipe_radius: f64,
    angle_start: f64,
    angle_end: f64,
    target_lineages: Vec<String>,
    reference_lineage: String,
    extrude_height: f64,
    radius2: f64,
    minor_radius: f64,
    sides: i32,
    module: f64,
    pressure_angle: f64,
    target_uuid: String,
    count: i32,
    distance: f64,
    pattern_axis: String,
    top_shape: String,
    bot_shape: String,
    sweep_path_uuid: String,
    sweep_profile_uuid: String,
    sweep_frame_mode: String,
    sweep_roll_degrees: f64,
    loft_uuids: Vec<String>,
    points: Option<Vec<[f64; 4]>>,
    segments: Option<Vec<SegmentData>>,
    unify_faces: Option<bool>,
    unify_edges: Option<bool>,
    // V8.1.5: 可変フィレット - (edge_token, radius) の個別上書きペア。空 = 全edgeがデフォルト radius を使う。
    edge_radii: Option<Vec<(String, f64)>>,
}

pub struct MeshDataCache {
    pub total_hash: u64,
    pub deflection: f64,
    pub angular_deflection: f64,
    pub verts: Vec<f32>,
    pub tris: Vec<i32>,
    pub face_ids: Vec<String>,
    pub tri_counts: Vec<i32>,
}

use std::collections::HashMap;
use std::sync::OnceLock;

static MESH_CACHES: OnceLock<std::sync::Mutex<HashMap<isize, MeshDataCache>>> = OnceLock::new();
static STACK_TOTAL_HASHES: OnceLock<std::sync::Mutex<HashMap<isize, u64>>> = OnceLock::new();

pub fn get_mesh_caches() -> &'static std::sync::Mutex<HashMap<isize, MeshDataCache>> {
    MESH_CACHES.get_or_init(|| std::sync::Mutex::new(HashMap::new()))
}
pub fn get_stack_total_hashes() -> &'static std::sync::Mutex<HashMap<isize, u64>> {
    STACK_TOTAL_HASHES.get_or_init(|| std::sync::Mutex::new(HashMap::new()))
}

#[derive(serde::Serialize)]
pub struct AsyncResult {
    pub total_hash: u64,
    pub deflection: f64,
    pub angular_deflection: f64,
    pub edge_points: Vec<f32>,
    pub edge_counts: Vec<i32>,
    pub edge_lineages: Vec<String>,
    pub mesh_verts: Vec<f32>,
    pub mesh_tris: Vec<i32>,
    pub mesh_face_ids: Vec<String>,
    pub mesh_tri_counts: Vec<i32>,
pub perf_bool: f64,
pub perf_edge: f64,
pub perf_mesh: f64,
pub perf_prim: f64,
pub perf_bool_main: f64,
pub perf_bool_modifier: f64,
pub perf_extrema: f64,
    pub perf_resume_restore: f64,
    pub perf_modifier_target_assign: f64,
    pub perf_modifier_apply: f64,
    pub perf_modifier_recluster: f64,
    pub perf_fillet_setup: f64,
    pub perf_fillet_target_resolve: f64,
    pub perf_fillet_add: f64,
    pub perf_fillet_build: f64,
    pub perf_fillet_history: f64,
    pub perf_fillet_added_edges: f64,
    pub perf_fillet_contours: f64,
pub perf_unify: f64,
}

static ASYNC_RESULT: std::sync::Mutex<Option<AsyncResult>> = std::sync::Mutex::new(None);
use std::sync::Arc;
static STACK_LOCKS: std::sync::OnceLock<std::sync::Mutex<std::collections::HashMap<isize, Arc<std::sync::Mutex<()>>>>> = std::sync::OnceLock::new();

pub fn get_stack_lock(stack_ptr: isize) -> Arc<std::sync::Mutex<()>> {
    let mut locks = STACK_LOCKS.get_or_init(|| std::sync::Mutex::new(std::collections::HashMap::new())).lock().unwrap();
    locks.entry(stack_ptr).or_insert_with(|| Arc::new(std::sync::Mutex::new(()))).clone()
}

// create_cad_stack() が発行した生ポインタの生存確認レジストリ。
// C++側は `if (!stack) return` というNULLチェックのみで、失効/不正な
// stack_ptr が渡された場合の生存確認をしていないため、Python側のバグ等で
// 既に削除済みのポインタが送られるとUB(セグフォルト等)に直結しうる。
// FFI呼び出し前にここでメンバーシップを確認することで、少なくとも
// Rust側で確実に検出できる不正な値については早期にErrへ倒す。
static VALID_STACK_PTRS: std::sync::OnceLock<std::sync::Mutex<std::collections::HashSet<isize>>> = std::sync::OnceLock::new();

pub fn register_stack_ptr(stack_ptr: isize) {
    if stack_ptr == 0 { return; }
    VALID_STACK_PTRS.get_or_init(|| std::sync::Mutex::new(std::collections::HashSet::new()))
        .lock().unwrap().insert(stack_ptr);
}

pub fn unregister_stack_ptr(stack_ptr: isize) {
    if let Some(set) = VALID_STACK_PTRS.get() {
        set.lock().unwrap().remove(&stack_ptr);
    }
}

pub fn is_valid_stack_ptr(stack_ptr: isize) -> bool {
    if stack_ptr == 0 { return false; }
    match VALID_STACK_PTRS.get() {
        Some(set) => set.lock().unwrap().contains(&stack_ptr),
        None => false,
    }
}

static STACK_COMPUTING: std::sync::OnceLock<std::sync::Mutex<std::collections::HashSet<isize>>> = std::sync::OnceLock::new();

pub fn set_is_computing(stack_ptr: isize, computing: bool) {
    let mut stacks = STACK_COMPUTING.get_or_init(|| std::sync::Mutex::new(std::collections::HashSet::new())).lock().unwrap();
    if computing {
        stacks.insert(stack_ptr);
    } else {
        stacks.remove(&stack_ptr);
    }
}

pub fn is_computing(stack_ptr: isize) -> bool {
    let stacks = STACK_COMPUTING.get_or_init(|| std::sync::Mutex::new(std::collections::HashSet::new())).lock().unwrap();
    stacks.contains(&stack_ptr)
}

/// 幾何フロートを 1e-3 グリッドに量子化した整数値を返す。
/// プロキシ同期(matrix 分解)由来の微小ドリフト(書き戻し EPSILON=5e-4 級)を吸収し、
/// 未変更プリミティブのハッシュを安定させることで resume キャッシュ(first_dirty_idx)を
/// 機能させる。deflection=0.1 に対し 1e-3 は不可視なので形状精度には影響しない。
/// Python 側の重複除去(_quantize_for_sig, 1e-3)と粒度を一致させている。
#[inline]
fn quantize_geo(f: f64) -> i64 {
    if f.is_finite() {
        (f * 1000.0).round() as i64
    } else {
        // NaN/Inf は生ビットで区別(通常来ないが安全側)
        f.to_bits() as i64
    }
}

impl PrimitiveInput {
    fn calculate_geo_hash(&self) -> u64 {
        use std::collections::hash_map::DefaultHasher;
        use std::hash::{Hash, Hasher};
        let mut s = DefaultHasher::new();
        self.p_type.hash(&mut s);
        self.operation.hash(&mut s);
        self.uuid.hash(&mut s);
        
        for &f in &self.size { quantize_geo(f).hash(&mut s); }
        self.radius.to_bits().hash(&mut s);
        self.fill_closed.hash(&mut s);
        self.use_pipe.hash(&mut s);
        self.pipe_radius.to_bits().hash(&mut s);
        self.angle_start.to_bits().hash(&mut s);
        self.angle_end.to_bits().hash(&mut s);
        self.target_lineages.hash(&mut s);
        self.reference_lineage.hash(&mut s);
        self.extrude_height.to_bits().hash(&mut s);
        self.radius2.to_bits().hash(&mut s);
        self.minor_radius.to_bits().hash(&mut s);
        self.sides.hash(&mut s);
        self.module.to_bits().hash(&mut s);
        self.pressure_angle.to_bits().hash(&mut s);
        self.target_uuid.hash(&mut s);
        if self.p_type == "INSTANCE" {
            if let Ok(addr) = usize::from_str_radix(&self.target_uuid, 10) {
                let parent_ptr = addr as *mut std::ffi::c_void;
                let parent_hash = unsafe { cpp!([parent_ptr as "void*"] -> u64 as "uint64_t" {
                    if (!parent_ptr) return 0;
                    occ_core::CADStack* stack = static_cast<occ_core::CADStack*>(parent_ptr);
                    if (stack->stack_results.empty()) return 0;
                    return stack->stack_results.back().cumulative_hash;
                }) };
                parent_hash.hash(&mut s);
            }
        }
        self.count.hash(&mut s);
        self.distance.to_bits().hash(&mut s);
        self.pattern_axis.hash(&mut s);
        self.top_shape.hash(&mut s);
        self.bot_shape.hash(&mut s);
        self.sweep_path_uuid.hash(&mut s);
        self.sweep_profile_uuid.hash(&mut s);
        self.sweep_frame_mode.hash(&mut s);
        self.sweep_roll_degrees.to_bits().hash(&mut s);
        self.loft_uuids.hash(&mut s);
        if let Some(ref pts) = self.points {
            for pt in pts { for &f in pt { f.to_bits().hash(&mut s); } }
        }
        if let Some(ref segs) = self.segments {
            for seg in segs {
                seg.s_type.hash(&mut s);
                if let Some(ref p) = seg.start { for &f in p { f.to_bits().hash(&mut s); } }
                if let Some(ref p) = seg.end { for &f in p { f.to_bits().hash(&mut s); } }
                if let Some(ref p) = seg.mid { for &f in p { f.to_bits().hash(&mut s); } }
                if let Some(ref p) = seg.center { for &f in p { f.to_bits().hash(&mut s); } }
                if let Some(r) = seg.radius { r.to_bits().hash(&mut s); }
                if let Some(ref p) = seg.normal { for &f in p { f.to_bits().hash(&mut s); } }
            }
        }
        s.finish()
    }
    fn calculate_full_hash(&self) -> u64 {
        use std::collections::hash_map::DefaultHasher;
        use std::hash::{Hash, Hasher};
        let mut s = DefaultHasher::new();
        self.calculate_geo_hash().hash(&mut s);
        for &f in &self.location { quantize_geo(f).hash(&mut s); }
        for &f in &self.rotation { quantize_geo(f).hash(&mut s); }
        s.finish()
    }
}

// スタック削除時、そのスタック分のジオメトリだけを wgpu オーバーレイから取り除く
// (他の生存中のCADパーツの表示には影響しない)
pub fn remove_render_scene_stack(stack_ptr: isize) {
    renderer::remove_stack_edges(stack_ptr);
}

pub fn render_viewport(width: u32, height: u32, view_proj: Vec<f32>) -> Result<Vec<u8>, String> {
    if view_proj.len() != 16 { return Err(String::from("view_proj must have 16 elements")); }
    let mut vp = [[0.0; 4]; 4];
    for row in 0..4 { for col in 0..4 { vp[col][row] = view_proj[row * 4 + col]; } }
    if let Some(r) = renderer::get_renderer() {
        Ok(r.render_to_pixels(width, height, vp))
    } else { Err(String::from("WGPU Renderer not initialized")) }
}

pub fn render_viewport_sdf(
    width: u32,
    height: u32,
    view_proj: Vec<f32>,
    inv_view_proj: Vec<f32>,
    camera_pos: Vec<f32>,
    fillet_radius: f32,
    box_size: Vec<f32>,
) -> Result<Vec<u8>, String> {
    if view_proj.len() != 16 { return Err(String::from("view_proj must have 16 elements")); }
    if inv_view_proj.len() != 16 { return Err(String::from("inv_view_proj must have 16 elements")); }
    if camera_pos.len() != 3 { return Err(String::from("camera_pos must have 3 elements")); }
    if box_size.len() != 3 { return Err(String::from("box_size must have 3 elements")); }

    let mut vp = [[0.0; 4]; 4];
    for row in 0..4 { for col in 0..4 { vp[col][row] = view_proj[row * 4 + col]; } }

    let mut inv_vp = [[0.0; 4]; 4];
    for row in 0..4 { for col in 0..4 { inv_vp[col][row] = inv_view_proj[row * 4 + col]; } }

    let c_pos = [camera_pos[0], camera_pos[1], camera_pos[2], 1.0];
    let b_sz = [box_size[0], box_size[1], box_size[2]];

    if let Some(r) = renderer::get_renderer() {
        Ok(r.render_to_pixels_sdf(width, height, vp, inv_vp, c_pos, fillet_radius, b_sz))
    } else { Err(String::from("WGPU Renderer not initialized")) }
}
