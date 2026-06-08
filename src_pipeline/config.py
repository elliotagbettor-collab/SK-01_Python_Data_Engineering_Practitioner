from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────────────────

CONFIG = {
    "input_dir": Path("data/raw"),
    "output_dir": Path("data/processed"),
    "log_dir": Path("logs"),         # Use environment variable in production
    "valid_regions": ["US", "EU", "APAC"],
    "email_regex": r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$",
    "quality_threshold": 0.95,         # 95% of records must pass each check
    "source_priority": {},
}