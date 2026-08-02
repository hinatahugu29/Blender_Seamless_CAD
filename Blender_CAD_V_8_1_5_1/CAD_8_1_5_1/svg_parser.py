# SPDX-License-Identifier: GPL-2.0-or-later
#
# Copyright (C) 2026 hinata_hugu
#
# This file is part of Seamless CAD.
#
# Seamless CAD is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation; either version 2 of the License, or (at your
# option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, see <https://www.gnu.org/licenses/>.

import os
import sys
import math

try:
    from . import vendor_libs
except ImportError:
    # `python svg_parser.py foo.svg` のような単体実行用フォールバック
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import vendor_libs

vendor_libs.ensure_on_path()

try:
    from svgpathtools import Document
except ImportError as e:
    Document = None
    _DOCUMENT_IMPORT_ERROR = e
else:
    _DOCUMENT_IMPORT_ERROR = None

def parse_svg_to_flat_array(filepath):
    """
    SVGのパスを抽出し、C++へ渡しやすいフラットな数値配列に変換する。
    フォーマット:
    [
      総パス数,
      [パス1の要素数],
        [セグメント1タイプ, パラメータ...],
        [セグメント2タイプ, パラメータ...],
      [パス2の要素数],
        ...
    ]
    タイプ定義:
      0: Line (x1, y1, x2, y2) -> 長さ5
      1: CubicBezier (x1, y1, cx1, cy1, cx2, cy2, x2, y2) -> 長さ9
      2: QuadraticBezier (x1, y1, cx, cy, x2, y2) -> 長さ7
      3: Arc (x1, y1, rx, ry, rot_deg, large_arc, sweep, x2, y2) -> 長さ10
    """
    if Document is None:
        # ここに来るのは同梱の libs/svgpathtools (と依存の libs/svgwrite) が
        # 配布物から欠落している場合。原因を必ず添えて出す。
        print(
            "Seamless: SVG import unavailable - failed to import svgpathtools from "
            f"{vendor_libs.LIBS_DIR}: {_DOCUMENT_IMPORT_ERROR!r}"
        )
        return []
    
    try:
        doc = Document(filepath)
        paths = doc.paths()
    except Exception as e:
        print(f"Failed to parse SVG Document: {e}")
        return []

    flat_data = []
    
    # 最初に総パス数を記録
    flat_data.append(float(len(paths)))

    for path in paths:
        # このパスに含まれるサブパス（つながった線分の塊）の数を記録
        subpaths = path.continuous_subpaths()
        flat_data.append(float(len(subpaths)))
        
        for subpath in subpaths:
            # サブパス内のセグメント数を記録
            flat_data.append(float(len(subpath)))
            
            for segment in subpath:
                seg_type = type(segment).__name__
                if seg_type == 'Line':
                    flat_data.extend([0.0, segment.start.real, segment.start.imag, segment.end.real, segment.end.imag])
                elif seg_type == 'CubicBezier':
                    flat_data.extend([1.0, segment.start.real, segment.start.imag, 
                                      segment.control1.real, segment.control1.imag, 
                                      segment.control2.real, segment.control2.imag, 
                                      segment.end.real, segment.end.imag])
                elif seg_type == 'QuadraticBezier':
                    flat_data.extend([2.0, segment.start.real, segment.start.imag, 
                                      segment.control.real, segment.control.imag, 
                                      segment.end.real, segment.end.imag])
                elif seg_type == 'Arc':
                    flat_data.extend([3.0, segment.start.real, segment.start.imag, 
                                      segment.radius.real, segment.radius.imag, 
                                      segment.rotation, float(segment.large_arc), float(segment.sweep), 
                                      segment.end.real, segment.end.imag])
                else:
                    # 不明なセグメントはLineとして近似するなどのフォールバック（ここでは無視）
                    pass
                
    return flat_data

if __name__ == "__main__":
    if len(sys.argv) > 1:
        data = parse_svg_to_flat_array(sys.argv[1])
        print(data)
