# SK-01 Capstone: Multi-Source HR Data Integration Pipeline — GlobalTech Corp

## Business Context

GlobalTech Corp has acquired AcquiredCo and needs a unified employee dataset within 10 business days to support Day 1 integration, benefits enrollment, payroll migration, and compliance reporting. This pipeline ingests data from 4 source systems, cleans and deduplifies it, validates data quality, and produces a golden employee dataset partitioned by company origin.

---

## Input Sources

| Source | File | Format | Volume | Known Issues |
|---|---|---|---|---|
| GlobalTech HRIS | `src_pipeline/data/raw/globaltech_hris.csv` | CSV UTF-8 | 15,000 rows | — |
| AcquiredCo HRIS | `src_pipeline/data/raw/acquiredco_api.json` | JSON (paginated) | 3,200 records | IDs overlap with GT range |
| Combined Payroll | `src_pipeline/data/raw/payroll_data.xlsx` | Excel | 19,000 rows | Mixed currencies; ADP duplicates |
| Benefits | `src_pipeline/data/raw/benefits_enrollment.xml` | XML | 12,000 enrollments | GT employees only |

---

## Output Files

| File | Format | Description |
|---|---|---|
| `data/processed/golden_employees.parquet/` | Parquet (partitioned) | Golden dataset, partitioned by `company_origin` |
| `data/processed/ghost_employees.csv` | CSV | Payroll records with no HRIS match |
| `data/processed/probable_matches.csv` | CSV | Fuzzy-matched pairs for HR review |
| `data/processed/validation_report.csv` | CSV | Data quality check results |
| `data/processed/validation_report.html` | HTML | Visual quality report |
| `data/processed/eda_report.png` | PNG 300 DPI | 6-panel EDA visualization |
| `logs/pipeline.log` | Text | Full pipeline log |
| `logs/dead_letter.csv` | CSV | Malformed records rejected during ingestion |

---

## How to Run

```bash
# From project root
python src_pipeline/pipeline.py
```

### Prerequisites

```bash
pip install -r requirement.txt
```

Required packages: `pandas`, `numpy`, `matplotlib`, `seaborn`, `openpyxl`, `pyarrow`, `rapidfuzz`

---

## Module Reference

| Module | Deliverable | Description |
|---|---|---|
| `config.py` | — | All configuration constants (paths, FX rates, department map, validation settings) |
| `utils.py` | — | Logger setup; dead-letter CSV logging |
| `ingest.py` | D1 | 4 ingestion functions + schema alignment |
| `clean.py` | D2 | Name normalisation, ID namespacing, salary normalisation, dept mapping, date standardisation |
| `dedup.py` | D3 | 3-pass deduplication; ghost employee detection |
| `validate.py` | D4 | `DataQualityValidator` with 15 checks; HTML + CSV report |
| `visualize.py` | D5 | 6-panel EDA report at 300 DPI |
| `export.py` | D6 | Parquet golden dataset + CSV outputs |
| `pipeline.py` | — | Orchestrator — runs all steps in sequence |

---

## Standard Employee Schema

| Column | Type | Description | Example |
|---|---|---|---|
| `employee_id` | str | Namespaced ID | `GT-001042` |
| `first_name` | str | Unicode NFC, title case | `O'Brien` |
| `last_name` | str | Unicode NFC, title case | `Van-Der-Berg` |
| `email` | str | Work email | `john.doe@globaltech.com` |
| `department` | str | Standard taxonomy | `Engineering` |
| `job_title` | str | Role title | `Data Engineer` |
| `hire_date` | datetime64 | Normalised from any source format | `2022-03-15` |
| `country` | str | Country of work location | `United States` |
| `employment_type` | str | Full-Time / Part-Time / Contractor | `Full-Time` |
| `manager_id` | str | Namespaced manager employee_id | `GT-000566` |
| `base_salary` | float | Amount in original currency | `95000.0` |
| `currency` | str | ISO 4217 | `USD` |
| `pay_frequency` | str | Annual / Monthly / Bi-Weekly | `Monthly` |
| `salary_usd_annual` | float | Normalised USD annual salary | `1,240,200.0` |
| `bonus_target_pct` | float | Target bonus % | `15.0` |
| `plan_type` | str | Benefits plan | `Health Insurance` |
| `coverage_level` | str | Benefits coverage tier | `Family` |
| `enrollment_date` | datetime64 | Benefits enrollment date | `2022-01-01` |
| `source_systems` | str | Comma-joined contributing sources | `globaltech_hris,payroll` |
| `dedup_method` | str | Dedup resolution method | `exact_id` |
| `company_origin` | str | Partition key | `GlobalTech` |

---

## Deduplication Logic

| Pass | Method | Action |
|---|---|---|
| Pass 1 | Exact `employee_id` match | Coalesce merge by source priority; HRIS > Payroll > Benefits |
| Pass 2 | Email match across companies | Merge cross-company contractor records; remap orphaned `manager_id` references |
| Pass 3 | Fuzzy name + hire date (±30 days) | Flag pairs with ≥88% name similarity as `probable_match` for HR review |
| Ghost | Payroll with no HRIS record | Written to `ghost_employees.csv` as compliance flag |

---

## Data Quality Checks

| Check Type | Fields |
|---|---|
| NOT NULL | `employee_id`, `first_name`, `last_name`, `email`, `department`, `country` |
| UNIQUE | `email`, `employee_id` |
| VALUES IN SET | `employment_type` ∈ {Full-Time, Part-Time, Contractor}; `currency` ∈ {USD, EUR, GBP} |
| REGEX | `email` (RFC 5321 format); `employee_id` (GT-XXXXXX or AC-XXXXXX) |
| NUMERIC RANGE | `salary_usd_annual` between $15,000 and $10,000,000 |
| DATE RANGE | `hire_date` between 1970-01-01 and today |
| REFERENTIAL INTEGRITY | Every `manager_id` must exist as an `employee_id` |

Pipeline gate: if more than 2 checks fail, the pipeline halts with a CRITICAL log and exits with code 1.

---

## Known Limitations & Assumptions

1. **FX rates are fixed** at EUR→USD 1.09, GBP→USD 1.27 (not live market rates).
2. **Salary interpretation**: `base_salary` in payroll is the per-period amount (monthly/bi-weekly/annual); the pipeline annualises accordingly. The test dataset has high per-period salaries that produce annual values >$1M for many employees — this is a characteristic of the generated data, not a pipeline bug.
3. **Benefits data is enrollment-level**: an employee enrolled in multiple plans produces multiple XML records. After dedup, only the first plan's fields are retained in the golden record. Full multi-plan history is preserved in the raw data only.
4. **Pass 2 email merge aggressiveness**: The test dataset has many GT/AC employees sharing emails (likely contractors). 8,918 cross-company email merges in the test data is unusually high for a real scenario; validate carefully before applying to production data.
5. **AcquiredCo inactive employees** are included in the golden dataset (not filtered on `employment.status`).

---

## Change Log

| Date | Change |
|---|---|
| 2026-06-08 | Initial implementation — all 6 deliverables |
