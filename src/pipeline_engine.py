"""
Project Nexus | Phase 1: Python Ingestion Engine
Harrize Consulting | UK E-Commerce Revenue Leakage & CRM Ingestion Pipeline

What this does
  1. Simulates 5000 chaotic raw transaction log strings (mixed date formats,
     messy currency, missing fields, inconsistent casing, corrupted rows).
  2. Parses every string with Regex into structured fields.
  3. Enforces enterprise type casting:
        Revenue_Amount_GBP     -> float
        Transaction_Timestamp  -> datetime64
        Customer_UUID          -> stripped str
        Deal_Stage             -> stripped str
  4. Tags Closed-Lost deals and classifies friction:
        Response Delay | Warehouse Stockout | Navigation Friction
  5. Routes clean rows to  data/processed/clean_crm_migration.csv
     and rejected rows to  data/quarantine/rejected_records.csv
     (each rejected row carries a Rejection_Reason for auditability).

Run from the project root:
    python src/pipeline_engine.py
"""

from __future__ import annotations

import logging
import random
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 0. CONFIG
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
QUARANTINE_DIR = PROJECT_ROOT / "data" / "quarantine"
LOG_DIR = PROJECT_ROOT / "logs"

RAW_FILE = RAW_DIR / "raw_transaction_logs.csv"
CLEAN_FILE = PROCESSED_DIR / "clean_crm_migration.csv"
REJECT_FILE = QUARANTINE_DIR / "rejected_records.csv"

N_RECORDS = 5000
SEED = 42
RESPONSE_SLA_HOURS = 24  # replies slower than this count as Response Delay

for d in (RAW_DIR, PROCESSED_DIR, QUARANTINE_DIR, LOG_DIR):
    d.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "pipeline_run.log", mode="w", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("nexus")

random.seed(SEED)
np.random.seed(SEED)


# ---------------------------------------------------------------------------
# 1. CHAOS GENERATOR (simulates the raw source system export)
# ---------------------------------------------------------------------------
CHANNELS = ["Email", "Live Chat", "WhatsApp", "Phone", "Web Form", "Instagram DM"]
REGIONS = ["London", "Manchester", "Birmingham", "Leeds", "Glasgow",
           "Bristol", "Leicester", "Cardiff", "Belfast", "Edinburgh"]
CATEGORIES = ["Skincare", "Electronics", "Homeware", "Fashion", "Fitness", "Grocery"]

STAGE_VARIANTS = {
    "Closed-Won": ["closed won", "CLOSED-WON", "Won", " won ", "closed_won", "WON!!"],
    "Closed-Lost": ["closed lost", "CLOSED-LOST", "lost", "Lost ", "closed_lost",
                    "dead", "churned", "cancelled"],
    "Open": ["open", "OPEN", "in progress", "negotiation", "pending", "Prospect"],
}

FRICTION_NOTES = {
    "Response Delay": [
        "customer waited {h} hrs for a reply",
        "no response from sales for {h}h, buyer went cold",
        "chased twice, first reply after {h} hours",
        "ticket unanswered {h}hrs; customer escalated",
    ],
    "Warehouse Stockout": [
        "item OUT OF STOCK at Coventry DC",
        "backorder 3 weeks, customer cancelled",
        "OOS on checkout; SKU {sku} unavailable",
        "warehouse stockout, no restock ETA",
    ],
    "Navigation Friction": [
        "abandoned checkout at payment page",
        "404 on product link from campaign email",
        "couldn't find size guide, left site",
        "checkout loop error; cart abandoned",
    ],
    None: [
        "smooth purchase, repeat buyer",
        "upsold to bundle",
        "follow up next week",
        "",
        "requested invoice copy",
    ],
}


def _messy_date(ts: datetime) -> str:
    """Render one timestamp in a random, inconsistent format."""
    fmt = random.choice([
        "%Y-%m-%d %H:%M:%S",   # ISO
        "%d/%m/%Y %H:%M",      # UK
        "%d-%m-%Y",            # UK dashed
        "%d %b %Y %H:%M",      # 05 Mar 2025 14:22
        "%d %B %Y",            # 05 March 2025
        "%Y%m%d",              # compact
        "%Y-%m-%dT%H:%M:%SZ",  # ISO 8601 Zulu
        "%d.%m.%Y",            # European dotted
    ])
    return ts.strftime(fmt)


def _messy_amount(val: float) -> str:
    """Render GBP in a random, inconsistent style."""
    style = random.randint(0, 6)
    if style == 0:
        return f"£{val:,.2f}"
    if style == 1:
        return f"GBP {val:.2f}"
    if style == 2:
        return f"{val:.2f} gbp"
    if style == 3:
        return f" £ {val:,.0f} "
    if style == 4:
        return f"{val / 1000:.1f}k" if val >= 1000 else f"£{val:.2f}"
    if style == 5:
        return f"£ {val:.2f} GBP"
    return f"{val:,.2f}"


def _messy_uuid(u: str) -> str:
    style = random.randint(0, 4)
    if style == 0:
        return u
    if style == 1:
        return u.upper()
    if style == 2:
        return f"  {u}  "
    if style == 3:
        return "{" + u + "}"
    return u.replace("-", "")


def generate_chaotic_logs(n: int = N_RECORDS) -> pd.DataFrame:
    """Build n raw, semi structured log lines plus deliberate corruption."""
    start = datetime(2025, 1, 1)
    customers = [str(uuid.uuid4()) for _ in range(900)]  # repeat buyers exist
    rows = []

    for i in range(n):
        ts = start + timedelta(minutes=random.randint(0, 60 * 24 * 600))
        cust = random.choice(customers)
        amount = round(float(np.random.lognormal(mean=5.2, sigma=0.9)), 2)

        stage_key = random.choices(
            ["Closed-Won", "Closed-Lost", "Open"], weights=[0.48, 0.34, 0.18])[0]
        stage_raw = random.choice(STAGE_VARIANTS[stage_key])

        if stage_key == "Closed-Lost":
            friction = random.choices(
                ["Response Delay", "Warehouse Stockout", "Navigation Friction", None],
                weights=[0.40, 0.30, 0.25, 0.05])[0]
        else:
            friction = random.choices(
                ["Response Delay", "Warehouse Stockout", "Navigation Friction", None],
                weights=[0.06, 0.04, 0.05, 0.85])[0]

        hours = random.randint(30, 140) if friction == "Response Delay" else random.randint(1, 20)
        note = random.choice(FRICTION_NOTES[friction]).format(
            h=hours, sku=f"SKU{random.randint(10000, 99999)}")

        parts = {
            "TXN": f"TXN{100000 + i}",
            "DATE": _messy_date(ts),
            "CUST": _messy_uuid(cust),
            "AMT": _messy_amount(amount),
            "STAGE": stage_raw,
            "CH": random.choice(CHANNELS),
            "REGION": random.choice(REGIONS),
            "CAT": random.choice(CATEGORIES),
            "RESP": f"{hours}h" if random.random() > 0.1 else "",
            "NOTE": note,
        }

        # Missing field chaos
        if random.random() < 0.05:
            parts["AMT"] = random.choice(["", "N/A", "TBC", "null"])
        if random.random() < 0.03:
            parts["CUST"] = random.choice(["", "unknown", "NULL"])
        if random.random() < 0.03:
            parts["DATE"] = random.choice(["", "yesterday", "32/13/2025", "00/00/0000"])
        if random.random() < 0.04:
            parts["STAGE"] = ""

        # Inconsistent key casing and delimiters
        delim = random.choice([" | ", "|", " ; ", ";", " || "])
        keycase = random.choice([str.upper, str.lower, str.title])
        sep = random.choice([":", "=", ": ", " = "])
        line = delim.join(f"{keycase(k)}{sep}{v}" for k, v in parts.items())

        # Hard corruption: truncated, binary noise, or total garbage
        r = random.random()
        if r < 0.015:
            line = line[: random.randint(5, 40)]
        elif r < 0.025:
            line = "".join(random.choice("#@!?%$^&*~") for _ in range(random.randint(10, 60)))
        elif r < 0.03:
            line = ""

        rows.append({"raw_log": line})

    df = pd.DataFrame(rows)

    # Duplicate injection (source system double posts)
    dupes = df.sample(frac=0.02, random_state=SEED)
    df = pd.concat([df, dupes], ignore_index=True).sample(frac=1, random_state=SEED)
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# 2. REGEX PARSER
# ---------------------------------------------------------------------------
FIELD_KEYS = ["TXN", "DATE", "CUST", "AMT", "STAGE", "CH", "REGION", "CAT", "RESP", "NOTE"]
FIELD_RE = {
    k: re.compile(
        rf"(?i)(?:^|[|;]\s*){k}\s*[:=]\s*(.*?)\s*(?=\s*(?:\|\||\||;)\s*(?:{'|'.join(FIELD_KEYS)})\s*[:=]|$)"
    )
    for k in FIELD_KEYS
}

UUID_RE = re.compile(r"(?i)\b([0-9a-f]{8})-?([0-9a-f]{4})-?([0-9a-f]{4})-?([0-9a-f]{4})-?([0-9a-f]{12})\b")
AMOUNT_RE = re.compile(r"(?i)^\s*(?:£|gbp)?\s*([0-9][0-9,]*\.?[0-9]*)\s*(k)?\s*(?:gbp|£)?\s*$")
HOURS_RE = re.compile(r"(?i)(\d{1,3})\s*(?:h|hr|hrs|hours)\b")

DATE_FORMATS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
    "%d/%m/%Y %H:%M",
    "%d-%m-%Y",
    "%d %b %Y %H:%M",
    "%d %B %Y",
    "%Y%m%d",
    "%d.%m.%Y",
]


def _blank(val) -> bool:
    """True for None, NaN, or whitespace only values."""
    return not isinstance(val, str) or not val.strip()


def extract_fields(line: str) -> dict:
    out = {}
    for k, rx in FIELD_RE.items():
        m = rx.search(line or "")
        out[k] = m.group(1).strip() if m else None
    return out


def parse_uuid(val):
    if _blank(val):
        return None
    m = UUID_RE.search(val.strip().strip("{}"))
    if not m:
        return None
    return "-".join(m.groups()).lower()


def parse_amount(val):
    if _blank(val):
        return None
    m = AMOUNT_RE.match(val)
    if not m:
        return None
    num = float(m.group(1).replace(",", ""))
    if m.group(2):
        num *= 1000
    return round(num, 2)


def parse_date(val):
    if _blank(val):
        return pd.NaT
    v = val.strip()
    for fmt in DATE_FORMATS:  # strict, UK day first, no guessing
        try:
            return pd.Timestamp(datetime.strptime(v, fmt))
        except ValueError:
            continue
    return pd.NaT


def normalise_stage(val):
    if _blank(val):
        return None
    v = re.sub(r"[^a-z ]", " ", val.lower()).strip()
    v = re.sub(r"\s+", " ", v)
    if re.search(r"\b(lost|dead|churned|cancelled)\b", v):
        return "Closed-Lost"
    if re.search(r"\bwon\b", v):
        return "Closed-Won"
    if re.search(r"\b(open|progress|negotiation|pending|prospect)\b", v):
        return "Open"
    return None


def parse_hours(resp, note):
    for source in (resp, note):
        if not _blank(source):
            m = HOURS_RE.search(source)
            if m:
                return int(m.group(1))
    return None


# ---------------------------------------------------------------------------
# 3. FRICTION CLASSIFIER
# ---------------------------------------------------------------------------
STOCKOUT_RE = re.compile(r"(?i)out of stock|\boos\b|backorder|stockout|unavailable|no restock")
NAV_RE = re.compile(r"(?i)abandon|\b404\b|couldn'?t find|checkout loop|left site|navigation")
DELAY_RE = re.compile(r"(?i)no response|unanswered|waited|chased|went cold|escalated")


def classify_friction(note, response_hours):
    note = "" if _blank(note) else note
    response_hours = None if pd.isna(response_hours) else response_hours
    if STOCKOUT_RE.search(note):
        return "Warehouse Stockout"
    if NAV_RE.search(note):
        return "Navigation Friction"
    if DELAY_RE.search(note) or (response_hours is not None and response_hours > RESPONSE_SLA_HOURS):
        return "Response Delay"
    return None


# ---------------------------------------------------------------------------
# 4. TRANSFORM
# ---------------------------------------------------------------------------
CHANNEL_CANON = {c.lower(): c for c in CHANNELS}  # keeps "WhatsApp", "Instagram DM" brand casing


def transform(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    log.info("Parsing %s raw log lines", f"{len(raw):,}")
    parsed = pd.DataFrame([extract_fields(x) for x in raw["raw_log"].fillna("")])
    parsed["raw_log"] = raw["raw_log"].values

    df = pd.DataFrame({
        "Transaction_ID": parsed["TXN"].str.upper(),
        "Transaction_Timestamp": parsed["DATE"].map(parse_date),
        "Customer_UUID": parsed["CUST"].map(parse_uuid),
        "Revenue_Amount_GBP": parsed["AMT"].map(parse_amount),
        "Deal_Stage": parsed["STAGE"].map(normalise_stage),
        "Channel": parsed["CH"].str.strip().str.lower().map(CHANNEL_CANON),
        "Region": parsed["REGION"].str.strip().str.title(),
        "Product_Category": parsed["CAT"].str.strip().str.title(),
        "Response_Time_Hours": [parse_hours(r, n) for r, n in zip(parsed["RESP"], parsed["NOTE"])],
        "Interaction_Note": parsed["NOTE"].fillna("").str.strip(),
        "raw_log": parsed["raw_log"],
    })

    df["Friction_Reason"] = [
        classify_friction(n, h) for n, h in zip(df["Interaction_Note"], df["Response_Time_Hours"])
    ]

    # Conditional Closed-Lost tagging:
    #   explicit lost stage            -> Closed-Lost
    #   blank stage + friction evidence -> Closed-Lost (inferred)
    inferred = df["Deal_Stage"].isna() & df["Friction_Reason"].notna()
    df.loc[inferred, "Deal_Stage"] = "Closed-Lost"
    df["Stage_Inferred"] = inferred
    df["Is_Closed_Lost"] = df["Deal_Stage"].eq("Closed-Lost")

    # Lost deals with no detectable cause still need a bucket for reporting
    df.loc[df["Is_Closed_Lost"] & df["Friction_Reason"].isna(), "Friction_Reason"] = "Unattributed"
    # Friction on non lost deals is a risk signal, not leakage
    df["Leakage_GBP"] = np.where(df["Is_Closed_Lost"], df["Revenue_Amount_GBP"], 0.0)

    # ---- Validation gate: build a reason per failure ----------------------
    reasons = pd.Series("", index=df.index)
    reasons[df["raw_log"].fillna("").str.strip().eq("")] += "EMPTY_ROW;"
    reasons[df["Transaction_ID"].isna()] += "MISSING_TXN_ID;"
    reasons[df["Transaction_Timestamp"].isna()] += "UNPARSEABLE_DATE;"
    reasons[df["Customer_UUID"].isna()] += "INVALID_CUSTOMER_UUID;"
    reasons[df["Revenue_Amount_GBP"].isna()] += "UNPARSEABLE_REVENUE;"
    reasons[df["Deal_Stage"].isna()] += "UNKNOWN_DEAL_STAGE;"
    dup_mask = df["Transaction_ID"].notna() & df.duplicated(subset="Transaction_ID", keep="first")
    reasons[dup_mask] += "DUPLICATE_TXN;"
    df["Rejection_Reason"] = reasons.str.rstrip(";")

    bad = df["Rejection_Reason"].ne("")
    rejected = df.loc[bad].copy()
    rejected["Quarantined_At"] = pd.Timestamp.now().floor("s")
    rejected = rejected[["Rejection_Reason", "Quarantined_At", "raw_log",
                         "Transaction_ID", "Transaction_Timestamp", "Customer_UUID",
                         "Revenue_Amount_GBP", "Deal_Stage"]]

    clean = df.loc[~bad].drop(columns=["raw_log", "Rejection_Reason"]).copy()

    # ---- Strict enterprise type casting -----------------------------------
    clean["Revenue_Amount_GBP"] = clean["Revenue_Amount_GBP"].astype("float64")
    clean["Leakage_GBP"] = clean["Leakage_GBP"].astype("float64")
    clean["Transaction_Timestamp"] = pd.to_datetime(clean["Transaction_Timestamp"])
    clean["Customer_UUID"] = clean["Customer_UUID"].astype(str).str.strip()
    clean["Deal_Stage"] = clean["Deal_Stage"].astype(str).str.strip()
    clean["Response_Time_Hours"] = clean["Response_Time_Hours"].astype("Int64")
    clean["Friction_Reason"] = clean["Friction_Reason"].fillna("None")
    for col in ("Transaction_ID", "Channel", "Region", "Product_Category"):
        clean[col] = clean[col].fillna("Unknown").astype(str).str.strip()

    clean = clean.sort_values("Transaction_Timestamp").reset_index(drop=True)
    return clean, rejected


# ---------------------------------------------------------------------------
# 5. DATA QUALITY ASSERTIONS (fail loudly, never ship bad data)
# ---------------------------------------------------------------------------
def assert_contract(clean: pd.DataFrame) -> None:
    assert clean["Revenue_Amount_GBP"].dtype == "float64"
    assert pd.api.types.is_datetime64_any_dtype(clean["Transaction_Timestamp"])
    assert clean["Customer_UUID"].str.fullmatch(r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}").all()
    assert clean["Deal_Stage"].isin(["Closed-Won", "Closed-Lost", "Open"]).all()
    assert clean["Transaction_ID"].is_unique
    assert (clean["Revenue_Amount_GBP"] > 0).all()
    log.info("Data contract checks passed")


# ---------------------------------------------------------------------------
# 6. ORCHESTRATION
# ---------------------------------------------------------------------------
def run() -> None:
    log.info("=== Project Nexus | Phase 1 ingestion start ===")
    raw = generate_chaotic_logs()
    raw.to_csv(RAW_FILE, index=False)
    log.info("Raw extract written: %s (%s rows)", RAW_FILE.name, f"{len(raw):,}")

    clean, rejected = transform(raw)
    assert_contract(clean)

    clean.to_csv(CLEAN_FILE, index=False, date_format="%Y-%m-%d %H:%M:%S")
    rejected.to_csv(REJECT_FILE, index=False, date_format="%Y-%m-%d %H:%M:%S")

    # ---- Run summary -------------------------------------------------------
    lost = clean[clean["Is_Closed_Lost"]]
    total_rev = clean["Revenue_Amount_GBP"].sum()
    leak = lost["Revenue_Amount_GBP"].sum()

    log.info("Clean rows:       %s -> %s", f"{len(clean):,}", CLEAN_FILE.relative_to(PROJECT_ROOT))
    log.info("Quarantined rows: %s -> %s", f"{len(rejected):,}", REJECT_FILE.relative_to(PROJECT_ROOT))
    log.info("Pipeline pass rate: %.1f%%", 100 * len(clean) / len(raw))
    log.info("Pipeline value: £%s | Closed-Lost leakage: £%s (%.1f%%)",
             f"{total_rev:,.2f}", f"{leak:,.2f}", 100 * leak / total_rev)

    print("\nLeakage by friction reason")
    print(lost.groupby("Friction_Reason")["Revenue_Amount_GBP"]
              .agg(Deals="count", Leakage_GBP="sum")
              .sort_values("Leakage_GBP", ascending=False)
              .round(2).to_string())

    print("\nTop quarantine reasons")
    print(rejected["Rejection_Reason"].str.split(";").explode()
              .value_counts().to_string())
    log.info("=== Phase 1 complete ===")


if __name__ == "__main__":
    run()
