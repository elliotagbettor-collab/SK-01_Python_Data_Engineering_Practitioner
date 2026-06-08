"""
Deliverable 3 — Deduplication Module

Pass 1 — Exact employee_id match (coalesce merge by source priority)
Pass 2 — Email match across companies (contractor overlap)
Pass 3 — Fuzzy name + hire date (flags probable matches for HR review; no auto-merge)
Ghost detection — payroll records with no HRIS counterpart
"""

import sys
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz

sys.path.insert(0, str(Path(__file__).parent))
from config import CONFIG
from utils import get_logger

logger = get_logger(__name__, CONFIG["log_dir"])

_PRIORITY = CONFIG["source_priority"]


def _priority(source_system: str) -> int:
    sources = [s.strip() for s in str(source_system).split(",")]
    return min(_PRIORITY.get(s, 99) for s in sources)


# ── Pass 1: Exact employee_id — coalesce merge ────────────────────────────────

def pass1_exact_id(df: pd.DataFrame) -> pd.DataFrame:
    """
    For every unique employee_id, merge all source rows by taking the first
    non-null value for each field from the highest-priority source.

    source_systems  →  comma-joined list of all contributing sources
    dedup_method    →  'exact_id' if merged across sources; 'single_source' otherwise
    """
    before = len(df)
    df = df.copy()
    df["_priority"] = df["source_system"].apply(_priority)
    df = df.sort_values(["employee_id", "_priority"]).reset_index(drop=True)

    skip_cols = {"_priority", "source_systems", "dedup_method", "source_system"}
    merge_cols = [c for c in df.columns if c not in skip_cols and c != "employee_id"]

    result_rows = []
    for emp_id, group in df.groupby("employee_id", sort=False):
        row: dict = {"employee_id": emp_id}
        all_sources = sorted(group["source_system"].dropna().unique().tolist())

        for col in merge_cols:
            col_vals = group[col].dropna()
            non_empty = col_vals[col_vals.astype(str).str.strip().ne("").ne("nan")]
            row[col] = non_empty.iloc[0] if len(non_empty) > 0 else pd.NA

        row["source_systems"] = ",".join(all_sources)
        row["dedup_method"] = "exact_id" if len(all_sources) > 1 else "single_source"
        result_rows.append(row)

    result = pd.DataFrame(result_rows).reset_index(drop=True)
    removed = before - len(result)
    logger.info(
        f"Pass 1 (exact_id): {before:,} → {len(result):,} records "
        f"({removed:,} rows merged via coalesce)"
    )
    return result


# ── Pass 2: Email match across companies ─────────────────────────────────────

def pass2_email_match(df: pd.DataFrame) -> pd.DataFrame:
    """
    Detect contractor overlap: same email address in both GT and AC records.
    Merges the pair, keeping fields from the higher-priority record.
    """
    before = len(df)
    df = df.copy()

    has_email = df["email"].notna() & (df["email"].astype(str).str.strip() != "")
    dup_emails = (
        df[has_email]
        .groupby("email")["employee_id"]
        .apply(list)
        .pipe(lambda s: s[s.apply(len) > 1])
    )

    if dup_emails.empty:
        logger.info("Pass 2 (email_match): no cross-company email duplicates found")
        return df

    drop_indices: set[int] = set()
    for email, emp_ids in dup_emails.items():
        rows = df[df["employee_id"].isin(emp_ids)].copy()
        rows["_p"] = rows["source_system"].apply(_priority)
        rows = rows.sort_values("_p")
        winner_idx = rows.index[0]
        loser_idxs = rows.index[1:]

        all_sources = ",".join(sorted(set(rows["source_system"].tolist())))
        df.at[winner_idx, "source_systems"] = all_sources
        df.at[winner_idx, "dedup_method"]   = "email_match"
        drop_indices.update(loser_idxs)

    df = df.drop(index=list(drop_indices)).reset_index(drop=True)
    removed = before - len(df)
    logger.info(
        f"Pass 2 (email_match): {before:,} → {len(df):,} records "
        f"({removed:,} email-duplicate rows merged)"
    )
    return df


# ── Pass 3: Fuzzy name + hire date ───────────────────────────────────────────

def pass3_fuzzy_name(
    df: pd.DataFrame,
    threshold: int = None,
    date_window_days: int = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Identify probable duplicates by fuzzy name similarity ≥ threshold AND
    hire_date within date_window_days of each other.

    Records are sorted by hire_date; the inner loop breaks when the date gap
    exceeds date_window_days, keeping complexity O(n · window_size) not O(n²).

    Does NOT auto-merge — produces a review file for HR.

    Returns
    -------
    df               Original df with 'probable_match_flag' column added
    probable_df      Pairs for HR review
    """
    threshold   = threshold       or CONFIG["fuzzy_name_threshold"]
    date_window = date_window_days or CONFIG["hire_date_window_days"]
    window_td   = pd.Timedelta(days=date_window)

    df = df.copy()
    df["probable_match_flag"] = False

    records = df[df["hire_date"].notna()].copy()
    records["_fullname"] = (
        records["first_name"].fillna("") + " " + records["last_name"].fillna("")
    ).str.strip().str.lower()
    records = records.sort_values("hire_date").reset_index()  # keep original index

    pairs: list[dict] = []
    n = len(records)

    for i in range(n):
        ri    = records.iloc[i]
        di    = ri["hire_date"]
        ni    = ri["_fullname"]
        id_i  = ri["employee_id"]

        for j in range(i + 1, n):
            rj = records.iloc[j]
            dj = rj["hire_date"]

            if abs(dj - di) > window_td:
                break  # sorted — no further match possible

            id_j = rj["employee_id"]
            if id_i == id_j:
                continue

            score = fuzz.token_sort_ratio(ni, rj["_fullname"])
            if score >= threshold:
                diff_days = abs((dj - di).days)
                pairs.append({
                    "record_1_id":         id_i,
                    "record_2_id":         id_j,
                    "record_1_name":       ni.title(),
                    "record_2_name":       rj["_fullname"].title(),
                    "similarity_score":    score,
                    "hire_date_diff_days": diff_days,
                    "record_1_source":     ri["source_system"],
                    "record_2_source":     rj["source_system"],
                    "recommended_action":  "REVIEW",
                })
                df.loc[df["employee_id"] == id_i, "probable_match_flag"] = True
                df.loc[df["employee_id"] == id_j, "probable_match_flag"] = True

    probable_df = pd.DataFrame(pairs) if pairs else pd.DataFrame(columns=[
        "record_1_id", "record_2_id", "record_1_name", "record_2_name",
        "similarity_score", "hire_date_diff_days",
        "record_1_source", "record_2_source", "recommended_action",
    ])
    logger.info(f"Pass 3 (fuzzy_name): {len(probable_df):,} probable match pairs flagged for HR review")
    return df, probable_df


# ── Ghost Employee Detection ──────────────────────────────────────────────────

def detect_ghost_employees(df: pd.DataFrame) -> pd.DataFrame:
    """
    Payroll records with no HRIS entry are ghost employees — a compliance/fraud risk.

    A record is a ghost if:
      - source_systems contains 'payroll'
      - source_systems does NOT contain 'globaltech_hris' or 'acquiredco_api'
    """
    is_payroll = df["source_systems"].str.contains("payroll", na=False)
    has_hris   = (
        df["source_systems"].str.contains("globaltech_hris", na=False)
        | df["source_systems"].str.contains("acquiredco_api", na=False)
    )
    ghost_mask = is_payroll & ~has_hris
    ghost_df   = df[ghost_mask].copy()

    ghost_df["name"] = (
        ghost_df["first_name"].fillna("") + " " + ghost_df["last_name"].fillna("")
    ).str.strip()
    ghost_df["ghost_flag_reason"] = "Payroll record with no matching HRIS entry"
    ghost_df = ghost_df.rename(columns={"employee_id": "payroll_employee_id"})

    result = ghost_df[
        ["payroll_employee_id", "name", "salary_usd_annual", "ghost_flag_reason"]
    ].reset_index(drop=True)

    if len(result):
        logger.warning(
            f"Ghost employee detection: {len(result):,} records flagged — "
            "review ghost_employees.csv immediately"
        )
    else:
        logger.info("Ghost employee detection: no ghost employees found")
    return result


# ── Orchestrator ──────────────────────────────────────────────────────────────

def dedup_all(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Run all deduplication passes.

    Returns
    -------
    clean_df         Deduplicated, provenance-tagged employee dataset
    ghost_df         Ghost employee report
    probable_df      Fuzzy match pairs for HR review
    """
    logger.info("=" * 60)
    logger.info("STEP 3  Deduplication starting")
    logger.info("=" * 60)

    if "source_systems" not in df.columns:
        df["source_systems"] = df["source_system"]
    if "dedup_method" not in df.columns:
        df["dedup_method"] = "single_source"

    df = pass1_exact_id(df)
    df = pass2_email_match(df)
    df, probable_df = pass3_fuzzy_name(df)
    ghost_df = detect_ghost_employees(df)

    logger.info(f"Deduplication complete — {len(df):,} unique records")
    return df, ghost_df, probable_df
