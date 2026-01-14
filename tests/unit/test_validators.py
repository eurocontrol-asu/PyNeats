"""Unit tests for primitive validators (Layer 1)."""

import pandas as pd
import pytest

from pyneats.core.validators import ValidationError, validate_attrs, validate_columns, validate_no_all_nan


class TestValidateColumns:
    """Test validate_columns function."""

    def test_valid_dataframe_with_required_columns(self) -> None:
        """Test that DataFrame with all required columns passes validation."""
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4], "c": [5, 6]})
        validate_columns(df, required=["a", "b"])  # Should not raise

    def test_valid_dataframe_with_optional_columns(self) -> None:
        """Test that optional columns parameter is accepted (not enforced)."""
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        validate_columns(df, required=["a"], optional=["c", "d"])  # Should not raise

    def test_missing_required_column_raises_error(self) -> None:
        """Test that missing required column raises ValidationError."""
        df = pd.DataFrame({"a": [1, 2]})
        with pytest.raises(ValidationError, match="Missing required columns: \\['b'\\]"):
            validate_columns(df, required=["a", "b"])

    def test_missing_multiple_required_columns(self) -> None:
        """Test error message with multiple missing columns."""
        df = pd.DataFrame({"a": [1, 2]})
        with pytest.raises(ValidationError, match="Missing required columns: \\['b', 'c'\\]"):
            validate_columns(df, required=["a", "b", "c"])

    def test_error_message_includes_available_columns(self) -> None:
        """Test that error message includes available columns."""
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        with pytest.raises(ValidationError, match="Available columns: \\['a', 'b'\\]"):
            validate_columns(df, required=["c"])

    def test_empty_required_columns(self) -> None:
        """Test that empty required list passes validation."""
        df = pd.DataFrame({"a": [1, 2]})
        validate_columns(df, required=[])  # Should not raise

    def test_empty_dataframe_with_no_required_columns(self) -> None:
        """Test that empty DataFrame passes when no columns required."""
        df = pd.DataFrame()
        validate_columns(df, required=[])  # Should not raise

    @pytest.mark.parametrize(
        "required,expected_missing",
        [
            (["x"], ["x"]),
            (["x", "y"], ["x", "y"]),
            (["a", "x"], ["x"]),
        ],
    )
    def test_parametrized_missing_columns(self, required: list[str], expected_missing: list[str]) -> None:
        """Test various combinations of missing columns."""
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        pattern = f"Missing required columns: {sorted(expected_missing)}"
        with pytest.raises(ValidationError, match=pattern.replace("[", r"\[").replace("]", r"\]")):
            validate_columns(df, required=required)


class TestValidateAttrs:
    """Test validate_attrs function."""

    def test_valid_dict_with_required_keys(self) -> None:
        """Test that dict with all required keys passes validation."""
        attrs = {"flight_id": "ABC123", "aircraft_type": "A320", "fuel": "JET-A1"}
        validate_attrs(attrs, required=["flight_id", "aircraft_type"])  # Should not raise

    def test_valid_dict_with_optional_keys(self) -> None:
        """Test that optional keys parameter is accepted (not enforced)."""
        attrs = {"flight_id": "ABC123"}
        validate_attrs(attrs, required=["flight_id"], optional=["aircraft_type", "fuel"])  # Should not raise

    def test_missing_required_key_raises_error(self) -> None:
        """Test that missing required key raises ValidationError."""
        attrs = {"flight_id": "ABC123"}
        with pytest.raises(ValidationError, match="Missing required attributes: \\['aircraft_type'\\]"):
            validate_attrs(attrs, required=["flight_id", "aircraft_type"])

    def test_missing_multiple_required_keys(self) -> None:
        """Test error message with multiple missing keys."""
        attrs = {"flight_id": "ABC123"}
        with pytest.raises(ValidationError, match="Missing required attributes: \\['aircraft_type', 'fuel'\\]"):
            validate_attrs(attrs, required=["flight_id", "aircraft_type", "fuel"])

    def test_error_message_includes_available_attributes(self) -> None:
        """Test that error message includes available keys."""
        attrs = {"flight_id": "ABC123", "aircraft_type": "A320"}
        with pytest.raises(ValidationError, match="Available attributes: \\['aircraft_type', 'flight_id'\\]"):
            validate_attrs(attrs, required=["fuel"])

    def test_empty_required_keys(self) -> None:
        """Test that empty required list passes validation."""
        attrs = {"flight_id": "ABC123"}
        validate_attrs(attrs, required=[])  # Should not raise

    def test_empty_dict_with_no_required_keys(self) -> None:
        """Test that empty dict passes when no keys required."""
        attrs: dict[str, str] = {}
        validate_attrs(attrs, required=[])  # Should not raise

    @pytest.mark.parametrize(
        "required,expected_missing",
        [
            (["x"], ["x"]),
            (["x", "y"], ["x", "y"]),
            (["flight_id", "x"], ["x"]),
        ],
    )
    def test_parametrized_missing_keys(self, required: list[str], expected_missing: list[str]) -> None:
        """Test various combinations of missing keys."""
        attrs = {"flight_id": "ABC123", "aircraft_type": "A320"}
        pattern = f"Missing required attributes: {sorted(expected_missing)}"
        with pytest.raises(ValidationError, match=pattern.replace("[", r"\[").replace("]", r"\]")):
            validate_attrs(attrs, required=required)


class TestValidateNoAllNan:
    """Test validate_no_all_nan function."""

    def test_valid_columns_with_no_nans(self) -> None:
        """Test that columns with no NaNs pass validation."""
        df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
        validate_no_all_nan(df, columns=["a", "b"])  # Should not raise

    def test_valid_columns_with_some_nans(self) -> None:
        """Test that columns with some (but not all) NaNs pass validation."""
        df = pd.DataFrame({"a": [1, None, 3], "b": [None, 5, 6]})
        validate_no_all_nan(df, columns=["a", "b"])  # Should not raise

    def test_column_with_all_nans_raises_error(self) -> None:
        """Test that column with all NaNs raises ValidationError."""
        df = pd.DataFrame({"a": [1, 2, 3], "b": [None, None, None]})
        with pytest.raises(ValidationError, match="Columns with all NaN values: \\['b'\\]"):
            validate_no_all_nan(df, columns=["a", "b"])

    def test_multiple_columns_with_all_nans(self) -> None:
        """Test error message with multiple all-NaN columns."""
        df = pd.DataFrame({"a": [None, None], "b": [None, None], "c": [1, 2]})
        with pytest.raises(ValidationError, match="Columns with all NaN values: \\['a', 'b'\\]"):
            validate_no_all_nan(df, columns=["a", "b", "c"])

    def test_ignores_nonexistent_columns(self) -> None:
        """Test that nonexistent columns are silently ignored."""
        df = pd.DataFrame({"a": [1, 2, 3]})
        validate_no_all_nan(df, columns=["a", "nonexistent"])  # Should not raise

    def test_empty_columns_list(self) -> None:
        """Test that empty columns list passes validation."""
        df = pd.DataFrame({"a": [None, None]})
        validate_no_all_nan(df, columns=[])  # Should not raise

    def test_empty_dataframe(self) -> None:
        """Test that empty DataFrame passes validation."""
        df = pd.DataFrame()
        validate_no_all_nan(df, columns=["a", "b"])  # Should not raise

    @pytest.mark.parametrize(
        "data,columns,expected_all_nan",
        [
            ({"a": [None, None], "b": [1, 2]}, ["a", "b"], ["a"]),
            ({"a": [None, None], "b": [None, None]}, ["a", "b"], ["a", "b"]),
            ({"a": [1, None], "b": [None, None]}, ["a", "b"], ["b"]),
        ],
    )
    def test_parametrized_all_nan_detection(
        self, data: dict[str, list[int | None]], columns: list[str], expected_all_nan: list[str]
    ) -> None:
        """Test various combinations of all-NaN columns."""
        df = pd.DataFrame(data)
        pattern = f"Columns with all NaN values: {sorted(expected_all_nan)}"
        with pytest.raises(ValidationError, match=pattern.replace("[", r"\[").replace("]", r"\]")):
            validate_no_all_nan(df, columns=columns)
