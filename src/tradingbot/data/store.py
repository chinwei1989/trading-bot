"""Parquet bar storage and panel helpers."""

from __future__ import annotations

from pathlib import Path

import polars as pl

REQUIRED = ["timestamp", "asset", "open", "high", "low", "close", "volume"]


def ensure_utc(df: pl.DataFrame, column: str = "timestamp") -> pl.DataFrame:
    """Normalize a timestamp column to UTC Datetime."""
    dtype = df.schema[column]
    if dtype == pl.Date:
        return df.with_columns(
            pl.col(column).cast(pl.Datetime("us")).dt.replace_time_zone("UTC").alias(column)
        )
    if isinstance(dtype, pl.Datetime):
        if dtype.time_zone is None:
            return df.with_columns(
                pl.col(column).dt.replace_time_zone("UTC").alias(column)
            )
        if dtype.time_zone != "UTC":
            return df.with_columns(
                pl.col(column).dt.convert_time_zone("UTC").alias(column)
            )
        return df
    raise TypeError(f"{column} must be Date or Datetime, got {dtype}")


def normalize_bars(df: pl.DataFrame) -> pl.DataFrame:
    """Validate and normalize a long OHLCV frame."""
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"missing columns: {missing}")
    out = ensure_utc(df.select(REQUIRED))
    out = out.with_columns(
        pl.col("asset").cast(pl.Utf8),
        *[pl.col(c).cast(pl.Float64) for c in ["open", "high", "low", "close", "volume"]],
    )
    return out.unique(subset=["timestamp", "asset"], keep="last").sort(["timestamp", "asset"])


def load_bars(path: str | Path) -> pl.DataFrame:
    df = pl.read_parquet(path)
    return normalize_bars(df)


def save_bars(df: pl.DataFrame, path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    normalize_bars(df).write_parquet(out)
    return out


def wide(df: pl.DataFrame, field: str = "close") -> pl.DataFrame:
    """Pivot a long frame to timestamp x asset."""
    if field not in df.columns:
        raise ValueError(f"field not in frame: {field}")
    return (
        df.select(["timestamp", "asset", field])
        .pivot(index="timestamp", on="asset", values=field)
        .sort("timestamp")
    )


def long(wide_df: pl.DataFrame, value_name: str = "value") -> pl.DataFrame:
    """Unpivot a timestamp x asset frame to long format."""
    return (
        wide_df.unpivot(index="timestamp", variable_name="asset", value_name=value_name)
        .drop_nulls(value_name)
        .sort(["timestamp", "asset"])
    )


def asset_columns(df: pl.DataFrame) -> list[str]:
    return [c for c in df.columns if c != "timestamp"]


def validate_bars(df: pl.DataFrame) -> dict[str, object]:
    """Return a compact data-quality report."""
    normalized = normalize_bars(df)
    duplicate_rows = normalized.height - normalized.unique(subset=["timestamp", "asset"]).height
    ohlc_bad = normalized.filter(
        (pl.col("low") > pl.min_horizontal("open", "close"))
        | (pl.col("high") < pl.max_horizontal("open", "close"))
        | (pl.col("low") <= 0)
        | (pl.col("high") <= 0)
        | (pl.col("close") <= 0)
    ).height
    null_rows = normalized.filter(
        pl.any_horizontal([pl.col(c).is_null() for c in ["open", "high", "low", "close"]])
    ).height
    return {
        "rows": normalized.height,
        "assets": normalized["asset"].n_unique(),
        "start": normalized["timestamp"].min(),
        "end": normalized["timestamp"].max(),
        "duplicates": duplicate_rows,
        "ohlc_violations": ohlc_bad,
        "null_prices": null_rows,
        "assets_list": sorted(normalized["asset"].unique().to_list()),
    }
