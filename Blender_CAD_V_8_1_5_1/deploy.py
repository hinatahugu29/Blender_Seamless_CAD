import shutil
import os

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

src_dll = os.path.join(TARGET, "seamless_core.dll")
src_exe = os.path.join(TARGET, "cad_server.exe")

dst_pyd = os.path.join(CAD_DIR, "seamless_core.pyd")
dst_dll = os.path.join(CAD_DIR, "seamless_core.dll")
dst_exe = os.path.join(CAD_DIR, "cad_server.exe")

try:
    print(f"Copying binaries into {CAD_DIR_NAME} ...")
    # seamless_core.dll is only rebuilt/copied when it exists (the addon runs the
    # geometry kernel via cad_server.exe over TCP; the .pyd/.dll are kept for
    # parity with previous deploys). cad_server.exe is the one that must update.
    if os.path.exists(src_dll):
        shutil.copy2(src_dll, dst_pyd)
        shutil.copy2(src_dll, dst_dll)
    shutil.copy2(src_exe, dst_exe)

    print(f"Zipping {CAD_DIR_NAME} ...")
    zip_path = os.path.join(ROOT, CAD_DIR_NAME)  # shutil.make_archive adds .zip
    shutil.make_archive(zip_path, 'zip', root_dir=ROOT, base_dir=CAD_DIR_NAME)

    print("Deployment successful! Zip created.")
except Exception as e:
    print(f"Error deploying: {e}")
