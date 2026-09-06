#!/usr/bin/env bash
# 配布用の Linux ZIP を、手元の WSL で実際に動かして確かめる。
#
#     bash tools/wsl/verify_linux_build.sh <zip>
#     bash tools/wsl/verify_linux_build.sh <zip> --blender /path/to/blender
#     bash tools/wsl/verify_linux_build.sh <zip> --download-blender [version]
#
# CI がやっているのと同じ再生テストを、30分待たずに数秒で回すためのもの。
# CI との違いは、**配布する ZIP そのもの**を展開して動かす点。CI はビルド
# ツリーのカーネルを叩くので、ZIP に詰める過程で壊れた場合を見られない
# (libs/svgpathtools が10版にわたって脱落していた事故は、まさにそこで起きた)。
#
# Blender を渡すと、回帰テスト52件を**Linux のカーネルで**回す。これは
# 2026-09-06 時点で一度も実施していない (CROSS_PLATFORM_BUILD.md §8)。
#
# 終了コード 0 = 全部通った / 1 = どれかで落ちた / 2 = 段取りの失敗
set -euo pipefail

ZIP=""
BLENDER=""
BLENDER_VERSION=""
DOWNLOAD=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --blender)
            BLENDER=${2:-}; shift 2 ;;
        --download-blender)
            DOWNLOAD=1
            # 次の引数が版番号らしければ拾う。無ければ既定値。
            if [[ ${2:-} =~ ^[0-9]+\.[0-9]+(\.[0-9]+)?$ ]]; then
                BLENDER_VERSION=$2; shift 2
            else
                shift
            fi ;;
        -h|--help)
            sed -n '2,16p' "$0"; exit 0 ;;
        -*)
            echo "unknown option: $1" >&2; exit 2 ;;
        *)
            if [[ -z "$ZIP" ]]; then ZIP=$1
            # 旧い呼び方 (第2引数に Blender のパス) も受ける
            elif [[ -z "$BLENDER" ]]; then BLENDER=$1
            else echo "unexpected argument: $1" >&2; exit 2
            fi
            shift ;;
    esac
done

if [[ -z "$ZIP" ]]; then
    echo "usage: verify_linux_build.sh <CAD_*_install_LINUX.zip> [--blender <path> | --download-blender [version]]" >&2
    exit 2
fi
[[ -f "$ZIP" ]] || { echo "no such zip: $ZIP" >&2; exit 2; }

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
TOOLS=$(dirname "$HERE")

# --- Blender の取得 --------------------------------------------------------
#
# blender.org の公式アーカイブからしか取らない。**必ず sha256 を照合する**:
# 検証用に落としたものを検証せずに使うのでは意味が無いし、後で「Blender が
# 壊れていたのか、こちらのカーネルが壊れていたのか」を切り分けられなくなる。
#
# 既定は 5.2 系。報告が来ているのがこの系列で、手元の Windows (Steam 5.1.2)
# とは別に「利用者と同じ Blender」で確かめられることに意味がある。
BLENDER_MIRROR=https://download.blender.org/release
CACHE=${XDG_CACHE_HOME:-$HOME/.cache}/seamless-cad/blender

download_blender() {
    local ver=$1 series
    if [[ ! $ver =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        # 系列だけ指定された場合、その中の最新パッチを選ぶ
        series=$ver
        echo "[blender] resolving the newest $series release" >&2
        ver=$(curl -fsSL --max-time 60 "$BLENDER_MIRROR/Blender$series/" \
              | grep -oE "blender-${series//./\.}\.[0-9]+-linux-x64\.tar\.xz" \
              | sed -E 's/blender-([0-9.]+)-linux-x64\.tar\.xz/\1/' \
              | sort -V | tail -1)
        [[ -n "$ver" ]] || { echo "[blender] no linux build found for $series" >&2; return 2; }
    fi
    series=${ver%.*}

    local tarball="blender-${ver}-linux-x64.tar.xz"
    local url="$BLENDER_MIRROR/Blender${series}/${tarball}"
    local dest="$CACHE/$tarball"
    local root="$CACHE/blender-${ver}-linux-x64"

    if [[ -x "$root/blender" ]]; then
        echo "[blender] using the cached $ver at $root" >&2
        echo "$root/blender"
        return 0
    fi

    mkdir -p "$CACHE"
    if [[ ! -f "$dest" ]]; then
        echo "[blender] downloading $url" >&2
        echo "[blender] (about 300 MB, cached in $CACHE for next time)" >&2
        curl -fSL --max-time 1800 -o "$dest.part" "$url"
        mv "$dest.part" "$dest"
    fi

    # blender-<ver>.sha256 はその版の全ファイル分の一覧。自分の行だけ照合する。
    echo "[blender] verifying sha256" >&2
    local sums="$CACHE/blender-${ver}.sha256"
    curl -fsSL --max-time 120 -o "$sums" "$BLENDER_MIRROR/Blender${series}/blender-${ver}.sha256"
    local want
    want=$(awk -v f="$tarball" '$2 == f || $2 == "*"f {print $1}' "$sums" | head -1)
    [[ -n "$want" ]] || { echo "[blender] $tarball is not listed in the checksum file" >&2; return 2; }
    local got
    got=$(sha256sum "$dest" | cut -d' ' -f1)
    if [[ "$want" != "$got" ]]; then
        echo "[blender] SHA-256 MISMATCH" >&2
        echo "[blender]   expected $want" >&2
        echo "[blender]   got      $got" >&2
        rm -f "$dest"
        return 1
    fi
    echo "[blender] sha256 ok" >&2

    echo "[blender] extracting" >&2
    tar -xJf "$dest" -C "$CACHE"
    [[ -x "$root/blender" ]] || { echo "[blender] no blender binary under $root" >&2; return 2; }
    echo "$root/blender"
}

if [[ $DOWNLOAD -eq 1 ]]; then
    [[ -n "$BLENDER" ]] && { echo "--blender and --download-blender are mutually exclusive" >&2; exit 2; }
    BLENDER=$(download_blender "${BLENDER_VERSION:-5.2}")
fi
if [[ -n "$BLENDER" && ! -x "$BLENDER" ]]; then
    echo "not executable: $BLENDER" >&2
    exit 2
fi

# --- ZIP の検証 ------------------------------------------------------------
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

# PREFLIGHT と同じ主眼: 同梱ライブラリが実際に入っているか。
for lib in svgpathtools svgwrite; do
    [[ -d "$ADDON/libs/$lib" ]] || { echo "[verify] FAIL libs/$lib is missing from the zip"; exit 1; }
done
echo "[verify] libs/svgpathtools and libs/svgwrite present"

echo "[verify] replaying the recorded Face Inset sweep"
python3 "$TOOLS/replay_kernel_requests.py" "$KERNEL"

if [[ -n "$BLENDER" ]]; then
    echo "[verify] regression suite against this build ($("$BLENDER" --version | head -1))"
    RUN="$WORK/run"
    mkdir -p "$RUN"
    cp -r "$ADDON" "$RUN/"
    cp "$TOOLS/../regression_test.py" "$RUN/"
    # 落ちても後片付けを済ませたいので、失敗を握って自分で報告する。
    if "$BLENDER" --background --factory-startup --python "$RUN/regression_test.py"; then
        echo "[verify] regression suite passed on the Linux kernel"
    else
        echo "[verify] FAIL the regression suite failed on the Linux kernel"
        exit 1
    fi
fi

echo "[verify] PASS"
