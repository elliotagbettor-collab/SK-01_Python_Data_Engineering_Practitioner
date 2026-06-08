"""Unit tests for clean.py cleaning functions."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from clean import (
    normalize_names,
    normalize_employment_types,
    namespace_employee_ids,
    map_departments,
    normalize_dates,
    normalize_salaries,
)


def _make_df(**kwargs) -> pd.DataFrame:
    """Build a minimal test DataFrame."""
    base = {
        "employee_id": ["1", "2"],
        "first_name": ["alice", "BOB"],
        "last_name": ["o'brien", "van-der-berg"],
        "email": ["a@test.com", "b@test.com"],
        "department": ["Engineering", "ENG-01"],
        "job_title": ["engineer", "manager"],
        "hire_date": ["2022-01-15", "2020-06-30"],
        "country": ["US", "DE"],
        "employment_type": ["FT", "CONTRACTOR"],
        "manager_id": ["5", pd.NA],
        "base_salary": ["85000", "120000"],
        "currency": ["USD", "EUR"],
        "pay_frequency": ["Annual", "Monthly"],
        "bonus_target_pct": [10.0, pd.NA],
        "effective_date": [pd.NA, pd.NA],
        "plan_type": [pd.NA, pd.NA],
        "coverage_level": [pd.NA, pd.NA],
        "enrollment_date": [pd.NA, pd.NA],
        "premium_employee": [pd.NA, pd.NA],
        "premium_employer": [pd.NA, pd.NA],
        "source_system": ["globaltech_hris", "acquiredco_api"],
        "payroll_company_source": [pd.NA, pd.NA],
    }
    base.update(kwargs)
    return pd.DataFrame(base)


class TestNormalizeNames:
    def test_title_case_basic(self):
        df = _make_df(first_name=["alice", "BOB"], last_name=["smith", "JONES"])
        result = normalize_names(df)
        assert result["first_name"].tolist() == ["Alice", "Bob"]
        assert result["last_name"].tolist() == ["Smith", "Jones"]

    def test_apostrophe_name(self):
        df = _make_df(last_name=["o'brien", "d'angelo"])
        result = normalize_names(df)
        assert result["last_name"].tolist() == ["O'Brien", "D'Angelo"]

    def test_hyphenated_name(self):
        df = _make_df(last_name=["van-der-berg", "smith-jones"])
        result = normalize_names(df)
        assert result["last_name"].tolist() == ["Van-Der-Berg", "Smith-Jones"]


class TestNormalizeEmploymentTypes:
    def test_abbreviation_expansion(self):
        df = _make_df(employment_type=["FT", "PT"])
        result = normalize_employment_types(df)
        assert result["employment_type"].tolist() == ["Full-Time", "Part-Time"]

    def test_contractor_all_caps(self):
        df = _make_df(employment_type=["CONTRACTOR", "Contractor"])
        result = normalize_employment_types(df)
        assert result["employment_type"].tolist() == ["Contractor", "Contractor"]

    def test_already_standard(self):
        df = _make_df(employment_type=["Full-Time", "Part-Time"])
        result = normalize_employment_types(df)
        assert result["employment_type"].tolist() == ["Full-Time", "Part-Time"]


class TestNamespaceEmployeeIds:
    def test_globaltech_integer(self):
        df = _make_df(employee_id=["42", "1042"])
        result = namespace_employee_ids(df)
        assert result["employee_id"].tolist() == ["GT-000042", "GT-001042"]

    def test_acquiredco_acq_prefix(self):
        df = _make_df(
            employee_id=["ACQ_00001", "ACQ_02436"],
            source_system=["acquiredco_api", "acquiredco_api"],
        )
        result = namespace_employee_ids(df)
        assert result["employee_id"].tolist() == ["AC-000001", "AC-002436"]

    def test_idempotent_if_already_namespaced(self):
        df = _make_df(employee_id=["GT-001042", "AC-000001"])
        result = namespace_employee_ids(df)
        assert result["employee_id"].tolist() == ["GT-001042", "AC-000001"]

    def test_manager_na_stays_na(self):
        df = _make_df(manager_id=[pd.NA, pd.NA])
        result = namespace_employee_ids(df)
        assert pd.isna(result["manager_id"].iloc[0])


class TestMapDepartments:
    def test_globaltech_code(self):
        df = _make_df(department=["ENG-01", "MKT-03"])
        result = map_departments(df)
        assert result["department"].tolist() == ["Engineering", "Marketing"]

    def test_already_standard(self):
        df = _make_df(department=["Engineering", "Finance"])
        result = map_departments(df)
        assert result["department"].tolist() == ["Engineering", "Finance"]

    def test_information_technology_alias(self):
        df = _make_df(department=["Information Technology", "HR"])
        result = map_departments(df)
        assert result["department"].tolist() == ["IT", "Human Resources"]


class TestNormalizeDates:
    def test_iso_format(self):
        df = _make_df(hire_date=["2022-01-15", "2020-06-30"])
        result = normalize_dates(df)
        assert pd.api.types.is_datetime64_any_dtype(result["hire_date"])
        assert result["hire_date"].iloc[0] == pd.Timestamp("2022-01-15")

    def test_iso8601_with_time(self):
        df = _make_df(hire_date=["2021-06-09T00:00:00", "2020-01-01T00:00:00"])
        result = normalize_dates(df)
        assert result["hire_date"].iloc[0] == pd.Timestamp("2021-06-09")

    def test_out_of_range_flagged(self):
        df = _make_df(hire_date=["1960-01-01", "2022-01-01"])
        result = normalize_dates(df)
        assert pd.notna(result["hire_date_flag"].iloc[0])  # 1960 < 1970 → flagged
        assert pd.isna(result["hire_date_flag"].iloc[1])   # 2022 is fine


class TestNormalizeSalaries:
    def test_annual_usd(self):
        df = _make_df(base_salary=["85000"], currency=["USD"], pay_frequency=["Annual"])
        result = normalize_salaries(df)
        assert result["salary_usd_annual"].iloc[0] == pytest.approx(85000.0)

    def test_monthly_eur(self):
        df = _make_df(base_salary=["5000"], currency=["EUR"], pay_frequency=["Monthly"])
        result = normalize_salaries(df)
        expected = round(5000 * 1.09 * 12, 2)
        assert result["salary_usd_annual"].iloc[0] == pytest.approx(expected)

    def test_string_with_currency_symbol(self):
        df = _make_df(base_salary=["$85,000"], currency=["USD"], pay_frequency=["Annual"])
        result = normalize_salaries(df)
        assert result["salary_usd_annual"].iloc[0] == pytest.approx(85000.0)

    def test_null_salary_stays_null(self):
        df = _make_df(base_salary=[pd.NA], currency=["USD"], pay_frequency=["Annual"])
        result = normalize_salaries(df)
        assert pd.isna(result["salary_usd_annual"].iloc[0])
