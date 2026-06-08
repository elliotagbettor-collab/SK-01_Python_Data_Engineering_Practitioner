"""
GlobalTech HR Integration Pipeline — main orchestrator.

Run from project root:
    python src_pipeline/pipeline.py

Or from within src_pipeline/:
    python pipeline.py
"""

import sys
from pathlib import Path

# Ensure src_pipeline/ is on the path regardless of where this is invoked from
sys.path.insert(0, str(Path(__file__).parent))

from config import CONFIG
from utils import get_logger
from ingest import ingest_all
from clean import clean_all
from dedup import dedup_all
from validate import run_validation, DataQualityValidator
from visualize import generate_eda_report
from export import export_all

logger = get_logger("pipeline", CONFIG["log_dir"])


def run_pipeline() -> None:
    # Ensure all output directories exist
    for path in CONFIG["outputs"].values():
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    CONFIG["log_dir"].mkdir(parents=True, exist_ok=True)

    logger.info("╔══════════════════════════════════════════════════╗")
    logger.info("║   GlobalTech HR Integration Pipeline — START     ║")
    logger.info("╚══════════════════════════════════════════════════╝")

    # Step 1: Ingest all 4 sources
    dfs = ingest_all()

    # Step 2: Clean & transform
    clean_df = clean_all(dfs)

    # Step 3: Deduplicate
    dedup_df, ghost_df, probable_df = dedup_all(clean_df)

    # Step 4: Validate + pipeline gate
    report_df, gate_ok, validator = run_validation(dedup_df)
    validator.export_report(
        CONFIG["outputs"]["validation_report_csv"],
        CONFIG["outputs"]["validation_report_html"],
    )

    if not gate_ok:
        logger.critical(
            "Pipeline halted at validation gate. "
            "Fix data quality issues and re-run. "
            f"Report: {CONFIG['outputs']['validation_report_html']}"
        )
        sys.exit(1)

    # Step 5: EDA report
    generate_eda_report(dedup_df, report_df)

    # Step 6: Export golden dataset + supporting files
    export_all(dedup_df, ghost_df, probable_df, report_df)

    logger.info("╔══════════════════════════════════════════════════╗")
    logger.info("║   GlobalTech HR Integration Pipeline — DONE      ║")
    logger.info("╚══════════════════════════════════════════════════╝")
    logger.info(f"  Golden dataset : {CONFIG['outputs']['golden_dataset']}")
    logger.info(f"  Ghost employees: {CONFIG['outputs']['ghost_employees']}")
    logger.info(f"  Probable matches: {CONFIG['outputs']['probable_matches']}")
    logger.info(f"  Validation HTML : {CONFIG['outputs']['validation_report_html']}")
    logger.info(f"  EDA report      : {CONFIG['outputs']['eda_report']}")


if __name__ == "__main__":
    run_pipeline()
