import shutil
import os
import sys

# 実行ファイル名と共有ライブラリ名は OS ごとに違う。cad_server が本命で、
# seamless_core は過去のデプロイとの互換で置いているだけ(アドオンは import しない)。
if sys.platform == "win32":
    KERNEL_NAME = "cad_server.exe"
    CORE_LIB_NAME = "seamless_core.dll"
elif sys.platform == "darwin":
    KERNEL_NAME = "cad_server"
    CORE_LIB_NAME = "libseamless_core.dylib"
else:
    KERNEL_NAME = "cad_server"
    CORE_LIB_NAME = "libseamless_core.so"

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

src_lib = os.path.join(TARGET, CORE_LIB_NAME)
src_exe = os.path.join(TARGET, KERNEL_NAME)

dst_pyd = os.path.join(CAD_DIR, "seamless_core.pyd")
dst_lib = os.path.join(CAD_DIR, CORE_LIB_NAME)
dst_exe = os.path.join(CAD_DIR, KERNEL_NAME)

try:
    print(f"Copying binaries into {CAD_DIR_NAME} ...")
    # The core lib is only rebuilt/copied when it exists (the addon runs the
    # geometry kernel via cad_server over TCP; the .pyd/.dll are kept for
    # parity with previous deploys). cad_server is the one that must update.
    if os.path.exists(src_lib):
        if sys.platform == "win32":
            shutil.copy2(src_lib, dst_pyd)
        shutil.copy2(src_lib, dst_lib)
    shutil.copy2(src_exe, dst_exe)
    if sys.platform != "win32":
        os.chmod(dst_exe, os.stat(dst_exe).st_mode | 0o111)

    print(f"Zipping {CAD_DIR_NAME} ...")
    zip_path = os.path.join(ROOT, CAD_DIR_NAME)  # shutil.make_archive adds .zip
    shutil.make_archive(zip_path, 'zip', root_dir=ROOT, base_dir=CAD_DIR_NAME)

    print("Deployment successful! Zip created.")
except Exception as e:
    print(f"Error deploying: {e}")
