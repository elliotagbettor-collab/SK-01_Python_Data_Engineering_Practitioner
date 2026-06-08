"""
Deliverable 1 - Multi-Source Ingestion Module

Loads all 4 HR data sources into standardised Pandas DataFrames and aligns
them to a common schema. Malformed or incomplete records are written to a
dead-letter CSV rather than crashing the pipeline.

Standard schema columns (every source is normalised to these after ingestion):
    employee_id, first_name, last_name, email, department, job_title,
    hire_date, country, employment_type, manager_id,
    base_salary, currency, pay_frequency, bonus_target_pct, effective_date,
    plan_type, coverage_level, enrollment_date, premium_employee,
    premium_employer, source_system, payroll_company_source
"""

import json
import logging
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from config import CONFIG
from utils import get_logger, log_dead_letter, log_record_counts

logger = get_logger(__name__, CONFIG["log_dir"])

STANDARD_COLUMNS = [
    "employee_id", "first_name", "last_name", "email", "department",
    "job_title", "hire_date", "country", "employment_type", "manager_id",
    "base_salary", "currency", "pay_frequency", "bonus_target_pct",
    "effective_date", "plan_type", "coverage_level", "enrollment_date",
    "premium_employee", "premium_employer", "source_system",
    "payroll_company_source",
]


def _ensure_standard_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add any missing standard columns as pd.NA without removing extra columns."""
    for col in STANDARD_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA
    return df


def ingest_globaltech_hris(
    filepath: Path = None,
    log_dir: Path = None,
) -> pd.DataFrame:
    """
    Ingest GlobalTech Workday CSV export.

    Column mapping (1:1 - field names already match standard schema):
        employee_id     integer, namespaced to GT-XXXXXX in clean.py
        first_name
        last_name
        email
        department      full names e.g. 'Engineering'
        job_title
        hire_date       format: YYYY-MM-DD
        country
        employment_type Full-Time / Part-Time / Contractor
        manager_id      integer, may be empty

    Salary columns absent here; enriched from payroll during dedup merge.
    """
    filepath = Path(filepath or CONFIG["sources"]["globaltech_hris"])
    log_dir  = Path(log_dir  or CONFIG["log_dir"])
    source   = "globaltech_hris"

    if not filepath.exists():
        logger.error("[%s] File not found: %s", source, filepath)
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    try:
        df = pd.read_csv(filepath, dtype=str, keep_default_na=False)
        raw_count = len(df)
        logger.info("[%s] Read %d rows from %s", source, raw_count, filepath.name)
    except Exception as exc:
        logger.error("[%s] Failed to read CSV: %s", source, exc)
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    required   = ["employee_id", "first_name", "last_name", "email"]
    clean_rows = []
    for _, row in df.iterrows():
        missing = [f for f in required if not str(row.get(f, "")).strip()]
        if missing:
            log_dead_letter(row.to_dict(), f"Missing required fields: {missing}", source, log_dir)
        else:
            clean_rows.append(row)

    if not clean_rows:
        logger.warning("[%s] All rows dropped to dead-letter", source)
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    result = pd.DataFrame(clean_rows).reset_index(drop=True)
    result["source_system"] = source
    result = _ensure_standard_columns(result)
    log_record_counts(logger, source, raw_count, len(result))
    return result


def ingest_acquiredco_api(
    filepath: Path = None,
    page_size: int = None,
    log_dir: Path = None,
) -> pd.DataFrame:
    """
    Ingest AcquiredCo BambooHR JSON export with simulated pagination.

    The full JSON is read from disk then sliced into page_size chunks to mimic
    real paginated API calls. Each page fetch is logged at DEBUG level.

    Column mapping:
        employee_identifier         -> employee_id   (ACQ_XXXXX -> AC-XXXXXX in clean.py)
        name.first                  -> first_name
        name.last                   -> last_name
        contact.email               -> email
        assignment.department       -> department
        assignment.role             -> job_title
        assignment.hire_timestamp   -> hire_date     (ISO 8601)
        assignment.location         -> country
        employment.type             -> employment_type  (FT/PT/CT expanded in clean.py)
        manager_employee_id         -> manager_id
    """
    filepath  = Path(filepath  or CONFIG["sources"]["acquiredco_api"])
    page_size = page_size or CONFIG["api_page_size"]
    log_dir   = Path(log_dir   or CONFIG["log_dir"])
    source    = "acquiredco_api"

    if not filepath.exists():
        logger.error("[%s] File not found: %s", source, filepath)
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    try:
        with open(filepath, encoding="utf-8") as f:
            payload = json.load(f)
        employees = payload.get("employees", [])
        total     = payload.get("total_records", len(employees))
        logger.info("[%s] API total_records=%d; %d loaded from file", source, total, len(employees))
    except Exception as exc:
        logger.error("[%s] Failed to parse JSON: %s", source, exc)
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    raw_count = len(employees)
    pages     = [employees[i:i + page_size] for i in range(0, len(employees), page_size)]
    all_rows  = []

    for page_num, page in enumerate(pages, start=1):
        logger.debug("[%s] Fetching page %d/%d (%d records)", source, page_num, len(pages), len(page))
        for emp in page:
            record = {}
            try:
                record = {
                    "employee_id":     emp.get("employee_identifier", ""),
                    "first_name":      emp.get("name", {}).get("first", ""),
                    "last_name":       emp.get("name", {}).get("last", ""),
                    "email":           emp.get("contact", {}).get("email", ""),
                    "department":      emp.get("assignment", {}).get("department", ""),
                    "job_title":       emp.get("assignment", {}).get("role", ""),
                    "hire_date":       emp.get("assignment", {}).get("hire_timestamp", ""),
                    "country":         emp.get("assignment", {}).get("location", ""),
                    "employment_type": emp.get("employment", {}).get("type", ""),
                    "manager_id":      emp.get("manager_employee_id", ""),
                }
                required = ["employee_id", "first_name", "last_name", "email"]
                missing  = [f for f in required if not str(record.get(f, "")).strip()]
                if missing:
                    log_dead_letter(record, f"Missing required fields: {missing}", source, log_dir)
                else:
                    all_rows.append(record)
            except Exception as exc:
                raw = emp if isinstance(emp, dict) else {"raw": str(emp)}
                log_dead_letter(raw, f"Parse error: {exc}", source, log_dir)

    if not all_rows:
        logger.warning("[%s] No valid rows extracted", source)
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    result = pd.DataFrame(all_rows)
    result["source_system"] = source
    result = _ensure_standard_columns(result)
    log_record_counts(logger, source, raw_count, len(result))
    return result


def ingest_payroll(
    filepath: Path = None,
    log_dir: Path = None,
) -> pd.DataFrame:
    """
    Ingest ADP payroll Excel export (.xlsx).

    Column mapping:
        employee_id      integer GlobalTech ID -> GT-XXXXXX in clean.py
        source           company name; stored as payroll_company_source for namespace
        base_salary      numeric (may be string with currency symbols)
        currency         USD / EUR / GBP
        pay_frequency    Annual / Monthly / Bi-Weekly
        bonus_target_pct float
        effective_date   YYYY-MM-DD

    Identity fields (name, email, department) come from HRIS; salary enriches
    the merged record in dedup.py.  ADP can have duplicate records per employee.
    """
    filepath = Path(filepath or CONFIG["sources"]["payroll"])
    log_dir  = Path(log_dir  or CONFIG["log_dir"])
    source   = "payroll"

    if not filepath.exists():
        logger.error("[%s] File not found: %s", source, filepath)
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    try:
        df = pd.read_excel(filepath, dtype=str)
        raw_count = len(df)
        logger.info("[%s] Read %d rows from %s", source, raw_count, filepath.name)
    except Exception as exc:
        logger.error("[%s] Failed to read Excel: %s", source, exc)
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    required   = ["employee_id", "base_salary"]
    clean_rows = []
    for _, row in df.iterrows():
        missing = [f for f in required if not str(row.get(f, "")).strip()]
        if missing:
            log_dead_letter(row.to_dict(), f"Missing required fields: {missing}", source, log_dir)
        else:
            clean_rows.append(row)

    if not clean_rows:
        logger.warning("[%s] All rows dropped to dead-letter", source)
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    result = pd.DataFrame(clean_rows).reset_index(drop=True)
    # Preserve the original 'source' column for namespace resolution in clean.py
    if "source" in result.columns:
        result["payroll_company_source"] = result["source"]
    else:
        result["payroll_company_source"] = "GlobalTech"
    result["source_system"] = source
    result = _ensure_standard_columns(result)
    log_record_counts(logger, source, raw_count, len(result))
    return result


def ingest_benefits(
    filepath: Path = None,
    log_dir: Path = None,
) -> pd.DataFrame:
    """
    Ingest MedShield XML benefits enrollment export using xml.etree.ElementTree.

    XML structure:
        <benefits_enrollments>
            <enrollment>
                <employee_id>      integer GlobalTech ID
                <plan_type>        e.g. Health Insurance / 401(k)
                <coverage_level>   Individual / Family / Employee+Spouse / Employee+Child
                <enrollment_date>  YYYY-MM-DD
                <premium_employee> float monthly contribution
                <premium_employer> float monthly contribution
            </enrollment>
        </benefits_enrollments>

    Covers GlobalTech employees only; not all employees are enrolled.
    """
    filepath = Path(filepath or CONFIG["sources"]["benefits"])
    log_dir  = Path(log_dir  or CONFIG["log_dir"])
    source   = "benefits"

    if not filepath.exists():
        logger.error("[%s] File not found: %s", source, filepath)
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    try:
        tree = ET.parse(filepath)
        root = tree.getroot()
    except ET.ParseError as exc:
        logger.error("[%s] XML parse error: %s", source, exc)
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    raw_count = 0
    all_rows  = []

    for enrollment in root.findall("enrollment"):
        raw_count += 1
        record: dict = {}
        try:
            record = {
                "employee_id":    (enrollment.findtext("employee_id")      or "").strip(),
                "plan_type":      (enrollment.findtext("plan_type")        or "").strip(),
                "coverage_level": (enrollment.findtext("coverage_level")   or "").strip(),
                "enrollment_date":(enrollment.findtext("enrollment_date")  or "").strip(),
                "premium_employee": enrollment.findtext("premium_employee"),
                "premium_employer": enrollment.findtext("premium_employer"),
            }
            if not record["employee_id"]:
                log_dead_letter(record, "Missing employee_id", source, log_dir)
            else:
                all_rows.append(record)
        except Exception as exc:
            log_dead_letter(record or {}, f"Parse error: {exc}", source, log_dir)

    logger.info("[%s] Parsed %d <enrollment> elements from %s", source, raw_count, filepath.name)

    if not all_rows:
        logger.warning("[%s] No valid enrollment records extracted", source)
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    result = pd.DataFrame(all_rows)
    result["source_system"] = source
    result = _ensure_standard_columns(result)
    log_record_counts(logger, source, raw_count, len(result))
    return result


def ingest_all() -> dict:
    """Run all 4 ingestion functions and return source_name -> DataFrame."""
    logger.info("=" * 60)
    logger.info("STEP 1  Multi-source ingestion starting")
    logger.info("=" * 60)

    dfs = {
        "globaltech_hris": ingest_globaltech_hris(),
        "acquiredco_api":  ingest_acquiredco_api(),
        "payroll":         ingest_payroll(),
        "benefits":        ingest_benefits(),
    }

    total = sum(len(df) for df in dfs.values())
    logger.info("Ingestion complete - %d total records across %d sources", total, len(dfs))
    return dfs
