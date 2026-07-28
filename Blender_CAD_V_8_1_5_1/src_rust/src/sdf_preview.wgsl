struct Uniforms {
    view_proj: mat4x4<f32>,
    inv_view_proj: mat4x4<f32>,
    camera_pos: vec4<f32>,
    fillet_radius: f32,
    box_size_x: f32,
    box_size_y: f32,
    box_size_z: f32,
};

@group(0) @binding(0)
var<uniform> uniforms: Uniforms;

struct VertexInput {
    @location(0) position: vec3<f32>,
};

struct VertexOutput {
    @builtin(position) clip_position: vec4<f32>,
    @location(0) world_pos: vec3<f32>,
    @location(1) screen_pos: vec2<f32>,
};

@vertex
fn vs_main(model: VertexInput) -> VertexOutput {
    var out: VertexOutput;
    // 頂点データは単位立方体(-1..1)で固定。box_sizeによる拡大はここで行う
    // (以前はCPU側で毎フレームVecを組み立ててスケール済み頂点をアップロードしていた)。
    let box_sz = vec3<f32>(uniforms.box_size_x, uniforms.box_size_y, uniforms.box_size_z);
    let world_position = model.position * box_sz * 1.5;
    let pos = uniforms.view_proj * vec4<f32>(world_position, 1.0);
    let z_wgpu = (pos.z + pos.w) * 0.5;
    out.clip_position = vec4<f32>(pos.x, pos.y, z_wgpu, pos.w);
    out.world_pos = world_position;
    out.screen_pos = pos.xy / pos.w;
    return out;
}

// 角丸ボックスのSDF（全エッジをradiusで丸める）
// b は丸め処理を差し引いた内側ボックスの半サイズ、外形サイズは b + r になる
fn sdf_round_box(p: vec3<f32>, outer_half: vec3<f32>, r: f32) -> f32 {
    let b = max(outer_half - vec3<f32>(r), vec3<f32>(0.0001));
    let q = abs(p) - b;
    return length(max(q, vec3<f32>(0.0))) + min(max(q.x, max(q.y, q.z)), 0.0) - r;
}

// シーンマップ：フィレット半径で角丸されたボックスをプレビュー
fn map(p: vec3<f32>) -> f32 {
    let box_sz = vec3<f32>(uniforms.box_size_x, uniforms.box_size_y, uniforms.box_size_z);
    let r = clamp(uniforms.fillet_radius, 0.0, min(box_sz.x, min(box_sz.y, box_sz.z)));
    return sdf_round_box(p, box_sz, r);
}

// 法線の算出
fn calc_normal(p: vec3<f32>) -> vec3<f32> {
    let e = vec2<f32>(0.001, 0.0);
    return normalize(vec3<f32>(
        map(p + e.xyy) - map(p - e.xyy),
        map(p + e.yxy) - map(p - e.yxy),
        map(p + e.yyx) - map(p - e.yyx)
    ));
}

@fragment
fn fs_main(in: VertexOutput) -> @location(0) vec4<f32> {
    let ro = uniforms.camera_pos.xyz;
    
    // スクリーン座標からレイ方向を計算
    let ndc = vec4<f32>(in.screen_pos.x, in.screen_pos.y, 0.0, 1.0);
    var target = uniforms.inv_view_proj * ndc;
    target = target / target.w;
    let rd = normalize(target.xyz - ro);
    
    // Sphere Tracing
    var t = 0.0;
    var hit = false;
    var p = ro;
    for (var i = 0; i < 80; i = i + 1) {
        p = ro + rd * t;
        let d = map(p);
        if (d < 0.0005) {
            hit = true;
            break;
        }
        t = t + d;
        if (t > 40.0) {
            break;
        }
    }
    
    if (hit) {
        let n = calc_normal(p);
        let l = normalize(vec3<f32>(1.0, 2.0, 3.0));
        let diff = max(dot(n, l), 0.0);
        let ambient = 0.2;
        let col = vec3<f32>(0.2, 0.6, 1.0) * (diff + ambient); // 水色
        return vec4<f32>(col, 1.0);
    }
    
    discard; // 背景を透過
}
