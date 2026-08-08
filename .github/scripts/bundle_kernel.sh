#!/usr/bin/env bash
#
# 幾何カーネルと、それが必要とする OCCT の共有ライブラリをアドオン
# ディレクトリへ集める。Windows が DLL をアドオン直下に置いているのと同じ配置で、
# build.rs が rpath に $ORIGIN / @loader_path を入れてあるので隣に置けば見つかる。
#
# 使い方: bundle_kernel.sh <アドオンディレクトリ> <ビルド済み cad_server> <OCCT prefix>
#
# macOS ランナーの /bin/bash は 3.2 なので、配列や連想配列に頼らない。
# 依存を辿るのに worklist ではなく「増えなくなるまで走査を繰り返す」形にしてある
# のはそのため。

set -euo pipefail

cad="$1"
bin="$2"
prefix="$3"

cp "$bin" "$cad/cad_server"
chmod +x "$cad/cad_server"

case "$(uname -s)" in
Linux)
  # ldd はバイナリの rpath($ORIGIN = コピー先)を見る。コピー先はまだ空なので
  # 素で実行すると全部 "not found" になり、パスが1つも取れない。探索先を
  # OCCT の prefix に向けて解決させる。
  export LD_LIBRARY_PATH="$prefix/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

  for pass in 1 2 3 4 5 6; do
    before=$(find "$cad" -maxdepth 1 -name '*.so*' | wc -l)
    for f in "$cad/cad_server" "$cad"/*.so*; do
      [ -f "$f" ] || continue
      # 何も一致しないのは普通にあること(システムライブラリだけの層)。
      # pipefail 下で grep の 1 がステップ全体を落とさないよう握り潰す。
      ldd "$f" | awk '{print $3}' | grep -F "$prefix/" | sort -u > /tmp/deps.txt || true
      while read -r dep; do
        [ -n "$dep" ] || continue
        base=$(basename "$dep")
        [ -e "$cad/$base" ] && continue
        cp -L "$dep" "$cad/$base"
      done < /tmp/deps.txt
    done
    after=$(find "$cad" -maxdepth 1 -name '*.so*' | wc -l)
    [ "$before" = "$after" ] && break
  done
  ;;

Darwin)
  # OCCT は install name を @rpath/libTK*.dylib の形で持つ。書き換えないと
  # 実行時に自分の rpath 頼みになるので、参照を @loader_path に付け替える。
  resolve() {
    case "$1" in
      @rpath/*)   echo "$prefix/lib/${1#@rpath/}" ;;
      "$prefix"/*) echo "$1" ;;
      *)          echo "" ;;   # /usr/lib などシステム側は同梱しない
    esac
  }

  for pass in 1 2 3 4 5 6; do
    before=$(find "$cad" -maxdepth 1 -name '*.dylib' | wc -l)
    for f in "$cad/cad_server" "$cad"/*.dylib; do
      [ -f "$f" ] || continue
      chmod u+w "$f"
      otool -L "$f" | tail -n +2 | awk '{print $1}' | sort -u > /tmp/deps.txt
      while read -r dep; do
        [ -n "$dep" ] || continue
        src=$(resolve "$dep")
        [ -n "$src" ] || continue
        [ -f "$src" ] || continue
        base=$(basename "$src")
        if [ ! -e "$cad/$base" ]; then
          cp -L "$src" "$cad/$base"
          chmod u+w "$cad/$base"
          install_name_tool -id "@loader_path/$base" "$cad/$base"
        fi
        install_name_tool -change "$dep" "@loader_path/$base" "$f"
      done < /tmp/deps.txt
    done
    after=$(find "$cad" -maxdepth 1 -name '*.dylib' | wc -l)
    [ "$before" = "$after" ] && break
  done

  # install_name_tool はバイナリを書き換えるので、付いていた ad-hoc 署名が
  # 無効になる。Apple Silicon は署名の壊れた実行ファイルを起動時に SIGKILL
  # するため、ここで署名し直さないと「何も言わずに落ちる」形で失敗する。
  for f in "$cad/cad_server" "$cad"/*.dylib; do
    [ -f "$f" ] || continue
    codesign --force --sign - "$f"
  done
  ;;

*)
  echo "::error::unsupported platform: $(uname -s)"
  exit 1
  ;;
esac

# 1つも拾えていないのに成功扱いで先へ進むのが一番まずい。同梱漏れは
# 実行するまで表に出ないので、ここで積極的に確かめる。
if ! ls "$cad" | grep -q '^libTKernel'; then
  echo "::error::no OCCT libraries were bundled into $cad"
  echo "--- contents ---"
  ls -la "$cad"
  exit 1
fi

echo "--- bundled ---"
ls -la "$cad" | grep -E 'cad_server|\.so|\.dylib'
count=$(ls "$cad" | grep -cE '\.so|\.dylib')
echo "$count shared libraries bundled"
