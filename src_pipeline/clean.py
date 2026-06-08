"""
Deliverable 2 — Data Cleaning & Transformation Module

Functions
---------
normalize_names           Unicode normalization + title case (handles O'Brien, Van-Der-Berg)
namespace_employee_ids    GT-XXXXXX / AC-XXXXXX namespacing for all sources
normalize_employment_types  Expand FT/PT/CT abbreviations
map_departments           Unify GlobalTech codes and AcquiredCo names to a standard taxonomy
normalize_dates           Parse all date columns to datetime64[ns]; flag out-of-range values
normalize_salaries        Parse salary strings, convert to USD, annualise → salary_usd_annual
clean_all                 Orchestrates all steps on the merged DataFrame
"""

import re
import sys
import unicodedata
from pathlib import Path
from typing import Optional

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from config import CONFIG
from utils import get_logger

logger = get_logger(__name__, CONFIG["log_dir"])

_UNMAPPED_DEPARTMENTS: set[str] = set()

STANDARD_DEPARTMENTS = {
    "Engineering", "Marketing", "Human Resources", "Finance", "Operations",
    "Product", "Sales", "IT", "Legal", "Data Science", "DevOps",
    "Business Development", "Strategy", "Manufacturing", "Executive",
    "Customer Success", "Research & Development", "Accounting",
}

_DATE_FORMATS = [
    "%Y-%m-%d",
    "%Y-%m-%dT%H:%M:%S",
    "%m/%d/%Y",
    "%d-%b-%Y",
    "%d/%m/%Y",
    "%m-%d-%Y",
]

_HIRE_DATE_MIN = pd.Timestamp("1970-01-01")
_HIRE_DATE_MAX = pd.Timestamp.today().normalize()


# ── 1. Name Standardization ───────────────────────────────────────────────────

def _normalize_unicode(text: str) -> str:
    return unicodedata.normalize("NFC", text).strip() if isinstance(text, str) else text


def _title_case_name(name: str) -> str:
    """Title-case preserving hyphens and O' apostrophe prefixes."""
    if not isinstance(name, str) or not name.strip():
        return name
    parts = []
    for segment in name.split("-"):
        if "'" in segment:
            parts.append("'".join(s.capitalize() for s in segment.split("'")))
        else:
            parts.append(segment.capitalize())
    return "-".join(parts)


def normalize_names(df: pd.DataFrame) -> pd.DataFrame:
    for col in ("first_name", "last_name"):
        if col in df.columns:
            df[col] = df[col].apply(
                lambda x: _title_case_name(_normalize_unicode(x)) if pd.notna(x) else x
            )
    logger.debug(f"Name normalization applied to {len(df):,} records")
    return df


# ── 2. Employee ID Namespacing ────────────────────────────────────────────────

def _namespace_one_id(raw_id: str, source: str, company_hint: str = "") -> str:
    """Convert a raw ID string to GT-XXXXXX or AC-XXXXXX format."""
    raw_id = str(raw_id).strip()

    # Already namespaced — idempotent
    if re.match(r"^(GT|AC)-\d{6}$", raw_id):
        return raw_id

    # AcquiredCo JSON IDs come as ACQ_00001
    if raw_id.upper().startswith("ACQ_"):
        numeric = raw_id[4:].lstrip("0") or "0"
        try:
            return f"AC-{int(numeric):06d}"
        except ValueError:
            return f"AC-{raw_id[4:]}"

    # AcquiredCo API source → always AC
    if source == "acquiredco_api":
        try:
            return f"AC-{int(raw_id):06d}"
        except ValueError:
            return raw_id

    # Payroll records: check payroll_company_source column
    if source == "payroll":
        prefix = "AC" if "acquired" in company_hint.lower() else "GT"
        try:
            return f"{prefix}-{int(raw_id):06d}"
        except ValueError:
            return raw_id

    # GlobalTech HRIS / Benefits → GT
    prefix = CONFIG["id_namespace"].get(source, "GT")
    try:
        return f"{prefix}-{int(raw_id):06d}"
    except ValueError:
        logger.warning(f"Cannot namespace ID '{raw_id}' from source '{source}'")
        return raw_id


def namespace_employee_ids(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    def _apply_id(row):
        return _namespace_one_id(
            row["employee_id"],
            str(row.get("source_system", "")),
            str(row.get("payroll_company_source", "")),
        )

    def _apply_mgr(row):
        raw = str(row.get("manager_id", "")).strip()
        if not raw or raw in ("nan", "None", ""):
            return pd.NA
        return _namespace_one_id(
            raw,
            str(row.get("source_system", "")),
            str(row.get("payroll_company_source", "")),
        )

    df["employee_id"] = df.apply(_apply_id, axis=1)
    df["manager_id"]  = df.apply(_apply_mgr, axis=1)
    logger.debug(f"Employee ID namespacing complete on {len(df):,} records")
    return df


# ── 3. Employment Type Normalization ─────────────────────────────────────────

def normalize_employment_types(df: pd.DataFrame) -> pd.DataFrame:
    type_map = CONFIG["employment_type_map"]

    def _norm(val):
        if pd.isna(val) or not str(val).strip():
            return pd.NA
        return type_map.get(str(val).strip(), str(val).strip())

    df["employment_type"] = df["employment_type"].apply(_norm)
    return df


# ── 4. Department Taxonomy Mapping ────────────────────────────────────────────

_AC_DEPT_ALIASES = {
    "HR":        "Human Resources",
    "Tech":      "Engineering",
    "R&D":       "Research & Development",
    "Acctg":     "Accounting",
    "Mktg":      "Marketing",
    "Biz Dev":   "Business Development",
    "Cust Succ": "Customer Success",
}


def map_departments(df: pd.DataFrame) -> pd.DataFrame:
    """
    Unify GlobalTech codes (e.g. ENG-01) and AcquiredCo names (e.g. Engineering)
    to a standard department taxonomy.  Logs unmapped values for manual review.
    """
    code_map = CONFIG["dept_code_map"]

    def _map(dept):
        if pd.isna(dept):
            return pd.NA
        dept = str(dept).strip()
        if not dept or dept == "nan":
            return pd.NA
        if dept in STANDARD_DEPARTMENTS:
            return dept
        # GlobalTech codes (e.g. ENG-01)
        if re.match(r"^[A-Z]+-\d{2,}$", dept):
            mapped = code_map.get(dept)
            if mapped:
                return mapped
        # AcquiredCo aliases
        alias = _AC_DEPT_ALIASES.get(dept)
        if alias:
            return alias
        # Case-insensitive match against standard set
        dept_lower = dept.lower()
        for std in STANDARD_DEPARTMENTS:
            if std.lower() == dept_lower:
                return std
        _UNMAPPED_DEPARTMENTS.add(dept)
        return dept

    df["department"] = df["department"].apply(_map)

    if _UNMAPPED_DEPARTMENTS:
        logger.warning(f"Unmapped departments (manual review required): {sorted(_UNMAPPED_DEPARTMENTS)}")

    return df


# ── 5. Date Standardization ───────────────────────────────────────────────────

def _parse_date(value) -> pd.Timestamp:
    if pd.isna(value) or not str(value).strip():
        return pd.NaT
    s = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return pd.to_datetime(s, format=fmt)
        except (ValueError, TypeError):
            continue
    return pd.to_datetime(s, errors="coerce")


def normalize_dates(df: pd.DataFrame) -> pd.DataFrame:
    for col in ("hire_date", "effective_date", "enrollment_date"):
        if col in df.columns:
            df[col] = df[col].apply(_parse_date)
            df[col] = pd.to_datetime(df[col], errors="coerce")

    if "hire_date" in df.columns:
        too_old = df["hire_date"] < _HIRE_DATE_MIN
        too_new = df["hire_date"] > _HIRE_DATE_MAX
        df["hire_date_flag"] = pd.NA
        df.loc[too_old, "hire_date_flag"] = f"hire_date before {_HIRE_DATE_MIN.date()}"
        df.loc[too_new, "hire_date_flag"] = f"hire_date after {_HIRE_DATE_MAX.date()}"
        flagged = (too_old | too_new).sum()
        if flagged:
            logger.warning(f"hire_date out of valid range on {flagged:,} records")

    logger.debug(f"Date normalization complete on {len(df):,} records")
    return df


# ── 6. Salary / Currency Normalization ───────────────────────────────────────

def _parse_salary(value) -> Optional[float]:
    if pd.isna(value) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    s = re.sub(r"[£€$,\s]", "", str(value).strip())
    try:
        result = float(s)
        return result if result > 0 else None
    except ValueError:
        return None


def normalize_salaries(df: pd.DataFrame) -> pd.DataFrame:
    """
    1. Parse base_salary strings → float
    2. Convert currency to USD via fixed FX rates
    3. Annualise via pay_frequency multiplier
    4. Write result to salary_usd_annual (original columns retained)
    """
    fx   = CONFIG["fx_rates_to_usd"]
    mult = CONFIG["pay_frequency_multiplier"]

    df["base_salary"] = df["base_salary"].apply(_parse_salary)

    def _to_usd_annual(row) -> Optional[float]:
        salary = row.get("base_salary")
        if salary is None or pd.isna(salary):
            return pd.NA
        currency = str(row.get("currency", "USD")).strip().upper()
        freq     = str(row.get("pay_frequency", "Annual")).strip()
        return round(salary * fx.get(currency, 1.0) * mult.get(freq, 1), 2)

    df["salary_usd_annual"] = df.apply(_to_usd_annual, axis=1)
    non_null = df["salary_usd_annual"].notna().sum()
    logger.debug(
        f"Salary normalization: {non_null:,}/{len(df):,} records have salary_usd_annual"
    )
    return df


# ── 7. Orchestrator ──────────────────────────────────────────────────────────

def clean_all(dfs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Concatenate all source DataFrames and run every cleaning step."""
    logger.info("=" * 60)
    logger.info("STEP 2  Data cleaning starting")
    logger.info("=" * 60)

    combined = pd.concat(dfs.values(), ignore_index=True)
    logger.info(f"Combined: {len(combined):,} rows from {len(dfs)} sources")

    combined = normalize_names(combined)
    combined = namespace_employee_ids(combined)
    combined = normalize_employment_types(combined)
    combined = map_departments(combined)
    combined = normalize_dates(combined)
    combined = normalize_salaries(combined)

    logger.info(f"Cleaning complete — {len(combined):,} records, {len(combined.columns)} columns")
    return combined
