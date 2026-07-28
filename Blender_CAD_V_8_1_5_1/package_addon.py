"""配布用 ZIP を作る。

使い方:
    python package_addon.py            # CAD_<version>_install_<日付>.zip を作る
    python package_addon.py --out foo.zip

ZIP の中身は「CAD_8_1_5_1/ を丸ごと」で、Blender の
Edit > Preferences > Add-ons > Install... にそのまま渡せる形にする。

出荷前チェック(PREFLIGHT)を必ず通す。
8.1.2.5 でディレクトリコピー時に libs/svgpathtools と libs/svgwrite が脱落し、
SVG インポートが10バージョン以上にわたり無言で壊れていた。人間の目視では
その手の欠落は捕まらないので、必須ファイルの存在をここで機械的に検査する。
"""

import argparse
import datetime
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))

CAD_DIR_NAME = next(
    (d for d in sorted(os.listdir(ROOT))
     if d.startswith("CAD_") and os.path.isdir(os.path.join(ROOT, d))),
    None,
)

# ZIP に含めないもの
EXCLUDE_DIRS = {"__pycache__", ".git", ".vscode", "target"}
EXCLUDE_SUFFIXES = (".pyc", ".pyo", ".log", ".zip", ".bak", ".whl")

# これが無ければ出荷しない(パスは CAD ディレクトリ相対)
REQUIRED_PATHS = [
    "__init__.py",
    "core_bridge.py",
    "utils.py",
    "vendor_libs.py",
    "svg_parser.py",
    # SVG インポートの必須依存。svgpathtools/__init__.py は paths2svg を
    # 無条件 import し、それが svgwrite を要求するので両方必要。
    "libs/svgpathtools/__init__.py",
    "libs/svgwrite/__init__.py",
    # 幾何カーネル本体。無いとアドオンは起動するが何も計算できない。
    "cad_server.exe",
]


def read_bl_info_version(cad_dir):
    """bl_info の version を __init__.py から読む(import せずにテキスト解析)。"""
    init_py = os.path.join(cad_dir, "__init__.py")
    with open(init_py, encoding="utf-8") as f:
        text = f.read(4000)
    m = re.search(r'"version"\s*:\s*\(([^)]*)\)', text)
    if not m:
        return None
    return ".".join(part.strip() for part in m.group(1).split(","))


def preflight(cad_dir):
    problems = []

    for rel in REQUIRED_PATHS:
        if not os.path.exists(os.path.join(cad_dir, rel.replace("/", os.sep))):
            problems.append(f"missing required path: {rel}")

    # bl_info と core_bridge.get_version() の食い違いを防ぐ。
    # get_version() は bl_info から導出しているので、リテラルが残っていたら異常。
    core_bridge = os.path.join(cad_dir, "core_bridge.py")
    with open(core_bridge, encoding="utf-8") as f:
        cb = f.read()
    if re.search(r'def get_version\(\):\s*\n\s*return\s*"', cb):
        problems.append("core_bridge.get_version() returns a hardcoded string (must derive from bl_info)")

    # 文字化けコメントの再発検知(不可逆なので、混入したら元に戻せない)
    moji = ("郢", "邵ｺ", "繝ｻ")
    for dirpath, dirnames, filenames in os.walk(cad_dir):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS and d != "libs"]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
            if any(ch in text for ch in moji):
                rel = os.path.relpath(path, cad_dir)
                problems.append(f"mojibake (double-encoded) text in {rel}")

    return problems


def iter_files(cad_dir):
    for dirpath, dirnames, filenames in os.walk(cad_dir):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for name in filenames:
            if name.endswith(EXCLUDE_SUFFIXES):
                continue
            yield os.path.join(dirpath, name)


def main():
    if not CAD_DIR_NAME:
        print(f"ERROR: no CAD_* directory under {ROOT}", file=sys.stderr)
        return 1
    cad_dir = os.path.join(ROOT, CAD_DIR_NAME)

    version = read_bl_info_version(cad_dir) or "unknown"
    default_name = (
        f"{CAD_DIR_NAME}_install_"
        f"{datetime.date.today().strftime('%Y%m%d')}.zip"
    )

    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=os.path.join(ROOT, default_name))
    parser.add_argument("--skip-preflight", action="store_true",
                        help="出荷前チェックを飛ばす(デバッグ用。通常は使わない)")
    args = parser.parse_args()

    print(f"addon dir : {CAD_DIR_NAME}")
    print(f"bl_info   : {version}")

    problems = [] if args.skip_preflight else preflight(cad_dir)
    if problems:
        print("\nPREFLIGHT FAILED:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print("preflight : OK")

    files = sorted(iter_files(cad_dir))
    total = sum(os.path.getsize(f) for f in files)
    print(f"files     : {len(files)} ({total / 1024 / 1024:.1f} MB uncompressed)")
    print(f"writing   : {args.out}")

    with zipfile.ZipFile(args.out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in files:
            # ZIP 内のトップレベルは CAD_<version>/ にする
            arc = os.path.join(CAD_DIR_NAME, os.path.relpath(path, cad_dir))
            zf.write(path, arc.replace(os.sep, "/"))

    size = os.path.getsize(args.out)
    print(f"done      : {size / 1024 / 1024:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
