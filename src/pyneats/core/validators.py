"""Primitive validators for Fleet data validation (Layer 1).

This module provides low-level validation functions for DataFrames and dictionaries.
These primitives are used by FleetSchema (Layer 2) for declarative validation.
"""

from typing import Any, Iterable

import pandas as pd


class ValidationError(Exception):
    """Raised when validation fails."""

    pass


def validate_columns(
    df: pd.DataFrame | dict[str, Any],
    required: Iterable[str],
    optional: Iterable[str] | None = None,
) -> None:
    """Validate that DataFrame or dict has required columns/keys.

    Args:
        df: DataFrame or dict-like object (e.g., VectorDataDict) to validate
        required: Required column/key names
        optional: Optional column/key names (for documentation, not enforced)

    Raises:
        ValidationError: If required columns are missing
    """
    required_set = set(required)

    # Handle both DataFrame and dict-like objects (VectorDataDict)
    if hasattr(df, 'columns'):
        actual_cols = set(df.columns)
    elif hasattr(df, 'keys'):
        actual_cols = set(df.keys())
    else:
        raise TypeError(f"Expected DataFrame or dict-like object, got {type(df)}")

    missing = required_set - actual_cols

    if missing:
        raise ValidationError(
            f"Missing required columns: {sorted(missing)}. "
            f"Available columns: {sorted(actual_cols)}"
        )


def validate_attrs(
    attrs: dict[str, Any],
    required: Iterable[str],
    optional: Iterable[str] | None = None,
) -> None:
    """Validate that dictionary has required keys.

    Args:
        attrs: Dictionary to validate
        required: Required key names
        optional: Optional key names (for documentation, not enforced)

    Raises:
        ValidationError: If required keys are missing
    """
    required_set = set(required)
    actual_keys = set(attrs.keys())

    missing = required_set - actual_keys

    if missing:
        raise ValidationError(
            f"Missing required attributes: {sorted(missing)}. "
            f"Available attributes: {sorted(actual_keys)}"
        )


def validate_no_all_nan(df: pd.DataFrame, columns: Iterable[str]) -> None:
    """Validate that specified columns are not all NaN.

    Args:
        df: DataFrame to validate
        columns: Column names to check

    Raises:
        ValidationError: If any column is all NaN
    """
    all_nan_cols = []

    for col in columns:
        if col in df.columns:
            if df[col].isna().all():
                all_nan_cols.append(col)

    if all_nan_cols:
        raise ValidationError(
            f"Columns with all NaN values: {sorted(all_nan_cols)}"
        )
