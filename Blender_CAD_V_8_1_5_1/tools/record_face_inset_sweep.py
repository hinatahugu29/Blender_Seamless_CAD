"""Face Inset のスイープを、カーネルへ送られる生のリクエストとして録音する。

Windows の Blender で1回走らせ、出来た fixture を Linux の CI で再生する
(tools/replay_kernel_requests.py)。**プロトコルを書き直さない**のが狙い:
録音するのはアドオン自身が組み立てた本物のリクエストで、update の
シリアライズを手で再実装すると、そこが違っていた場合に「再現しない」のか
「送り方が違う」のか区別できなくなる。

    blender --background --factory-startup --python tools/record_face_inset_sweep.py

2026-09-05 の Fedora 44 クラッシュ報告(円柱の平面に Inset、押し込み量を
少し大きくすると SIGSEGV)を、実機を持たずに追いかけるための仕掛け。
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON_PARENT = os.path.dirname(HERE)
if ADDON_PARENT not in sys.path:
    sys.path.insert(0, ADDON_PARENT)

import bpy  # noqa: E402
import regression_test as R  # noqa: E402
import CAD_8_1_5_1 as addon  # noqa: E402

addon.register()
from CAD_8_1_5_1 import core_bridge  # noqa: E402

OUT = os.path.join(HERE, "fixtures", "face_inset_sweep.json")

captured = []
_orig_send = core_bridge.send_and_receive


def spy(req_dict):
    if req_dict.get("action") == "update":
        payload = req_dict.get("binary_payload")
        # dict は下流で pop されるのでここで複製する
        body = {k: v for k, v in req_dict.items() if k != "binary_payload"}
        captured.append({
            "label": spy.label,
            "request": body,
            "binary_payload_hex": bytes(payload).hex() if payload else "",
        })
    return _orig_send(req_dict)


spy.label = "setup"
core_bridge.send_and_receive = spy

col, props = R._fresh_part()
bpy.ops.seamless.add_primitive(type='CYLINDER')
core_bridge.update_cad_preview_forced(bpy.context)
ptr = int(col.seamless_cad_stack_ptr)

# 上面(平らな面)を選ぶ。報告者が触ったのと同じ場所。
top = None
for lid in R._capture_face_lineages(col):
    info = core_bridge.measure_entity(ptr, lid, True)
    if info and info.get("resolved") and info.get("shape") == "Plane":
        top = lid
        break
assert top, "a cylinder must expose a flat end"

bpy.ops.seamless.add_primitive(type='FACE_INSET')
ins = R.utils_props().primitives[-1]
ins.target_lineages = top
ins.extrude_height = -0.2

captured.clear()
# 報告者は 0.1 -> 0.2 までは動き、その先で落ちた。手元(Windows)では
# 0.02 と 0.03 の間で幾何が崩壊する。両方をまたぐように振る。
for amount in (0.01, 0.02, 0.025, 0.03, 0.04, 0.05, 0.1, 0.2, 0.3, 0.5):
    ins.radius = amount
    spy.label = f"inset={amount}"
    core_bridge.update_cad_preview_forced(bpy.context)

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8", newline="\n") as f:
    json.dump({
        "note": "recorded on Windows by tools/record_face_inset_sweep.py; replay with tools/replay_kernel_requests.py",
        "target_face": top,
        "requests": captured,
    }, f, indent=1, sort_keys=True)

print(f"[record] wrote {len(captured)} update requests to {OUT}", flush=True)
sys.stdout.flush()
os._exit(0)
