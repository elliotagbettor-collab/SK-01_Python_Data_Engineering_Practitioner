"""Unit tests for validate.py DataQualityValidator."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from validate import DataQualityValidator


def _sample_df() -> pd.DataFrame:
    return pd.DataFrame({
        "employee_id":       ["GT-000001", "GT-000002", "AC-000001"],
        "first_name":        ["Alice", "Bob", "Carol"],
        "last_name":         ["Smith", "Jones", "Lee"],
        "email":             ["alice@gt.com", "bob@gt.com", "carol@ac.com"],
        "department":        ["Engineering", "Marketing", "Sales"],
        "country":           ["US", "DE", "JP"],
        "employment_type":   ["Full-Time", "Part-Time", "Contractor"],
        "currency":          ["USD", "EUR", "GBP"],
        "salary_usd_annual": [85000.0, 75000.0, 95000.0],
        "hire_date":         pd.to_datetime(["2020-01-15", "2019-06-01", "2022-03-10"]),
        "manager_id":        [pd.NA, "GT-000001", "GT-000001"],
    })


class TestNotNull:
    def test_no_nulls_passes(self):
        v = DataQualityValidator(_sample_df())
        v.check_not_null("employee_id")
        assert v.report().iloc[0]["status"] == "PASS"

    def test_null_fails(self):
        df = _sample_df()
        df.at[0, "email"] = None
        v = DataQualityValidator(df)
        v.check_not_null("email")
        assert v.report().iloc[0]["failed"] == 1


class TestUnique:
    def test_unique_passes(self):
        v = DataQualityValidator(_sample_df())
        v.check_unique("employee_id")
        assert v.report().iloc[0]["status"] == "PASS"

    def test_duplicate_fails(self):
        df = _sample_df()
        df.at[1, "email"] = "alice@gt.com"
        v = DataQualityValidator(df)
        v.check_unique("email")
        assert v.report().iloc[0]["status"] == "FAIL"


class TestValuesInSet:
    def test_all_valid_passes(self):
        v = DataQualityValidator(_sample_df())
        v.check_values_in_set("employment_type", {"Full-Time", "Part-Time", "Contractor"})
        assert v.report().iloc[0]["status"] == "PASS"

    def test_invalid_value_fails(self):
        df = _sample_df()
        df.at[0, "employment_type"] = "CONTRACTOR"
        v = DataQualityValidator(df)
        v.check_values_in_set("employment_type", {"Full-Time", "Part-Time", "Contractor"})
        assert v.report().iloc[0]["failed"] == 1


class TestRegex:
    def test_valid_email_passes(self):
        v = DataQualityValidator(_sample_df())
        v.check_regex("email", r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$", "email")
        assert v.report().iloc[0]["status"] == "PASS"

    def test_invalid_id_fails(self):
        df = _sample_df()
        df.at[0, "employee_id"] = "XX-99999"
        v = DataQualityValidator(df)
        v.check_regex("employee_id", r"^(GT|AC)-\d{6}$", "employee_id format")
        assert v.report().iloc[0]["failed"] == 1


class TestNumericRange:
    def test_valid_salary_passes(self):
        v = DataQualityValidator(_sample_df())
        v.check_numeric_range("salary_usd_annual", 15_000, 10_000_000)
        assert v.report().iloc[0]["status"] == "PASS"

    def test_below_min_fails(self):
        df = _sample_df()
        df.at[0, "salary_usd_annual"] = 5000.0
        v = DataQualityValidator(df)
        v.check_numeric_range("salary_usd_annual", 15_000, 10_000_000)
        assert v.report().iloc[0]["failed"] == 1


class TestReferentialIntegrity:
    def test_valid_manager_refs_pass(self):
        v = DataQualityValidator(_sample_df())
        v.check_referential_integrity("manager_id", "employee_id")
        assert v.report().iloc[0]["status"] == "PASS"

    def test_orphan_manager_fails(self):
        df = _sample_df()
        df.at[0, "manager_id"] = "GT-999999"
        v = DataQualityValidator(df)
        v.check_referential_integrity("manager_id", "employee_id")
        assert v.report().iloc[0]["failed"] == 1
