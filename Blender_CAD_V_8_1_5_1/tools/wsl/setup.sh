#!/usr/bin/env bash
# WSL (Ubuntu) を、この addon の Linux 検証ができる状態にする。一度だけ実行する。
#
#     bash /mnt/e/blender_addon/Blender_CAD/Blender_CAD_V_8_1_5_1/tools/wsl/setup.sh
#
# 入れるものは2種類だけ:
#   1. カーネル(cad_server)を動かすのに要るもの
#   2. Blender をヘッドレスで動かすのに要る X/GL 系の共有ライブラリ
#      (--background でも Blender はこれらをリンクしており、欠けると起動しない)
#
# OCCT や TBB は**入れない**。配布 ZIP が自前で同梱しており、システム側に
# 別版が入っていると「利用者の環境では動かないのに手元では動く」という、
# 一番避けたい食い違いを作るため。ldd で $ORIGIN 側を掴んでいることを
# verify_linux_build.sh が確認する。
set -euo pipefail

echo "[setup] apt update"
sudo apt-get update -qq

echo "[setup] installing packages"
sudo apt-get install -y -qq \
    unzip python3 \
    libx11-6 libxi6 libxxf86vm1 libxfixes3 libxrender1 libsm6 libice6 \
    libgl1 libegl1 libxkbcommon0 \
    file binutils

echo "[setup] done"
echo
echo "next:"
echo "  bash tools/wsl/verify_linux_build.sh <path to CAD_*_install_LINUX.zip>"
