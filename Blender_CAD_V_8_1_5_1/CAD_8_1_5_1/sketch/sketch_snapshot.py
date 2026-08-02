import json
import uuid as uuid_mod
import mathutils
from . import sketch_globals

SNAPSHOT_VERSION = 1


def serialize_sketch_snapshot(props):
    """現在のスクラッチスケッチコレクション(points/lines/circles/arcs/constraints)+
    参照平面行列をJSON文字列にシリアライズする。finalize_sketch がスクラッチデータを
    clear() する直前に呼ぶこと。"""
    mat = sketch_globals._reference_matrix
    data = {
        "snapshot_version": SNAPSHOT_VERSION,
        "reference_matrix": [v for row in mat for v in row] if mat is not None else None,
        "points": [
            {"id": p.id, "co": [p.co[0], p.co[1]], "is_segment": p.is_segment}
            for p in props.sketch_points
        ],
        "lines": [
            {
                "id": l.id,
                "start_point_id": l.start_point_id,
                "end_point_id": l.end_point_id,
                "is_construction": l.is_construction,
            }
            for l in props.sketch_lines
        ],
        "circles": [
            {
                "id": c.id,
                "center_point_id": c.center_point_id,
                "radius_point_id": c.radius_point_id,
                "is_construction": c.is_construction,
            }
            for c in props.sketch_circles
        ],
        "arcs": [
            {
                "id": a.id,
                "center_point_id": a.center_point_id,
                "start_point_id": a.start_point_id,
                "end_point_id": a.end_point_id,
                "mid_point_id": a.mid_point_id,
                "is_construction": a.is_construction,
                "is_fillet": getattr(a, "is_fillet", False),
            }
            for a in props.sketch_arcs
        ],
        "constraints": [
            {
                "id": c.id,
                "type": c.type,
                "target_ids_str": c.target_ids_str,
                "value": c.value,
            }
            for c in props.sketch_constraints
        ],
    }
    return json.dumps(data)


def save_sketch_snapshot(props, sketch_uuid=None):
    """現在のスクラッチスケッチ状態を props.sketch_snapshots に保存する(既存の
    同一sketch_uuidエントリがあれば上書き、無ければ新規追加)。sketch_uuidを省略した場合は
    新規UUIDを発行する。保存に使ったsketch_uuidを返す。"""
    if not sketch_uuid:
        sketch_uuid = str(uuid_mod.uuid4())[:8]
    snapshot_json = serialize_sketch_snapshot(props)
    existing = next((s for s in props.sketch_snapshots if s.sketch_uuid == sketch_uuid), None)
    if existing:
        existing.snapshot_json = snapshot_json
    else:
        entry = props.sketch_snapshots.add()
        entry.sketch_uuid = sketch_uuid
        entry.snapshot_json = snapshot_json
    return sketch_uuid


def restore_sketch_snapshot(props, sketch_uuid):
    """props.sketch_snapshotsからsketch_uuidに対応するエントリを探し、その内容を
    スクラッチコレクション(sketch_points/lines/circles/arcs/constraints)と
    参照平面行列に復元する。成功すればTrue、見つからなければFalseを返す。"""
    entry = next((s for s in props.sketch_snapshots if s.sketch_uuid == sketch_uuid), None)
    if entry is None:
        return False
    try:
        data = json.loads(entry.snapshot_json)
    except (ValueError, TypeError):
        return False

    props.sketch_points.clear()
    for p in data.get("points", []):
        np = props.sketch_points.add()
        np.id = p["id"]
        np.co = tuple(p["co"])
        np.is_segment = p.get("is_segment", False)

    props.sketch_lines.clear()
    for l in data.get("lines", []):
        nl = props.sketch_lines.add()
        nl.id = l["id"]
        nl.start_point_id = l["start_point_id"]
        nl.end_point_id = l["end_point_id"]
        nl.is_construction = l.get("is_construction", False)

    props.sketch_circles.clear()
    for c in data.get("circles", []):
        nc = props.sketch_circles.add()
        nc.id = c["id"]
        nc.center_point_id = c["center_point_id"]
        nc.radius_point_id = c["radius_point_id"]
        nc.is_construction = c.get("is_construction", False)

    props.sketch_arcs.clear()
    for a in data.get("arcs", []):
        na = props.sketch_arcs.add()
        na.id = a["id"]
        na.center_point_id = a["center_point_id"]
        na.start_point_id = a["start_point_id"]
        na.end_point_id = a["end_point_id"]
        na.mid_point_id = a["mid_point_id"]
        na.is_construction = a.get("is_construction", False)
        na.is_fillet = a.get("is_fillet", False)

    props.sketch_constraints.clear()
    for c in data.get("constraints", []):
        nc = props.sketch_constraints.add()
        nc.id = c["id"]
        nc.type = c["type"]
        nc.target_ids_str = c["target_ids_str"]
        nc.value = c["value"]

    rm = data.get("reference_matrix")
    if rm and len(rm) == 16:
        sketch_globals._reference_matrix = mathutils.Matrix(
            (rm[0:4], rm[4:8], rm[8:12], rm[12:16])
        )
    else:
        sketch_globals._reference_matrix = None

    props.sketch_selected_point_id = -1
    props.sketch_selected_point_id_2 = -1
    props.sketch_selected_line_id = -1
    props.sketch_selected_line_id_2 = -1
    props.sketch_selected_points_str = ""

    return True


# V8.1.5バグ修正: finalize_sketchが再生成する際に「新しいジオメトリそのもの」を表す
# フィールド(座標・寸法など、finalize/add_standalone_arc_primitiveが都度計算し直すもの)。
# これらは新primitive側の値を優先し、旧primitiveの値で上書きしてはいけない。
# それ以外の全フィールド(operation, extrude_height, name 等ユーザーが個別調整した値)は
# 再編集後も引き継ぐ。
_SKETCH_REGEN_GEOMETRY_FIELDS = {
    'points', 'segments_json', 'location', 'rotation', 'fill_closed',
    'type', 'sketch_source_uuid', 'uuid', 'radius', 'angle_start', 'angle_end',
}


def _snapshot_primitive_user_fields(prim):
    """geometry系フィールドを除く、プリミティブの単純プロパティ値をdictへ退避する。"""
    data = {}
    for prop in prim.bl_rna.properties:
        pid = prop.identifier
        if prop.is_readonly or prop.type == 'COLLECTION' or pid in _SKETCH_REGEN_GEOMETRY_FIELDS:
            continue
        try:
            value = getattr(prim, pid)
            if getattr(prop, "array_length", 0) > 1:
                value = tuple(value)
            data[pid] = value
        except Exception:
            pass
    return data


def _apply_primitive_user_fields(prim, data):
    for pid, value in data.items():
        try:
            setattr(prim, pid, value)
        except Exception:
            pass


def finalize_sketch_edit_inplace(op, context, props, editing_uuid):
    """V8.1.5: スケッチ編集履歴 - Edit Sketchで再編集したスケッチをApplyする際に呼ぶ。
    通常のfinalize_sketch(新規primitiveをprimitivesの末尾にappendするだけ)と違い、
    再編集前に同じsketch_source_uuidを持っていた既存primitiveの`uuid`と、
    operation/extrude_height/nameなどのユーザー調整済みプロパティを新primitiveに
    引き継がせる。これにより、REVOLVE/EXTRUDE/SWEEP/LOFT等のtarget_uuid参照が
    再finalize後も自動的に新しいジオメトリを指し続け、かつユーザーが個別に設定した
    値(押し出し高さ・ブーリアン演算種別など)もリセットされずに保たれる。

    アイランド数(finalizeで生成されるprimitive数)が編集前後で変わった場合は
    1:1の引き継ぎができないため、新しいprimitiveはデフォルト値・fresh uuidのまま
    追加し、古いprimitiveは削除した上でユーザーに警告する。
    """
    from .sketch_finalize import finalize_sketch

    old_indices = [i for i, p in enumerate(props.primitives) if p.sketch_source_uuid == editing_uuid]
    old_uuids = [props.primitives[i].uuid for i in old_indices]
    old_field_snapshots = [_snapshot_primitive_user_fields(props.primitives[i]) for i in old_indices]

    # V8.1.5バグ修正: 旧primitiveをremove()すると後続の全インデックスがズレるため、
    # active_primitive_index を更新しないとUIパネルが無関係な別primitiveを表示してしまう
    # (押し出し高さ等のプロパティは正しく引き継がれているのに、選択がズレて別の値に
    # 見える、という不具合の原因だった)。uuidベースで後から選択を復元する。
    active_uuid_before = None
    if 0 <= props.active_primitive_index < len(props.primitives):
        active_uuid_before = props.primitives[props.active_primitive_index].uuid

    finalize_sketch(context, props, sketch_uuid=editing_uuid)

    # finalize_sketch は新primitiveを末尾にappendする。旧primitiveはまだ残っているので、
    # 「sketch_source_uuidが一致し、かつ旧インデックス集合に含まれない」ものが新規分。
    new_indices = [
        i for i, p in enumerate(props.primitives)
        if p.sketch_source_uuid == editing_uuid and i not in old_indices
    ]

    if old_indices and len(new_indices) == len(old_indices):
        # 1:1対応: 新primitiveに旧uuid・旧プロパティを引き継がせ、旧primitiveを削除する
        for new_i, old_uuid, old_fields in zip(new_indices, old_uuids, old_field_snapshots):
            if old_uuid:
                props.primitives[new_i].uuid = old_uuid
            _apply_primitive_user_fields(props.primitives[new_i], old_fields)
        for i in sorted(old_indices, reverse=True):
            props.primitives.remove(i)

        # V8.1.5バグ修正: finalize_sketchは新primitiveを常にスタックの末尾にappendするため、
        # 上のremove()だけだと編集したスケッチが元の位置(Base/Fillet適用順序)から
        # 末尾に移動してしまう(Fillet等の下流モディファイアより後ろに来て破綻する)。
        # 各new primitiveをuuidで検索し直しながら、元あったスロット(old_indices)へ
        # 1つずつmove()で戻す。move()のたびに他要素の位置が変わるため、都度uuidで
        # 現在位置を再検索することで、アイランド数が複数でも正しく復元できる。
        for target_pos, old_uuid in zip(old_indices, old_uuids):
            if not old_uuid:
                continue
            cur_idx = next((idx for idx, p in enumerate(props.primitives) if p.uuid == old_uuid), None)
            if cur_idx is not None and cur_idx != target_pos:
                props.primitives.move(cur_idx, target_pos)

        op.report({'INFO'}, f"Sketch updated in place ({len(new_indices)} feature(s)).")
    elif old_indices:
        # アイランド数が変化: uuidを引き継げないため、旧primitiveを削除し新規のまま残す
        for i in sorted(old_indices, reverse=True):
            props.primitives.remove(i)
        op.report(
            {'WARNING'},
            f"Sketch topology changed ({len(old_indices)} -> {len(new_indices)} feature(s)); "
            "downstream features referencing the old sketch may need to be reassigned."
        )
    # old_indices が空(通常は起こらないはずだが、念のため)の場合は何もしない。

    # V8.1.5バグ修正: remove()によるインデックスのズレを補正し、Active Primitiveの
    # 選択(=UIパネルが表示するprimitive)を編集前と同じものに復元する。
    if active_uuid_before:
        for i, p in enumerate(props.primitives):
            if p.uuid == active_uuid_before:
                props.active_primitive_index = i
                break

    from ..core_bridge import update_cad_preview_forced
    update_cad_preview_forced(context)
