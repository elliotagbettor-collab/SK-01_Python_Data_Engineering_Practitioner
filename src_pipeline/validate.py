"""
Deliverable 4 — Data Quality Validation Module

DataQualityValidator runs 12+ checks and produces a structured report.
Pipeline gate halts execution if more than 2 checks fail.

Report columns: check | description | total | passed | failed | pass_rate | status
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from config import CONFIG
from utils import get_logger

logger = get_logger(__name__, CONFIG["log_dir"])


class DataQualityValidator:
    def __init__(self, df: pd.DataFrame):
        self.df = df.copy()
        self._results: list[dict] = []

    # ── Internal recorder ────────────────────────────────────────────────────

    def _record(
        self,
        check: str,
        description: str,
        total: int,
        failed: int,
        status_override: str = None,
    ) -> "DataQualityValidator":
        passed    = total - failed
        pass_rate = passed / total if total > 0 else 0.0
        threshold = CONFIG["quality_threshold"]
        status    = status_override or ("PASS" if pass_rate >= threshold else "FAIL")
        self._results.append({
            "check":       check,
            "description": description,
            "total":       total,
            "passed":      passed,
            "failed":      failed,
            "pass_rate":   round(pass_rate, 4),
            "status":      status,
        })
        return self

    # ── Check types ──────────────────────────────────────────────────────────

    def check_not_null(self, column: str) -> "DataQualityValidator":
        total  = len(self.df)
        failed = int(self.df[column].isna().sum()) if column in self.df.columns else total
        return self._record(f"not_null.{column}", f"{column} must not be null", total, failed)

    def check_unique(self, column: str) -> "DataQualityValidator":
        if column not in self.df.columns:
            return self._record(f"unique.{column}", f"{column} must be unique", 0, 0, "SKIP")
        total  = len(self.df)
        failed = total - int(self.df[column].nunique(dropna=True))
        return self._record(
            f"unique.{column}",
            f"{column} must be unique across all records",
            total, failed,
        )

    def check_values_in_set(self, column: str, valid_set: set) -> "DataQualityValidator":
        if column not in self.df.columns:
            return self._record(f"values_in_set.{column}", f"{column} ∈ {valid_set}", 0, 0, "SKIP")
        non_null = self.df[column].dropna()
        total    = len(non_null)
        failed   = int((~non_null.isin(valid_set)).sum())
        return self._record(
            f"values_in_set.{column}",
            f"{column} ∈ {{{', '.join(sorted(str(v) for v in valid_set))}}}",
            total, failed,
        )

    def check_regex(self, column: str, pattern: str, description: str) -> "DataQualityValidator":
        if column not in self.df.columns:
            return self._record(f"regex.{column}", description, 0, 0, "SKIP")
        non_null = self.df[column].dropna().astype(str)
        total    = len(non_null)
        failed   = int((~non_null.str.match(pattern)).sum())
        return self._record(f"regex.{column}", description, total, failed)

    def check_numeric_range(
        self, column: str, min_val: float, max_val: float
    ) -> "DataQualityValidator":
        if column not in self.df.columns:
            return self._record(
                f"numeric_range.{column}", f"{column} in [{min_val}, {max_val}]", 0, 0, "SKIP"
            )
        numeric = pd.to_numeric(self.df[column], errors="coerce").dropna()
        total   = len(numeric)
        failed  = int(((numeric < min_val) | (numeric > max_val)).sum())
        return self._record(
            f"numeric_range.{column}",
            f"{column} between {min_val:,} and {max_val:,}",
            total, failed,
        )

    def check_date_range(
        self, column: str, min_date: str, max_date: str = None
    ) -> "DataQualityValidator":
        if column not in self.df.columns:
            return self._record(
                f"date_range.{column}",
                f"{column} between {min_date} and {max_date or 'today'}",
                0, 0, "SKIP",
            )
        dates   = pd.to_datetime(self.df[column], errors="coerce").dropna()
        total   = len(dates)
        min_ts  = pd.Timestamp(min_date)
        max_ts  = pd.Timestamp(max_date) if max_date else pd.Timestamp.today().normalize()
        failed  = int(((dates < min_ts) | (dates > max_ts)).sum())
        return self._record(
            f"date_range.{column}",
            f"{column} between {min_date} and {max_date or 'today'}",
            total, failed,
        )

    def check_referential_integrity(
        self, fk_column: str, pk_column: str
    ) -> "DataQualityValidator":
        if fk_column not in self.df.columns or pk_column not in self.df.columns:
            return self._record(
                f"ref_integrity.{fk_column}",
                f"Every {fk_column} must exist as a {pk_column}",
                0, 0, "SKIP",
            )
        pk_set  = set(self.df[pk_column].dropna().unique())
        fk_vals = self.df[fk_column].dropna()
        total   = len(fk_vals)
        failed  = int((~fk_vals.isin(pk_set)).sum())
        return self._record(
            f"ref_integrity.{fk_column}",
            f"Every {fk_column} must exist as an {pk_column}",
            total, failed,
        )

    # ── Run all 12+ required checks ──────────────────────────────────────────

    def run_all_checks(self) -> "DataQualityValidator":
        cfg = CONFIG
        # NOT NULL (6 fields)
        for col in ("employee_id", "first_name", "last_name", "email", "department", "country"):
            self.check_not_null(col)
        # UNIQUE (2)
        self.check_unique("email")
        self.check_unique("employee_id")
        # VALUES IN SET (2)
        self.check_values_in_set("employment_type", cfg["valid_employment_types"])
        self.check_values_in_set("currency",        cfg["valid_currencies"])
        # REGEX (2)
        self.check_regex("email",       cfg["email_regex"],         "email format (RFC 5321)")
        self.check_regex("employee_id", cfg["employee_id_pattern"], "employee_id format GT-XXXXXX or AC-XXXXXX")
        # NUMERIC RANGE (1)
        self.check_numeric_range("salary_usd_annual", cfg["salary_min_usd"], cfg["salary_max_usd"])
        # DATE RANGE (1)
        self.check_date_range("hire_date", cfg["hire_date_min"])
        # REFERENTIAL INTEGRITY (1)
        self.check_referential_integrity("manager_id", "employee_id")
        return self

    # ── Report & export ──────────────────────────────────────────────────────

    def report(self) -> pd.DataFrame:
        return pd.DataFrame(self._results)

    def export_report(self, csv_path: Path, html_path: Path) -> None:
        report_df = self.report()
        csv_path  = Path(csv_path)
        html_path = Path(html_path)
        csv_path.parent.mkdir(parents=True, exist_ok=True)

        report_df.to_csv(csv_path, index=False)

        html_rows = ""
        for _, row in report_df.iterrows():
            css = "background:#d4edda" if row["status"] == "PASS" else "background:#f8d7da"
            html_rows += (
                f"<tr style='{css}'>"
                + "".join(f"<td>{row[c]}</td>" for c in report_df.columns)
                + "</tr>\n"
            )

        header_cells = "".join(f"<th>{c}</th>" for c in report_df.columns)
        now = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Data Quality Report</title>
<style>
  body{{font-family:Arial,sans-serif;margin:40px}}
  table{{border-collapse:collapse;width:100%}}
  th,td{{border:1px solid #ccc;padding:8px;text-align:left}}
  th{{background:#343a40;color:#fff}}
</style></head><body>
<h1>GlobalTech HR Integration — Data Quality Report</h1>
<p>Generated: {now}</p>
<table><thead><tr>{header_cells}</tr></thead><tbody>
{html_rows}</tbody></table>
</body></html>"""

        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)

        logger.info(f"Validation report → {csv_path.name} and {html_path.name}")

    def check_pipeline_gate(self) -> bool:
        failures = int((self.report()["status"] == "FAIL").sum())
        max_fail = CONFIG["pipeline_gate_max_failures"]
        if failures > max_fail:
            logger.critical(
                f"PIPELINE GATE FAILED: {failures} checks failed "
                f"(max allowed: {max_fail}). Halting — review validation_report.html"
            )
            return False
        logger.info(f"Pipeline gate PASSED ({failures}/{len(self._results)} checks failed)")
        return True


def run_validation(df: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    """Convenience wrapper: run all checks, return (report_df, gate_passed)."""
    logger.info("=" * 60)
    logger.info("STEP 4  Data quality validation starting")
    logger.info("=" * 60)
    v = DataQualityValidator(df)
    v.run_all_checks()
    gate_ok = v.check_pipeline_gate()
    return v.report(), gate_ok, v
