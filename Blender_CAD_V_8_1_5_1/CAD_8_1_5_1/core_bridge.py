import bpy
import os
import sys
import json
import uuid
import math
import datetime
import socket
import struct
import subprocess
import threading
import collections
import time
import array
import tempfile
import atexit

try:
    from . import utils
    from .core.semantic_targets import find_snapshot_entry_for_token, parse_target_coord, replace_target_coord
except ImportError:
    import utils
    from core.semantic_targets import find_snapshot_entry_for_token, parse_target_coord, replace_target_coord

addon_dir = os.path.dirname(__file__)
# バージョン番号をファイル名に埋めない。埋めると版を上げるたびに更新漏れが起きる。
_cad_server_log_path = os.path.join(tempfile.gettempdir(), "seamless_cad_server_debug.log")

# cad_server の待ち受けアドレス。ポートは Rust 側と揃えること。
_SERVER_HOST = '127.0.0.1'
_SERVER_PORT = 8080

_IS_WINDOWS = sys.platform == "win32"

# 幾何カーネルの実行ファイル名。拡張子が付くのは Windows だけ。
_SERVER_EXE_NAME = "cad_server.exe" if _IS_WINDOWS else "cad_server"

# CREATE_NO_WINDOW は subprocess の Windows 専用属性で、macOS/Linux では
# 参照した時点で AttributeError になる。存在しないフラグを渡さないよう、
# プラットフォーム依存の Popen 引数はここに閉じ込める。
_POPEN_PLATFORM_KWARGS = (
    {"creationflags": subprocess.CREATE_NO_WINDOW} if _IS_WINDOWS else {}
)

_server_process = None


class ShortReadError(Exception):
    """応答を読み切る前に接続が閉じられた(サーバーが落ちた/killされた)。"""


def _recv_exact_strict(s, n):
    """n バイト読み切る。読み切れなければ例外にする。

    途中までのバッファを返すと、ゼロ埋め部分を正常な幾何データとして
    解釈してしまい「無言で形状が壊れる」ため、必ず失敗として扱う。
    """
    data = _recv_exact(s, n)
    if data is None:
        raise ShortReadError(f"connection closed while expecting {n} bytes")
    return data

def terminate_server():
    """このBlenderセッションが起動したcad_server.exeを終了する。
    次回起動時に必ず新規プロセス(GLOBAL_SCENEが空の状態)から始まるようにし、
    wgpuオーバーレイに古いジオメトリが残留する問題を防ぐ。
    """
    global _server_process
    if _server_process is not None and _server_process.poll() is None:
        try:
            _server_process.terminate()
            _server_process.wait(timeout=2.0)
        except Exception:
            try:
                _server_process.kill()
            except Exception:
                pass
    _server_process = None

def _atexit_shutdown():
    # 順序が重要: サーバーを先に落とさないと共有メモリファイルを消せない。
    terminate_server()
    close_shm()

atexit.register(_atexit_shutdown)
_async_results = collections.deque()
_computing_stacks = set()
_computing_stacks_lock = threading.Lock()
_stack_ptr_to_col = {}
_serialize_cache = {}
# 顔②対策: stack_ptr ごとに「最後に dispatch したフル品質リクエストの内容シグネチャ」を保持。
# 確定/再描画のたびに飛ぶ内容同一の全再計算(OCCブーリアン)を送信前に潰す。
# force=True と interactive(drag) は対象外。無効化は delete_cad_stack で行う。
_last_dispatched_sig = {}

_last_request_time = 0.0
_pending_preview_data = {}  
_debounce_timers = {}       
_pending_async_requests = {}  
_pending_matrices = {}
_latest_request_id = 0
_latest_request_ids = {}
_latest_completed_ids = {}
_modifier_interactive_until = {}
_modifier_finish_tokens = {}
_interactive_preview_kind = {}
_last_mesh_update_by_col = {}
_preview_throttle_times = {}
_modifier_preview_times = {}
_modifier_live_preview_times = {}
# Adaptive live-preview pacing for modifier (fillet/chamfer/...) slider drags.
# We pace the next update at ~110% of the last compute's wall time, clamped to
# [MIN, MAX], so light modifiers refresh at high frequency while heavy ones
# self-throttle to what the machine can actually service (no queue backlog).
_modifier_last_compute_ms = {}
_MODIFIER_LIVE_PREVIEW_MIN = 0.033   # ~30 fps ceiling for cheap modifiers
_MODIFIER_LIVE_PREVIEW_MAX = 0.30    # never slower than this while dragging
_MODIFIER_LIVE_PREVIEW_PACE = 1.1    # target = 110% of last compute time
_created_stack_pointers = set()
_server_generation = 0
_step_session_imports = {}
_step_target_refresh_in_progress = False

_INTERACTIVE_MODIFIER_TYPES = {'FILLET', 'CHAMFER', 'FACE_OFFSET', 'FACE_INSET', 'DRAFT', 'SHELL', 'FACE_LOFT', 'FACE_REVOLVE', 'SWEEP'}



def _adjust_target_coords_v810(tls, prim, props):
    import mathutils

    snapshot_str = getattr(prim, 'edge_ref_snapshot', '')
    if not snapshot_str:
        return tls

    try:
        snapshot = json.loads(snapshot_str)
    except Exception:
        return tls

    if not snapshot:
        return tls

    uuid_map = {p.uuid: p for p in props.primitives}
    adjusted = []
    for lid in tls:
        if isinstance(lid, str) and lid.startswith("SemLoop:EDGESET@"):
            adjusted.append(lid)
            continue

        entry = find_snapshot_entry_for_token(snapshot, lid)
        if not entry:
            adjusted.append(lid)
            continue

        orig_coord = parse_target_coord(lid)
        best_adjusted = None
        best_source = ""
        best_dist = float("inf")

        refs_data = entry.get("refs", {})
        if not refs_data and entry.get("ref"):
            refs_data = {entry["ref"]: entry}

        def _project_from_ref(ref_uuid, ref_data):
            if ref_uuid not in uuid_map:
                return None
            try:
                ref_prim = uuid_map[ref_uuid]
                rloc = mathutils.Vector(ref_data["rloc"])
                cur_loc = mathutils.Vector(ref_prim.location)
                cur_rot = mathutils.Euler(ref_prim.rotation, 'XYZ').to_matrix()
                return cur_loc + cur_rot @ rloc
            except Exception:
                return None

        primary_ref_uuid = entry.get("ref", "")
        if primary_ref_uuid and primary_ref_uuid in refs_data:
            primary_adjusted = _project_from_ref(primary_ref_uuid, refs_data[primary_ref_uuid])
            if primary_adjusted is not None:
                best_adjusted = primary_adjusted
                best_source = primary_ref_uuid

        if best_adjusted is None:
            for ref_uuid, ref_data in refs_data.items():
                prop_coord = _project_from_ref(ref_uuid, ref_data)
                if prop_coord is None:
                    continue

                if orig_coord:
                    dist = (prop_coord - orig_coord).length
                    if dist < best_dist:
                        best_dist = dist
                        best_adjusted = prop_coord
                        best_source = ref_uuid
                else:
                    best_adjusted = prop_coord
                    best_source = ref_uuid
                    break

        if best_adjusted and "@" in lid:
            if lid.startswith("Edge:") and lid.count("@") == 1 and "@Loop:" not in lid:
                insert_idx = len(lid)
                for marker in ["@Loop:", "#", "|"]:
                    idx = lid.find(marker)
                    if idx != -1 and idx < insert_idx:
                        insert_idx = idx
                new_lid = (
                    f"{lid[:insert_idx]}"
                    f"@{best_adjusted.x:.3f};{best_adjusted.y:.3f};{best_adjusted.z:.3f}"
                    f"{lid[insert_idx:]}"
                )
            else:
                new_lid = replace_target_coord(lid, best_adjusted)
            adjusted.append(new_lid)
            if orig_coord:
                drift = (best_adjusted - orig_coord).length
                if drift > 0.25:
                    utils.debug_print(
                        f"[V8.1.3.3] Target coord adjusted: drift={drift:.3f} ref={best_source} {lid} -> {new_lid}"
                    )
        else:
            adjusted.append(lid)

    return adjusted


def _adjust_single_lineage_coord_v810(lineage, snapshot_attr, prim, props):
    import mathutils

    if not isinstance(lineage, str) or "@" not in lineage:
        return lineage

    snapshot_str = getattr(prim, snapshot_attr, '')
    if not snapshot_str:
        return lineage

    try:
        snapshot = json.loads(snapshot_str)
    except Exception:
        return lineage

    if not isinstance(snapshot, dict) or not snapshot:
        return lineage

    entry = find_snapshot_entry_for_token(snapshot, lineage)
    if not entry:
        return lineage

    orig_coord = parse_target_coord(lineage)
    if orig_coord is None:
        return lineage

    uuid_map = {p.uuid: p for p in props.primitives}
    refs_data = entry.get("refs", {}) if isinstance(entry, dict) else {}
    if not refs_data and isinstance(entry, dict) and entry.get("ref"):
        refs_data = {entry["ref"]: entry}

    def _project_from_ref(ref_uuid, ref_data):
        if ref_uuid not in uuid_map:
            return None
        try:
            ref_prim = uuid_map[ref_uuid]
            rloc = mathutils.Vector(ref_data["rloc"])
            cur_loc = mathutils.Vector(ref_prim.location)
            cur_rot = mathutils.Euler(ref_prim.rotation, 'XYZ').to_matrix()
            return cur_loc + cur_rot @ rloc
        except Exception:
            return None

    best_adjusted = None
    best_source = ""
    best_dist = float("inf")

    primary_ref_uuid = entry.get("ref", "") if isinstance(entry, dict) else ""
    if primary_ref_uuid and primary_ref_uuid in refs_data:
        primary_adjusted = _project_from_ref(primary_ref_uuid, refs_data[primary_ref_uuid])
        if primary_adjusted is not None:
            best_adjusted = primary_adjusted
            best_source = primary_ref_uuid

    if best_adjusted is None:
        for ref_uuid, ref_data in refs_data.items():
            prop_coord = _project_from_ref(ref_uuid, ref_data)
            if prop_coord is None:
                continue
            dist = (prop_coord - orig_coord).length
            if dist < best_dist:
                best_dist = dist
                best_adjusted = prop_coord
                best_source = ref_uuid

    if best_adjusted is None:
        return lineage

    new_lineage = replace_target_coord(lineage, best_adjusted)
    drift = (best_adjusted - orig_coord).length
    if new_lineage != lineage and drift > 0.25:
        utils.debug_print(
            f"[V8.1.3.3] Reference coord adjusted: drift={drift:.3f} ref={best_source} "
            f"{lineage} -> {new_lineage}"
        )
    return new_lineage

# 後方互換のために残しているが、エンジンの実状は表さない(常に True)。
# 実際にサーバーが応答するかは is_server_alive() を使うこと。
CORE_AVAILABLE = True

_VERSION_FALLBACK = "unknown"


def get_version():
    """アドオンのバージョン文字列を bl_info から取る。

    bl_info は Blender がファイルをテキスト解析して読むため、リテラルの dict の
    まま残さなければならない。そのため「bl_info を単一ソースにして、こちらが
    読む」向きにしている。以前はここにハードコードされた別の値があり、
    bl_info(8.1.5.1) と get_version()(8.1.3.7) が食い違っていた。
    """
    try:
        root = sys.modules.get(__package__ or "")
        version = getattr(root, "bl_info", {}).get("version")
        if version:
            return ".".join(str(x) for x in version)
    except Exception:
        pass
    return _VERSION_FALLBACK


def _pack_primitive(p):
    buffers = []
    # Strings
    for key in ['type', 'operation', 'uuid', 'reference_lineage', 'target_uuid', 'pattern_axis', 'top_shape', 'bot_shape', 'sweep_path_uuid', 'sweep_profile_uuid', 'sweep_frame_mode']:
        s = str(p.get(key, '')).encode('utf-8')
        buffers.append(struct.pack('<H', len(s)) + s)
        
    # Floats
    loc = p.get('location', [0,0,0])
    rot = p.get('rotation', [0,0,0])
    sz = p.get('size', [0,0,0])
    import mathutils
    eu = mathutils.Euler((rot[0], rot[1], rot[2]), 'XYZ')
    q = eu.to_quaternion()
    buffers.append(struct.pack('<13d', loc[0], loc[1], loc[2], rot[0], rot[1], rot[2], sz[0], sz[1], sz[2], q.x, q.y, q.z, q.w))
    
    # Bools and scalars
    buffers.append(struct.pack('<BB', int(p.get('fill_closed', 0)), int(p.get('use_pipe', 0))))
    buffers.append(struct.pack('<dddddddi ddi dd', 
        float(p.get('radius', 0.0) or 0.0), float(p.get('pipe_radius', 0.0) or 0.0),
        float(p.get('angle_start', 0.0) or 0.0), float(p.get('angle_end', 0.0) or 0.0),
        float(p.get('extrude_height', 0.0) or 0.0), float(p.get('radius2', 0.0) or 0.0), float(p.get('minor_radius', 0.0) or 0.0),
        int(p.get('sides', 0) or 0), float(p.get('module', 0.0) or 0.0), float(p.get('pressure_angle', 0.0) or 0.0),
        int(p.get('count', 0) or 0), float(p.get('distance', 0.0) or 0.0), float(p.get('sweep_roll_degrees', 0.0) or 0.0)
    ))
    
    # target_lineages
    tls = p.get('target_lineages', [])
    buffers.append(struct.pack('<H', len(tls)))
    for t in tls:
        s = str(t).encode('utf-8')
        buffers.append(struct.pack('<H', len(s)) + s)
        
    # loft_uuids
    lofts = p.get('loft_uuids', [])
    buffers.append(struct.pack('<H', len(lofts)))
    for t in lofts:
        s = str(t).encode('utf-8')
        buffers.append(struct.pack('<H', len(s)) + s)
        
    # points
    pts = p.get('points', [])
    if pts is None: pts = []
    buffers.append(struct.pack('<I', len(pts)))
    for pt in pts:
        # pt has [x, y, z, use_fillet_flag]
        flag = float(pt[3]) if len(pt) > 3 else 1.0
        buffers.append(struct.pack('<4d', float(pt[0]), float(pt[1]), float(pt[2]), flag))
        
    # segments
    segs = p.get('segments', [])
    if segs is None: segs = []
    buffers.append(struct.pack('<I', len(segs)))
    for seg in segs:
        s_type = str(seg.get('type', '')).encode('utf-8')
        buffers.append(struct.pack('<H', len(s_type)) + s_type)
        
        def pack_opt_pt(pt):
            if pt is None: return struct.pack('<B', 0)
            return struct.pack('<B3d', 1, float(pt[0]), float(pt[1]), float(pt[2]))
            
        buffers.append(pack_opt_pt(seg.get('start')))
        buffers.append(pack_opt_pt(seg.get('end')))
        buffers.append(pack_opt_pt(seg.get('mid')))
        buffers.append(pack_opt_pt(seg.get('center')))
        
        rad = seg.get('radius')
        if rad is None: buffers.append(struct.pack('<B', 0))
        else: buffers.append(struct.pack('<Bd', 1, float(rad)))
        
        buffers.append(pack_opt_pt(seg.get('normal')))

    # V8.1.5: 可変フィレット - トークンごとの半径上書きペア。
    # 末尾追加ブロック(既存フィールドの並び替えは絶対に行わないこと。core_bridge.pyと
    # cad_server.exeは常にセットでビルド・デプロイする前提)。
    edge_radii = p.get('edge_radii', [])
    if edge_radii is None: edge_radii = []
    buffers.append(struct.pack('<I', len(edge_radii)))
    for token, radius in edge_radii:
        s = str(token).encode('utf-8')
        buffers.append(struct.pack('<H', len(s)) + s)
        buffers.append(struct.pack('<d', float(radius)))

    return b''.join(buffers)

def serialize_primitives(stack_data):
    buffers = [struct.pack('<I', len(stack_data))]
    for p in stack_data:
        buffers.append(_pack_primitive(p))
    return b''.join(buffers)


def is_core_busy(stack_ptr=None):
    global _computing_stacks
    with _computing_stacks_lock:
        if stack_ptr is not None:
            return stack_ptr in _computing_stacks
        return len(_computing_stacks) > 0

import mmap
import tempfile

_SHM_SIZE = 64 * 1024 * 1024

# ファイル名に自分のPIDを含める。固定名だと Blender を2つ起動したときに
# 両方が同じ64MBへメッシュを書き込み、互いの結果を破壊する。
# サーバー側はこのパスを argv[1] で受け取るだけなので Rust 側の変更は不要
# (main.rs の「argv[1] は Python の共有メモリファイル」参照)。
_shm_file = os.path.join(tempfile.gettempdir(), f'seamless_cad_shm_{os.getpid()}.bin')
_shm_fd = None
_shm = None
_shm_view = None

def init_shm():
    global _shm_fd, _shm, _shm_view
    if _shm is None:
        if not os.path.exists(_shm_file) or os.path.getsize(_shm_file) != _SHM_SIZE:
            try:
                with open(_shm_file, 'wb') as f:
                    f.truncate(_SHM_SIZE)
            except Exception:
                pass
        _shm_fd = open(_shm_file, 'r+b')
        _shm = mmap.mmap(_shm_fd.fileno(), 0)
        _shm_view = memoryview(_shm)

def close_shm():
    """mmap / ファイルハンドル / 一時ファイルを解放する。

    unregister と atexit から呼ぶ。以前は解放処理が無く、アドオンを
    リロードするたびに 64MB のマッピングとファイルハンドルが積み上がっていた。
    """
    global _shm_fd, _shm, _shm_view
    if _shm_view is not None:
        try:
            _shm_view.release()
        except Exception:
            pass
        _shm_view = None
    if _shm is not None:
        try:
            _shm.close()
        except Exception:
            pass
        _shm = None
    if _shm_fd is not None:
        try:
            _shm_fd.close()
        except Exception:
            pass
        _shm_fd = None
    try:
        if os.path.exists(_shm_file):
            os.remove(_shm_file)
    except OSError:
        # サーバー側がまだ握っている場合は消せない。次回起動時に truncate で
        # 作り直されるので放置してよい。
        pass

_SERVER_PROBE_TIMEOUT = 2.0
_foreign_port_warned = False


def _is_port_open(timeout=1.0):
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((_SERVER_HOST, _SERVER_PORT))
        return True
    except Exception:
        return False
    finally:
        if s is not None:
            try:
                s.close()
            except Exception:
                pass


def is_server_alive(timeout=_SERVER_PROBE_TIMEOUT):
    """ポートに居るのが本当に cad_server かを確認する。

    connect が成功しただけでは足りない。8080 は各種開発サーバの定番ポートで、
    無関係なプロセスが握っていると CAD のバイナリをそこへ投げ続けてしまう。
    副作用の無い csg_preview_end(存在しない stack_ptr=0)を投げ、返ってきた
    1バイトが CAD プロトコルのステータス値かどうかで判定する。
    HTTP サーバー等なら 'H' などが返るので弾ける。

    NOTE: 本来はマジックバイト+プロトコル版のハンドシェイクにすべきだが、
    それは cad_server.exe 側の改修が必要なので暫定策。
    """
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((_SERVER_HOST, _SERVER_PORT))
        req = json.dumps({"action": "csg_preview_end", "stack_ptr": 0}).encode('utf-8')
        s.sendall(struct.pack('<I', len(req)) + req)
        status = s.recv(1)
        return bool(status) and status[0] in (0, 1, 2)
    except Exception:
        return False
    finally:
        if s is not None:
            try:
                s.close()
            except Exception:
                pass


_engine_status_cache = (0.0, False)


def is_server_running(ttl=2.0):
    """UI 表示用の軽量なサーバー生存確認。

    draw() から呼ばれるので、ネットワーク I/O は極力避ける:
    自分の子プロセスが生きていれば通信せずに True、そうでない場合のみ
    loopback へ短いタイムアウトで connect を試し、結果を ttl 秒キャッシュする。
    """
    global _engine_status_cache
    if _server_process is not None and _server_process.poll() is None:
        return True
    now = time.monotonic()
    last_t, last_val = _engine_status_cache
    if (now - last_t) < ttl:
        return last_val
    val = _is_port_open(timeout=0.2)
    _engine_status_cache = (now, val)
    return val


def start_server():
    global _server_process, _server_generation, _step_session_imports, _foreign_port_warned

    init_shm()

    # 自分が起動した cad_server が生きていれば即 return する。
    # start_server() は send_and_receive のたびに呼ばれるため、ここでソケットを
    # 張らないこと自体がリクエスト毎のオーバーヘッド削減になる
    # (従来は毎回 connect/close を1往復していた)。
    if _server_process is not None and _server_process.poll() is None:
        return True
    _server_process = None

    # 自分が起動していないプロセスがポートに居るケース(前セッションが残した
    # cad_server など)。従来どおり再利用する = 挙動は変えない。ただし相手が
    # cad_server でない場合は原因不明のまま黙るので、一度だけ警告を出す。
    # ここで強制的に失敗させないのは、重い演算中のサーバーが probe に
    # 応答できず誤判定するリスクを避けるため。
    if _is_port_open():
        if not _foreign_port_warned and not is_server_alive():
            _foreign_port_warned = True
            utils.error_print(
                f"Seamless: port {_SERVER_PORT} responded but does not look like {_SERVER_EXE_NAME}. "
                "If CAD operations fail, free that port and re-enable the addon."
            )
        return True


    # `bin/` を候補から外してある。8.1.5.5 まで、配布物の bin/ には 7月14日の
    # cad_server.exe が残っていた。ルートが先に見つかるので普段は使われないが、
    # ルートが失われた環境ではそれが黙って起動し、OCCT 8.0.1 どころか
    # 8.1.5.3 の修正すら入っていないカーネルで「直したはずの不具合が再現する」
    # という一番追いにくい形になる。フォールバックする価値のある場所ではない。
    #
    # 開発ツリーの target/release は残す。手元でビルドしただけで動くのは有用で、
    # かつユーザーの環境には ../src_rust が存在しない。
    candidate_paths = [
        os.path.abspath(os.path.join(addon_dir, _SERVER_EXE_NAME)),
        os.path.abspath(os.path.join(addon_dir, "..", "src_rust", "target", "release", _SERVER_EXE_NAME)),
    ]
    exe_path = next((path for path in candidate_paths if os.path.exists(path)), None)
    utils.info_print(
        f"Seamless CAD start_server: addon_dir={addon_dir}, bridge={get_version()}, exe={exe_path or 'MISSING'}"
    )

    if not exe_path:
        utils.error_print(f"Seamless: {_SERVER_EXE_NAME} not found in the addon root or the dev target path")
        return False

    # ZIP は実行ビットを保存しない(Python の zipfile も Blender のインストーラも
    # パーミッションを落とす)。展開直後の macOS/Linux では実行ビットが無く、
    # Popen が PermissionError になるので、起動前に自分で付ける。
    if not _IS_WINDOWS and not os.access(exe_path, os.X_OK):
        try:
            os.chmod(exe_path, os.stat(exe_path).st_mode | 0o111)
        except OSError as e:
            utils.error_print(f"Seamless: could not make {exe_path} executable: {e}")
            return False

    try:
        log_file = open(_cad_server_log_path, "a", encoding="utf-8", errors="replace")
        # Pass our (Blender's) PID so the server self-terminates if Blender
        # crashes without running atexit — otherwise the orphaned server keeps
        # port 8080 and the next session reuses it, drawing stale geometry.
        _server_process = subprocess.Popen(
            [exe_path, _shm_file, str(os.getpid())],
            stdout=log_file,
            stderr=log_file,
            **_POPEN_PLATFORM_KWARGS
        )
        time.sleep(0.5)
        _server_generation += 1
        _foreign_port_warned = False
        _step_session_imports.clear()
        # 新サーバでは全 stack が作り直され ptr が再利用されうるので内容シグネチャを破棄。
        _last_dispatched_sig.clear()
        _serialize_cache.clear()
        utils.info_print(
            f"Seamless CAD server launched: generation={_server_generation}, exe={exe_path}, log={_cad_server_log_path}"
        )
        return True
    except Exception as e:
        utils.error_print(f"Seamless: Failed to start server: {e}")
        return False

def _normalize_step_path(filepath):
    if not filepath:
        return ""
    return os.path.normcase(os.path.abspath(filepath))

def _normalize_step_scale(scale):
    try:
        scale = float(scale)
    except Exception:
        scale = 1.0
    return max(scale, 1e-6)

def _make_step_session_key(filepath, scale):
    return (_normalize_step_path(filepath), round(_normalize_step_scale(scale), 9))

def ensure_step_primitive_targets(props):
    global _step_target_refresh_in_progress
    if not props:
        return

    step_prims = [prim for prim in props.primitives if getattr(prim, "type", "") in ('STEP_PART', 'SVG_PART')]
    if not step_prims:
        return

    if not start_server():
        return

    grouped_step = collections.defaultdict(list)
    grouped_svg = collections.defaultdict(list)
    for prim in step_prims:
        source_path = _normalize_step_path(getattr(prim, "step_source_path", ""))
        source_index = int(getattr(prim, "step_source_index", -1))
        step_scale = _normalize_step_scale(getattr(prim, "step_scale", 1.0))
        if source_path and source_index >= 0:
            if prim.type == 'SVG_PART':
                grouped_svg[(source_path, step_scale)].append(prim)
            else:
                grouped_step[(source_path, step_scale)].append(prim)

    for (source_path, step_scale), prims in grouped_step.items():
        cache_key = _make_step_session_key(source_path, step_scale)
        cached = _step_session_imports.get(cache_key)
        if not cached or cached.get("generation") != _server_generation:
            if not os.path.exists(source_path):
                utils.error_print(f"Seamless: STEP source missing: {source_path}")
                continue

            imported_ids = import_step(source_path, step_scale)
            if not imported_ids:
                utils.error_print(f"Seamless: Failed to refresh STEP source: {source_path} (scale={step_scale})")
                continue

            cached = {
                "generation": _server_generation,
                "ids": imported_ids,
            }
            _step_session_imports[cache_key] = cached

        imported_ids = cached.get("ids", [])
        for prim in prims:
            source_index = int(getattr(prim, "step_source_index", -1))
            if 0 <= source_index < len(imported_ids):
                if prim.target_uuid != imported_ids[source_index]:
                    _step_target_refresh_in_progress = True
                    try:
                        prim.target_uuid = imported_ids[source_index]
                    finally:
                        _step_target_refresh_in_progress = False
            else:
                utils.error_print(
                    f"Seamless: STEP part index {source_index} out of range for {source_path}"
                )

    for (source_path, step_scale), prims in grouped_svg.items():
        cache_key = ("svg", source_path, round(step_scale, 9))
        cached = _step_session_imports.get(cache_key)
        if not cached or cached.get("generation") != _server_generation:
            if not os.path.exists(source_path):
                utils.error_print(f"Seamless: SVG source missing: {source_path}")
                continue

            imported_ids = import_svg(source_path, step_scale)
            if not imported_ids:
                utils.error_print(f"Seamless: Failed to refresh SVG source: {source_path} (scale={step_scale})")
                continue

            cached = {
                "generation": _server_generation,
                "ids": imported_ids,
            }
            _step_session_imports[cache_key] = cached

        imported_ids = cached.get("ids", [])
        for prim in prims:
            source_index = int(getattr(prim, "step_source_index", -1))
            if 0 <= source_index < len(imported_ids):
                if prim.target_uuid != imported_ids[source_index]:
                    _step_target_refresh_in_progress = True
                    try:
                        prim.target_uuid = imported_ids[source_index]
                    finally:
                        _step_target_refresh_in_progress = False
            else:
                utils.error_print(
                    f"Seamless: SVG part index {source_index} out of range for {source_path}"
                )

_PICK_TIMEOUT_SECONDS = 2.0

def _pick_common(op_code, op_name, stack_ptr, origin, direction, tolerance, stack_idx=None, timeout=_PICK_TIMEOUT_SECONDS):
    """全pick_*関数共通のTCPリクエスト送受信処理。

    サーバーがハングした場合にBlender UIが無限に固まらないよう、
    接続・送受信の双方にタイムアウトを設定する。失敗時は原因を
    ログへ残した上でNoneを返す(呼び出し側は「ヒットなし」として扱う)。
    """
    import struct, array
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((_SERVER_HOST, _SERVER_PORT))
        if stack_idx is None:
            msg = struct.pack(
                '<Bq3f3ff', op_code, int(stack_ptr),
                float(origin[0]), float(origin[1]), float(origin[2]),
                float(direction[0]), float(direction[1]), float(direction[2]),
                float(tolerance)
            )
        else:
            msg = struct.pack(
                '<Bqi3f3ff', op_code, int(stack_ptr), int(stack_idx),
                float(origin[0]), float(origin[1]), float(origin[2]),
                float(direction[0]), float(direction[1]), float(direction[2]),
                float(tolerance)
            )
        s.sendall(struct.pack('<I', len(msg)) + msg)

        status = s.recv(1)
        if not status or status[0] != 1:
            return None

        len_bytes = s.recv(4)
        res_len = struct.unpack('<I', len_bytes)[0]

        data = bytearray(res_len)
        view = memoryview(data)
        n = res_len
        while n > 0:
            n_recv = s.recv_into(view, n)
            if n_recv == 0:
                break
            view = view[n_recv:]
            n -= n_recv

        offset = 0
        lid_len = struct.unpack_from('<I', data, offset)[0]
        offset += 4
        lid = data[offset:offset + lid_len].decode('utf-8')
        offset += lid_len
        floats_len = struct.unpack_from('<I', data, offset)[0]
        offset += 4
        floats = array.array('f', data[offset:offset + floats_len * 4]).tolist()
        return [lid] + floats
    except socket.timeout:
        utils.error_print(f"Seamless: {op_name} timed out after {timeout}s (server may be hung)")
        return None
    except Exception as e:
        utils.error_print(f"Seamless: {op_name} failed: {e}")
        return None
    finally:
        if s is not None:
            try:
                s.close()
            except Exception:
                pass

def pick_edge(stack_ptr, origin, direction, tolerance):
    return _pick_common(1, "pick_edge", stack_ptr, origin, direction, tolerance)

def generate_mesh(stack_ptr, deflection, angular_deflection):
    req_dict = {
        "action": "generate_mesh",
        "stack_ptr": stack_ptr,
        "deflection": deflection,
        "angular_deflection": angular_deflection
    }
    return send_and_receive(req_dict)

def pick_face(stack_ptr, origin, direction, tolerance=0.1):
    return _pick_common(2, "pick_face", stack_ptr, origin, direction, tolerance)

def pick_vertex_from_stack(stack_ptr, stack_idx, origin, direction, tolerance=0.6):
    return _pick_common(3, "pick_vertex_from_stack", stack_ptr, origin, direction, tolerance, stack_idx=stack_idx)

def pick_midpoint_from_stack(stack_ptr, stack_idx, origin, direction, tolerance=0.6):
    return _pick_common(4, "pick_midpoint_from_stack", stack_ptr, origin, direction, tolerance, stack_idx=stack_idx)

def pick_face_from_stack(stack_ptr, stack_idx, origin, direction, tolerance=0.6):
    return _pick_common(5, "pick_face_from_stack", stack_ptr, origin, direction, tolerance, stack_idx=stack_idx)

def pick_edge_from_stack(stack_ptr, stack_idx, origin, direction, tolerance=0.6):
    return _pick_common(6, "pick_edge_from_stack", stack_ptr, origin, direction, tolerance, stack_idx=stack_idx)

_SEND_RECEIVE_TIMEOUT_SECONDS = 60.0

def send_and_receive(req_dict):
    start_server()
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # サーバーがハング/デッドロックした際にBlenderのメインスレッドが
        # 無限にブロックされないよう、上限を設ける(重いブーリアン演算や
        # STEP入出力も許容する必要があるため長めの値にしている)。
        s.settimeout(_SEND_RECEIVE_TIMEOUT_SECONDS)
        s.connect((_SERVER_HOST, _SERVER_PORT))

        def recv_exact(n):
            """短い読み込み(=サーバーが応答途中で死んだ)を例外にする。
            以前は途中までのバッファをそのまま返していたため、切断時に
            ゼロ埋めデータを正常な応答として解釈してしまっていた。"""
            return _recv_exact_strict(s, n)

        # Binary payload injection
        if req_dict.get('action') == 'update' and 'binary_payload' in req_dict:
            b_payload = req_dict.pop('binary_payload')
            msg_json = json.dumps(req_dict).encode('utf-8')
            msg = struct.pack('<I', len(msg_json)) + msg_json + b_payload
            s.sendall(struct.pack('<I', len(msg)) + msg)
        else:
            msg = json.dumps(req_dict).encode('utf-8')
            s.sendall(struct.pack('<I', len(msg)) + msg)


        status = s.recv(1)
        if not status:
            return None

        if status[0] == 2:
            return None

        if status[0] == 1:
            if req_dict.get('action') == 'create_stack':
                ptr_bytes = recv_exact(8)
                ptr = struct.unpack('<q', ptr_bytes)[0]
                return ptr
            elif req_dict.get('action') == 'delete_stack':
                return True
            elif req_dict.get('action') in ('import_step', 'import_svg'):
                len_bytes = recv_exact(4)
                res_len = struct.unpack('<I', len_bytes)[0]
                data = recv_exact(res_len)
                res_json = data.decode('utf-8')
                return json.loads(res_json)
            elif req_dict.get('action') in {'export_step', 'export_stack_to_step',
                                            'export_parts_to_step', 'export_stack_to_stl'}:
                return True
            elif req_dict.get('action') == 'measure_entity':
                # f64 が10個 (種別, 長さor面積, 半径, 形状コード, 中心xyz, 法線xyz)
                return list(struct.unpack('<10d', recv_exact(80)))
            elif req_dict.get('action') == 'measure_stack':
                # f64 が 11 個 (体積, 表面積, 重心xyz, bbox 6値)
                return list(struct.unpack('<11d', recv_exact(88)))
            elif req_dict.get('action') == 'render_viewport':
                pix_len = struct.unpack('<I', recv_exact(4))[0]
                pixels = bytes(recv_exact(pix_len))
                return pixels
            elif req_dict.get('action') == 'update':
                l_bytes = recv_exact(20)
                ep_len, ec_len, v_len, t_len, mtc_len = struct.unpack('<IIIII', l_bytes)
                m_len_bytes = recv_exact(4)
                m_len = struct.unpack('<I', m_len_bytes)[0]
                meta_json = recv_exact(m_len).decode('utf-8')
                meta = json.loads(meta_json)
                
                import numpy as np
                use_mmap = meta.get('use_mmap', False)
                if use_mmap:
                    offsets = meta['mmap_offsets']
                    # .copy() is REQUIRED: np.frombuffer over the shm is a zero-copy
                    # view, but this result is consumed later on the main thread
                    # (poll_async_results) while the server may reuse the slot. Copy
                    # now so the arrays own their data.
                    edge_points = np.frombuffer(_shm_view[offsets[0]:offsets[0]+ep_len], dtype=np.float32).copy()
                    edge_counts = np.frombuffer(_shm_view[offsets[1]:offsets[1]+ec_len], dtype=np.int32).copy()
                    mesh_verts = np.frombuffer(_shm_view[offsets[2]:offsets[2]+v_len], dtype=np.float32).copy()
                    mesh_tris = np.frombuffer(_shm_view[offsets[3]:offsets[3]+t_len], dtype=np.int32).copy()
                    mesh_tri_counts = np.frombuffer(_shm_view[offsets[4]:offsets[4]+mtc_len], dtype=np.int32).copy()
                else:
                    ep_bytes = recv_exact(ep_len)
                    ec_bytes = recv_exact(ec_len)
                    v_bytes = recv_exact(v_len)
                    t_bytes = recv_exact(t_len)
                    mtc_bytes = recv_exact(mtc_len)
                    
                    edge_points = np.frombuffer(ep_bytes, dtype=np.float32)
                    edge_counts = np.frombuffer(ec_bytes, dtype=np.int32)
                    mesh_verts = np.frombuffer(v_bytes, dtype=np.float32)
                    mesh_tris = np.frombuffer(t_bytes, dtype=np.int32)
                    mesh_tri_counts = np.frombuffer(mtc_bytes, dtype=np.int32)

                return (edge_points, edge_counts, meta['edge_lineages'],
                        mesh_verts, mesh_tris, meta['mesh_face_ids'], mesh_tri_counts,
                        meta.get('perf_bool', 0), meta.get('perf_edge', 0), meta.get('perf_mesh', 0),
                        meta.get('perf_prim', 0), meta.get('perf_bool_main', 0), meta.get('perf_bool_modifier', 0),
                        meta.get('perf_extrema', 0), meta.get('perf_unify', 0),
                        meta.get('perf_resume_restore', 0), meta.get('perf_modifier_target_assign', 0),
                        meta.get('perf_modifier_apply', 0), meta.get('perf_modifier_recluster', 0),
                        meta.get('perf_fillet_setup', 0), meta.get('perf_fillet_target_resolve', 0),
                        meta.get('perf_fillet_add', 0), meta.get('perf_fillet_build', 0),
                        meta.get('perf_fillet_history', 0), meta.get('perf_fillet_added_edges', 0),
                        meta.get('perf_fillet_contours', 0))
            elif req_dict.get('action') == 'generate_mesh':
                l_bytes = recv_exact(12)
                v_len, t_len, mtc_len = struct.unpack('<III', l_bytes)

                m_len_bytes = recv_exact(4)
                m_len = struct.unpack('<I', m_len_bytes)[0]
                meta_json = recv_exact(m_len).decode('utf-8')
                meta = json.loads(meta_json)

                import numpy as np
                # generate_mesh はサーバー側(main.rs)が mmap 経路を持たないため
                # 常に TCP 本文で返る。use_mmap は読み飛ばす。

                v_bytes = recv_exact(v_len)
                t_bytes = recv_exact(t_len)
                mtc_bytes = recv_exact(mtc_len)

                mesh_verts = np.frombuffer(v_bytes, dtype=np.float32)
                mesh_tris = np.frombuffer(t_bytes, dtype=np.int32)
                mesh_tri_counts = np.frombuffer(mtc_bytes, dtype=np.int32)

                return (mesh_verts, mesh_tris, meta['face_ids'], mesh_tri_counts)
            else:
                # status=1(成功)だが応答の読み方が実装されていない action。
                # 以前は暗黙 None が返っていて原因が分からなかったので明示する。
                utils.error_print(
                    f"Seamless: no response reader for action={req_dict.get('action')!r}"
                )
                return None
        else:
            err_len_bytes = recv_exact(4)
            err_len = struct.unpack('<I', err_len_bytes)[0]
            err_msg = recv_exact(err_len).decode('utf-8')
            utils.error_print(f"CAD Server Error: {err_msg}")
            return None

    except Exception as e:
        utils.error_print(f"Seamless: Socket communication error: {e}")
        return None
    finally:
        # 例外パスでもソケットを必ず閉じる(以前は各分岐の s.close() 任せで、
        # 途中で例外が飛ぶと fd がリークしていた)。
        if s is not None:
            try:
                s.close()
            except Exception:
                pass

def create_cad_stack():
    ptr = send_and_receive({"action": "create_stack"})
    if ptr:
        _created_stack_pointers.add(ptr)
    return ptr or 0

def delete_cad_stack(stack_ptr):
    send_and_receive({"action": "delete_stack", "stack_ptr": stack_ptr})
    if stack_ptr in _created_stack_pointers:
        _created_stack_pointers.remove(stack_ptr)
    if str(stack_ptr) in _stack_ptr_to_col:
        del _stack_ptr_to_col[str(stack_ptr)]
    _last_dispatched_sig.pop(stack_ptr, None)

def import_step(filepath, scale=1.0):
    filepath = _normalize_step_path(filepath)
    scale = _normalize_step_scale(scale)
    cache_key = _make_step_session_key(filepath, scale)
    req_dict = {
        "action": "import_step",
        "filepath": filepath,
        "scale": scale,
    }
    result = send_and_receive(req_dict)
    if result:
        _step_session_imports[cache_key] = {
            "generation": _server_generation,
            "ids": result,
        }
    return result

def import_svg(filepath, scale=1.0):
    try:
        from . import svg_parser
        flat_data = svg_parser.parse_svg_to_flat_array(filepath)
    except Exception as e:
        import traceback
        err_msg = f"Failed to parse SVG: {e}\n{traceback.format_exc()}"
        from . import utils
        utils.error_print(err_msg)
        return []

    req_dict = {
        "action": "import_svg",
        "filepath": filepath,
        "scale": scale,
        "flat_data": flat_data
    }
    result = send_and_receive(req_dict)
    from . import utils
    utils.debug_print(f"DEBUG SVG IMPORT: filepath={filepath}, flat_data_len={len(flat_data)}, result={result}")
    return result

def export_step(uuids, filepath):
    req_dict = {
        "action": "export_step",
        "filepath": filepath,
        "uuids": uuids
    }
    return send_and_receive(req_dict)

def export_stack_to_step(stack_ptr, filepath, scale=1.0):
    """STEP 書き出し。scale は「1 Blender 単位を何 mm として出すか」。

    既定 1.0 は従来どおり 1 単位 = 1 mm。以前はこれが固定で、
    ミリ単位で作ることを強制していた(docs/en/limitations.md)。
    インポート側の scale と同じ意味なので、10 で取り込んだものは
    10 で書き出せば元に戻る。
    """
    req_dict = {
        "action": "export_stack_to_step",
        "stack_ptr": stack_ptr,
        "filepath": filepath,
        "scale": float(scale)
    }
    return send_and_receive(req_dict)

def export_parts_to_step(parts, filepath, scale=1.0, assembly_name="Assembly"):
    """名前付き STEP 書き出し。複数 Part を渡すとアセンブリ構造になる。

    parts は (stack_ptr, 名前) の並び。

    export_stack_to_step との違いは **XCAF を通すこと**だけ。あちらは
    STEPControl_Writer に直接渡すので形状しか出ず、受け取った側では
    名前の無い塊がひとつ見えるだけになる。旧関数は互換のために残してある。

    形状を持たない Part は**サーバー側が読み飛ばす**。Part を作っただけで
    まだ何も置いていない状態は普通に起こるため。全部空なら失敗が返る。
    """
    req_dict = {
        "action": "export_parts_to_step",
        "filepath": filepath,
        "scale": float(scale),
        "assembly_name": str(assembly_name),
        "parts": [{"ptr": int(ptr), "name": str(name)} for ptr, name in parts],
    }
    return send_and_receive(req_dict)

def export_stack_to_stl(stack_ptr, filepath, scale=1.0,
                        linear_deflection=0.1, angular_deflection_deg=0.5,
                        ascii_mode=False):
    """STL 書き出し。scale の意味は export_stack_to_step と同じ。

    **angular_deflection_deg は度で受け取り、ここでラジアンへ直して送る。**
    アドオンのプロパティ (mesh_angular_quality / bake_angular_quality) が度で
    持っているためで、operators/bake.py が generate_mesh を呼ぶときと同じ約束。

    Bake してから Blender の STL エクスポータに通す経路と違い、テセレーションを
    ベイク品質の設定で直接指定できる。

    三角形が1枚も出なければサーバー側が**書かずに**失敗を返す。
    「開けるが中身が空」の STL を成功として返さないため。
    """
    import math
    req_dict = {
        "action": "export_stack_to_stl",
        "stack_ptr": stack_ptr,
        "filepath": filepath,
        "scale": float(scale),
        "linear_deflection": float(linear_deflection),
        "angular_deflection": math.radians(float(angular_deflection_deg)),
        "ascii": bool(ascii_mode),
    }
    return send_and_receive(req_dict)

def measure_stack(stack_ptr):
    """スタックの質量特性を測る。

    返り値は dict、測れなければ None。

    **volume が 0.0 のときは「測定に失敗した」ではなく「ソリッドではない」**
    という意味。閉じていないシェルの体積は定義できないので、カーネルは 0 を
    返す。UI 側でそう表示すること。
    """
    if not stack_ptr:
        return None
    vals = send_and_receive({"action": "measure_stack", "stack_ptr": stack_ptr})
    if not vals or len(vals) != 11:
        return None
    return {
        "volume": vals[0],
        "area": vals[1],
        "centre_of_mass": (vals[2], vals[3], vals[4]),
        "bbox_min": (vals[5], vals[6], vals[7]),
        "bbox_max": (vals[8], vals[9], vals[10]),
        "size": (vals[8] - vals[5], vals[9] - vals[6], vals[10] - vals[7]),
    }


# measure_entity が返す形状コードの意味。カーネル側 occ_core.cpp の
# switch と一対一で対応させること。片方だけ足すと表示だけが古くなる。
_EDGE_KIND = {0: "Line", 1: "Circle", 2: "Ellipse", 3: "Curve"}
_FACE_KIND = {0: "Plane", 1: "Cylinder", 2: "Cone", 3: "Sphere", 4: "Torus", 5: "Surface"}


def measure_entity(stack_ptr, lineage, is_face):
    """選択されている辺/面ひとつを測る。

    返り値は dict、通信できなければ None。

    **resolved が False のときは値を表示しないこと。** lineage の照合は
    トポロジが変わると外れることがあり、そのとき近い別の辺の寸法を出すと
    「自信満々に間違った数字」になる。数字が出ないほうが害が小さい。
    """
    if not stack_ptr or not lineage:
        return None
    vals = send_and_receive({
        "action": "measure_entity",
        "stack_ptr": stack_ptr,
        "lineage": lineage,
        "is_face": bool(is_face),
    })
    if not vals or len(vals) != 10:
        return None

    kind, amount, radius, shape_code = vals[:4]
    centre = tuple(vals[4:7])
    normal = tuple(vals[7:10])
    if kind == 0.0:
        return {"resolved": False}

    is_face_result = (kind == 2.0)
    table = _FACE_KIND if is_face_result else _EDGE_KIND
    return {
        "resolved": True,
        "is_face": is_face_result,
        "amount": amount,                      # 辺なら長さ、面なら面積
        "radius": radius if radius > 0.0 else None,
        "shape": table.get(int(shape_code), "Unknown"),
        # 厳密な幾何(倍精度)。面なら面積重心、辺なら中点。
        "centre": centre,
        # 平面のときだけ。(0,0,0) は「厳密な法線は無い」の意味。
        "normal": normal if any(abs(v) > 1e-12 for v in normal) else None,
    }


def get_or_create_stack_ptr(scene_or_col):
    if not scene_or_col:
        return 0
    ptr_str = getattr(scene_or_col, "seamless_cad_stack_ptr", "0")
    try:
        ptr = int(ptr_str)
    except ValueError:
        ptr = 0
    
    if ptr != 0 and ptr not in _created_stack_pointers:
        ptr = 0
        
    if ptr == 0:
        ptr = create_cad_stack()
        scene_or_col.seamless_cad_stack_ptr = str(ptr)
    if ptr != 0:
        _stack_ptr_to_col[str(ptr)] = scene_or_col
    return ptr


def _profile_enabled(props=None):
    if hasattr(utils, "ENABLE_PERF_LOGGING"):
        return bool(utils.ENABLE_PERF_LOGGING)
    return bool(getattr(utils, "DEBUG_LOGS", False))

_profile_log_path = os.path.join(tempfile.gettempdir(), "seamless_cad_profile.log")

def _profile_log_line(msg):
    # アドオンのインストールディレクトリではなく tempdir に書く。
    # Extensions としてインストールした場合、アドオン配下は書き込み不可に
    # なり得るため。
    ts = datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]
    try:
        with open(_profile_log_path, "a", encoding="utf-8") as lg:
            lg.write(f"[{ts}] {msg}\n")
    except OSError as e:
        utils.error_print(f"Seamless: failed to write profile log {_profile_log_path}: {e}")

def _profile_print(msg, props=None):
    if _profile_enabled(props):
        print(msg)
        _profile_log_line(msg)

# プロキシの matrix_world を分解して prim へ書き戻すフィールド。
# 書き戻しは utils.py の EPSILON=5e-4 判定を通るので、この3つだけが
# 「動かしていないのに毎回わずかに変わる」性質を持つ。
_MATRIX_DERIVED_KEYS = frozenset({"location", "rotation", "size"})


def _quantize_for_sig(obj, ndigits=3, quantize=False):
    """stack_data(list[dict]) をハッシュ可能構造に変換する。

    プロキシ同期の matrix 分解による微小ドリフト(±5e-4級)を吸収し、
    「実質同一」なフル品質リクエストの重複除去(顔②)を成立させるための鍵。
    丸め粒度(1e-3)は書き戻しEPSILON(5e-4)より広く取り、ドリフト連発を確実に畳む。
    ドラッグ(interactive)はこの経路を通らないため精密性に影響しない。

    丸めるのは _MATRIX_DERIVED_KEYS の中だけ。以前は stack_data 全体を無差別に
    丸めていたため、ドリフトとは無縁の「利用者が数値欄に打ち込む値」——
    radius / extrude_height / pipe_radius / radius2 / minor_radius など——まで
    1e-3 粒度で潰れていた。Blender の内部単位はメートルなので、これは
    「1mm 未満の変更が無視される」ということ。半径を 0.2000 から 0.2003 へ
    変えてもシグネチャが動かず再計算がスキップされ、しかもプロパティ側の値は
    更新済みなので、パネルは 0.2003・形状は 0.2000 という食い違いが残る。
    後で force 付きの再計算が走った瞬間に形状が飛ぶので、
    「値を変えても効かない、後から急に反映される」という形で表面化する。
    """
    if isinstance(obj, float):
        # -0.0 を 0.0 に正規化する(丸めの有無に関わらず)
        if quantize:
            obj = round(obj, ndigits)
        return 0.0 if obj == 0.0 else obj
    if isinstance(obj, (list, tuple)):
        return tuple(_quantize_for_sig(x, ndigits, quantize) for x in obj)
    if isinstance(obj, dict):
        return tuple(
            (k, _quantize_for_sig(v, ndigits, quantize or k in _MATRIX_DERIVED_KEYS))
            for k, v in sorted(obj.items())
        )
    return obj


def _needs_face_mesh_update(props, interactive_preview):
    # Fast Modifier Drag for FILLET/CHAMFER must win even inside selection mode.
    # These modifiers pick EDGES (not faces), so the shaded face mesh — the
    # heaviest per-frame cost — is not needed for interaction while dragging the
    # radius. The old order returned True at the is_selection_mode check below
    # before ever reaching the fast_modifier_preview branch, so the fast path was
    # silently bypassed for the entire time the selection modal was running
    # (which persists after inserting the modifier until ESC/RMB) — leaving the
    # result heavy/thick until selection mode was exited. Check it up front.
    # The full shaded surface is restored on release (interactive_preview False).
    if interactive_preview and getattr(props, "fast_modifier_preview", False):
        if 0 <= props.active_primitive_index < len(props.primitives):
            active = props.primitives[props.active_primitive_index]
            if active.type in {'FILLET', 'CHAMFER'}:
                return False
    selected_f_ids = [x.strip() for x in props.selected_faces_str.split("|") if x.strip()]
    if selected_f_ids:
        return True
    if props.is_selection_mode:
        return True
    if 0 <= props.active_primitive_index < len(props.primitives):
        active = props.primitives[props.active_primitive_index]
        if active.type in {'FILLET', 'CHAMFER', 'FACE_OFFSET', 'FACE_INSET', 'DRAFT', 'SHELL'}:
            # Fast Modifier Drag skips the heavy shaded-face tessellation ONLY for
            # FILLET/CHAMFER, where the live edge wireframe already conveys the
            # radius change. For FACE_OFFSET/FACE_INSET/DRAFT/SHELL the shaded
            # surface itself IS the thing being edited (the pushed/pulled/insetted
            # face), so it must update live during the drag — otherwise only the
            # blue wireframe moves and the face lags until the settle recompute,
            # which reads as "the extrude isn't updating / updates at odd times".
            # Interactive drags still use the coarse deflection; full-res on settle.
            if active.type in {'FILLET', 'CHAMFER'} and interactive_preview and getattr(props, "fast_modifier_preview", False):
                return False
            return True
    if not interactive_preview:
        return True
    return False

def _is_modifier_retargeting(props, prim):
    """この prim が「今まさに選択モードでターゲットを選び直されている
    アクティブなモディファイア」かどうか。

    型集合は _INTERACTIVE_MODIFIER_TYPES と同一(検証済み)なので定数を共有する。
    """
    if not props.is_selection_mode:
        return False
    idx = getattr(props, "active_primitive_index", -1)
    if not (0 <= idx < len(props.primitives)):
        return False
    if props.primitives[idx] != prim:
        return False
    return prim.type in _INTERACTIVE_MODIFIER_TYPES


def _get_active_preview_primitive(props):
    if not props:
        return None
    idx = getattr(props, "active_primitive_index", -1)
    if 0 <= idx < len(props.primitives):
        return props.primitives[idx]
    return None

def _is_heavy_boolean_preview(props):
    prim = _get_active_preview_primitive(props)
    if not prim:
        return False
    op = str(getattr(prim, "operation", "")).upper()
    return op in {"SUB", "SUBTRACT", "INT", "INTERSECT", "ADD", "UNION"}

def _should_use_geometry_fast_mode(props, interactive_preview, interactive_kind):
    if not interactive_preview:
        return False
    if interactive_kind == "modifier":
        return False
    if props and getattr(props, "is_selection_mode", False):
        return False
    prim = _get_active_preview_primitive(props)
    if prim and prim.type in _INTERACTIVE_MODIFIER_TYPES:
        return False
    return True

def _get_preview_debug_info(props, interactive_preview, interactive_kind, geometry_fast_mode, heavy_boolean_preview):
    prim = _get_active_preview_primitive(props)
    prim_type = getattr(prim, "type", "-") if prim else "-"
    prim_op = str(getattr(prim, "operation", "-")).upper() if prim else "-"
    selection_mode = bool(getattr(props, "is_selection_mode", False)) if props else False
    return {
        "interactive_preview": interactive_preview,
        "interactive_kind": interactive_kind or "none",
        "geometry_fast_mode": geometry_fast_mode,
        "heavy_boolean_preview": heavy_boolean_preview,
        "selection_mode": selection_mode,
        "active_prim_type": prim_type,
        "active_prim_op": prim_op,
    }

def _get_modifier_interactive_min_interval(props, interactive_preview, interactive_kind):
    if not interactive_preview or interactive_kind != "modifier":
        return 0.0
    if not props or getattr(props, "is_selection_mode", False):
        return 0.0

    prim = _get_active_preview_primitive(props)
    if not prim or prim.type not in {"FILLET", "CHAMFER"}:
        return 0.0

    target_count = len([x for x in getattr(prim, "target_lineages", "").split("|") if x.strip()])
    if target_count >= 5:
        return 0.12
    if target_count >= 3:
        return 0.09
    if target_count >= 2:
        return 0.07
    return 0.05


def update_cad_preview(self, context):
    props = utils.get_active_props(context)
    col = utils.get_active_collection(context)
    fast = (props.is_dragging if props else False) or _is_modifier_interactive(col)
    _update_cad_preview_internal(context, fast_preview=fast)

def update_cad_preview_forced(context):
    _update_cad_preview_internal(context, force=True)

def update_cad_preview_forced_sync(context):
    """強制更新を、**戻ってきた時点で結果が反映されている**形で行う。

    update_cad_preview_forced は非同期。投げて即座に返り、結果は
    poll_async_results が後から適用する。直後に描画キャッシュや形状を
    読む処理は、**更新前のものを読む**。

    厄介なのは、背景実行では `not bpy.app.background` の条件で同期パスへ
    落ちるため、**ヘッドレスのテストではこの違いが現れない**こと。GUI で
    しか出ない差なので、読み戻しが要る場面ではこちらを明示的に使う。
    """
    _update_cad_preview_internal(context, force=True, sync=True)

def update_cad_preview_high_quality(context, deflection_override=None, angular_override=None):
    _update_cad_preview_internal(context, fast_preview=False, override_deflection=deflection_override, override_angular=angular_override, sync=True)

def update_cad_preview_fast(context):
    _update_cad_preview_internal(context, fast_preview=True)

def update_cad_preview_fast_throttled(context, throttle_key="default", min_interval=0.08):
    now = time.perf_counter()
    last_t = _preview_throttle_times.get(throttle_key, 0.0)
    if (now - last_t) < max(0.0, float(min_interval)):
        return False
    _preview_throttle_times[throttle_key] = now
    update_cad_preview_fast(context)
    return True

def _queue_debounced_preview_update(col_name, interactive_preview, override_deflection, override_angular, delay):
    _pending_preview_data[col_name] = (interactive_preview, override_deflection, override_angular)
    if col_name in _debounce_timers:
        return

    def make_timer(c_name):
        def timer_cb():
            if c_name in _pending_preview_data:
                fp, od, oa = _pending_preview_data[c_name]
                target_col = bpy.data.collections.get(c_name)
                if target_col:
                    _update_cad_preview_internal_for_col(
                        target_col, bpy.context, fast_preview=fp,
                        override_deflection=od, override_angular=oa, force=True
                    )
                _pending_preview_data.pop(c_name, None)
            _debounce_timers.pop(c_name, None)
            return None
        return timer_cb

    cb = make_timer(col_name)
    _debounce_timers[col_name] = cb
    bpy.app.timers.register(cb, first_interval=max(0.02, float(delay)))

def _is_modifier_interactive(col):
    if not col:
        return False
    return time.time() < _modifier_interactive_until.get(col.name, 0.0)

def _set_interactive_preview_state(col_name, settle_delay, kind):
    now = time.time()
    _modifier_interactive_until[col_name] = now + max(0.05, float(settle_delay))
    _interactive_preview_kind[col_name] = kind
    token = _modifier_finish_tokens.get(col_name, 0) + 1
    _modifier_finish_tokens[col_name] = token
    return token

def _schedule_interactive_finish(col_name, settle_delay):
    token = _modifier_finish_tokens.get(col_name, 0)

    def finish_cb(expected_token=token, target_col_name=col_name):
        if _modifier_finish_tokens.get(target_col_name) != expected_token:
            return None

        remaining = _modifier_interactive_until.get(target_col_name, 0.0) - time.time()
        if remaining > 0.02:
            return min(0.05, remaining)

        _modifier_finish_tokens.pop(target_col_name, None)
        _modifier_interactive_until.pop(target_col_name, None)
        _interactive_preview_kind.pop(target_col_name, None)

        target_col = bpy.data.collections.get(target_col_name)
        if target_col:
            bpy.context.scene.is_sdf_preview_mode = False
            _update_cad_preview_internal_for_col(target_col, bpy.context, fast_preview=False, force=True)
        return None

    bpy.app.timers.register(finish_cb, first_interval=max(0.05, float(settle_delay)))

def trigger_modifier_numeric_preview(context, settle_delay=0.18):
    col = utils.get_active_collection(context)
    if not col:
        _update_cad_preview_internal(context, fast_preview=True)
        return

    col_name = col.name
    if not _is_modifier_interactive(col):
        _modifier_live_preview_times.pop(col_name, None)
    _set_interactive_preview_state(col_name, settle_delay, "modifier")

    props = utils.get_active_props(context)
    if props and 0 <= props.active_primitive_index < len(props.primitives):
        prim = props.primitives[props.active_primitive_index]
        if prim.type in {'FILLET', 'CHAMFER'}:
            context.scene.sdf_preview_fillet_radius = prim.radius
        elif prim.type == 'BOX':
            context.scene.sdf_preview_box_size = prim.size

    context.scene.is_sdf_preview_mode = True

    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()

    _schedule_interactive_finish(col_name, settle_delay)

def trigger_transform_numeric_preview(context, settle_delay=0.14):
    col = utils.get_active_collection(context)
    if not col:
        _update_cad_preview_internal(context, fast_preview=True)
        return

    col_name = col.name
    _set_interactive_preview_state(col_name, settle_delay, "transform")

    _update_cad_preview_internal_for_col(col, context, fast_preview=True)
    _schedule_interactive_finish(col_name, settle_delay)

def _get_interactive_preview_kind(col):
    if not col:
        return ""
    return _interactive_preview_kind.get(col.name, "")

def trigger_dependent_updates(parent_col, context, fast_preview=False, override_deflection=None, override_angular=None, visited=None, force_sync=False):
    parent_ptr_str = getattr(parent_col, "seamless_cad_stack_ptr", "0")
    if parent_ptr_str == "0":
        return
        
    for col in bpy.data.collections:
        if col == parent_col:
            continue
        if not hasattr(col, "seamless_props"):
            continue
        col_ptr_str = getattr(col, "seamless_cad_stack_ptr", "0")
        if col_ptr_str == "0":
            continue
            
        has_dep = False
        for prim in col.seamless_props.primitives:
            if prim.type == 'INSTANCE' and prim.target_uuid.strip() == parent_ptr_str:
                has_dep = True
                break
                
        if has_dep:
            _update_cad_preview_internal_for_col(col, context, fast_preview=fast_preview, override_deflection=override_deflection, override_angular=override_angular, force=True, sync=force_sync, visited=visited)

def update_cad_preview_fast_for_col(col, context):
    _update_cad_preview_internal_for_col(col, context, fast_preview=True)

def update_cad_preview_high_quality_for_col(col, context, force=False, sync=False):
    _update_cad_preview_internal_for_col(col, context, fast_preview=False, force=force, sync=sync)

def _update_cad_preview_internal(context, fast_preview=False, override_deflection=None, override_angular=None, force=False, sync=False):
    col = utils.get_active_collection(context)
    if not col:
        return
    _update_cad_preview_internal_for_col(col, context, fast_preview=fast_preview, override_deflection=override_deflection, override_angular=override_angular, force=force, sync=sync)

def _make_async_request_id(stack_ptr):
    global _latest_request_id
    _latest_request_id += 1
    _latest_request_ids[stack_ptr] = _latest_request_id
    return _latest_request_id

def _queue_pending_async_request(col, context, fast_preview, override_deflection, override_angular, force, sync, visited):
    if not col:
        return
    _pending_async_requests[col.name] = {
        "fast_preview": fast_preview,
        "override_deflection": override_deflection,
        "override_angular": override_angular,
        "force": force,
        "sync": sync,
        "visited": visited,
    }

def _launch_async_update(stack_ptr, req_id, req_dict, interactive_kind="", is_interactive=False):
    def async_task(s_ptr, r_id, rq, i_kind, is_interactive_req):
        try:
            t_geom_0 = time.perf_counter()
            res = send_and_receive(rq)
            geom_ms = (time.perf_counter() - t_geom_0) * 1000.0
            latest_id = _latest_request_ids.get(s_ptr, 0)
            if res and r_id == latest_id:
                _async_results.append((s_ptr, r_id, res, geom_ms, i_kind, is_interactive_req))
        finally:
            with _computing_stacks_lock:
                _computing_stacks.discard(s_ptr)

    with _computing_stacks_lock:
        _computing_stacks.add(stack_ptr)

    t = threading.Thread(target=async_task, args=(stack_ptr, req_id, req_dict, interactive_kind, is_interactive), daemon=True)
    t.start()

def _update_cad_preview_internal_for_col(col, context, fast_preview=False, override_deflection=None, override_angular=None, force=False, sync=False, visited=None):
    op_t0 = time.perf_counter()
    global _last_request_time
    
    if visited is None:
        visited = set()
    if col.name in visited:
        return
    visited.add(col.name)
    
    props = col.seamless_props
    if not props:
        return
    ensure_step_primitive_targets(props)
    perf_enabled = _profile_enabled(props)

    is_syncing = getattr(utils, "_is_updating_proxies", False)
    if is_syncing and not force:
        return

    # SDFプレビュー中はGPU側のレイマーチング表示が実体を代替するため、
    # ドラッグ中の重いOCCT再計算(TCP往復込み)を基本的にスキップする。
    # ただしFILLET/CHAMFERはエッジ表示がSDFに追従しないため、下の
    # modifier throttle(_get_modifier_interactive_min_interval)による
    # 間引き付き実計算を許可し、辺描画も低頻度に更新され続けるようにする。
    # 確定/キャンセル時はforce=Trueで呼ばれるのでここには来ない。
    if fast_preview and not force and getattr(context.scene, "is_sdf_preview_mode", False):
        active_prim = _get_active_preview_primitive(props)
        if not (active_prim and active_prim.type in {'FILLET', 'CHAMFER'}):
            return

    # 顔①対策: この col で BSP CSGライブプレビューが作動中は、ドラッグ中の OCC 往復
    # (fast_preview)を抑止する。純Rust BSP tick が描画を担うため、ここで OCCブーリアン
    # (stack深いと fast でも 10〜25ms)を二重に叩くとカクつきの原因になる。
    # 確定/キャンセルは force=True で呼ばれるためここに来ない。
    if fast_preview and not force:
        csg_state = getattr(utils, "_csg_preview_state", None)
        if csg_state and col.name in csg_state:
            return

    interactive_preview = fast_preview
    interactive_kind = _get_interactive_preview_kind(col) if interactive_preview else ""
    geometry_fast_mode = _should_use_geometry_fast_mode(props, interactive_preview, interactive_kind)
    heavy_boolean_preview = geometry_fast_mode and _is_heavy_boolean_preview(props)
    preview_info = _get_preview_debug_info(props, interactive_preview, interactive_kind, geometry_fast_mode, heavy_boolean_preview)
    
    if interactive_preview and not force:
        modifier_min_interval = _get_modifier_interactive_min_interval(props, interactive_preview, interactive_kind)
        if modifier_min_interval > 0.0:
            now_perf = time.perf_counter()
            last_modifier_t = _modifier_preview_times.get(col.name, 0.0)
            elapsed_modifier = now_perf - last_modifier_t
            if elapsed_modifier < modifier_min_interval:
                remaining = modifier_min_interval - elapsed_modifier
                _queue_debounced_preview_update(col.name, interactive_preview, override_deflection, override_angular, remaining)
                if perf_enabled:
                    _profile_print(
                        f"[Preview Skip] CAD={col.name} mode={preview_info['interactive_kind']} "
                        f"prim={preview_info['active_prim_type']}:{preview_info['active_prim_op']} "
                        f"reason=modifier_throttle remaining_ms={remaining * 1000.0:.1f}",
                        props,
                    )
                return
            _modifier_preview_times[col.name] = now_perf

        now = time.time()
        min_request_gap = 0.16 if heavy_boolean_preview else 0.06
        debounce_delay = 0.2 if heavy_boolean_preview else 0.1
        # **force のときは間隔で捨てないこと。**
        #
        # ここは連続入力(ドラッグ・数値の連打)を間引くための throttle で、
        # 捨てた分は debounce タイマーへ回される。ところが force まで対象に
        # していたため、「必ず反映されなければならない更新」も直前の更新から
        # 60ms 以内なら後回しになっていた。
        #
        # 実害が出ていたのが削除で、Feature Tree を空にしても最後の1つが
        # 画面に残る(利用者報告 2026-08-14)。削除は直前に別の更新を伴うので
        # この間隔に収まりやすく、本来の再計算が捨てられて、ワイヤーだけが
        # hidden_primitive_uuids で消え、シェーディングされた面が残っていた。
        #
        # force を投げているのは確定・キャンセル・削除といった離散的な操作
        # だけで(毎フレーム呼ぶ経路は fast / throttled 系を使う)、素通しに
        # しても連打にはならない。
        if not force and now - _last_request_time < min_request_gap:
            _queue_debounced_preview_update(col.name, interactive_preview, override_deflection, override_angular, debounce_delay)
            return
            
        _last_request_time = now
    
    rollback_index = getattr(props, "rollback_index", -1)
    
    for prim in props.primitives:
        if not prim.uuid:
            prim.uuid = str(uuid.uuid4())[:8]
    
    edge_ids = [x.strip() for x in props.selected_edges_str.split("|") if x.strip()]
    face_ids = [x.strip() for x in props.selected_faces_str.split("|") if x.strip()]
    lineage_list = edge_ids + face_ids

    consumed_uuids = set()
    for i, prim in enumerate(props.primitives):
        if rollback_index >= 0 and i > rollback_index:
            continue
        if prim.target_uuid.strip() and prim.type != 'INSTANCE':
            consumed_uuids.add(prim.target_uuid.strip())
        if prim.type == 'LOFT':
            for u in [x.strip() for x in getattr(prim, "loft_uuids", "").split("|") if x.strip()]:
                consumed_uuids.add(u)

    t_stack_build_0 = time.perf_counter()
    stack_data = []
    for i, prim in enumerate(props.primitives):
        if rollback_index >= 0 and i > rollback_index:
            break
        if prim.type == 'INSTANCE' and not prim.target_uuid.strip():
            continue

        is_consumed = prim.uuid in consumed_uuids
        op = prim.operation if not is_consumed else 'NOP'
        
        if _is_modifier_retargeting(props, prim):
            # 対象を選び直している最中はターゲットを空で送る。そうしないと
            # 選択途中の中途半端な集合でモディファイアが適用されてしまう。
            tls = []
        else:
            tls = [x.strip() for x in prim.target_lineages.split("|") if x.strip()]
        if prim.type == 'SWEEP':
            prof = [x.strip() for x in prim.target_lineages.split("|") if x.strip()]
            first_prof = prof[0] if prof else getattr(prim, "sweep_profile_uuid", "")
            tls = [first_prof, getattr(prim, "sweep_path_uuid", "")]
        elif prim.type == 'LOFT':
            tls = [x.strip() for x in getattr(prim, "loft_uuids", "").split("|") if x.strip()]

        # V8.0.1: FILLET/CHAMFERの辺座標を参照プリミティブの移動に追従させる
        if prim.type in _INTERACTIVE_MODIFIER_TYPES and tls and any("@" in x for x in tls):
            tls = _adjust_target_coords_v810(tls, prim, props)
        adjusted_reference_lineage = prim.reference_lineage
        if prim.type == 'DRAFT' and adjusted_reference_lineage and "@" in adjusted_reference_lineage:
            adjusted_reference_lineage = _adjust_single_lineage_coord_v810(
                adjusted_reference_lineage,
                'reference_ref_snapshot',
                prim,
                props
            )
        if prim.type == 'DRAFT':
            try:
                utils.debug_print(
                    f"[DRAFT_STACK] uuid={prim.uuid} op={op} selection_mode={props.is_selection_mode} "
                    f"ref={getattr(prim, 'reference_lineage', '')!r} raw_targets={getattr(prim, 'target_lineages', '')!r} "
                    f"stack_targets={tls!r} adjusted_ref={adjusted_reference_lineage!r} "
                    f"target_snapshot_entries={len(json.loads(getattr(prim, 'edge_ref_snapshot', '') or '{}'))} "
                    f"ref_snapshot_entries={len(json.loads(getattr(prim, 'reference_ref_snapshot', '') or '{}'))}"
                )
            except Exception as e:
                utils.debug_print(f"[DRAFT_STACK] log error: {e}")

        p_data = {
            "type": prim.type, "operation": op, "uuid": prim.uuid,
            "is_consumed": is_consumed, 
            "location": [prim.location[0], prim.location[1], prim.location[2]],
            "rotation": [prim.rotation[0], prim.rotation[1], prim.rotation[2]],
            "size": [prim.size[0], prim.size[1], prim.size[2]], "radius": prim.radius,
            "fill_closed": prim.fill_closed,
            "use_pipe": prim.use_pipe,
            "pipe_radius": prim.pipe_radius,
            "angle_start": prim.angle_start, "angle_end": prim.angle_end,
            "target_lineages": tls,
            "reference_lineage": adjusted_reference_lineage,
            "extrude_height": prim.extrude_height,
            "radius2": prim.radius2,
            "minor_radius": prim.minor_radius,
            "sides": prim.sides,
            "module": prim.module,
            "pressure_angle": prim.pressure_angle,
            "turns": getattr(prim, "turns", 3.0),
            "target_uuid": prim.target_uuid,
            "count": prim.count,
            "distance": getattr(prim, "turns", 3.0) if prim.type == 'HELIX' else prim.distance,
            "pattern_axis": prim.pattern_axis,
            "top_shape": prim.top_shape,
            "bot_shape": prim.bot_shape,
            "sweep_path_uuid": getattr(prim, "sweep_path_uuid", ""),
            "sweep_profile_uuid": getattr(prim, "sweep_profile_uuid", ""),
            "sweep_frame_mode": getattr(prim, "sweep_frame_mode", "AUTO"),
            "sweep_roll_degrees": getattr(prim, "sweep_roll_degrees", 0.0),
            "loft_uuids": [x.strip() for x in getattr(prim, "loft_uuids", "").split("|") if x.strip()],
            "unify_faces": getattr(prim, "unify_faces", True),
            "unify_edges": getattr(prim, "unify_edges", True),
            # V8.1.5: 可変フィレット - トークンごとの上書き半径のみ送る(radius<0はデフォルトなので送らない)
            "edge_radii": [(er.token, er.radius) for er in getattr(prim, "edge_radii", []) if er.radius >= 0.0],
        }
        if prim.type == 'VARIABLE_BOX':
            # 高さは size.z としてカーネルへ渡す(make_variable_box の第3引数 h)。
            p_data["size"][2] = prim.extrude_height
            # ただし extrude_height をそのまま送ってはいけない。カーネルの
            # 汎用押し出し(occ_core.cpp の [EXTRUDE] ブロック)は型で絞られておらず、
            # extrude_height が非0なら **どんな形状でも** BRepPrimAPI_MakePrism に
            # かける。VARIABLE_BOX は既に高さ h のロフト済みソリッドなので、
            # そこへさらに押し出しが走って形状生成が失敗し、結果が空になる
            # → generate_mesh が古いキャッシュを返し、「高さを変えても何も起きない」
            # ように見えていた(2026-08-01、カーネルログで確認)。
            # 高さは size.z 側で効いているので、押し出しには 0 を渡して黙らせる。
            p_data["extrude_height"] = 0.0
        if prim.type in {'CURVE', 'SURFACE', 'POLYLINE'}:
            p_data["points"] = [[pt.co[0], pt.co[1], pt.co[2], 1.0 if getattr(pt, "use_fillet", True) else 0.0] for pt in prim.points]
            if hasattr(prim, "segments_json") and prim.segments_json:
                try:
                    p_data["segments"] = json.loads(prim.segments_json)
                except Exception as e:
                    pass
        stack_data.append(p_data)
    
    json_str = ""
    try:
        stack_hash = hash(repr(stack_data))
    except Exception:
        stack_hash = None
    cached_entry = _serialize_cache.get(col.name)
    if stack_hash is not None and cached_entry is not None and cached_entry[0] == stack_hash:
        binary_payload = cached_entry[1]
    else:
        binary_payload = serialize_primitives(stack_data)
        if stack_hash is not None:
            _serialize_cache[col.name] = (stack_hash, binary_payload)
    t_stack_build_ms = (time.perf_counter() - t_stack_build_0) * 1000.0
            
    from .utils import sync_proxies, _is_updating_proxies
    from .drawing import get_wireframe_engine
    
    try:
        should_sync_proxies = not (interactive_preview and interactive_kind == "modifier")

        if should_sync_proxies and not _is_updating_proxies and col == utils.get_active_collection(context):
            t_sync_proxy_0 = time.perf_counter()
            sync_proxies(context)
            t_sync_proxy_ms = (time.perf_counter() - t_sync_proxy_0) * 1000.0
        else:
            t_sync_proxy_ms = 0.0
        
        stack_ptr = get_or_create_stack_ptr(col)
        
        has_instance = any(p.type == 'INSTANCE' for i, p in enumerate(props.primitives) if not (rollback_index >= 0 and i > rollback_index))
        if override_deflection is not None:
            deflection = override_deflection
        elif interactive_preview:
            base_deflection = max(0.35 if has_instance else 0.25, props.mesh_quality)
            if heavy_boolean_preview:
                deflection = max(base_deflection, 1.6 if has_instance else 1.3)
            else:
                deflection = base_deflection
        else:
            deflection = props.mesh_quality

        if override_angular is not None:
            angular_deflection = override_angular
        elif interactive_preview:
            base_angular = max(18.0 if has_instance else 15.0, props.mesh_angular_quality)
            if heavy_boolean_preview:
                angular_deflection = max(base_angular, 55.0 if has_instance else 45.0)
            else:
                angular_deflection = base_angular
        else:
            angular_deflection = props.mesh_angular_quality
        angular_deflection_rad = math.radians(angular_deflection)
        
        current_matrices = {}
        for obj in col.objects:
            if obj.get("is_seamless_proxy") and obj.get("primitive_uuid"):
                current_matrices[obj.get("primitive_uuid")] = obj.matrix_world.copy()

        req_dict = {
            "action": "update",
            "stack_ptr": stack_ptr,
            "fast_mode": geometry_fast_mode,
            "f_radius": props.fillet_radius,
            "f_deflection": deflection,
            "f_angular_deflection": angular_deflection_rad,
            "f_lineage_list": lineage_list,
            "json_str": "", "binary_payload": binary_payload
        }
        face_mesh_update_needed = _needs_face_mesh_update(props, interactive_preview)
        req_dict["include_mesh"] = face_mesh_update_needed

        # 顔②対策: フル品質(非interactive)かつ非forceの再同期は、内容が前回 dispatch と
        # 完全一致するなら送信をスキップする。確定/再描画のたびに飛ぶ内容同一の
        # 全再計算(OCCブーリアン 数十〜100ms)を1回に潰す。
        # シグネチャは「OCC結果に効く入力」だけで構成する(binary_payload=形状/op、
        # lineage=選択辺面、rollback、include_mesh、テッセレーション解像度、選択モード、active)。
        # interactive(drag)は binary_payload が毎tick変わるため対象外かつ誤スキップしない。
        dispatch_sig = None
        if not interactive_preview:
            try:
                dispatch_sig = (
                    # 生バイトではなく丸めた幾何でハッシュ(プロキシ同期の微小ドリフト吸収)
                    hash(_quantize_for_sig(stack_data)),
                    tuple(lineage_list),
                    rollback_index,
                    bool(face_mesh_update_needed),
                    bool(geometry_fast_mode),
                    round(float(props.fillet_radius), 5),
                    round(deflection, 3),
                    round(angular_deflection_rad, 4),
                    bool(getattr(props, "is_selection_mode", False)),
                    int(getattr(props, "active_primitive_index", -1)),
                )
            except Exception:
                dispatch_sig = None
            # 非force のみスキップ。シグネチャの「記録」は実際に dispatch する地点
            # (async launch / sync send)でのみ行う。ここで記録するとキューイングされた
            # 本物の変更が再実行時に誤スキップされるため、記録は下流に置く。
            if dispatch_sig is not None and not force and _last_dispatched_sig.get(stack_ptr) == dispatch_sig:
                if perf_enabled:
                    _profile_print(
                        f"[Preview Skip] CAD={col.name} reason=duplicate_content "
                        f"stack_prims={len(stack_data)}",
                        props,
                    )
                return

        if perf_enabled:
            _profile_print(
                "[Preview Request] "
                f"CAD={col.name} "
                f"mode={preview_info['interactive_kind']} "
                f"interactive={preview_info['interactive_preview']} "
                f"geom_fast={preview_info['geometry_fast_mode']} "
                f"heavy_bool={preview_info['heavy_boolean_preview']} "
                f"selection={preview_info['selection_mode']} "
                f"prim={preview_info['active_prim_type']}:{preview_info['active_prim_op']} "
                f"stack_prims={len(stack_data)} lineages={len(lineage_list)} "
                f"face_mesh={face_mesh_update_needed} "
                f"defl={deflection:.3f} ang_deg={angular_deflection:.1f} "
                f"stack_build_ms={t_stack_build_ms:.2f} sync_proxy_ms={t_sync_proxy_ms:.2f}",
                props,
            )

        # ASYNC MODE (also used for interactive drag previews, so the main/modal
        # thread never blocks on the OCC round-trip; poll_async_results() applies
        # results, discarding any whose req_id is stale relative to the latest
        # request for this stack so an out-of-order response can't clobber newer state)
        if not sync and not bpy.app.background:
            if stack_ptr in _computing_stacks:
                _queue_pending_async_request(
                    col, context, interactive_preview, override_deflection,
                    override_angular, force, sync, visited
                )
                return

            req_id = _make_async_request_id(stack_ptr)
            _pending_matrices[stack_ptr] = (current_matrices, req_id)
            if dispatch_sig is not None:
                _last_dispatched_sig[stack_ptr] = dispatch_sig
            _launch_async_update(stack_ptr, req_id, req_dict, interactive_kind=interactive_kind, is_interactive=interactive_preview)

            if not interactive_preview:
                trigger_dependent_updates(col, context, interactive_preview, override_deflection, override_angular, visited, force_sync=False)
            return

        # SYNC MODE
        req_id = _make_async_request_id(stack_ptr)
        _latest_completed_ids[stack_ptr] = req_id
        _pending_matrices.pop(stack_ptr, None)
        if dispatch_sig is not None:
            _last_dispatched_sig[stack_ptr] = dispatch_sig

        t_geom_0 = time.perf_counter()
        res = send_and_receive(req_dict)
        t_geom_ms = (time.perf_counter() - t_geom_0) * 1000.0
        
        if res:
            edge_points, edge_counts, res_lineages, m_verts, m_tris, m_f_ids, m_tc, p_bool, p_edge, p_mesh, p_prim, p_bool_main, p_bool_modifier, p_extrema, p_unify, p_resume, p_t_assign, p_m_apply, p_recluster, p_f_setup, p_f_target, p_f_add, p_f_build, p_f_history, p_f_added_edges, p_f_contours = res
            t_wire_0 = time.perf_counter()
            get_wireframe_engine().update_data(stack_ptr, edge_points, edge_counts, res_lineages)
            t_wire_ms = (time.perf_counter() - t_wire_0) * 1000.0
            if hasattr(utils, "_proxy_initial_matrices"):
                utils._proxy_initial_matrices.update(current_matrices)
                
            selected_f_ids = set(x.strip() for x in props.selected_faces_str.split("|") if x.strip())
            modifier_f_ids = set()
            reference_f_ids = set()
            if 0 <= props.active_primitive_index < len(props.primitives):
                prim = props.primitives[props.active_primitive_index]
                if prim.type in {'FILLET', 'CHAMFER', 'FACE_OFFSET', 'FACE_INSET', 'DRAFT', 'SHELL', 'FACE_LOFT', 'FACE_REVOLVE', 'SWEEP'}:
                    targets = [x.strip() for x in prim.target_lineages.split("|") if x.strip()]
                    for t_id in targets:
                        if "Face:" in t_id or ":F" in t_id:
                            modifier_f_ids.add(t_id)
                    if hasattr(prim, "reference_lineage") and prim.reference_lineage:
                        reference_f_ids.add(prim.reference_lineage)
            
            is_modifier_zero = False
            if 0 <= props.active_primitive_index < len(props.primitives):
                prim = props.primitives[props.active_primitive_index]
                if prim.type in {'FILLET', 'CHAMFER', 'FACE_OFFSET', 'FACE_INSET', 'DRAFT', 'SHELL', 'FACE_LOFT', 'FACE_REVOLVE', 'SWEEP'}:
                    is_modifier_zero = (abs(prim.radius) < 1e-5)
                    if prim.type == 'FACE_INSET' and hasattr(prim, 'extrude_height'):
                        is_modifier_zero = is_modifier_zero and (abs(prim.extrude_height) < 1e-5)
            
            show_mod = props.is_selection_mode or is_modifier_zero
            
            safe_selected_f_ids = selected_f_ids if props.is_selection_mode else set()
            safe_modifier_f_ids = modifier_f_ids if show_mod else set()
            safe_reference_f_ids = reference_f_ids if show_mod else set()
            safe_preselected_f_id = props.preselected_face_id if props.is_selection_mode else ""
            
            if face_mesh_update_needed:
                t_face_0 = time.perf_counter()
                get_wireframe_engine().update_face_data(
                    stack_ptr, m_verts, m_tris, m_f_ids, m_tc, 
                    opacity=props.viewport_opacity,
                    selected_f_ids=safe_selected_f_ids,
                    preselected_f_id=safe_preselected_f_id,
                    modifier_f_ids=safe_modifier_f_ids,
                    reference_f_ids=safe_reference_f_ids
                )
                t_face_ms = (time.perf_counter() - t_face_0) * 1000.0
            else:
                t_face_ms = 0.0
            _profile_print(
                "[Profiling SYNC] "
                f"CAD={col.name} "
                f"mode={preview_info['interactive_kind']} "
                f"interactive={preview_info['interactive_preview']} "
                f"geom_fast={preview_info['geometry_fast_mode']} "
                f"heavy_bool={preview_info['heavy_boolean_preview']} "
                f"selection={preview_info['selection_mode']} "
                f"prim={preview_info['active_prim_type']}:{preview_info['active_prim_op']} "
                f"face_mesh={face_mesh_update_needed} "
                f"defl={deflection:.3f} ang_deg={angular_deflection:.1f} | "
                f"C++ Total: {p_bool:.2f} ms "
                f"(Prim: {p_prim:.2f}ms, BoolMain: {p_bool_main:.2f}ms, BoolMod: {p_bool_modifier:.2f}ms, "
                f"Extrema: {p_extrema:.2f}ms, Res: {p_resume:.2f}ms, Tgt: {p_t_assign:.2f}ms, "
                f"ModApp: {p_m_apply:.2f}ms, Reclus: {p_recluster:.2f}ms, Unify: {p_unify:.2f}ms) | "
                f"FilletDetail: setup={p_f_setup:.2f}ms target={p_f_target:.2f}ms add={p_f_add:.2f}ms build={p_f_build:.2f}ms hist={p_f_history:.2f}ms edges={int(round(p_f_added_edges))} contours={int(round(p_f_contours))} | "
                f"C++ Edge: {p_edge:.2f} ms | C++ Mesh: {p_mesh:.2f} ms | "
                f"Python Wire: {t_wire_ms:.2f} ms | Python Face: {t_face_ms:.2f} ms | "
                f"Python Total: {t_wire_ms + t_face_ms:.2f} ms | "
                f"Wall Total: {t_geom_ms + t_wire_ms + t_face_ms:.2f} ms",
                props,
            )

            # Record this modifier compute's wall time for adaptive live pacing.
            if interactive_kind == "modifier":
                _modifier_last_compute_ms[col.name] = t_geom_ms + t_wire_ms + t_face_ms

            if not interactive_preview:
                trigger_dependent_updates(col, context, interactive_preview, override_deflection, override_angular, visited, force_sync=True)
                
            for window in context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == 'VIEW_3D':
                        area.tag_redraw()

    except Exception as e:
        utils.error_print(f"Seamless CAD Update Error on '{col.name}': {e}")

_delayed_redraw_pending = False


def _delayed_redraw_cb():
    global _delayed_redraw_pending
    _delayed_redraw_pending = False
    try:
        for w in bpy.context.window_manager.windows:
            for a in w.screen.areas:
                if a.type == 'VIEW_3D':
                    a.tag_redraw()
    except Exception:
        pass
    return None


def _schedule_delayed_redraw(delay=0.1):
    """0.1秒後の再描画を1本だけ予約する。

    以前は非同期結果1件ごとに新しいタイマーを register していたため、
    ドラッグ中は毎フレーム分のワンショットタイマーが積み上がっていた。
    再描画は冪等なので、未消化の予約があるなら追加は不要。
    """
    global _delayed_redraw_pending
    if _delayed_redraw_pending:
        return
    _delayed_redraw_pending = True
    try:
        bpy.app.timers.register(_delayed_redraw_cb, first_interval=delay)
    except Exception:
        _delayed_redraw_pending = False


def poll_async_results():
    if not _async_results:
        return 0.05
    
    try:
        target_stack_ptr, req_id, res, geom_ms, interactive_kind, is_interactive = _async_results.popleft()

        edge_points, edge_counts, edge_lineages, m_verts, m_tris, m_f_ids, m_tc, p_bool, p_edge, p_mesh, p_prim, p_bool_main, p_bool_modifier, p_extrema, p_unify, p_resume, p_t_assign, p_m_apply, p_recluster, p_f_setup, p_f_target, p_f_add, p_f_build, p_f_history, p_f_added_edges, p_f_contours = res
        
        latest_id = _latest_request_ids.get(target_stack_ptr, 0)
        if req_id < latest_id:
            return 0.02

        completed_id = _latest_completed_ids.get(target_stack_ptr, 0)
        if req_id < completed_id:
            return 0.02

        if target_stack_ptr not in _pending_matrices:
            return 0.02

        pending_info = _pending_matrices[target_stack_ptr]
        if isinstance(pending_info, tuple) and len(pending_info) == 2:
            matrices, saved_req_id = pending_info
        else:
            matrices = pending_info
            saved_req_id = req_id

        if req_id != saved_req_id:
            return 0.02

        _latest_completed_ids[target_stack_ptr] = req_id
        if hasattr(utils, "_proxy_initial_matrices"):
            utils._proxy_initial_matrices.update(matrices)
        if saved_req_id == req_id:
            del _pending_matrices[target_stack_ptr]
            
        context = bpy.context
        target_col = _stack_ptr_to_col.get(str(target_stack_ptr))

        props = target_col.seamless_props if target_col else utils.get_active_props(context)
        if not props:
            return 0.02

        from .drawing import get_wireframe_engine

        t_wire_0 = time.perf_counter()
        get_wireframe_engine().update_data(target_stack_ptr, edge_points, edge_counts, edge_lineages)
        t_wire_ms = (time.perf_counter() - t_wire_0) * 1000.0

        selected_f_ids = set(x.strip() for x in props.selected_faces_str.split("|") if x.strip())
        modifier_f_ids = set()
        reference_f_ids = set()
        is_modifier_zero = False
        if 0 <= props.active_primitive_index < len(props.primitives):
            prim = props.primitives[props.active_primitive_index]
            if prim.type in {'FILLET', 'CHAMFER', 'FACE_OFFSET', 'DRAFT', 'SHELL', 'FACE_INSET', 'FACE_LOFT', 'FACE_REVOLVE'}:
                targets = [x.strip() for x in prim.target_lineages.split("|") if x.strip()]
                for t_id in targets:
                    if "Face:" in t_id or ":F" in t_id:
                        modifier_f_ids.add(t_id)
                if hasattr(prim, "reference_lineage") and prim.reference_lineage:
                    reference_f_ids.add(prim.reference_lineage)
                    
                is_modifier_zero = (abs(prim.radius) < 1e-5)
                if prim.type == 'FACE_INSET' and hasattr(prim, 'extrude_height'):
                    is_modifier_zero = is_modifier_zero and (abs(prim.extrude_height) < 1e-5)

        show_mod = props.is_selection_mode or is_modifier_zero

        safe_selected_f_ids = selected_f_ids if props.is_selection_mode else set()
        safe_modifier_f_ids = modifier_f_ids if show_mod else set()
        safe_reference_f_ids = reference_f_ids if show_mod else set()
        safe_preselected_f_id = props.preselected_face_id if props.is_selection_mode else ""
        
        if _needs_face_mesh_update(props, is_interactive):
            t_face_0 = time.perf_counter()
            get_wireframe_engine().update_face_data(
                target_stack_ptr,
                m_verts, m_tris, m_f_ids, m_tc,
                opacity=props.viewport_opacity,
                selected_f_ids=safe_selected_f_ids,
                preselected_f_id=safe_preselected_f_id,
                modifier_f_ids=safe_modifier_f_ids,
                reference_f_ids=safe_reference_f_ids
            )
            t_face_ms = (time.perf_counter() - t_face_0) * 1000.0
        else:
            t_face_ms = 0.0

        if interactive_kind == "modifier" and target_col:
            _modifier_last_compute_ms[target_col.name] = geom_ms + t_wire_ms + t_face_ms
        
        if _profile_enabled(props):
            col_name = target_col.name if target_col else "Unknown"
            print("\n" + "="*50)
            print(f" [Seamless CAD {get_version()} Profiling] {col_name}")
            print("-" * 50)
            print(f"  [C++] プリミティブ生成 (Array等): {p_prim:.2f} ms")
            print(f"  [C++] メインブーリアン演算: {p_bool_main:.2f} ms")
            print(f"  [C++] モディファイア演算: {p_bool_modifier:.2f} ms")
            print(f"  [C++] BRepExtrema厳密距離: {p_extrema:.2f} ms")
            print(f"  [C++] (補)Resumeキャッシュ復元: {p_resume:.2f} ms")
            print(f"  [C++] (補)Modifierターゲット割当: {p_t_assign:.2f} ms")
            print(f"  [C++] (補)Modifier本体適用: {p_m_apply:.2f} ms")
            print(f"  [C++] (補)Modifier再クラスタ構築: {p_recluster:.2f} ms")
            print(f"  [C++] トポロジークリーンアップ: {p_unify:.2f} ms")
            print(f"  [C++] 輪郭線(エッジ)抽出: {p_edge:.2f} ms")
            print(f"  [C++] 描画用テセレーション(メッシュ): {p_mesh:.2f} ms")
            print("-" * 50)
            print(f"  [Rust] C++全体呼び出し時間: {p_bool:.2f} ms")
            print(f"  [Python] 輪郭線データ転送: {t_wire_ms:.2f} ms")
            print(f"  [Python] メッシュデータ転送: {t_face_ms:.2f} ms")
            print("="*50 + "\n")

        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()

        # タイミングの競合によるエッジ消失を防ぐための遅延再描画タイマー（0.1秒後）
        _schedule_delayed_redraw()

        if target_col and target_col.name in _pending_async_requests:
            pending = _pending_async_requests.pop(target_col.name)
            _update_cad_preview_internal_for_col(
                target_col,
                context,
                fast_preview=pending.get("fast_preview", False),
                override_deflection=pending.get("override_deflection"),
                override_angular=pending.get("override_angular"),
                force=pending.get("force", False),
                sync=pending.get("sync", False),
                visited=pending.get("visited"),
            )
            
    except Exception as e:
        utils.error_print(f"Seamless Polling Error: {e}")
        return 0.2

    return 0.01



def make_variable_box_mesh(tw, th, bw, bh, h, deflection):
    verts = [
        -bw, -bh, 0.0,
         bw, -bh, 0.0,
         bw,  bh, 0.0,
        -bw,  bh, 0.0,
        -tw, -th, h,
         tw, -th, h,
         tw,  th, h,
        -tw,  th, h
    ]
    tris = [
        0, 2, 1,   0, 3, 2,
        4, 5, 6,   4, 6, 7,
        0, 1, 5,   0, 5, 4,
        1, 2, 6,   1, 6, 5,
        2, 3, 7,   2, 7, 6,
        3, 0, 4,   3, 4, 7
    ]
    return verts, tris

def solve_sketch(points_list, constraints_list):
    req_dict = {
        "action": "solve_sketch",
        "points": points_list,
        "constraints": constraints_list
    }
    
    start_server()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(10.0)
        s.connect((_SERVER_HOST, _SERVER_PORT))

        # Binary payload injection
        if req_dict.get('action') == 'update' and 'binary_payload' in req_dict:
            b_payload = req_dict.pop('binary_payload')
            msg_json = json.dumps(req_dict).encode('utf-8')
            msg = struct.pack('<I', len(msg_json)) + msg_json + b_payload
            s.sendall(struct.pack('<I', len(msg)) + msg)
        else:
            msg = json.dumps(req_dict).encode('utf-8')
            s.sendall(struct.pack('<I', len(msg)) + msg)


        status = s.recv(1)
        if not status:
            return None

        if status[0] == 1:
            len_bytes = s.recv(4)
            res_len = struct.unpack('<I', len_bytes)[0]

            data = bytearray(res_len)
            view = memoryview(data)
            n = res_len
            while n > 0:
                n_recv = s.recv_into(view, n)
                if n_recv == 0: break
                view = view[n_recv:]
                n -= n_recv

            res_json = data.decode('utf-8')
            s.close()
            utils.debug_print(f"DEBUG CORE_BRIDGE: solve_sketch success, json={res_json}")
            return json.loads(res_json)
        else:
            err_len_bytes = s.recv(4)
            err_len = struct.unpack('<I', err_len_bytes)[0]
            err_msg = s.recv(err_len).decode('utf-8')
            s.close()
            utils.error_print(f"DEBUG CORE_BRIDGE: GCS Solver Error: {err_msg}")
            return None
    except Exception as e:
        utils.error_print(f"DEBUG CORE_BRIDGE: Socket communication error in solve_sketch: {e}")
        return None

def render_viewport(width: int, height: int, vp_list: list):
    req = {
        "action": "render_viewport",
        "width": int(width),
        "height": int(height),
        "view_proj": [float(v) for v in vp_list],
    }
    return send_and_receive(req)

def render_viewport_sdf(width: int, height: int, vp_list: list, inv_vp_list: list, camera_pos: list, fillet_radius: float, box_size: list):
    req = {
        "action": "render_viewport_sdf",
        "width": int(width),
        "height": int(height),
        "view_proj": [float(v) for v in vp_list],
        "inv_view_proj": [float(v) for v in inv_vp_list],
        "camera_pos": [float(v) for v in camera_pos],
        "fillet_radius": float(fillet_radius),
        "box_size": [float(v) for v in box_size],
    }
    return send_and_receive(req)

def _recv_exact(s, n):
    data = bytearray(n)
    view = memoryview(data)
    while n > 0:
        got = s.recv_into(view, n)
        if got == 0:
            return None
        view = view[got:]
        n -= got
    return data

def csg_preview_begin(stack_ptr, tool_index, tool_uuid, op="SUB", deflection=0.2, angular_deflection=0.7):
    """Start an interactive CSG preview: Rust tessellates the base (result before
    the tool) + the tool once, then each frame runs the pure-Rust BSP boolean of
    `op` (SUB/ADD/INT) off the OCC edit path. Returns True on success; False means
    the caller should fall back to the frozen display."""
    start_server()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5.0)
        s.connect((_SERVER_HOST, _SERVER_PORT))
        req = {
            "action": "csg_preview_begin", "stack_ptr": int(stack_ptr),
            "tool_index": int(tool_index), "tool_uuid": str(tool_uuid),
            "op": str(op).upper(),
            "deflection": float(deflection), "angular_deflection": float(angular_deflection),
        }
        msg = json.dumps(req).encode('utf-8')
        s.sendall(struct.pack('<I', len(msg)) + msg)
        status = s.recv(1)
        s.close()
        return bool(status and status[0] == 1)
    except Exception:
        return False

def csg_preview_update(stack_ptr, transform_16, feature_angle=20.0, include_ghost=False):
    """Send the tool's current drag transform (row-major 16 floats); returns
    (points, counts) numpy arrays of feature edges, or None.
    V8.1.5: when include_ghost=True, also requests the removed/added ghost
    volume (verts+tris) and returns (points, counts, ghost_verts, ghost_tris);
    ghost_verts/ghost_tris are None if the server didn't include them
    (old server build, or op not supported for ghosting, e.g. INT)."""
    start_server()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect((_SERVER_HOST, _SERVER_PORT))
        req = {
            "action": "csg_preview_update", "stack_ptr": int(stack_ptr),
            "transform": [float(v) for v in transform_16], "feature_angle": float(feature_angle),
            "include_ghost": bool(include_ghost),
        }
        msg = json.dumps(req).encode('utf-8')
        s.sendall(struct.pack('<I', len(msg)) + msg)
        status = s.recv(1)
        if not status or status[0] != 1:
            s.close()
            return None
        hdr = _recv_exact(s, 8)
        if hdr is None:
            s.close()
            return None
        p_len, c_len = struct.unpack('<II', hdr)
        pb = _recv_exact(s, p_len)
        cb = _recv_exact(s, c_len)
        ghost_verts = None
        ghost_tris = None
        if include_ghost:
            # サーバーが古い場合はこのブロックが来ないため、防御的に読む。
            ghost_hdr = _recv_exact(s, 8)
            if ghost_hdr is not None:
                gv_len, gt_len = struct.unpack('<II', ghost_hdr)
                gvb = _recv_exact(s, gv_len) if gv_len > 0 else b''
                gtb = _recv_exact(s, gt_len) if gt_len > 0 else b''
                if gvb is not None and gtb is not None:
                    import numpy as np
                    if len(gvb) > 0:
                        ghost_verts = np.frombuffer(gvb, dtype=np.float32)
                    if len(gtb) > 0:
                        ghost_tris = np.frombuffer(gtb, dtype=np.int32)
        s.close()
        if pb is None or cb is None:
            return None
        import numpy as np
        points = np.frombuffer(pb, dtype=np.float32)
        counts = np.frombuffer(cb, dtype=np.int32)
        if include_ghost:
            return points, counts, ghost_verts, ghost_tris
        return (points, counts)
    except Exception:
        return None

def csg_preview_end(stack_ptr):
    """Clear the Rust-side preview state for this stack."""
    start_server()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5.0)
        s.connect((_SERVER_HOST, _SERVER_PORT))
        req = {"action": "csg_preview_end", "stack_ptr": int(stack_ptr)}
        msg = json.dumps(req).encode('utf-8')
        s.sendall(struct.pack('<I', len(msg)) + msg)
        status = s.recv(1)
        s.close()
        return bool(status and status[0] == 1)
    except Exception:
        return False

def get_core():
    import sys
    return sys.modules[__name__]
