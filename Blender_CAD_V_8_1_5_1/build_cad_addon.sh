#!/bin/bash
# Blender_CAD 幾何カーネル(cad_server)の macOS / Linux ビルド & 梱包スクリプト。
#
# 前提: OCCT 8.0.0 が conda-forge から入っていること。
#   micromamba create -y -p ./occt-env -c conda-forge 'occt=8.0.0=*novtk*'
#   export OCCT_ROOT="$PWD/occt-env"
#
# 公式 dev.opencascade.org のプリビルドは Windows 専用なので使えない。
# Ubuntu の apt が持つ OCCT (7.5 / 7.6) は TKDESTEP が無いのでリンクできない。

set -euo pipefail
cd "$(dirname "$0")"

CAD_DIR="CAD_8_1_5_1"

case "$(uname)" in
    Darwin) TARGET_OS="darwin"; LIB_EXT="dylib" ;;
    Linux)  TARGET_OS="linux";  LIB_EXT="so" ;;
    *) echo "unsupported platform: $(uname)" >&2; exit 1 ;;
esac

if [ -z "${OCCT_ROOT:-}" ]; then
    echo "ERROR: OCCT_ROOT is not set. Point it at a conda-forge occt 8.0.0 prefix." >&2
    exit 1
fi
echo "--- target=$TARGET_OS  OCCT_ROOT=$OCCT_ROOT ---"

# --- 1. ビルド ---------------------------------------------------------------
# リンカに OCCT を見せる。LIBRARY_PATH は「リンク時」だけに効くので安全。
#
# ここで DYLD_LIBRARY_PATH / LD_LIBRARY_PATH を設定してはいけない。
# あれは「実行時」の探索パスで、この後に起動する cargo や git にも継承される。
# conda 環境の libcurl / libssl / libiconv がシステムのものを上書きし、
# cargo が起動直後に `dyld: missing symbol called` で abort する
# (実際に macOS の CI がこれで落ちた)。
export LIBRARY_PATH="$OCCT_ROOT/lib:${LIBRARY_PATH:-}"

(cd src_rust && cargo build --release --bin cad_server)

# --- 2. 配置 -----------------------------------------------------------------
# core_bridge.py はアドオン直下と bin/ の両方を探す。bin/ に置く。
mkdir -p "$CAD_DIR/bin"
cp -f src_rust/target/release/cad_server "$CAD_DIR/bin/cad_server"
chmod 755 "$CAD_DIR/bin/cad_server"

# OCCT ランタイムを同梱する。build.rs が rpath を @loader_path / $ORIGIN に
# 設定しているので、実行ファイルの隣に置けば解決される。
for lib in "$OCCT_ROOT"/lib/libTK*."$LIB_EXT"*; do
    [ -e "$lib" ] || continue
    cp -f "$lib" "$CAD_DIR/bin/"
done

if [ "$TARGET_OS" = "darwin" ]; then
    # conda-forge の dylib は install_name に絶対パスを持っている。
    # そのままだとユーザー環境で dyld が解決できないので @rpath 基準に直す。
    for lib in "$CAD_DIR"/bin/libTK*.dylib; do
        [ -e "$lib" ] || continue
        install_name_tool -id "@rpath/$(basename "$lib")" "$lib" 2>/dev/null || true
    done
    echo "--- otool -L cad_server (絶対パスが残っていないか確認) ---"
    otool -L "$CAD_DIR/bin/cad_server" | head -30
else
    echo "--- ldd cad_server (not found が無いか確認) ---"
    ldd "$CAD_DIR/bin/cad_server" | head -30
fi

# --- 3. 梱包 -----------------------------------------------------------------
# package_addon.py の PREFLIGHT をそのまま通す。実行権限は ZipInfo で明示される。
SEAMLESS_TARGET_OS="$TARGET_OS" python3 package_addon.py

echo "--- done ---"
ls -la ./*.zip
