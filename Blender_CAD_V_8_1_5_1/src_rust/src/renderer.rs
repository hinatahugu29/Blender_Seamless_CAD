use std::sync::Arc;
use wgpu::util::DeviceExt;

#[repr(C)]
#[derive(Debug, Copy, Clone, bytemuck::Pod, bytemuck::Zeroable)]
pub struct Uniforms {
    pub view_proj: [[f32; 4]; 4],
}

// SDFプレビューのレイマーチング境界となる単位立方体(-1..1)。box_sizeによる
// スケーリングは頂点シェーダ側(uniforms.box_size_*)で行うため、この頂点データ
// 自体はbox_sizeに依存せず固定であり、CadRenderer::new()で一度だけGPUへ
// アップロードして使い回す(以前はフレームごとに再構築・再アップロードしていた)。
const SDF_CUBE_VERTICES: [f32; 108] = [
    -1.0, -1.0,  1.0,   1.0, -1.0,  1.0,   1.0,  1.0,  1.0,
    -1.0, -1.0,  1.0,   1.0,  1.0,  1.0,  -1.0,  1.0,  1.0,
    -1.0, -1.0, -1.0,  -1.0,  1.0, -1.0,   1.0,  1.0, -1.0,
    -1.0, -1.0, -1.0,   1.0,  1.0, -1.0,   1.0, -1.0, -1.0,
    -1.0,  1.0, -1.0,  -1.0,  1.0,  1.0,   1.0,  1.0,  1.0,
    -1.0,  1.0, -1.0,   1.0,  1.0,  1.0,   1.0,  1.0, -1.0,
    -1.0, -1.0, -1.0,   1.0, -1.0, -1.0,   1.0, -1.0,  1.0,
    -1.0, -1.0, -1.0,   1.0, -1.0,  1.0,  -1.0, -1.0,  1.0,
     1.0, -1.0, -1.0,   1.0,  1.0, -1.0,   1.0,  1.0,  1.0,
     1.0, -1.0, -1.0,   1.0,  1.0,  1.0,   1.0, -1.0,  1.0,
    -1.0, -1.0, -1.0,  -1.0, -1.0,  1.0,  -1.0,  1.0,  1.0,
    -1.0, -1.0, -1.0,  -1.0,  1.0,  1.0,  -1.0,  1.0, -1.0,
];

#[repr(C)]
#[derive(Debug, Copy, Clone, bytemuck::Pod, bytemuck::Zeroable)]
pub struct SdfUniforms {
    pub view_proj: [[f32; 4]; 4],
    pub inv_view_proj: [[f32; 4]; 4],
    pub camera_pos: [f32; 4],
    pub fillet_radius: f32,
    pub box_size_x: f32,
    pub box_size_y: f32,
    pub box_size_z: f32,
}

pub struct CadRenderer {
    pub device: wgpu::Device,
    pub queue: wgpu::Queue,
    pub pipeline: wgpu::RenderPipeline,
    pub uniform_buffer: wgpu::Buffer,
    pub uniform_bind_group: wgpu::BindGroup,
    
    // SDFプレビュー用
    pub sdf_pipeline: wgpu::RenderPipeline,
    pub sdf_uniform_buffer: wgpu::Buffer,
    pub sdf_uniform_bind_group: wgpu::BindGroup,
    pub sdf_cube_vertex_buffer: wgpu::Buffer,

    // リソースの再利用
    pub offscreen_texture: Mutex<Option<(wgpu::Texture, wgpu::TextureView, u32, u32)>>,
    pub output_buffer: Mutex<Option<(wgpu::Buffer, u32)>>,
}

impl CadRenderer {
    pub async fn new() -> Option<Self> {
        let instance = wgpu::Instance::new(wgpu::InstanceDescriptor {
            // Windows/Intel環境で安定しているPRIMARY(DX12/Vulkan)を優先
            backends: wgpu::Backends::PRIMARY,
            ..Default::default()
        });

        let adapter = instance.request_adapter(
            &wgpu::RequestAdapterOptions {
                power_preference: wgpu::PowerPreference::HighPerformance,
                compatible_surface: None,
                force_fallback_adapter: false,
            },
        ).await?;

        let info = adapter.get_info();
        println!("Rust Debug: Renderer Initializing... Adapter: '{}', Backend: {:?}", info.name, info.backend);

        // --- 知見の活用: 90%ルールによるリソース制限の最適化 ---
        let limits = adapter.limits();
        let required_limits = wgpu::Limits {
            // 共有メモリ環境でのクラッシュを防ぐため、ハードウェアの限界の90%に抑える
            max_storage_buffer_binding_size: (limits.max_storage_buffer_binding_size as f64 * 0.9) as u32,
            max_buffer_size: (limits.max_buffer_size as f64 * 0.9) as u64,
            max_texture_dimension_2d: (limits.max_texture_dimension_2d as f32 * 0.9) as u32,
            ..wgpu::Limits::default()
        };

        let (device, queue) = adapter.request_device(
            &wgpu::DeviceDescriptor {
                required_features: wgpu::Features::empty(),
                required_limits,
                label: Some("CAD Render Device"),
            },
            None,
        ).await.ok()?;

        // 🌟【超重要】情報多めのデバッグログ: WGPUのエラー捕捉コールバックを登録し、内蔵GPUエラーを完全に検知する！
        device.on_uncaptured_error(Box::new(|error| {
            eprintln!("🔴 Rust WGPU Validation/Device Error [Uncaptured]: {:?}", error);
        }));

        device.set_device_lost_callback(Box::new(|reason, message| {
            eprintln!("🔴 Rust WGPU DEVICE LOST! Reason: {:?}, Message: {}", reason, message);
        }));

        // Uniforms Setup
        let uniforms = Uniforms { view_proj: [[0.0; 4]; 4] };
        let uniform_buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("Uniform Buffer"),
            contents: bytemuck::cast_slice(&[uniforms]),
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        });

        let uniform_bind_group_layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            entries: &[wgpu::BindGroupLayoutEntry {
                binding: 0,
                visibility: wgpu::ShaderStages::VERTEX,
                ty: wgpu::BindingType::Buffer {
                    ty: wgpu::BufferBindingType::Uniform,
                    has_dynamic_offset: false,
                    min_binding_size: None,
                },
                count: None,
            }],
            label: Some("uniform_bind_group_layout"),
        });

        let uniform_bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
            layout: &uniform_bind_group_layout,
            entries: &[wgpu::BindGroupEntry {
                binding: 0,
                resource: uniform_buffer.as_entire_binding(),
            }],
            label: Some("uniform_bind_group"),
        });

        // Pipeline Setup
        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("Line Shader"),
            source: wgpu::ShaderSource::Wgsl(include_str!("line.wgsl").into()),
        });

        let pipeline_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("Line Pipeline Layout"),
            bind_group_layouts: &[&uniform_bind_group_layout],
            push_constant_ranges: &[],
        });

        let pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("Line Pipeline"),
            layout: Some(&pipeline_layout),
            vertex: wgpu::VertexState {
                module: &shader,
                entry_point: "vs_main",
                buffers: &[
                    wgpu::VertexBufferLayout {
                        array_stride: 12,
                        step_mode: wgpu::VertexStepMode::Vertex,
                        attributes: &[wgpu::VertexAttribute {
                            format: wgpu::VertexFormat::Float32x3,
                            offset: 0,
                            shader_location: 0,
                        }],
                    },
                ],
            },
            fragment: Some(wgpu::FragmentState {
                module: &shader,
                entry_point: "fs_main",
                targets: &[Some(wgpu::ColorTargetState {
                    format: wgpu::TextureFormat::Rgba8Unorm,
                    blend: Some(wgpu::BlendState::ALPHA_BLENDING),
                    write_mask: wgpu::ColorWrites::ALL,
                })],
            }),
            primitive: wgpu::PrimitiveState {
                topology: wgpu::PrimitiveTopology::LineList,
                ..Default::default()
            },
            depth_stencil: None,
            multisample: wgpu::MultisampleState::default(),
            multiview: None,
        });

        // --- SDF Setup ---
        let sdf_uniforms = SdfUniforms {
            view_proj: [[0.0; 4]; 4],
            inv_view_proj: [[0.0; 4]; 4],
            camera_pos: [0.0; 4],
            fillet_radius: 0.0,
            box_size_x: 1.0,
            box_size_y: 1.0,
            box_size_z: 1.0,
        };
        let sdf_uniform_buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("SDF Uniform Buffer"),
            contents: bytemuck::cast_slice(&[sdf_uniforms]),
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        });

        let sdf_uniform_bind_group_layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            entries: &[wgpu::BindGroupLayoutEntry {
                binding: 0,
                visibility: wgpu::ShaderStages::VERTEX | wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Buffer {
                    ty: wgpu::BufferBindingType::Uniform,
                    has_dynamic_offset: false,
                    min_binding_size: None,
                },
                count: None,
            }],
            label: Some("sdf_uniform_bind_group_layout"),
        });

        let sdf_uniform_bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
            layout: &sdf_uniform_bind_group_layout,
            entries: &[wgpu::BindGroupEntry {
                binding: 0,
                resource: sdf_uniform_buffer.as_entire_binding(),
            }],
            label: Some("sdf_uniform_bind_group"),
        });

        let sdf_shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("SDF Shader"),
            source: wgpu::ShaderSource::Wgsl(include_str!("sdf_preview.wgsl").into()),
        });

        let sdf_pipeline_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("SDF Pipeline Layout"),
            bind_group_layouts: &[&sdf_uniform_bind_group_layout],
            push_constant_ranges: &[],
        });

        let sdf_pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("SDF Pipeline"),
            layout: Some(&sdf_pipeline_layout),
            vertex: wgpu::VertexState {
                module: &sdf_shader,
                entry_point: "vs_main",
                buffers: &[
                    wgpu::VertexBufferLayout {
                        array_stride: 12,
                        step_mode: wgpu::VertexStepMode::Vertex,
                        attributes: &[wgpu::VertexAttribute {
                            format: wgpu::VertexFormat::Float32x3,
                            offset: 0,
                            shader_location: 0,
                        }],
                    },
                ],
            },
            fragment: Some(wgpu::FragmentState {
                module: &sdf_shader,
                entry_point: "fs_main",
                targets: &[Some(wgpu::ColorTargetState {
                    format: wgpu::TextureFormat::Rgba8Unorm,
                    blend: Some(wgpu::BlendState::ALPHA_BLENDING),
                    write_mask: wgpu::ColorWrites::ALL,
                })],
            }),
            primitive: wgpu::PrimitiveState {
                topology: wgpu::PrimitiveTopology::TriangleList,
                ..Default::default()
            },
            depth_stencil: None,
            multisample: wgpu::MultisampleState::default(),
            multiview: None,
        });

        let sdf_cube_vertex_buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("SDF Bounding Cube"),
            contents: bytemuck::cast_slice(&SDF_CUBE_VERTICES),
            usage: wgpu::BufferUsages::VERTEX,
        });

        // --- 知見の活用: ウォームアップ・パスの実行 ---
        // 初回の本番描画でのドライバハングを防ぐため、1x1のダミー描画を実行
        {
            let dummy_texture = device.create_texture(&wgpu::TextureDescriptor {
                size: wgpu::Extent3d { width: 1, height: 1, depth_or_array_layers: 1 },
                mip_level_count: 1, sample_count: 1, dimension: wgpu::TextureDimension::D2,
                format: wgpu::TextureFormat::Rgba8Unorm,
                usage: wgpu::TextureUsages::RENDER_ATTACHMENT,
                label: Some("Warm-up Texture"), view_formats: &[],
            });
            let dummy_view = dummy_texture.create_view(&wgpu::TextureViewDescriptor::default());
            let mut encoder = device.create_command_encoder(&wgpu::CommandEncoderDescriptor { label: Some("Warm-up Encoder") });
            {
                let _render_pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                    label: Some("Warm-up Pass"),
                    color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                        view: &dummy_view, resolve_target: None,
                        ops: wgpu::Operations { load: wgpu::LoadOp::Clear(wgpu::Color::TRANSPARENT), store: wgpu::StoreOp::Store },
                    })],
                    depth_stencil_attachment: None, occlusion_query_set: None, timestamp_writes: None,
                });
            }
            queue.submit(Some(encoder.finish()));
            device.poll(wgpu::Maintain::Wait);
            println!("Rust Debug: Warm-up pass completed.");
        }

        Some(Self {
            device,
            queue,
            pipeline,
            uniform_buffer,
            uniform_bind_group,
            sdf_pipeline,
            sdf_uniform_buffer,
            sdf_uniform_bind_group,
            sdf_cube_vertex_buffer,
            offscreen_texture: Mutex::new(None),
            output_buffer: Mutex::new(None),
        })
    }

    pub fn update_uniforms(&self, view_proj: [[f32; 4]; 4]) {
        let uniforms = Uniforms { view_proj };
        self.queue.write_buffer(&self.uniform_buffer, 0, bytemuck::cast_slice(&[uniforms]));
    }

    pub fn create_buffer<T: bytemuck::Pod>(&self, data: &[T], label: &str) -> wgpu::Buffer {
        self.device.create_buffer_init(
            &wgpu::util::BufferInitDescriptor {
                label: Some(label),
                contents: bytemuck::cast_slice(data),
                usage: wgpu::BufferUsages::VERTEX | wgpu::BufferUsages::COPY_DST,
            }
        )
    }

    pub fn render_to_pixels(&self, width: u32, height: u32, view_proj: [[f32; 4]; 4]) -> Vec<u8> {
        self.update_uniforms(view_proj);
        
        let align = wgpu::COPY_BYTES_PER_ROW_ALIGNMENT;
        let unpadded_bytes_per_row = width * 4;
        let padding = (align - unpadded_bytes_per_row % align) % align;
        let padded_bytes_per_row = unpadded_bytes_per_row + padding;

        // テクスチャの再利用チェック
        {
            let mut tex_lock = self.offscreen_texture.lock().unwrap();
            let needs_recreate = match *tex_lock {
                Some((_, _, w, h)) => w != width || h != height,
                None => true,
            };
            if needs_recreate {
                // println!("Rust Debug: Creating offscreen texture ({}x{}). Size: {} bytes", width, height, width * height * 4);
                let texture_desc = wgpu::TextureDescriptor {
                    size: wgpu::Extent3d { width, height, depth_or_array_layers: 1 },
                    mip_level_count: 1,
                    sample_count: 1,
                    dimension: wgpu::TextureDimension::D2,
                    format: wgpu::TextureFormat::Rgba8Unorm,
                    usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC,
                    label: Some("Offscreen Texture"),
                    view_formats: &[],
                };
                let texture = self.device.create_texture(&texture_desc);
                let view = texture.create_view(&wgpu::TextureViewDescriptor::default());
                *tex_lock = Some((texture, view, width, height));
            }
        }

        // バッファの再利用チェック
        {
            let mut buf_lock = self.output_buffer.lock().unwrap();
            let output_buffer_size = (padded_bytes_per_row * height) as wgpu::BufferAddress;
            let needs_recreate = match *buf_lock {
                Some((_, size)) => (size as wgpu::BufferAddress) < output_buffer_size,
                None => true,
            };
            if needs_recreate {
                // println!("Rust Debug: Creating output buffer. Padded Bytes Per Row: {}, Padded Size: {} bytes", padded_bytes_per_row, output_buffer_size);
                let output_buffer_desc = wgpu::BufferDescriptor {
                    size: output_buffer_size,
                    usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
                    label: Some("Output Buffer"),
                    mapped_at_creation: false,
                };
                let output_buffer = self.device.create_buffer(&output_buffer_desc);
                *buf_lock = Some((output_buffer, output_buffer_size as u32));
            }
        }

        let tex_lock = self.offscreen_texture.lock().unwrap();
        let buf_lock = self.output_buffer.lock().unwrap();
        let (texture, view, _, _) = tex_lock.as_ref().unwrap();
        let (output_buffer, _) = buf_lock.as_ref().unwrap();

        // pending_stack_edges があればここでGPUアップロード（描画コールバックスレッド上）
        // edge_points はポリライン形式 (各辺N頂点) → LineList (連続する2頂点=1線分) へ変換
        // スタックごとに独立したバッファを持つことで、複数CADパーツが同時に存在する
        // シーンでも互いの辺データを上書きしないようにする。
        {
            let mut scene = GLOBAL_SCENE.lock().unwrap();
            let pending_keys: Vec<isize> = scene.pending_stack_edges.keys().cloned().collect();
            for stack_ptr in pending_keys {
                let (points, counts) = match scene.pending_stack_edges.remove(&stack_ptr) {
                    Some(v) => v,
                    None => continue,
                };
                let mut line_list: Vec<f32> = Vec::with_capacity(points.len() * 2);
                let mut offset = 0usize;
                for &count in &counts {
                    let n = count as usize;
                    for i in 0..n.saturating_sub(1) {
                        let a = (offset + i) * 3;
                        let b = (offset + i + 1) * 3;
                        if b + 3 <= points.len() {
                            line_list.extend_from_slice(&points[a..a + 3]);
                            line_list.extend_from_slice(&points[b..b + 3]);
                        }
                    }
                    offset += n;
                }
                if !line_list.is_empty() {
                    let count = (line_list.len() / 3) as u32;
                    let buffer = self.create_buffer(&line_list, "CAD Edges");
                    scene.stack_edges.insert(stack_ptr, (buffer, count));
                } else {
                    scene.stack_edges.remove(&stack_ptr);
                }
            }
        }

        let mut encoder = self.device.create_command_encoder(&wgpu::CommandEncoderDescriptor { label: Some("Render Encoder") });
        let scene = GLOBAL_SCENE.lock().unwrap();
        
        // Viewport debug logs removed to optimize viewport performance

        {
            let mut render_pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("Render Pass"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &view,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(wgpu::Color { r: 0.0, g: 0.0, b: 0.0, a: 0.0 }),
                        store: wgpu::StoreOp::Store,
                    },
                })],
                depth_stencil_attachment: None,
                occlusion_query_set: None,
                timestamp_writes: None,
            });

            render_pass.set_pipeline(&self.pipeline);
            render_pass.set_bind_group(0, &self.uniform_bind_group, &[]);

            // 全スタックの辺を同一パスでまとめて描画する（複数CADパーツ対応）
            for (buffer, count) in scene.stack_edges.values() {
                render_pass.set_vertex_buffer(0, buffer.slice(..));
                render_pass.draw(0..*count, 0..1);
            }
        }

        encoder.copy_texture_to_buffer(
            wgpu::ImageCopyTexture {
                aspect: wgpu::TextureAspect::All,
                texture: &texture,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
            },
            wgpu::ImageCopyBuffer {
                buffer: &output_buffer,
                layout: wgpu::ImageDataLayout {
                    offset: 0,
                    bytes_per_row: Some(padded_bytes_per_row),
                    rows_per_image: Some(height),
                },
            },
            wgpu::Extent3d { width, height, depth_or_array_layers: 1 },
        );

        self.queue.submit(Some(encoder.finish()));

        let buffer_slice = output_buffer.slice(..);
        let (tx, rx) = std::sync::mpsc::channel();
        buffer_slice.map_async(wgpu::MapMode::Read, move |res| {
            tx.send(res).unwrap();
        });
        self.device.poll(wgpu::Maintain::Wait);

        if width == 0 || height == 0 {
            return vec![0; (width * height * 4) as usize];
        }

        if let Ok(Ok(_)) = rx.recv() {
            let padded_data = buffer_slice.get_mapped_range();
            let mut result = Vec::with_capacity((width * height * 4) as usize);
            
            // 安全なコピー: バッファ全体ではなく、現在の height 分だけをコピーする
            for y in 0..height {
                let start = (y * padded_bytes_per_row) as usize;
                let end = start + unpadded_bytes_per_row as usize;
                if end <= padded_data.len() {
                    result.extend_from_slice(&padded_data[start..end]);
                } else {
                    // 万が一バッファが足りない場合は透明ピクセルで埋める
                    result.extend(std::iter::repeat(0).take(unpadded_bytes_per_row as usize));
                }
            }
            
            drop(padded_data);
            output_buffer.unmap();
            result
        } else {
            vec![0; (width * height * 4) as usize]
        }
    }

    pub fn render_to_pixels_sdf(
        &self,
        width: u32,
        height: u32,
        view_proj: [[f32; 4]; 4],
        inv_view_proj: [[f32; 4]; 4],
        camera_pos: [f32; 4],
        fillet_radius: f32,
        box_size: [f32; 3],
    ) -> Vec<u8> {
        let sdf_uniforms = SdfUniforms {
            view_proj,
            inv_view_proj,
            camera_pos,
            fillet_radius,
            box_size_x: box_size[0],
            box_size_y: box_size[1],
            box_size_z: box_size[2],
        };
        self.queue.write_buffer(&self.sdf_uniform_buffer, 0, bytemuck::cast_slice(&[sdf_uniforms]));

        let align = wgpu::COPY_BYTES_PER_ROW_ALIGNMENT;
        let unpadded_bytes_per_row = width * 4;
        let padding = (align - unpadded_bytes_per_row % align) % align;
        let padded_bytes_per_row = unpadded_bytes_per_row + padding;

        {
            let mut tex_lock = self.offscreen_texture.lock().unwrap();
            let needs_recreate = match *tex_lock {
                Some((_, _, w, h)) => w != width || h != height,
                None => true,
            };
            if needs_recreate {
                let texture_desc = wgpu::TextureDescriptor {
                    size: wgpu::Extent3d { width, height, depth_or_array_layers: 1 },
                    mip_level_count: 1,
                    sample_count: 1,
                    dimension: wgpu::TextureDimension::D2,
                    format: wgpu::TextureFormat::Rgba8Unorm,
                    usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC,
                    label: Some("SDF Offscreen Texture"),
                    view_formats: &[],
                };
                let texture = self.device.create_texture(&texture_desc);
                let view = texture.create_view(&wgpu::TextureViewDescriptor::default());
                *tex_lock = Some((texture, view, width, height));
            }
        }

        {
            let mut buf_lock = self.output_buffer.lock().unwrap();
            let output_buffer_size = (padded_bytes_per_row * height) as wgpu::BufferAddress;
            let needs_recreate = match *buf_lock {
                Some((_, size)) => (size as wgpu::BufferAddress) < output_buffer_size,
                None => true,
            };
            if needs_recreate {
                let output_buffer_desc = wgpu::BufferDescriptor {
                    size: output_buffer_size,
                    usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
                    label: Some("SDF Output Buffer"),
                    mapped_at_creation: false,
                };
                let output_buffer = self.device.create_buffer(&output_buffer_desc);
                *buf_lock = Some((output_buffer, output_buffer_size as u32));
            }
        }

        let tex_lock = self.offscreen_texture.lock().unwrap();
        let buf_lock = self.output_buffer.lock().unwrap();
        let (texture, view, _, _) = tex_lock.as_ref().unwrap();
        let (output_buffer, _) = buf_lock.as_ref().unwrap();

        // 境界キューブの頂点はCadRenderer::new()で一度だけ作成済み(sdf_cube_vertex_buffer)。
        // box_sizeによるスケーリングは頂点シェーダ側でuniformsを使って行うため、
        // ここで毎フレームVecを組み立ててGPUバッファを再生成する必要はない。
        let mut encoder = self.device.create_command_encoder(&wgpu::CommandEncoderDescriptor { label: Some("SDF Render Encoder") });

        {
            let mut render_pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("SDF Render Pass"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &view,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(wgpu::Color { r: 0.0, g: 0.0, b: 0.0, a: 0.0 }),
                        store: wgpu::StoreOp::Store,
                    },
                })],
                depth_stencil_attachment: None,
                occlusion_query_set: None,
                timestamp_writes: None,
            });

            render_pass.set_pipeline(&self.sdf_pipeline);
            render_pass.set_bind_group(0, &self.sdf_uniform_bind_group, &[]);
            render_pass.set_vertex_buffer(0, self.sdf_cube_vertex_buffer.slice(..));
            render_pass.draw(0..36, 0..1);
        }

        encoder.copy_texture_to_buffer(
            wgpu::ImageCopyTexture {
                aspect: wgpu::TextureAspect::All,
                texture: &texture,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
            },
            wgpu::ImageCopyBuffer {
                buffer: &output_buffer,
                layout: wgpu::ImageDataLayout {
                    offset: 0,
                    bytes_per_row: Some(padded_bytes_per_row),
                    rows_per_image: Some(height),
                },
            },
            wgpu::Extent3d { width, height, depth_or_array_layers: 1 },
        );

        self.queue.submit(Some(encoder.finish()));

        let buffer_slice = output_buffer.slice(..);
        let (tx, rx) = std::sync::mpsc::channel();
        buffer_slice.map_async(wgpu::MapMode::Read, move |res| {
            tx.send(res).unwrap();
        });
        self.device.poll(wgpu::Maintain::Wait);

        if width == 0 || height == 0 {
            return vec![0; (width * height * 4) as usize];
        }

        if let Ok(Ok(_)) = rx.recv() {
            let padded_data = buffer_slice.get_mapped_range();
            let mut result = Vec::with_capacity((width * height * 4) as usize);
            for y in 0..height {
                let start = (y * padded_bytes_per_row) as usize;
                let end = start + unpadded_bytes_per_row as usize;
                if end <= padded_data.len() {
                    result.extend_from_slice(&padded_data[start..end]);
                } else {
                    result.extend(std::iter::repeat(0).take(unpadded_bytes_per_row as usize));
                }
            }
            drop(padded_data);
            output_buffer.unmap();
            result
        } else {
            vec![0; (width * height * 4) as usize]
        }
    }
}

// グローバルなレンダラーインスタンスの管理
use once_cell::sync::Lazy;
use std::sync::Mutex;

pub static GLOBAL_RENDERER: Lazy<Mutex<Option<Arc<CadRenderer>>>> = Lazy::new(|| Mutex::new(None));

pub fn get_renderer() -> Option<Arc<CadRenderer>> {
    let mut renderer = GLOBAL_RENDERER.lock().unwrap();
    if renderer.is_none() {
        // 非同期初期化を同期的に実行（初回のみ）
        if let Some(r) = pollster::block_on(CadRenderer::new()) {
            *renderer = Some(Arc::new(r));
        }
    }
    renderer.clone()
}

use std::collections::HashMap;

pub struct GpuScene {
    // stack_ptr ごとの確定済みGPUバッファ (複数CADパーツが同時に存在しても
    // 互いの辺データを上書きしないよう、スタック単位で保持する)
    pub stack_edges: HashMap<isize, (wgpu::Buffer, u32)>,
    pub face_buffer: Option<wgpu::Buffer>,
    pub face_count: u32,
    // ジオメトリスレッドから書き込まれる生データ; render_to_pixels() でGPUアップロード
    // (points: flat xyz, counts: 各辺の頂点数)
    pub pending_stack_edges: HashMap<isize, (Vec<f32>, Vec<i32>)>,
}

impl GpuScene {
    pub fn new() -> Self {
        Self {
            stack_edges: HashMap::new(),
            face_buffer: None,
            face_count: 0,
            pending_stack_edges: HashMap::new(),
        }
    }
}

pub static GLOBAL_SCENE: Lazy<Mutex<GpuScene>> = Lazy::new(|| Mutex::new(GpuScene::new()));

pub fn update_scene_edges(stack_ptr: isize, points: &[f32], counts: &[i32]) {
    // GPUアロケーションをジオメトリスレッドで行わない。
    // 生データを pending に保存し、render_to_pixels() (描画コールバック) で遅延アップロードする。
    let mut scene = GLOBAL_SCENE.lock().unwrap();
    scene.pending_stack_edges.insert(stack_ptr, (points.to_vec(), counts.to_vec()));
}

// スタック削除時、そのスタック分の古いジオメトリだけをオーバーレイから取り除く
// (他の生存中のCADパーツの表示には影響しない)
pub fn remove_stack_edges(stack_ptr: isize) {
    let mut scene = GLOBAL_SCENE.lock().unwrap();
    scene.pending_stack_edges.remove(&stack_ptr);
    scene.stack_edges.remove(&stack_ptr);
}
