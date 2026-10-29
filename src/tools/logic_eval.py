"""Safe mathematical and logical evaluation tool for AIRA.

Evaluates arithmetic and boolean expressions using AST parsing without
the security hazards of raw eval().
"""

import ast
import operator
import json
from typing import Any

SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.BitXor: operator.xor,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}

def _eval_node(node: ast.AST) -> Any:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float, bool, str)):
            return node.value
        raise ValueError(f"Unsupported constant type: {type(node.value)}")

    elif isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in SAFE_OPERATORS:
            raise ValueError(f"Unsupported binary operator: {op_type}")
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        return SAFE_OPERATORS[op_type](left, right)

    elif isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in SAFE_OPERATORS:
            raise ValueError(f"Unsupported unary operator: {op_type}")
        return SAFE_OPERATORS[op_type](_eval_node(node.operand))

    elif isinstance(node, ast.Compare):
        left = _eval_node(node.left)
        for op, comparator in zip(node.ops, node.comparators):
            op_type = type(op)
            if op_type not in SAFE_OPERATORS:
                raise ValueError(f"Unsupported comparison operator: {op_type}")
            right = _eval_node(comparator)
            if not SAFE_OPERATORS[op_type](left, right):
                return False
            left = right
        return True

    elif isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            for val in node.values:
                if not _eval_node(val):
                    return False
            return True
        elif isinstance(node.op, ast.Or):
            for val in node.values:
                if _eval_node(val):
                    return True
            return False
        raise ValueError(f"Unsupported boolean operator: {type(node.op)}")

    else:
        raise ValueError(f"Unsupported expression node: {type(node)}")

def evaluate_logic(expression: str) -> str:
    """Safely evaluates an arithmetic or logical expression."""
    clean_expr = expression.strip()
    if not clean_expr:
        return json.dumps({"error": "Empty expression provided."})

    try:
        tree = ast.parse(clean_expr, mode="eval")
        result = _eval_node(tree.body)
        return json.dumps({
            "expression": clean_expr,
            "status": "success",
            "result": result
        })
    except Exception as e:
        return json.dumps({
            "expression": clean_expr,
            "status": "error",
            "error": f"Evaluation error: {str(e)}"
        })

EVALUATE_LOGIC_SCHEMA = {
    "type": "function",
    "function": {
        "name": "evaluate_logic",
        "description": "Safely evaluates an arithmetic or boolean logic expression without executing arbitrary code.",
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Mathematical or boolean expression to evaluate, e.g. '(128 * 1024) / 64' or '45 > 30 and 10 < 20'."
                }
            },
            "required": ["expression"]
        }
    }
}
