"""
Deliverable 6 — Golden Dataset & Output Exports

Outputs:
  golden_employees.parquet  — unified, cleaned, deduped employee records
                              partitioned by company_origin (GlobalTech / AcquiredCo)
  ghost_employees.csv       — payroll records with no HRIS counterpart
  probable_matches.csv      — fuzzy-match pairs for HR review
"""

import sys
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).parent))
from config import CONFIG
from utils import get_logger

logger = get_logger(__name__, CONFIG["log_dir"])


def export_golden_dataset(df: pd.DataFrame, output_path: Path = None) -> None:
    """
    Write the golden dataset as Parquet, partitioned by company_origin.

    company_origin is derived from the employee_id prefix:
        GT-XXXXXX → GlobalTech
        AC-XXXXXX → AcquiredCo
    """
    output_path = Path(output_path or CONFIG["outputs"]["golden_dataset"])
    output_path.parent.mkdir(parents=True, exist_ok=True)

    df = df.copy()
    df["company_origin"] = df["employee_id"].apply(
        lambda eid: "GlobalTech" if str(eid).startswith("GT") else "AcquiredCo"
    )

    # Convert datetime columns to timezone-naive for Parquet compatibility
    for col in df.select_dtypes(include=["datetime64[ns, UTC]", "datetimetz"]).columns:
        df[col] = df[col].dt.tz_localize(None)

    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_to_dataset(
        table,
        root_path=str(output_path),
        partition_cols=["company_origin"],
        existing_data_behavior="delete_matching",
    )
    logger.info(
        f"Golden dataset ({len(df):,} records) → {output_path} "
        f"[partitioned by company_origin]"
    )


def export_ghost_employees(ghost_df: pd.DataFrame, output_path: Path = None) -> None:
    output_path = Path(output_path or CONFIG["outputs"]["ghost_employees"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ghost_df.to_csv(output_path, index=False)
    logger.info(f"Ghost employees ({len(ghost_df):,} records) → {output_path.name}")


def export_probable_matches(probable_df: pd.DataFrame, output_path: Path = None) -> None:
    output_path = Path(output_path or CONFIG["outputs"]["probable_matches"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    probable_df.to_csv(output_path, index=False)
    logger.info(f"Probable match review ({len(probable_df):,} pairs) → {output_path.name}")


def export_all(
    df: pd.DataFrame,
    ghost_df: pd.DataFrame,
    probable_df: pd.DataFrame,
    report_df: pd.DataFrame,
) -> None:
    logger.info("=" * 60)
    logger.info("STEP 6  Exporting outputs")
    logger.info("=" * 60)
    export_golden_dataset(df)
    export_ghost_employees(ghost_df)
    export_probable_matches(probable_df)

    csv_path = CONFIG["outputs"]["validation_report_csv"]
    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    report_df.to_csv(csv_path, index=False)
    logger.info(f"Validation report CSV → {Path(csv_path).name}")

    logger.info("All exports complete")
