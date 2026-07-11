"""Simple moving average (SMA) columns for strategy ``prepare_indicators``."""

from __future__ import annotations

from typing import Any, List, Optional, Sequence, Union


def sma_column_name(period: int, *, column: Optional[str] = None) -> str:
    """Default column name for a single SMA length (override with ``column``)."""
    if column:
        return str(column)
    return f"sma_{max(1, int(period))}"


def sma_column_names(
    periods: Union[int, Sequence[int]],
    *,
    column: Optional[str] = None,
) -> List[str]:
    """
    Column names produced by ``add_sma`` for ``persisted_indicator_keys``.

    ``column`` is only valid with a single period; multiple periods always use
    ``sma_{N}`` names.
    """
    if isinstance(periods, int):
        return [sma_column_name(periods, column=column)]
    names: List[str] = []
    for p in periods:
        names.append(sma_column_name(int(p)))
    return names


def add_sma(
    df: Any,
    period: Optional[int] = None,
    *,
    periods: Optional[Sequence[int]] = None,
    source_col: str = "close",
    column: Optional[str] = None,
    min_periods: Optional[int] = None,
) -> Any:
    """
    Add simple moving average column(s) on ``source_col`` (default ``close``).

    Strategy defines length(s)::

        def prepare_indicators(self, df):
            return add_sma(df, period=self.sma_period)
            # or: return add_sma(df, periods=[9, 21])

    - Single ``period`` → column ``sma_{period}`` (or ``column`` if set).
    - ``periods=[...]`` → one ``sma_{N}`` column per length (``column`` ignored).
    """
    if df is None or len(df) == 0:
        return df
    if source_col not in df.columns:
        return df

    lengths: List[int] = []
    if periods is not None:
        lengths = [max(1, int(p)) for p in periods if p is not None]
    elif period is not None:
        lengths = [max(1, int(period))]
    if not lengths:
        return df

    series = df[source_col].astype(float)
    multi = len(lengths) > 1 or periods is not None
    for p in lengths:
        col = sma_column_name(p) if multi else sma_column_name(p, column=column)
        mp = p if min_periods is None else max(1, int(min_periods))
        df[col] = series.rolling(window=p, min_periods=mp).mean()
    return df
