import json
import math
import mathutils


SEMANTIC_OPENING_LOOP_PREFIX = "SemLoop:OPENING@"
SEMANTIC_EDGESET_LOOP_PREFIX = "SemLoop:EDGESET@"


def is_semantic_opening_loop(token: str) -> bool:
    return isinstance(token, str) and token.startswith(SEMANTIC_OPENING_LOOP_PREFIX)


def make_semantic_opening_loop_token(raw_lid: str) -> str:
    if not isinstance(raw_lid, str):
        return ""
    if "@" not in raw_lid:
        return ""
    parts = raw_lid.split("@")
    if len(parts) >= 3 and parts[2].startswith("Loop:"):
        loop_payload = parts[2][len("Loop:"):].strip()
        if loop_payload:
            return f"{SEMANTIC_OPENING_LOOP_PREFIX}{loop_payload}"
    return f"{SEMANTIC_OPENING_LOOP_PREFIX}{parts[1].strip()}"


def make_semantic_edgeset_loop_token(raw_ids: list[str]) -> str:
    if not raw_ids:
        return ""
    coords = [parse_target_coord(token) for token in raw_ids]
    coords = [c for c in coords if c is not None]
    if len(coords) < 2:
        return ""
    xs = [c.x for c in coords]
    ys = [c.y for c in coords]
    zs = [c.z for c in coords]
    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)
    cz = sum(zs) / len(zs)
    dx = max(xs) - min(xs)
    dy = max(ys) - min(ys)
    dz = max(zs) - min(zs)
    diag = math.sqrt(dx * dx + dy * dy + dz * dz)
    return f"{SEMANTIC_EDGESET_LOOP_PREFIX}{cx:.3f};{cy:.3f};{cz:.3f}@{diag:.3f};{len(coords)}"


def parse_target_coord(token: str):
    if not isinstance(token, str) or "@" not in token:
        return None
    try:
        parts = token.split("@")
        if token.startswith("Edge:"):
            coord_text = parts[1]
        elif token.startswith("SemLoop:"):
            coord_text = parts[1]
        else:
            coord_text = parts[-1]
        if "|" in coord_text:
            coord_text = coord_text.split("|")[0]
        if "#" in coord_text:
            coord_text = coord_text.split("#")[0]
        x, y, z = (float(v) for v in coord_text.split(";"))
        return mathutils.Vector((x, y, z))
    except Exception:
        return None


def replace_target_coord(token: str, coord) -> str:
    if not isinstance(token, str):
        return token
    if "@" not in token:
        return token
    parts = token.split("@")
    if len(parts) == 2:
        suffix = ""
        if "#" in parts[1]:
            idx = parts[1].find("#")
            suffix = parts[1][idx:]
        elif "|" in parts[1]:
            idx = parts[1].find("|")
            suffix = parts[1][idx:]
        return f"{parts[0]}@{coord.x:.3f};{coord.y:.3f};{coord.z:.3f}{suffix}"
    
    suffix = ""
    if "#" in parts[1]:
        idx = parts[1].find("#")
        suffix = parts[1][idx:]
    elif "|" in parts[1]:
        idx = parts[1].find("|")
        suffix = parts[1][idx:]
    parts[1] = f"{coord.x:.3f};{coord.y:.3f};{coord.z:.3f}{suffix}"
    return "@".join(parts)


def find_snapshot_entry_for_token(snapshot: dict, token: str):
    if not isinstance(snapshot, dict) or not isinstance(token, str):
        return None

    direct = snapshot.get(token)
    if direct:
        return direct

    token_coord = parse_target_coord(token)
    token_base = token.split("@")[0]

    if token_base.startswith("Edge:"):
        for k, v in snapshot.items():
            if not isinstance(k, str):
                continue
            if k.split("@")[0] == token_base:
                return v

    if token_coord is None:
        return None

    best_entry = None
    best_d2 = math.inf
    for k, v in snapshot.items():
        if not isinstance(k, str):
            continue
        key_coord = parse_target_coord(k)
        if key_coord is None:
            continue
        d2 = (key_coord - token_coord).length_squared
        if d2 < best_d2:
            best_d2 = d2
            best_entry = v
    return best_entry


def get_display_edge_targets(prim) -> list[str]:
    raw_targets = [x.strip() for x in getattr(prim, "target_lineages", "").split("|") if x.strip()]
    edge_targets = [x for x in raw_targets if x.startswith("Edge:")]
    if edge_targets:
        return edge_targets

    snapshot_str = getattr(prim, "edge_ref_snapshot", "")
    if not snapshot_str:
        return []

    try:
        snapshot = json.loads(snapshot_str)
    except Exception:
        return []

    if not isinstance(snapshot, dict):
        return []

    return [k for k in snapshot.keys() if isinstance(k, str) and k.startswith("Edge:")]
