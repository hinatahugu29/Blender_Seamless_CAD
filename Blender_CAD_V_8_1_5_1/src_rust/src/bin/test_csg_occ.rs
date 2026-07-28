// Stage-2 validation: feed REAL OCC-tessellated meshes into the pure-Rust BSP CSG.
// Uses make_variable_box_mesh (a real OCC ThruSections loft tessellation) as the
// mesh source, so this exercises actual OCC tessellation quirks (not synthetic).

use std::collections::HashMap;
use std::time::Instant;

fn validate(verts: &[f32], tris: &[i32]) {
    // weld
    let quant = 1e4_f64;
    let key = |i: usize| -> (i64, i64, i64) {
        let b = i * 3;
        (
            (verts[b] as f64 * quant).round() as i64,
            (verts[b + 1] as f64 * quant).round() as i64,
            (verts[b + 2] as f64 * quant).round() as i64,
        )
    };
    let mut vid: HashMap<(i64, i64, i64), usize> = HashMap::new();
    let mut remap: Vec<usize> = vec![0; verts.len() / 3];
    let mut welded = 0usize;
    for i in 0..(verts.len() / 3) {
        let k = key(i);
        let id = *vid.entry(k).or_insert_with(|| { let v = welded; welded += 1; v });
        remap[i] = id;
    }

    let mut edge_count: HashMap<(usize, usize), i32> = HashMap::new();
    let mut degenerate = 0;
    let mut i = 0;
    while i + 2 < tris.len() {
        let a = remap[tris[i] as usize];
        let b = remap[tris[i + 1] as usize];
        let c = remap[tris[i + 2] as usize];
        i += 3;
        if a == b || b == c || a == c { degenerate += 1; continue; }
        for &(u, v) in &[(a, b), (b, c), (c, a)] {
            let e = if u < v { (u, v) } else { (v, u) };
            *edge_count.entry(e).or_insert(0) += 1;
        }
    }
    let mut boundary = 0;
    let mut nonmanifold = 0;
    for (_, &c) in &edge_count {
        if c == 1 { boundary += 1; }
        else if c > 2 { nonmanifold += 1; }
    }
    let verdict = if boundary == 0 && nonmanifold == 0 && degenerate == 0 { "WATERTIGHT ✓" } else { "NOT CLEAN ✗" };
    println!(
        "    validate: raw_verts={} welded={} tris={} degenerate={} boundary_edges={} nonmanifold_edges={} => {}",
        verts.len() / 3, welded, tris.len() / 3, degenerate, boundary, nonmanifold, verdict
    );
}

// Weld coincident vertices (simulates what generate_full_mesh does globally).
fn weld_mesh(verts: &[f32], tris: &[i32]) -> (Vec<f32>, Vec<i32>) {
    let quant = 1e5_f64;
    let key = |i: usize| -> (i64, i64, i64) {
        let b = i * 3;
        (
            (verts[b] as f64 * quant).round() as i64,
            (verts[b + 1] as f64 * quant).round() as i64,
            (verts[b + 2] as f64 * quant).round() as i64,
        )
    };
    let mut vid: HashMap<(i64, i64, i64), i32> = HashMap::new();
    let mut out_v: Vec<f32> = Vec::new();
    let mut remap: Vec<i32> = vec![0; verts.len() / 3];
    for i in 0..(verts.len() / 3) {
        let k = key(i);
        let id = *vid.entry(k).or_insert_with(|| {
            out_v.push(verts[i * 3]); out_v.push(verts[i * 3 + 1]); out_v.push(verts[i * 3 + 2]);
            (out_v.len() / 3 - 1) as i32
        });
        remap[i] = id;
    }
    let out_t: Vec<i32> = tris.iter().map(|&t| remap[t as usize]).collect();
    (out_v, out_t)
}

fn report_geom(name: &str, verts: &[f32], tris: &[i32]) {
    let mut mn = [f32::MAX; 3];
    let mut mx = [f32::MIN; 3];
    let mut min_r = f32::MAX;
    for i in 0..(verts.len() / 3) {
        for a in 0..3 {
            mn[a] = mn[a].min(verts[i * 3 + a]);
            mx[a] = mx[a].max(verts[i * 3 + a]);
        }
        let r = (verts[i * 3] * verts[i * 3] + verts[i * 3 + 1] * verts[i * 3 + 1]).sqrt();
        min_r = min_r.min(r);
    }
    println!(
        "    [{}] bbox=[{:.3},{:.3},{:.3}]..[{:.3},{:.3},{:.3}] min_radial(xy)={:.3} tris={}",
        name, mn[0], mn[1], mn[2], mx[0], mx[1], mx[2], min_r, tris.len() / 3
    );
}

fn translation(x: f32, y: f32, z: f32) -> [f32; 16] {
    [
        1.0, 0.0, 0.0, x,
        0.0, 1.0, 0.0, y,
        0.0, 0.0, 1.0, z,
        0.0, 0.0, 0.0, 1.0,
    ]
}

fn main() {
    println!("=== Stage-2: BSP CSG on REAL OCC meshes ===");

    // Real OCC-tessellated meshes via ThruSections loft.
    let defl = 0.05;

    // base: 2 x 2 x 2 box
    let (base_v, base_t) = seamless_core::make_variable_box_mesh(2.0, 2.0, 2.0, 2.0, 2.0, defl)
        .expect("base box mesh failed");
    // tool: 0.8 x 0.8 x 4 bar (tall, to punch through the base)
    let (tool_v0, tool_t) = seamless_core::make_variable_box_mesh(0.8, 0.8, 0.8, 0.8, 4.0, defl)
        .expect("tool bar mesh failed");

    // Weld inputs to match what generate_full_mesh produces in the real pipeline.
    let (base_v, base_t) = weld_mesh(&base_v, &base_t);
    let (tool_v0, tool_t) = weld_mesh(&tool_v0, &tool_t);

    println!(
        "OCC meshes (welded): base verts={} tris={} | tool verts={} tris={}",
        base_v.len() / 3, base_t.len() / 3, tool_v0.len() / 3, tool_t.len() / 3
    );

    // Case A: centered through-cut
    {
        let (rv, rt) = seamless_core::csg::subtract(&base_v, &base_t, &tool_v0, &tool_t);
        // timing over repeated runs (steady state, simulating drag frames)
        let mut best = f64::MAX;
        for _ in 0..8 {
            let t0 = Instant::now();
            let _ = seamless_core::csg::subtract(&base_v, &base_t, &tool_v0, &tool_t);
            best = best.min(t0.elapsed().as_secs_f64() * 1000.0);
        }
        println!("[through-center] result verts={} tris={} | best={:.3} ms", rv.len() / 3, rt.len() / 3, best);
        validate(&rv, &rt);
        report_geom("through-center", &rv, &rt);
    }

    // Case B: off-center partial cut (tool shifted so it clips an edge)
    {
        let tool_v = seamless_core::csg::transform_verts(&tool_v0, &translation(0.7, 0.0, 0.0));
        let (rv, rt) = seamless_core::csg::subtract(&base_v, &base_t, &tool_v, &tool_t);
        println!("[through-offcenter] result verts={} tris={}", rv.len() / 3, rt.len() / 3);
        validate(&rv, &rt);
        report_geom("through-offcenter", &rv, &rt);
    }

    // Case C: simulate a drag sweep (tool moving across the base), timing each frame
    {
        println!("--- drag sweep (tool moving across base) ---");
        let mut total = 0.0;
        let n = 20;
        for k in 0..n {
            let x = -1.0 + 2.0 * (k as f32) / (n as f32);
            let tool_v = seamless_core::csg::transform_verts(&tool_v0, &translation(x, 0.0, 0.0));
            let t0 = Instant::now();
            let (_rv, _rt) = seamless_core::csg::subtract(&base_v, &base_t, &tool_v, &tool_t);
            total += t0.elapsed().as_secs_f64() * 1000.0;
        }
        println!("    avg frame subtract = {:.3} ms over {} frames", total / n as f64, n);
    }
}
