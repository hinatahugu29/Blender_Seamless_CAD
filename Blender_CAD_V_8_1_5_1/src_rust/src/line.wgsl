struct Uniforms {
    view_proj: mat4x4<f32>,
};
@group(0) @binding(0)
var<uniform> uniforms: Uniforms;

struct VertexInput {
    @location(0) position: vec3<f32>,
};

struct VertexOutput {
    @builtin(position) clip_position: vec4<f32>,
};

@vertex
fn vs_main(model: VertexInput) -> VertexOutput {
    var out: VertexOutput;
    let pos = uniforms.view_proj * vec4<f32>(model.position, 1.0);
    
    // WGPU のクリップ空間 Z は 0.0..1.0 (Blender/OpenGL は -1.0..1.0)
    // ハードウェアによる W 除算を考慮して Z を変換: Z_new = (Z + W) / 2
    let z_wgpu = (pos.z + pos.w) * 0.5;
    
    out.clip_position = vec4<f32>(pos.x, pos.y, z_wgpu, pos.w);
    return out;
}

@fragment
fn fs_main(in: VertexOutput) -> @location(0) vec4<f32> {
    return vec4<f32>(0.2, 0.8, 1.0, 1.0); // Cyan
}
