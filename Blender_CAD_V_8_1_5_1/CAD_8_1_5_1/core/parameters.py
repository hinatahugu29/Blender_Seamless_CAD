"""ユーザーパラメータ(変数と数式) — IMPLEMENTATION_ROADMAP 3.1。

カーネルには触らない。式を評価した結果を既存のプリミティブの欄へ書き込むだけで、
そこから先は欄ごとの update(=いつものプレビュー経路)が働く。

**`eval()` を使わない。** `.blend` は他人から受け取るファイルで、その中の文字列を
評価するのは任意コード実行になる。ここでは AST を明示的にホワイトリストし、
四則演算・累乗・剰余・単項符号・数値・変数名・下の関数表だけを通す。
属性アクセス・添字・内包表記・キーワード引数は全て拒否する。
"""

import ast
import math
import operator

MAX_EXPRESSION_LENGTH = 500

_FUNCS = {
    "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "radians": math.radians, "degrees": math.degrees,
    "abs": abs, "min": min, "max": max, "round": round,
    "floor": math.floor, "ceil": math.ceil,
}
_CONSTS = {"pi": math.pi}
_BINOPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}

# 欄の識別子 -> (プロパティ名, 成分 index or -1, 表示名, 角度か)
BINDABLE_FIELDS = [
    ("size_x", "size", 0, "Size X", False),
    ("size_y", "size", 1, "Size Y", False),
    ("size_z", "size", 2, "Size Z", False),
    ("location_x", "location", 0, "Location X", False),
    ("location_y", "location", 1, "Location Y", False),
    ("location_z", "location", 2, "Location Z", False),
    ("rotation_x", "rotation", 0, "Rotation X (deg)", True),
    ("rotation_y", "rotation", 1, "Rotation Y (deg)", True),
    ("rotation_z", "rotation", 2, "Rotation Z (deg)", True),
    ("radius", "radius", -1, "Radius", False),
    ("radius2", "radius2", -1, "Radius 2", False),
    ("minor_radius", "minor_radius", -1, "Minor Radius", False),
    ("pipe_radius", "pipe_radius", -1, "Pipe Radius", False),
    ("extrude_height", "extrude_height", -1, "Extrude Height", False),
    ("distance", "distance", -1, "Value / Angle", False),
    ("count", "count", -1, "Count", False),
    ("sides", "sides", -1, "Sides / Teeth", False),
    ("turns", "turns", -1, "Turns", False),
    ("module", "module", -1, "Module", False),
    ("angle_start", "angle_start", -1, "Angle Start", False),
    ("angle_end", "angle_end", -1, "Angle End", False),
]
_FIELD_MAP = {f[0]: f for f in BINDABLE_FIELDS}
RESERVED_NAMES = set(_FUNCS) | set(_CONSTS)


class ExpressionError(ValueError):
    pass


def _parse(expr):
    expr = (expr or "").strip()
    if not expr:
        raise ExpressionError("empty expression")
    if len(expr) > MAX_EXPRESSION_LENGTH:
        raise ExpressionError("expression too long")
    try:
        return ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise ExpressionError(f"syntax error: {e.msg}") from None


def referenced_names(expr):
    """式が参照する変数名(関数名・定数は除く)。構文エラーなら例外。"""
    tree = _parse(expr)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id not in RESERVED_NAMES:
            names.add(node.id)
    return names


def rename_in_expression(expr, old, new):
    """式中の変数名 old を new に置き換える。部分一致(width と width2)は触らない。

    構文が壊れている式は tokenize が失敗しうるので、そのときは元のまま返す。
    """
    import io
    import tokenize
    if not expr or old not in expr:
        return expr
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(expr).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return expr
    out = []
    prev_end = 0
    for tok in tokens:
        if tok.type in (tokenize.NEWLINE, tokenize.NL, tokenize.ENDMARKER):
            continue
        start, end = tok.start[1], tok.end[1]
        out.append(expr[prev_end:start])
        out.append(new if tok.type == tokenize.NAME and tok.string == old else tok.string)
        prev_end = end
    out.append(expr[prev_end:])
    return "".join(out)


def _eval_node(node, env):
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, env)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ExpressionError("only numbers are allowed")
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id in env:
            return env[node.id]
        if node.id in _CONSTS:
            return _CONSTS[node.id]
        raise ExpressionError(f"unknown name '{node.id}'")
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        left = _eval_node(node.left, env)
        right = _eval_node(node.right, env)
        if isinstance(node.op, ast.Pow) and abs(right) > 1000:
            raise ExpressionError("exponent too large")
        return float(_BINOPS[type(node.op)](left, right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval_node(node.operand, env))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS or node.keywords:
            raise ExpressionError("only sqrt/sin/cos/tan/radians/degrees/abs/min/max/round/floor/ceil may be called")
        args = [_eval_node(a, env) for a in node.args]
        return float(_FUNCS[node.func.id](*args))
    raise ExpressionError(f"'{type(node).__name__}' is not allowed in an expression")


def evaluate(expr, env=None):
    """式を評価して float を返す。失敗は ExpressionError。"""
    tree = _parse(expr)
    try:
        value = _eval_node(tree, env or {})
    except ExpressionError:
        raise
    except (ZeroDivisionError, OverflowError, ValueError, TypeError) as e:
        raise ExpressionError(str(e) or type(e).__name__) from None
    if not math.isfinite(value):
        raise ExpressionError("result is not a finite number")
    return value


def evaluate_parameters(definitions):
    """[(name, expression), ...] を依存順に評価する。

    戻り値は (values, errors)。循環・未定義参照・重複名はその変数だけ
    エラーにし、他の変数の評価は続ける。
    """
    exprs = {}
    errors = {}
    for name, expr in definitions:
        if not name.isidentifier() or name in RESERVED_NAMES:
            errors[name] = f"'{name}' is not a usable name"
        elif name in exprs:
            errors[name] = f"'{name}' is defined twice"
        else:
            exprs[name] = expr

    values = {}
    state = {}  # name -> "visiting" | "done"

    def resolve(name, chain):
        if state.get(name) == "done":
            return name in values
        if state.get(name) == "visiting":
            cycle = " -> ".join(chain[chain.index(name):] + [name])
            for n in chain[chain.index(name):]:
                errors.setdefault(n, f"circular reference: {cycle}")
            return False
        state[name] = "visiting"
        ok = True
        try:
            deps = referenced_names(exprs[name])
        except ExpressionError as e:
            errors[name] = str(e)
            ok = False
            deps = set()
        for d in sorted(deps):
            if d not in exprs:
                errors.setdefault(name, f"unknown name '{d}'")
                ok = False
            elif not resolve(d, chain + [name]):
                errors.setdefault(name, f"depends on '{d}', which has an error")
                ok = False
        if ok and name not in errors:
            try:
                values[name] = evaluate(exprs[name], values)
            except ExpressionError as e:
                errors[name] = str(e)
        state[name] = "done"
        return name in values

    for name in exprs:
        resolve(name, [])
    return values, errors


def field_value(prim, field_id):
    _, prop, index, _, is_angle = _FIELD_MAP[field_id]
    v = getattr(prim, prop)
    if index >= 0:
        v = v[index]
    return math.degrees(v) if is_angle else float(v)


def _write_field(prim, field_id, value):
    _, prop, index, _, is_angle = _FIELD_MAP[field_id]
    if is_angle:
        value = math.radians(value)
    current = getattr(prim, prop)
    if isinstance(current, int):
        value = int(round(value))
        if current != value:
            setattr(prim, prop, value)
            return True
        return False
    if index >= 0:
        vec = list(current)
        if abs(vec[index] - value) <= 1e-9:
            return False
        vec[index] = value
        setattr(prim, prop, vec)
        return True
    if abs(current - value) > 1e-9:
        setattr(prim, prop, value)
        return True
    return False


# 配置の欄はプロキシのオブジェクトが正で、depsgraph ハンドラが
# オブジェクトの行列を prim へ書き戻す(utils.py の world_scale 比較)。
# 書いた値をプロキシへ押し出さないと、次の更新で元に戻される。
_TRANSFORM_PROPS = {"size", "location", "rotation"}


_applying = False


def apply_parameters(props):
    """変数を評価し、結果を変数表とバインドされた欄へ書き込む。

    欄への書き込みは値が変わったときだけ行う(update が走ってプレビューが
    再計算されるので、無駄に書くと重くなる)。
    """
    global _applying
    if _applying or props is None:
        return
    _applying = True
    try:
        values, errors = evaluate_parameters([(p.name, p.expression) for p in props.parameters])
        for p in props.parameters:
            err = errors.get(p.name, "")
            if p.error != err:
                p.error = err
            if p.name in values and abs(p.value - values[p.name]) > 1e-12:
                p.value = values[p.name]
        moved = False
        for prim in props.primitives:
            for b in prim.bindings:
                err = ""
                if b.field not in _FIELD_MAP:
                    err = f"unknown field '{b.field}'"
                else:
                    try:
                        if _write_field(prim, b.field, evaluate(b.expression, values)):
                            moved = moved or _FIELD_MAP[b.field][1] in _TRANSFORM_PROPS
                    except ExpressionError as e:
                        err = str(e)
                if b.error != err:
                    b.error = err
    finally:
        _applying = False
    if moved:
        import bpy
        from .. import utils
        utils.sync_proxies(bpy.context, props=props)
