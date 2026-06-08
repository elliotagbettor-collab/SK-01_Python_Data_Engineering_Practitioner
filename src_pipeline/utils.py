"""Shared utilities: logging setup and dead-letter logging."""

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path


def get_logger(name: str, log_dir: Path = None) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    if log_dir:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_dir / "pipeline.log", encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    return logger


def log_dead_letter(record: dict, reason: str, source: str, log_dir: Path) -> None:
    """Append a malformed record to the dead-letter CSV instead of crashing."""
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "dead_letter.csv"

    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "reason": reason,
        **{k: str(v) for k, v in record.items()},
    }

    write_header = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()), extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def log_record_counts(logger: logging.Logger, source: str, raw: int, clean: int) -> None:
    dropped = raw - clean
    logger.info(
        f"[{source}] {raw:,} raw → {clean:,} clean ({dropped:,} dropped to dead-letter)"
    )
