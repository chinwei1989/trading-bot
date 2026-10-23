"""Point-in-time universe helpers.

The current public data sources only give us the symbols that still exist today.
That means a fully point-in-time universe (including delisted assets) is not
available yet. What we *can* do immediately is remove look-ahead from listing
and delisting dates: an asset is only eligible between its first and last
observed bar.

The file format is intentionally simple so a future vendor snapshot can replace
the inferred spans without changing the strategy code:

    asset,start,end
    BTCUSDT,2017-08-17,
    LUNAUSDT,2019-05-01,2022-05-13
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from tradingbot.data.store import normalize_bars

SPAN_COLUMNS = ["asset", "start", "end"]


def spans_from_bars(bars: pl.DataFrame, *, open_ended: bool = True) -> pl.DataFrame:
    """Infer active spans from the first and last observed bar per asset.

    By default current assets are left open-ended. A closed end means the asset
    was delisted and must not be used after that date.
    """
    bars = normalize_bars(bars)
    end = (
        pl.lit(None, dtype=pl.Date).alias("end")
        if open_ended
        else pl.col("timestamp").max().dt.date().alias("end")
    )
    return (
        bars.group_by("asset")
        .agg(
            pl.col("timestamp").min().dt.date().alias("start"),
            end,
            pl.len().alias("observations"),
        )
        .sort("asset")
    )


def save_spans(spans: pl.DataFrame, path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    spans.select(SPAN_COLUMNS).sort("asset").write_csv(out)
    return out


def load_spans(path: str | Path) -> pl.DataFrame:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"universe spans not found: {p}")
    if p.suffix.lower() == ".parquet":
        spans = pl.read_parquet(p)
    else:
        spans = pl.read_csv(p, try_parse_dates=True)
    missing = [c for c in SPAN_COLUMNS if c not in spans.columns]
    if missing:
        raise ValueError(f"universe file missing columns: {missing}")
    return spans.select(SPAN_COLUMNS).sort("asset")


def apply_spans(bars: pl.DataFrame, spans: pl.DataFrame) -> pl.DataFrame:
    """Keep only bars inside each asset's active span."""
    bars = normalize_bars(bars)
    active = spans.select(SPAN_COLUMNS).with_columns(
        pl.col("start").cast(pl.Date),
        pl.col("end").cast(pl.Date, strict=False),
    )
    out = (
        bars.join(active, on="asset", how="left")
        .filter(
            pl.col("start").is_not_null()
            & (pl.col("timestamp").dt.date() >= pl.col("start"))
            & (
                pl.col("end").is_null()
                | (pl.col("timestamp").dt.date() <= pl.col("end"))
            )
        )
        .drop(["start", "end"])
        .sort(["timestamp", "asset"])
    )
    return normalize_bars(out)


def load_bars_with_universe(
    bars_path: str | Path,
    spans_path: str | Path | None = None,
) -> pl.DataFrame:
    """Load bars and optionally apply a PIT span file."""
    from tradingbot.data.store import load_bars

    bars = load_bars(bars_path)
    if spans_path is None:
        return bars
    universe_file = Path(spans_path)
    if not universe_file.exists():
        raise FileNotFoundError(f"universe spans not found: {universe_file}")
    return apply_spans(bars, load_spans(universe_file))


def audit_spans(bars: pl.DataFrame) -> dict[str, object]:
    """Compact listing audit for a bar panel."""
    spans = spans_from_bars(bars)
    return {
        "assets": spans.height,
        "start": str(spans["start"].min()),
        "end": str(spans["end"].max()),
        "spans": spans.with_columns(
            pl.col("start").cast(pl.Utf8), pl.col("end").cast(pl.Utf8)
        ).to_dicts(),
    }
