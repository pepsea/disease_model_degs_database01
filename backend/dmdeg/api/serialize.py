"""DataFrame を JSON 安全な構造に変換する。

NaN / Inf をそのまま返すと不正な JSON になりブラウザ側でパースに失敗する
ため、null に落とす経路を 1 箇所に集約する。
"""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np
import pandas as pd


def clean(value: Any) -> Any:
    """単一値を JSON 安全にする。"""
    if value is None:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return None if not math.isfinite(number) else number
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, np.ndarray):
        return [clean(v) for v in value.tolist()]
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if value is pd.NA or (isinstance(value, float) and math.isnan(value)):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def records(df: pd.DataFrame) -> list[dict]:
    """DataFrame を dict のリストに変換する（NaN/Inf は null）。"""
    if df is None or df.empty:
        return []
    safe = df.copy()
    # Infinity は不正な JSON になるため NaN へ寄せる。DuckDB の list() 集約は
    # セルに ndarray を入れてくるので、数値列だけを対象にする
    # （object 列に対する replace は配列比較で例外になる）。
    numeric = safe.select_dtypes(include=["number"]).columns
    if len(numeric):
        safe[numeric] = safe[numeric].replace([np.inf, -np.inf], np.nan)
    # ndarray セルは to_json が扱えないため Python の list に落とす
    for column in safe.columns:
        if safe[column].dtype == object and safe[column].map(lambda v: isinstance(v, np.ndarray)).any():
            safe[column] = safe[column].map(lambda v: v.tolist() if isinstance(v, np.ndarray) else v)
    return json.loads(safe.to_json(orient="records", double_precision=6, date_format="iso"))


def row(series: pd.Series | dict | None) -> dict | None:
    if series is None:
        return None
    data = series.to_dict() if isinstance(series, pd.Series) else dict(series)
    return {k: clean(v) for k, v in data.items()}


def to_csv(df: pd.DataFrame) -> str:
    return df.to_csv(index=False)
