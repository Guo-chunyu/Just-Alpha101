"""Evaluate a fixed formula registry through a deliberately small safe AST.

No Python eval/exec, attributes, indexing, imports or arbitrary function calls
are allowed. Numeric comparisons preserve missingness rather than converting an
unknown comparison to False. Data never fill forwards or backwards.
"""
from __future__ import annotations

import ast
import operator
import re

import numpy as np
import pandas as pd

from . import operators as op
from .formulas import FORMULAS


class MissingFieldError(ValueError):
    """An alpha's required raw fields were not supplied."""

    def __init__(self, alpha_id, missing_fields, required_fields=None):
        self.alpha_id = alpha_id
        self.missing_fields = set(missing_fields)
        self.required_fields = set(required_fields or missing_fields)
        super().__init__(f"Alpha {alpha_id} requires missing fields: {', '.join(sorted(self.missing_fields))}")


_FIELDS = {"open", "high", "low", "close", "volume", "vwap", "cap", "sector", "industry", "subindustry", "dollar_volume"}
_WINDOW_FUNCTIONS = {"delay", "delta", "correlation", "covariance", "decay_linear", "ts_min", "ts_max", "ts_argmin", "ts_argmax", "ts_rank", "sum", "product", "stddev"}
_FUNCTIONS = _WINDOW_FUNCTIONS | {"rank", "scale", "signedpower", "indneutralize", "log", "abs", "sign", "minimum", "maximum", "min", "max", "where"}
_BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Pow: op.signedpower}
_COMPARE = {ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge, ast.Eq: operator.eq, ast.NotEq: operator.ne}


class FormulaEngine:
    def __init__(self, fields: dict[str, pd.DataFrame], window_scale=1.0, adv_basis="dollar", rank_method="average"):
        if not np.isscalar(window_scale) or not np.isfinite(window_scale) or window_scale <= 0:
            raise ValueError("window_scale must be finite and positive")
        if adv_basis not in {"dollar", "share", "shares", "volume"}:
            raise ValueError("adv_basis must be 'dollar' or 'share'")
        if rank_method not in {"average", "min", "max"}:
            raise ValueError("rank_method must be average, min or max (supported for both ranks)")
        if not fields:
            raise ValueError("At least one panel field is required")
        template = next(iter(fields.values()))
        if not isinstance(template, pd.DataFrame):
            raise TypeError("Every field must be a pandas DataFrame")
        if not template.index.is_unique or not template.index.is_monotonic_increasing or not template.columns.is_unique:
            raise ValueError("Panel dates must increase uniquely and securities must be unique")
        for name, value in fields.items():
            if not isinstance(value, pd.DataFrame):
                raise TypeError(f"Field {name!r} must be a pandas DataFrame")
            if not template.index.equals(value.index) or not template.columns.equals(value.columns):
                raise ValueError(f"Field {name!r} is not aligned with the panel")
        self.fields = {name.lower(): value.copy(deep=True) for name, value in fields.items()}
        self.window_scale = float(window_scale)
        self.adv_basis = "dollar" if adv_basis == "dollar" else "share"
        self.rank_method = rank_method
        self._template = next(iter(self.fields.values()))
        self._derived = {}

    def _tree(self, alpha_id):
        try:
            expression = FORMULAS[alpha_id]
        except KeyError:
            raise KeyError(f"Unknown alpha id: {alpha_id}") from None
        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as exc:
            raise ValueError(f"Invalid formula for alpha {alpha_id}") from exc
        self._validate(tree.body)
        return tree.body

    def _validate(self, node):
        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float, bool)) or not np.isfinite(node.value):
                raise ValueError("Only finite numeric constants are allowed")
        elif isinstance(node, ast.Name):
            name = node.id.lower()
            if name not in _FIELDS | {"returns"} and re.fullmatch(r"adv\d+", name) is None:
                raise ValueError(f"Unknown input name: {node.id}")
        elif isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id.lower() not in _FUNCTIONS or node.keywords:
                raise ValueError("Only named Alpha101 functions without keyword arguments are allowed")
            for child in node.args:
                self._validate(child)
        elif isinstance(node, ast.BinOp) and type(node.op) in set(_BINARY) | {ast.BitOr, ast.BitAnd}:
            self._validate(node.left)
            self._validate(node.right)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            self._validate(node.operand)
        elif isinstance(node, ast.Compare) and all(type(cmp) in _COMPARE for cmp in node.ops):
            self._validate(node.left)
            for child in node.comparators:
                self._validate(child)
        else:
            raise ValueError(f"Unsupported formula syntax: {type(node).__name__}")

    def requirements(self, alpha_id: int) -> set[str]:
        tree = self._tree(alpha_id)
        calls = {id(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
        names = {node.id.lower() for node in ast.walk(tree) if isinstance(node, ast.Name) and id(node) not in calls}
        required = names & _FIELDS
        if "returns" in names:
            required.add("close")
        if any(re.fullmatch(r"adv\d+", name) for name in names):
            if self.adv_basis == "share":
                required.add("volume")
            elif "dollar_volume" in self.fields:
                required.add("dollar_volume")
            else:
                required.update({"vwap", "volume"})
        return required

    def compute(self, alpha_id: int) -> pd.DataFrame:
        required = self.requirements(alpha_id)
        missing = required - self.fields.keys()
        if missing:
            raise MissingFieldError(alpha_id, missing, required)
        with np.errstate(all="ignore"):
            result = self._evaluate(self._tree(alpha_id))
        return op.clean(self._as_frame(result)).astype(float)

    def _as_frame(self, value):
        if isinstance(value, pd.DataFrame):
            return value
        return pd.DataFrame(value, index=self._template.index, columns=self._template.columns)

    def _window(self, d, allow_zero=False):
        if not np.isscalar(d) or not np.isfinite(d) or d < 0:
            raise ValueError("Windows/delays must be finite nonnegative scalars")
        return op.window(d * self.window_scale, allow_zero=allow_zero)

    def _name(self, name):
        name = name.lower()
        if name in self._derived:
            return self._derived[name]
        if name == "returns":
            result = op.clean(self.fields["close"]).pct_change(fill_method=None)
        elif re.fullmatch(r"adv\d+", name):
            size = self._window(int(name[3:]))
            if self.adv_basis == "share":
                raw = self.fields["volume"]
            elif "dollar_volume" in self.fields:
                raw = self.fields["dollar_volume"]
            else:
                raw = self.fields["vwap"] * self.fields["volume"]
            result = op.clean(raw).rolling(size, min_periods=size).mean()
        elif name in {"sector", "industry", "subindustry"}:
            return self.fields[name]
        else:
            return op.clean(self.fields[name])
        self._derived[name] = op.clean(result)
        return self._derived[name]

    def _logic(self, left, right, operation):
        lhs, rhs = self._as_frame(left), self._as_frame(right)
        result = operation(lhs.fillna(0).astype(bool), rhs.fillna(0).astype(bool)).astype(float)
        return result.where(lhs.notna() & rhs.notna())

    def _comparison(self, left, right, operation):
        lhs, rhs = self._as_frame(left), self._as_frame(right)
        return operation(lhs, rhs).astype(float).where(lhs.notna() & rhs.notna())

    def _evaluate(self, node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return self._name(node.id)
        if isinstance(node, ast.UnaryOp):
            value = self._evaluate(node.operand)
            return op.clean(-value if isinstance(node.op, ast.USub) else value)
        if isinstance(node, ast.BinOp):
            left, right = self._evaluate(node.left), self._evaluate(node.right)
            if isinstance(node.op, (ast.BitOr, ast.BitAnd)):
                return self._logic(left, right, operator.or_ if isinstance(node.op, ast.BitOr) else operator.and_)
            try:
                return op.clean(_BINARY[type(node.op)](left, right))
            except (ZeroDivisionError, OverflowError, FloatingPointError):
                return np.nan
        if isinstance(node, ast.Compare):
            left = self._evaluate(node.left)
            result = None
            for comparison, child in zip(node.ops, node.comparators):
                right = self._evaluate(child)
                current = self._comparison(left, right, _COMPARE[type(comparison)])
                result = current if result is None else self._logic(result, current, operator.and_)
                left = right
            return result
        if isinstance(node, ast.Call):
            name = node.func.id.lower()
            args = [self._evaluate(arg) for arg in node.args]
            if name in _WINDOW_FUNCTIONS:
                args[-1] = self._window(args[-1], allow_zero=name in {"delay", "delta"})
            elif name in {"min", "max"} and np.isscalar(args[-1]):
                args[-1] = self._window(args[-1])
            if name in {"rank", "ts_rank"}:
                return getattr(op, name)(*args, method=self.rank_method)
            return getattr(op, name)(*args)
        raise ValueError(f"Unsupported formula syntax: {type(node).__name__}")
