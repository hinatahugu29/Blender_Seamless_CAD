"""プリミティブごとに「UI に出ている項目」と「実際に形状へ効く項目」を突き合わせる。

    "C:\\Program Files\\Blender Foundation\\Blender 5.1\\blender.exe" ^
        --background --factory-startup --python audit_ui_params.py

なぜ要るか: 効かないパラメータが UI に並んでいると、利用者は「壊れている」と受け取る。
2026-08-01 の調査で CYLINDER/SPHERE の Radius、SLOT/CONE の size 余剰成分が
この状態だった。目視では見つけられないので機械で突き合わせる。

判定方法:
- **効く**   … 値を変えて強制再計算し、頂点数か bounding box が変わったもの
- **表示中** … Active Property Editor の draw を偽 layout で走らせて拾った prop 名

size は成分ごとに見る。`index=` 付きならその成分だけ、無しなら3成分すべてが
表示中とみなす。これをやらないと「Height と書いてあるのに X/Y も並んでいる」型の
不一致を取りこぼす。

終了コード 0 = 不一致なし、1 = 不一致あり。
"""

import math
import os
import sys

ADDON_PARENT = os.path.dirname(os.path.abspath(__file__))
if ADDON_PARENT not in sys.path:
    sys.path.insert(0, ADDON_PARENT)

import bpy  # noqa: E402

TYPES = ['BOX', 'CYLINDER', 'SPHERE', 'CONE', 'TORUS', 'SLOT',
         'POLYGON', 'GEAR', 'HELIX', 'VARIABLE_BOX', 'ARC']

SCALARS = ['radius', 'radius2', 'minor_radius', 'extrude_height', 'distance',
           'turns', 'pipe_radius', 'module', 'pressure_angle',
           'angle_start', 'angle_end']

# 形状に効かなくても UI にあってよいもの(配置・履歴・表示上の設定)
IGNORE = {'location', 'local_location', 'rotation', 'operation', 'name', 'uuid',
          'use_pipe', 'fill_closed', 'top_shape', 'bot_shape',
          'unify_faces', 'unify_edges', 'use_independent_transform', 'sides'}


class FakeLayout:
    """layout.prop で触られた名前を集めるだけの偽レイアウト。"""

    def __init__(self, sink):
        self.sink = sink

    def prop(self, data, name, **kw):
        # index= で1成分だけ描いている場合は、その成分だけが「表示中」。
        # これを見ないと size の余剰成分の死角を見逃す。
        idx = kw.get("index", -1)
        if name == "size" and idx in (0, 1, 2):
            self.sink.append(f"size.{'xyz'[idx]}")
        elif name == "size":
            self.sink.extend(["size.x", "size.y", "size.z"])
        else:
            self.sink.append(name)

    def operator(self, *a, **kw):
        return type("Op", (), {"index": 0, "prop_name": ""})()

    def row(self, **kw):
        return self

    def column(self, **kw):
        return self

    def box(self):
        return self

    def split(self, **kw):
        return self

    def __getattr__(self, n):
        return lambda *a, **kw: None


def _fresh():
    from CAD_8_1_5_1 import utils
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for col in list(bpy.data.collections):
        bpy.data.collections.remove(col)
    utils._registered_cad_collections.clear()
    bpy.ops.seamless.start_cad()
    return utils.get_active_collection(bpy.context)


def _signature(ptr, core):
    """形状の指紋。頂点数と bounding box。"""
    from CAD_8_1_5_1 import core_bridge
    # force=True にしないと「前回と同じ内容ならスキップ」の重複除去に引っかかる
    core_bridge.update_cad_preview_forced(bpy.context)
    res = core.generate_mesh(ptr, 0.08, math.radians(12.0))
    if not res or len(res[0]) == 0:
        return None
    v = res[0]
    xs, ys, zs = v[0::3], v[1::3], v[2::3]
    return (len(xs), round(max(xs) - min(xs), 3),
            round(max(ys) - min(ys), 3), round(max(zs) - min(zs), 3))


def effective_params(prim_type):
    """この型で実際に形状を変えるパラメータ名の集合を返す。"""
    from CAD_8_1_5_1 import utils, core_bridge
    col = _fresh()
    ptr = int(col.seamless_cad_stack_ptr)
    core = core_bridge.get_core()
    bpy.ops.seamless.add_primitive(type=prim_type)
    prim = utils.get_active_props(bpy.context).primitives[-1]

    base = _signature(ptr, core)
    if base is None:
        return None, prim

    live = set()
    for i, axis in enumerate("xyz"):
        old = list(prim.size)
        bumped = list(old)
        bumped[i] = old[i] * 2.0 + 0.3
        prim.size = bumped
        if _signature(ptr, core) != base:
            live.add(f"size.{axis}")
        prim.size = old

    for name in SCALARS:
        if not hasattr(prim, name):
            continue
        old = getattr(prim, name)
        # 角度は「2倍+0.3」だと既定 0 のとき 0.3度しか動かず、形は変わっても
        # bounding box が同じままで「効かない」と誤判定する(ARC の angle_start で
        # 実際に踏んだ)。角度だけは十分大きく振る。
        bumped = (old + 60.0) if name.startswith("angle") else (old * 2.0 + 0.3)
        try:
            setattr(prim, name, bumped)
        except Exception:
            continue
        if _signature(ptr, core) != base:
            live.add(name)
        setattr(prim, name, old)
    return live, prim


def shown_params(prim_type):
    """Active Property Editor が描く prop 名の集合。"""
    from CAD_8_1_5_1 import utils
    from CAD_8_1_5_1.ui import ui_main_panel as P
    props = utils.get_active_props(bpy.context)
    props.active_primitive_index = len(props.primitives) - 1
    sink = []
    shim = type("Shim", (), {})()
    shim.layout = FakeLayout(sink)
    P.SEAMLESS_PT_PropertyEditorPanel.draw(shim, bpy.context)
    return set(sink)


def main():
    import CAD_8_1_5_1 as addon
    addon.register()

    problems = []
    print(f"{'type':14} {'効く':46} {'UI に出ているが効かない'}")
    print("-" * 100)
    for t in TYPES:
        live, prim = effective_params(t)
        if live is None:
            print(f"{t:14} (既定で空の形状。判定できず)")
            continue
        shown = shown_params(t) - IGNORE
        dead_shown = sorted(shown - live)
        print(f"{t:14} {', '.join(sorted(live)) or '-':46} {', '.join(dead_shown) or '-'}")
        if dead_shown:
            problems.append((t, dead_shown))

    print("-" * 100)
    if problems:
        print("⚠️ UI に出ているのに形状へ効かない項目があります:")
        for t, names in problems:
            print(f"   {t}: {', '.join(names)}")
        print("\nUI 側を直す(出さない)か、カーネル側の配線を直すかを判断すること。")
    else:
        print("UI に出ている項目はすべて形状に効いています。")

    sys.stdout.flush()
    os._exit(1 if problems else 0)


if __name__ == "__main__":
    main()
