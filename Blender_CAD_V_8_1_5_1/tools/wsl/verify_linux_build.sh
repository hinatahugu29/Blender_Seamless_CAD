#!/usr/bin/env bash
# 配布用の Linux ZIP を、手元の WSL で実際に動かして確かめる。
#
#     bash tools/wsl/verify_linux_build.sh ../../MAC_LINUX/CAD_8.1.5.11_install_LINUX.zip
#     bash tools/wsl/verify_linux_build.sh <zip> /path/to/blender   # 回帰テストも回す
#
# CI がやっているのと同じ再生テストを、30分待たずに数秒で回すためのもの。
# CI との違いは、**配布する ZIP そのもの**を展開して動かす点。CI はビルド
# ツリーのカーネルを叩くので、ZIP に詰める過程で壊れた場合を見られない
# (libs/svgpathtools が10版にわたって脱落していた事故は、まさにそこで起きた)。
#
# 終了コード 0 = 全部通った / 1 = どれかで落ちた
set -euo pipefail

ZIP=${1:-}
BLENDER=${2:-}
if [[ -z "$ZIP" ]]; then
    echo "usage: verify_linux_build.sh <CAD_*_install_LINUX.zip> [path to blender]" >&2
    exit 2
fi
if [[ ! -f "$ZIP" ]]; then
    echo "no such zip: $ZIP" >&2
    exit 2
fi

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
TOOLS=$(dirname "$HERE")
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

echo "[verify] unpacking $(basename "$ZIP")"
unzip -q "$ZIP" -d "$WORK"
ADDON="$WORK/CAD_8_1_5_1"
KERNEL="$ADDON/cad_server"
[[ -f "$KERNEL" ]] || { echo "[verify] FAIL no cad_server in the zip"; exit 1; }
chmod +x "$KERNEL"

echo "[verify] bl_info: $(grep -m1 '"version"' "$ADDON/__init__.py" | tr -d ' ')"
echo "[verify] kernel : $(stat -c %s "$KERNEL") bytes"

# 同梱ライブラリだけで立つことを見る。LD_LIBRARY_PATH は**わざと設定しない**。
# 設定して確かめると、システム側に同じ .so がある開発機でだけ通り、利用者の
# 環境で落ちる。CROSS_PLATFORM_BUILD.md の「DT_RUNPATH は推移しない」参照。
echo "[verify] ldd (unresolved libraries would show as 'not found')"
if ldd "$KERNEL" | grep -q "not found"; then
    ldd "$KERNEL" | grep "not found"
    echo "[verify] FAIL the bundled libraries do not satisfy the kernel"
    exit 1
fi
echo "[verify]   all resolved"

# PREFLIGHT と同じ主眼: 同梱 Python ライブラリが実際に import できるか。
for lib in svgpathtools svgwrite; do
    [[ -d "$ADDON/libs/$lib" ]] || { echo "[verify] FAIL libs/$lib is missing from the zip"; exit 1; }
done
echo "[verify] libs/svgpathtools and libs/svgwrite present"

echo "[verify] replaying the recorded Face Inset sweep"
python3 "$TOOLS/replay_kernel_requests.py" "$KERNEL"

if [[ -n "$BLENDER" ]]; then
    # 回帰テスト52件は、これまで Windows のカーネルでしか回していない。
    # ここを通せば「Linux のカーネルで形状が正しいか」に初めて答えが出る。
    echo "[verify] running the headless regression suite against this build"
    RUN="$WORK/run"
    mkdir -p "$RUN"
    cp -r "$ADDON" "$RUN/"
    cp "$TOOLS/../regression_test.py" "$RUN/"
    "$BLENDER" --background --factory-startup --python "$RUN/regression_test.py"
fi

echo "[verify] PASS"
