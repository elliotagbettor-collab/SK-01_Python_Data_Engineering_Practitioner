"""
Deliverable 5 — EDA & Visualization Report

Generates a 6-panel figure saved at 300 DPI:
  1. Headcount by Department (horizontal bar)
  2. Headcount by Country (horizontal bar)
  3. Salary Distribution by Employment Type (violin)
  4. Tenure Distribution (histogram)
  5. Benefits Enrollment Rate by Department (horizontal bar)
  6. Data Quality Summary (stacked horizontal bar: passed vs failed)
"""

import sys
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd
import seaborn as sns

sys.path.insert(0, str(Path(__file__).parent))
from config import CONFIG
from utils import get_logger

logger = get_logger(__name__, CONFIG["log_dir"])

# Colorblind-safe palette (Wong 2011)
PALETTE = ["#0072B2", "#009E73", "#D55E00", "#CC79A7", "#F0E442", "#56B4E9", "#E69F00", "#000000"]
_SRC_NOTE = "Source: GlobalTech HR Integration Pipeline"


def _annotate(ax: plt.Axes, note: str = _SRC_NOTE) -> None:
    ax.text(0.99, -0.06, note, transform=ax.transAxes,
            ha="right", va="top", fontsize=7, color="#666666")


# ── Chart 1 ──────────────────────────────────────────────────────────────────

def plot_headcount_by_department(df: pd.DataFrame, ax: plt.Axes) -> None:
    counts = df["department"].dropna().value_counts().sort_values().tail(15)
    counts.plot(kind="barh", ax=ax, color=PALETTE[0])
    ax.set_title("Headcount by Department", fontweight="bold")
    ax.set_xlabel("Employees")
    ax.set_ylabel("")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
    _annotate(ax)


# ── Chart 2 ──────────────────────────────────────────────────────────────────

def plot_headcount_by_country(df: pd.DataFrame, ax: plt.Axes) -> None:
    counts = df["country"].dropna().value_counts().sort_values().tail(20)
    counts.plot(kind="barh", ax=ax, color=PALETTE[1])
    ax.set_title("Headcount by Country", fontweight="bold")
    ax.set_xlabel("Employees")
    ax.set_ylabel("")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
    _annotate(ax)


# ── Chart 3 ──────────────────────────────────────────────────────────────────

def plot_salary_by_employment_type(df: pd.DataFrame, ax: plt.Axes) -> None:
    salary_df = df[["employment_type", "salary_usd_annual"]].copy()
    salary_df["salary_usd_annual"] = pd.to_numeric(
        salary_df["salary_usd_annual"], errors="coerce"
    )
    salary_df = salary_df.dropna()

    emp_types = sorted(salary_df["employment_type"].dropna().unique())
    data      = [salary_df.loc[salary_df["employment_type"] == et, "salary_usd_annual"].values
                 for et in emp_types]
    # Filter out empty groups
    emp_types = [et for et, d in zip(emp_types, data) if len(d) > 0]
    data      = [d for d in data if len(d) > 0]

    if not data:
        ax.set_title("Salary Distribution by Employment Type\n(no salary data)", fontweight="bold")
        return

    parts = ax.violinplot(data, showmedians=True, showextrema=True)
    for body, color in zip(parts["bodies"], PALETTE):
        body.set_facecolor(color)
        body.set_alpha(0.7)
    parts["cmedians"].set_colors("black")
    ax.set_xticks(range(1, len(emp_types) + 1))
    ax.set_xticklabels(emp_types)
    ax.set_title("Salary Distribution by Employment Type", fontweight="bold")
    ax.set_ylabel("Annual Salary (USD)")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x/1_000:.0f}K"))
    _annotate(ax)


# ── Chart 4 ──────────────────────────────────────────────────────────────────

def plot_tenure_distribution(df: pd.DataFrame, ax: plt.Axes) -> None:
    today  = pd.Timestamp.today().normalize()
    tenure = (
        (today - pd.to_datetime(df["hire_date"], errors="coerce")).dt.days / 365.25
    ).dropna()
    tenure = tenure[(tenure >= 0) & (tenure <= 50)]

    ax.hist(tenure, bins=25, color=PALETTE[2], edgecolor="white", linewidth=0.5)
    ax.set_title("Tenure Distribution", fontweight="bold")
    ax.set_xlabel("Years at Company")
    ax.set_ylabel("Employees")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
    _annotate(ax)


# ── Chart 5 ──────────────────────────────────────────────────────────────────

def plot_benefits_enrollment_rate(df: pd.DataFrame, ax: plt.Axes) -> None:
    enrolled = df[df["plan_type"].notna()].groupby("department").size().rename("enrolled")
    total    = df.groupby("department").size().rename("total")
    rate_df  = pd.concat([enrolled, total], axis=1).dropna()

    if rate_df.empty:
        ax.set_title("Benefits Enrollment Rate by Department\n(no benefits data)", fontweight="bold")
        return

    rate_df["rate"] = (rate_df["enrolled"] / rate_df["total"] * 100).round(1)
    rate_df = rate_df.sort_values("rate").tail(15)

    rate_df["rate"].plot(kind="barh", ax=ax, color=PALETTE[5])
    ax.set_title("Benefits Enrollment Rate by Department", fontweight="bold")
    ax.set_xlabel("Enrollment Rate (%)")
    ax.set_ylabel("")
    ax.set_xlim(0, 100)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.0f}%"))
    _annotate(ax)


# ── Chart 6 ──────────────────────────────────────────────────────────────────

def plot_data_quality_summary(report_df: pd.DataFrame, ax: plt.Axes) -> None:
    labels  = report_df["check"].values
    passed  = report_df["passed"].values
    failed  = report_df["failed"].values
    y_pos   = range(len(labels))

    ax.barh(list(y_pos), passed, color=PALETTE[1], label="Passed", alpha=0.85)
    ax.barh(list(y_pos), failed, left=passed, color=PALETTE[2], label="Failed", alpha=0.85)
    ax.set_yticks(list(y_pos))
    ax.set_yticklabels(labels, fontsize=7)
    ax.set_title("Data Quality: Passed vs. Failed per Check", fontweight="bold")
    ax.set_xlabel("Record Count")
    ax.legend(loc="lower right", fontsize=8)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
    _annotate(ax)


# ── Orchestrator ──────────────────────────────────────────────────────────────

def generate_eda_report(
    df: pd.DataFrame,
    report_df: pd.DataFrame,
    output_path: Path = None,
) -> None:
    logger.info("=" * 60)
    logger.info("STEP 5  Generating EDA report")
    logger.info("=" * 60)

    output_path = Path(output_path or CONFIG["outputs"]["eda_report"])
    output_path.parent.mkdir(parents=True, exist_ok=True)

    sns.set_theme(style="whitegrid", font_scale=0.9)
    fig, axes = plt.subplots(3, 2, figsize=(20, 28), constrained_layout=True)
    axes = axes.flatten()

    fig.suptitle(
        "GlobalTech Corp — HR Integration Pipeline: EDA Report\n"
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        fontsize=14, fontweight="bold",
    )

    plot_headcount_by_department(df, axes[0])
    plot_headcount_by_country(df, axes[1])
    plot_salary_by_employment_type(df, axes[2])
    plot_tenure_distribution(df, axes[3])
    plot_benefits_enrollment_rate(df, axes[4])
    plot_data_quality_summary(report_df, axes[5])

    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    logger.info(f"EDA report saved → {output_path}")
