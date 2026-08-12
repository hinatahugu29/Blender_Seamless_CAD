import shutil
import os
import sys

# 配るのは cad_server だけ。実行ファイル名は OS ごとに違う。
if sys.platform == "win32":
    KERNEL_NAME = "cad_server.exe"
else:
    KERNEL_NAME = "cad_server"

# Paths are derived from this script's location so the deploy step doesn't rot
# when the version folder is renamed/copied (previous versions hard-coded the
# absolute V8.1.3.3 debug paths).
ROOT = os.path.dirname(os.path.abspath(__file__))          # Blender_CAD_V_8_1_3_7
CAD_DIR_NAME = next(
    (d for d in os.listdir(ROOT) if d.startswith("CAD_") and os.path.isdir(os.path.join(ROOT, d))),
    "CAD_8_1_4",
)
CAD_DIR = os.path.join(ROOT, CAD_DIR_NAME)
TARGET = os.path.join(ROOT, "src_rust", "target", "release")  # release build

src_exe = os.path.join(TARGET, KERNEL_NAME)

dst_exe = os.path.join(CAD_DIR, KERNEL_NAME)

try:
    print(f"Copying binaries into {CAD_DIR_NAME} ...")
    # cad_server だけを配る。
    #
    # 以前は seamless_core を .dll と .pyd の2つの名前でも置いていたが、
    # V7.0.0 でカーネルが別プロセスになって以来、Python 側はネイティブ
    # コードを一切 import していない(`CAD_8_1_5_1` 以下を再帰 grep しても
    # seamless_core の参照は1件も無い)。"parity with previous deploys" と
    # いう理由だけで、同一内容のファイルが2つ、毎回配布物に入っていた。
    shutil.copy2(src_exe, dst_exe)
    if sys.platform != "win32":
        os.chmod(dst_exe, os.stat(dst_exe).st_mode | 0o111)

    print(f"Zipping {CAD_DIR_NAME} ...")
    zip_path = os.path.join(ROOT, CAD_DIR_NAME)  # shutil.make_archive adds .zip
    shutil.make_archive(zip_path, 'zip', root_dir=ROOT, base_dir=CAD_DIR_NAME)

    print("Deployment successful! Zip created.")
except Exception as e:
    print(f"Error deploying: {e}")
