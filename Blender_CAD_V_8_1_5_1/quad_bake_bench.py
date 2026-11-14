"""Quad Bake benchmark over sample .blend files, with a regression gate.

    blender --background --factory-startup --python quad_bake_bench.py -- \
        <samples_dir> [--write-baseline]

Every collection with a CAD stack in every .blend in <samples_dir> is baked at
two tolerances, uniform density on and off. Per run it records the quad share,
polygon count, volume, non-manifold edges, skewed quads (a corner under 30 or
over 150 degrees), the smallest corner angle and the time taken.

With --write-baseline the results go to quad_bake_baseline.json next to this
script. Without it they are compared to that baseline. The run fails (exit
code 1) when, for any run:
  - the quad share drops by more than QUAD_DROP points,
  - the smallest angle drops by more than ANGLE_DROP degrees, or below MIN_ANGLE,
  - the volume moves by more than VOL_REL (relative),
  - a non-manifold edge appears, or a face fails to fill.
The kernel listens on port 8080. Close any running Blender that holds it first,
or the numbers come from its kernel.
"""
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy  # noqa: E402
import bmesh  # noqa: E402

QUAD_DROP = 0.5
ANGLE_DROP = 5.0
MIN_ANGLE = 10.0
VOL_REL = 5e-3
BASELINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "quad_bake_baseline.json")


def measure(samples):
    import CAD_8_1_5_1 as addon
    addon.register()
    from CAD_8_1_5_1 import core_bridge as cb
    from CAD_8_1_5_1.operators.quad_bake_mesh import make_quad_bake_mesh
    rows = {}
    for fn in sorted(os.listdir(samples)):
        if not fn.endswith(".blend"):
            continue
        bpy.ops.wm.open_mainfile(filepath=os.path.join(samples, fn))
        for col in list(bpy.data.collections):
            try:
                cb._update_cad_preview_internal_for_col(col, bpy.context, force=True, sync=True)
                ptr = cb.get_or_create_stack_ptr(col)
            except Exception:
                continue
            if not ptr:
                continue
            for tol in (0.01, 0.002):
                for uni in (True, False):
                    key = "%s|%s|%g|%s" % (fn, col.name, tol, "uni" if uni else "raw")
                    t0 = time.time()
                    try:
                        d = cb.get_core().quad_topology(int(ptr), tol, uni)
                        if not d:
                            continue                # no solid in this collection
                        me, rep = make_quad_bake_mesh("bench", d)
                    except Exception as e:
                        if "empty shape" not in repr(e):
                            rows[key] = {"error": repr(e)}
                        continue
                    bm = bmesh.new()
                    bm.from_mesh(me)
                    sizes = [len(f.verts) for f in bm.faces]
                    mins, bad = [], 0
                    for f in bm.faces:
                        if len(f.verts) != 4:
                            continue
                        a = [math.degrees(lo.calc_angle()) for lo in f.loops]
                        mins.append(min(a))
                        if min(a) < 30.0 or max(a) > 150.0:
                            bad += 1
                    rows[key] = {
                        "polys": len(sizes),
                        "quad": round(100.0 * sizes.count(4) / max(1, len(sizes)), 3),
                        "vol": bm.calc_volume(signed=True),
                        "nonman": sum(1 for e in bm.edges if not e.is_manifold),
                        "failed": rep.get("failed", 0),
                        "bad": bad,
                        "min_angle": round(min(mins), 2) if mins else 90.0,
                        "t": round(time.time() - t0, 3),
                    }
                    bm.free()
                    bpy.data.meshes.remove(me)
    return rows


def compare(base, cur):
    problems = []
    for key, b in sorted(base.items()):
        c = cur.get(key)
        if c is None:
            problems.append("%s: missing" % key)
            continue
        if "error" in c and "error" not in b:
            problems.append("%s: error %s" % (key, c["error"]))
            continue
        if "error" in c:
            continue
        if c["quad"] < b["quad"] - QUAD_DROP:
            problems.append("%s: quads %.2f%% -> %.2f%%" % (key, b["quad"], c["quad"]))
        if c["min_angle"] < min(b["min_angle"] - ANGLE_DROP, MIN_ANGLE):
            problems.append("%s: smallest angle %.1f -> %.1f" % (key, b["min_angle"], c["min_angle"]))
        if abs(c["vol"] - b["vol"]) > VOL_REL * max(abs(b["vol"]), 1e-9):
            problems.append("%s: volume %.5f -> %.5f" % (key, b["vol"], c["vol"]))
        if c["nonman"] > b["nonman"]:
            problems.append("%s: non-manifold edges %d -> %d" % (key, b["nonman"], c["nonman"]))
        if c["failed"] > b["failed"]:
            problems.append("%s: failed faces %d -> %d" % (key, b["failed"], c["failed"]))
    return problems


def main():
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if not args:
        print("usage: ... --python quad_bake_bench.py -- <samples_dir> [--write-baseline]")
        os._exit(2)
    cur = measure(args[0])
    if "--write-baseline" in args:
        json.dump(cur, open(BASELINE, "w", encoding="utf-8"), indent=1, sort_keys=True)
        print("baseline written: %d runs" % len(cur))
        sys.stdout.flush()
        os._exit(0)
    base = json.load(open(BASELINE, encoding="utf-8"))
    problems = compare(base, cur)
    tb = sum(v.get("t", 0) for v in base.values())
    tc = sum(v.get("t", 0) for v in cur.values())
    print("runs %d, time %.1fs (baseline %.1fs)" % (len(cur), tc, tb))
    for p in problems:
        print("REGRESSION", p)
    print("QUAD BAKE BENCH:", "FAIL" if problems else "OK")
    sys.stdout.flush()
    os._exit(1 if problems else 0)


main()
