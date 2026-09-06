"""録音した update リクエストをカーネルへ再生し、生き残るかを見る。

Blender も Python の依存も要らない。**カーネル単体**を起動して、
tools/record_face_inset_sweep.py が Windows で録った本物のリクエストを
そのまま投げ直す。Linux の CI ランナーで走らせるためのもの。

    python3 tools/replay_kernel_requests.py CAD_8_1_5_1/cad_server

終了コード
    0  全部投げ終えてカーネルが生きている
    1  カーネルが途中で死んだ (これが 2026-09-05 の Fedora 報告の再現)
    2  段取りの失敗 (起動できない、create_stack が通らない等)

「落ちない」ことを確かめるのが目的なので、応答の中身は見ない。形が正しいか
どうかは Blender 側の回帰テストの担当。ここが見るのはプロセスの生死だけ。
"""
import json
import os
import socket
import struct
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "fixtures", "face_inset_sweep.json")
HOST, PORT = "127.0.0.1", 8080


def frame(req, payload=b""):
    body = json.dumps(req).encode("utf-8")
    if payload:
        inner = struct.pack("<I", len(body)) + body + payload
    else:
        inner = body
    return struct.pack("<I", len(inner)) + inner


def send(req, payload=b"", timeout=120.0):
    """1リクエスト投げて、接続が閉じるまで読み捨てる。

    応答を最後まで読むのは、こちらが先に切って相手に EPIPE を渡さないため。
    サーバーが死んだ場合はここで空が返る。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((HOST, PORT))
        s.sendall(frame(req, payload))
        chunks = []
        while True:
            b = s.recv(65536)
            if not b:
                break
            chunks.append(b)
        return b"".join(chunks)
    finally:
        s.close()


def main():
    if len(sys.argv) < 2:
        print("usage: replay_kernel_requests.py <path to cad_server>")
        return 2
    exe = os.path.abspath(sys.argv[1])
    if not os.path.exists(exe):
        print(f"[replay] no such kernel: {exe}")
        return 2
    os.chmod(exe, os.stat(exe).st_mode | 0o111)

    with open(FIXTURE, encoding="utf-8") as f:
        fixture = json.load(f)
    requests = fixture["requests"]
    print(f"[replay] {len(requests)} recorded requests, target face {fixture['target_face']}")

    proc = subprocess.Popen([exe], stdout=sys.stdout, stderr=subprocess.STDOUT)
    try:
        for _ in range(60):
            try:
                socket.create_connection((HOST, PORT), timeout=0.5).close()
                break
            except OSError:
                if proc.poll() is not None:
                    print(f"[replay] kernel exited during startup: {proc.returncode}")
                    return 2
                time.sleep(0.5)
        else:
            print("[replay] kernel never opened port 8080")
            return 2

        reply = send({"action": "create_stack"})
        if len(reply) < 9 or reply[0] != 1:
            print(f"[replay] create_stack failed: {reply[:16]!r}")
            return 2
        stack_ptr = struct.unpack("<q", reply[1:9])[0]
        print(f"[replay] stack_ptr={stack_ptr}")

        for entry in requests:
            req = dict(entry["request"])
            # 録音時とは別プロセスなので ptr は当然違う。ここだけ差し替える。
            req["stack_ptr"] = stack_ptr
            payload = bytes.fromhex(entry["binary_payload_hex"])
            label = entry["label"]
            print(f"[replay] {label} ...", flush=True)
            try:
                reply = send(req, payload)
            except OSError as e:
                print(f"[replay] FAIL {label}: socket error {e}")
                reply = b""
            if proc.poll() is not None:
                print(f"[replay] FAIL the kernel died on {label} (exit {proc.returncode})")
                print("[replay] this is the 2026-09-05 Fedora 44 Face Inset crash, "
                      "reproduced without the reporter's machine")
                return 1
            if not reply:
                print(f"[replay] {label}: empty reply but the kernel is alive "
                      "(the operation failed and was caught -- not a crash)")
            else:
                print(f"[replay] {label}: {len(reply)} bytes back, kernel alive")

        print("[replay] PASS every request replayed, kernel still alive")
        return 0
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    sys.exit(main())
