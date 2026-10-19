"""
Project Nexus | Preflight Check (run before Phase 3 Power BI build)
Harrize Consulting

Prints the project folder structure and verifies the environment:
  Python and venv, required files, UTF-8 encoding, pipeline settings,
  data outputs against the 5,000 record baseline, SQLite database,
  Power BI assets, .gitignore rules and Git checkpoints.

Run from the project root:
    python src/preflight_check.py

A copy of the report is saved to logs/preflight_report.txt
Exit code 0 = ready (PASS/WARN only), 1 = at least one FAIL.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT_FILE = ROOT / "logs" / "preflight_report.txt"

SKIP_DIRS = {"venv", ".venv", ".git", "__pycache__", ".pbi", "node_modules"}
TREE_DEPTH = 3

# 5,000 record baseline (checkpoint-02)
BASELINE = {
    "clean_rows": 4274,
    "quarantine_rows": 826,
    "pipeline_gbp": 1178155.39,
    "leakage_gbp": 424692.27,
    "hygiene_rows": 10,
}

REQUIRED_FILES = [
    "src/pipeline_engine.py",
    "src/db_loader.py",
    "sql/analytical_queries.sql",
    "requirements.txt",
    ".gitignore",
    "README.md",
    "powerbi/measures.dax",
    "powerbi/nexus_theme.json",
    "docs/phase3_powerbi_build_guide.md",
]

DATA_FILES = {
    "clean": "data/processed/clean_crm_migration.csv",
    "quarantine": "data/quarantine/rejected_records.csv",
    "hygiene": "data/processed/sql_3a_data_hygiene_scorecard.csv",
    "hygiene_detail": "data/processed/sql_3b_data_hygiene_detail.csv",
    "leakage_audit": "data/processed/sql_1_revenue_leakage_audit.csv",
    "forecast": "data/processed/sql_2_active_forecasting_pipeline.csv",
}

TEXT_EXTENSIONS = {".py", ".sql", ".md", ".txt", ".dax", ".json", ".gitignore"}

lines: list[str] = []
results: list[tuple[str, str, str]] = []


def out(text: str = "") -> None:
    lines.append(text)
    print(text)


def record(status: str, check: str, detail: str) -> None:
    results.append((status, check, detail))


# ---------------------------------------------------------------------------
# Folder tree
# ---------------------------------------------------------------------------
def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def print_tree(folder: Path, prefix: str = "", depth: int = 0) -> None:
    if depth >= TREE_DEPTH:
        return
    try:
        entries = sorted(folder.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except PermissionError:
        return
    entries = [e for e in entries if e.name not in SKIP_DIRS]
    for i, entry in enumerate(entries):
        last = i == len(entries) - 1
        branch = "`-- " if last else "|-- "
        if entry.is_dir():
            out(f"{prefix}{branch}{entry.name}/")
            print_tree(entry, prefix + ("    " if last else "|   "), depth + 1)
        else:
            out(f"{prefix}{branch}{entry.name}  ({human_size(entry.stat().st_size)})")


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
def check_python() -> None:
    v = sys.version_info
    status = "PASS" if v >= (3, 10) else "FAIL"
    record(status, "Python version", f"{v.major}.{v.minor}.{v.micro} (need 3.10+)")

    in_venv = sys.prefix != sys.base_prefix
    record("PASS" if in_venv else "WARN", "Virtual environment active",
           sys.prefix if in_venv else "Not active: run venv\\Scripts\\Activate.ps1")

    try:
        import pandas
        import numpy
        record("PASS", "pandas / numpy installed", f"pandas {pandas.__version__}, numpy {numpy.__version__}")
    except ImportError as exc:
        record("FAIL", "pandas / numpy installed", f"{exc}: run pip install -r requirements.txt")


def check_required_files() -> None:
    missing = [f for f in REQUIRED_FILES if not (ROOT / f).is_file()]
    if missing:
        record("FAIL", "Required files present", "Missing: " + ", ".join(missing))
    else:
        record("PASS", "Required files present", f"All {len(REQUIRED_FILES)} found")


def check_encoding() -> None:
    bad = []
    scanned = 0
    for folder in ("src", "sql", "powerbi", "docs", "tests"):
        base = ROOT / folder
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if path.is_file() and (path.suffix.lower() in TEXT_EXTENSIONS):
                scanned += 1
                if not is_utf8(path):
                    bad.append(str(path.relative_to(ROOT)))
    for name in ("requirements.txt", "README.md", ".gitignore"):
        path = ROOT / name
        if path.is_file():
            scanned += 1
            if not is_utf8(path):
                bad.append(name)
    if bad:
        record("FAIL", "UTF-8 encoding", "Not UTF-8 (resave in VS Code as UTF-8): " + ", ".join(bad))
    else:
        record("PASS", "UTF-8 encoding", f"{scanned} text files checked")


def is_utf8(path: Path) -> bool:
    raw = path.read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return False
    try:
        raw.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def check_pipeline_settings() -> None:
    engine = ROOT / "src/pipeline_engine.py"
    if not engine.is_file() or not is_utf8(engine):
        record("FAIL", "Pipeline set to 5,000 records", "pipeline_engine.py missing or unreadable")
        return
    m = re.search(r"^N_RECORDS\s*=\s*(\d+)", engine.read_text(encoding="utf-8"), flags=re.M)
    value = int(m.group(1)) if m else None
    record("PASS" if value == 5000 else "FAIL", "Pipeline set to 5,000 records",
           f"N_RECORDS = {value}")


def check_data_outputs() -> None:
    missing = [p for p in DATA_FILES.values() if not (ROOT / p).is_file()]
    if missing:
        record("FAIL", "Pipeline outputs exist",
               "Missing: " + ", ".join(missing) + ". Run pipeline_engine.py then db_loader.py")
        return
    record("PASS", "Pipeline outputs exist", f"All {len(DATA_FILES)} CSVs found")

    import pandas as pd
    clean = pd.read_csv(ROOT / DATA_FILES["clean"])
    quar = pd.read_csv(ROOT / DATA_FILES["quarantine"])
    hyg = pd.read_csv(ROOT / DATA_FILES["hygiene"])

    def compare(label: str, actual, expected, money: bool = False) -> None:
        ok = abs(actual - expected) < 0.01 if money else actual == expected
        fmt = (lambda x: f"GBP {x:,.2f}") if money else (lambda x: f"{x:,}")
        record("PASS" if ok else "FAIL", label, f"{fmt(actual)} (expected {fmt(expected)})")

    compare("Clean CRM rows", len(clean), BASELINE["clean_rows"])
    compare("Quarantined rows", len(quar), BASELINE["quarantine_rows"])
    compare("Pipeline value", round(clean["Revenue_Amount_GBP"].sum(), 2), BASELINE["pipeline_gbp"], money=True)
    lost = clean.loc[clean["Deal_Stage"] == "Closed-Lost", "Revenue_Amount_GBP"].sum()
    compare("Closed-Lost leakage", round(lost, 2), BASELINE["leakage_gbp"], money=True)
    compare("Hygiene scorecard rows", len(hyg), BASELINE["hygiene_rows"])

    engine = ROOT / "src/pipeline_engine.py"
    if (ROOT / DATA_FILES["clean"]).stat().st_mtime < engine.stat().st_mtime:
        record("WARN", "Data newer than code",
               "pipeline_engine.py changed after the last run: rerun both scripts")
    else:
        record("PASS", "Data newer than code", "Outputs were produced after the latest code change")


def check_database() -> None:
    db = ROOT / "data/nexus.db"
    if not db.is_file():
        record("FAIL", "SQLite database", "data/nexus.db missing: run python src/db_loader.py")
        return
    try:
        con = sqlite3.connect(db)
        n = con.execute("SELECT COUNT(*) FROM uk_ecommerce_pipeline").fetchone()[0]
        con.close()
        record("PASS" if n == BASELINE["clean_rows"] else "FAIL", "SQLite database",
               f"uk_ecommerce_pipeline has {n:,} rows (expected {BASELINE['clean_rows']:,})")
    except sqlite3.Error as exc:
        record("FAIL", "SQLite database", str(exc))


def check_powerbi_assets() -> None:
    theme = ROOT / "powerbi/nexus_theme.json"
    if theme.is_file():
        try:
            data = json.loads(theme.read_text(encoding="utf-8"))
            record("PASS", "Theme JSON valid", f"'{data.get('name')}' with {len(data.get('dataColors', []))} colours")
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            record("FAIL", "Theme JSON valid", f"Cannot parse: {exc}")

    dax = ROOT / "powerbi/measures.dax"
    if dax.is_file() and is_utf8(dax):
        text = dax.read_text(encoding="utf-8")
        needed = ["Calendar =", "Total Pipeline £", "Leakage £", "Weighted Open £",
                  "Recoverable Revenue £", "Pipeline Pass Rate %", "Hygiene Status Colour"]
        absent = [n for n in needed if n not in text]
        record("FAIL" if absent else "PASS", "DAX measures file",
               "Missing: " + ", ".join(absent) if absent else f"All {len(needed)} key measures found")
        if "1,178,155.39" not in text:
            record("WARN", "DAX expected values", "measures.dax comments are not the 5,000 record version")

    pbi_files = list((ROOT / "powerbi").glob("*.pbix")) + list((ROOT / "powerbi").glob("*.pbip"))
    if pbi_files:
        record("PASS", "Power BI report in powerbi/", ", ".join(p.name for p in pbi_files))
    else:
        record("WARN", "Power BI report in powerbi/",
               "No .pbix or .pbip yet: save your report into the powerbi folder")


def check_powerbi_installed() -> None:
    if os.name != "nt":
        record("WARN", "Power BI Desktop installed", "Not Windows: Power BI Desktop requires Windows")
        return
    paths = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Microsoft Power BI Desktop/bin/PBIDesktop.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WindowsApps/PBIDesktopStore.exe",
    ]
    if any(p.exists() for p in paths):
        record("PASS", "Power BI Desktop installed", "Found")
        return
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-AppxPackage -Name *PowerBI* | Select-Object -ExpandProperty Version"],
            capture_output=True, text=True, timeout=20)
        if res.stdout.strip():
            record("PASS", "Power BI Desktop installed", f"Microsoft Store version {res.stdout.strip()}")
            return
    except (OSError, subprocess.SubprocessError):
        pass
    record("WARN", "Power BI Desktop installed", "Not detected: install from the Microsoft Store")


def check_gitignore() -> None:
    gi = ROOT / ".gitignore"
    if not gi.is_file() or not is_utf8(gi):
        record("FAIL", ".gitignore rules", ".gitignore missing or not UTF-8")
        return
    text = gi.read_text(encoding="utf-8")
    rules = ["venv/", ".venv/", "data/*.db", "data/raw/*.csv",
             "data/processed/*.csv", "data/quarantine/*.csv", "__pycache__/"]
    absent = [r for r in rules if r not in text]
    record("WARN" if absent else "PASS", ".gitignore rules",
           "Add: " + ", ".join(absent) if absent else "venv, database and data CSVs excluded")


def git(*args: str) -> str | None:
    try:
        res = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=20)
        return res.stdout.strip() if res.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def check_git() -> None:
    if shutil.which("git") is None:
        record("FAIL", "Git installed", "git not found on PATH")
        return
    if git("rev-parse", "--is-inside-work-tree") != "true":
        record("FAIL", "Git repository", "Not a Git repo: run git init")
        return
    branch = git("branch", "--show-current") or "unknown"
    remote = git("remote", "get-url", "origin")
    record("PASS" if remote else "WARN", "Git remote",
           f"branch '{branch}' -> {remote}" if remote else "No origin remote set")
    if remote and "YOUR-USERNAME" in remote:
        record("FAIL", "Git remote URL", "Still the placeholder: git remote set-url origin <your repo URL>")

    tags = (git("tag", "--list") or "").split()
    for tag in ("checkpoint-01", "checkpoint-02"):
        record("PASS" if tag in tags else "WARN", f"Tag {tag}", "present" if tag in tags else "missing")

    status = git("status", "--porcelain") or ""
    changed = [l for l in status.splitlines() if l.strip()]
    record("PASS" if not changed else "WARN", "Uncommitted changes",
           "Working tree clean" if not changed else f"{len(changed)} file(s) changed or untracked "
           "(expected now if you just added powerbi/ and docs/ files)")

    tracked = git("ls-files") or ""
    leaks = [f for f in tracked.splitlines()
             if f.startswith(("venv/", ".venv/")) or f.endswith(".db")]
    if leaks:
        record("FAIL", "Nothing private or bulky tracked",
               f"{len(leaks)} venv/db files are committed: git rm -r --cached venv data/nexus.db")
    else:
        record("PASS", "Nothing private or bulky tracked", "No venv or database files in Git")


# ---------------------------------------------------------------------------
def main() -> int:
    out("=" * 78)
    out("PROJECT NEXUS | PREFLIGHT CHECK")
    out(f"Root: {ROOT}")
    out(f"Run:  {datetime.now():%Y-%m-%d %H:%M:%S}")
    out("=" * 78)
    out("\nFOLDER STRUCTURE (venv, .git and caches hidden)\n")
    out(f"{ROOT.name}/")
    print_tree(ROOT)

    for check in (check_python, check_required_files, check_encoding, check_pipeline_settings,
                  check_data_outputs, check_database, check_powerbi_assets,
                  check_powerbi_installed, check_gitignore, check_git):
        try:
            check()
        except Exception as exc:  # keep running other checks
            record("FAIL", check.__name__, f"Unexpected error: {exc}")

    out("\nREADINESS CHECKS\n")
    width = max(len(c) for _, c, _ in results)
    for status, check, detail in results:
        out(f"[{status:<4}] {check:<{width}}  {detail}")

    fails = sum(1 for s, _, _ in results if s == "FAIL")
    warns = sum(1 for s, _, _ in results if s == "WARN")
    out("\n" + "=" * 78)
    if fails:
        out(f"NOT READY: {fails} FAIL, {warns} WARN. Fix the FAIL lines, then rerun.")
    else:
        out(f"READY FOR PHASE 3: 0 FAIL, {warns} WARN. Review any WARN lines above.")
    out("=" * 78)

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport saved to {REPORT_FILE.relative_to(ROOT)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
