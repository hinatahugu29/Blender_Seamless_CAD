"""同梱サードパーティ依存(libs/)を sys.path に載せるための唯一の入口。

bpy に依存しないので、Blender 内・スタンドアロン実行のどちらからも呼べる。

`sys.path.append` であって `insert(0, ...)` ではない点が重要:
libs/ には numpy が同梱されているが、Blender は自前の numpy を必ず同梱している。
先頭に挿すと同梱版が Blender の numpy を隠し、しかも sys.path はプロセス全体で
共有されるため他のアドオンまで巻き込む。末尾に足しておけば Blender 側が優先され、
libs/ は「Blender 側に無いもの(svgpathtools 等)だけ」のフォールバックとして働く。
"""

import os
import sys

LIBS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libs")


def ensure_on_path():
    """libs/ を sys.path の末尾に一度だけ追加する。何度呼んでも安全。"""
    if os.path.isdir(LIBS_DIR) and LIBS_DIR not in sys.path:
        sys.path.append(LIBS_DIR)
    return LIBS_DIR


# import 時点で通しておく。drawing.py などが `import numpy` するのは
# モジュールロード時であり register() より前なので、遅延させられない。
ensure_on_path()
