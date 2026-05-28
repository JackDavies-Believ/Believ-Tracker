"""
build.py  —  Believ Status Movement Tracker
Fetches the Sitetracker history report from Salesforce,
processes the data, and writes the tracker HTML to docs/index.html
"""
import os, json, re
from datetime import datetime, timedelta
from collections import defaultdict
from simple_salesforce import Salesforce

# ── CONFIG ─────────────────────────────────────────────────────
# Replace this with your actual Report ID from Step 1.1
REPORT_ID = "YOUR_REPORT_ID_HERE"

# ── CONNECT TO SALESFORCE ──────────────────────────────────────
sf = Salesforce(
    username        = os.environ["SF_USERNAME"],
    password        = os.environ["SF_PASSWORD"],
    security_token  = os.environ["SF_TOKEN"],
    consumer_key    = os.environ["SF_CONSUMER_KEY"],
    consumer_secret = os.environ["SF_CONSUMER_SECRET"],
)
print("✓ Connected to Salesforce")

# ── FETCH REPORT ───────────────────────────────────────────────
# includeDetails=true returns every individual row
url = f"{sf.base_url}analytics/reports/{REPORT_ID}?includeDetails=true"
response = sf._call_salesforce("GET", url)
report_data = response.json()

# Extract column headers
columns = report_data["reportMetadata"]["detailColumns"]
col_labels = {
    col: report_data["reportExtendedMetadata"]["detailColumnInfo"][col]["label"]
    for col in columns
}
print(f"✓ Report columns: {list(col_labels.values())}")

# Extract rows
rows = report_data["factMap"]["T!T"]["rows"]
print(f"✓ Fetched {len(rows)} rows")

# ── PARSE ROWS ─────────────────────────────────────────────────
# Map column labels to our expected field names
# Adjust these if your column names differ slightly
LABEL_MAP = {
    "Site History: Site History ID": "site",
    "Account":                     "account",
    "Old Value":                    "old_v",
    "New Value":                    "new_v",
    "Modify Date":                  "date",
    "Total No. Active Bays":        "bays",
    "Field":                        "field",
}

# Build index: column API name → our field name
col_index = {}
for api_name, label in col_labels.items():
    if label in LABEL_MAP:
        col_index[api_name] = LABEL_MAP[label]

raw_data = []
for row in rows:
    rec = {}
    for i, col in enumerate(columns):
        field_name = col_index.get(col)
        if field_name:
            rec[field_name] = row["dataCells"][i]["label"] or ""
    raw_data.append(rec)

# ── NORMALISE STATUSES ─────────────────────────────────────────
LEGACY_MAP = {
    "Newly Selected Site":               "1. Site Selection",
    "Site Planning and Survey":          "3. Surveys and HLD",
    "Site Planning and Surveys":         "3. Surveys and HLD",
    "HLD Review":                        "5. HLD Review",
    "HLD Drawing Review":               "5. HLD Review",
    "Approval to Plan":                  "8. ATP Preparation",
    "ATP Preparation":                   "8. ATP Preparation",
    "Detailed Design Review":            "10. DD Review",
    "DNO Checks":                        "12. Connection Legals",
    "DNO Requested":                     "12. Connection Legals",
    "Planning - Consultations & Applications": "13. Public Consultation",
    "IAAS Completed":                    "14. ATB Preparation",
    "ATB Preparation":                   "14. ATB Preparation",
    "Approval to Build":                 "14. ATB Preparation",
    "Civils Planned":                    "15. Equipment Procurement",
    "Infrastructure Permits":            "17. Permitting",
    "Approved to Build - Awaiting Legal": "16. Legals",
    "Stage 4":                           "16. Legals",
    "Build in Progress":                 "18. Build in Progress",
    "Civils in Progress":               "18. Build in Progress",
    "Civils Completed":                  "19. Civils complete - awaiting power",
    "Power Connection in Progress":      "19. Civils complete - awaiting power",
    "Metering Pending":                  "20. Meter pending",
    "Meter Pending":                     "20. Meter pending",
    "On Hold - Waiting for Customer":    "On Hold",
    "On Hold - Waiting from LA":         "On Hold",
    "Decommissioned":                    "Terminated",
}

VALID_STATUSES = [
    "1. Site Selection", "2. Site Selection Client Approval",
    "3. Surveys and HLD", "4. Awaiting POC", "5. HLD Review",
    "6. HLD Client Approval", "7. Contract Negotiation", "8. ATP Preparation",
    "9. DD Preparation", "10. DD Review", "11. DD Client Approval",
    "12. Connection Legals", "13. Public Consultation", "14. ATB Preparation",
    "15. Equipment Procurement", "16. Legals", "17. Permitting",
    "18. Build in Progress", "19. Civils complete - awaiting power",
    "20. Meter pending", "21. Commissioning Pending",
    "CP Live", "On Hold", "Terminated",
]

def normalise(s):
    s = s.strip()
    if s in LEGACY_MAP: return LEGACY_MAP[s]
    return s if s in VALID_STATUSES else None

# ── BUILD RECORDS ──────────────────────────────────────────────
records = []
created = []
accounts_set = set()

for r in raw_data:
    site    = r.get("site", "")
    account = r.get("account", "")
    old_v   = r.get("old_v", "")
    new_v   = r.get("new_v", "")
    date_s  = r.get("date", "")
    field   = r.get("field", "")
    try:
        bays = int(float(r.get("bays", 0) or 0))
    except:
        bays = 0
    if not date_s: continue
    try:
        dt = datetime.strptime(date_s[:16], "%d/%m/%Y, %H:%M")
    except:
        try:
            dt = datetime.strptime(date_s[:10], "%d/%m/%Y")
        except:
            continue
    mon  = dt - timedelta(days=dt.weekday())
    week = mon.strftime("%Y-%m-%d")
    accounts_set.add(account)
    if field == "Created":
        created.append({"s":site, "a":account, "d":dt.strftime("%Y-%m-%d"), "w":week, "b":bays})
    else:
        old_n = normalise(old_v)
        new_n = normalise(new_v)
        if old_n and new_n and old_n != new_n:
            records.append({"s":site, "a":account, "o":old_n, "n":new_n,
                            "d":dt.strftime("%Y-%m-%d"), "w":week, "b":bays})

accounts_list = sorted([a for a in accounts_set if a])
print(f"✓ {len(records)} status-change records, {len(created)} created records")

# ── WRITE HTML ─────────────────────────────────────────────────
# Read the template, inject the data JSON, write to docs/index.html
db = {"records": records, "created": created,
      "statuses": VALID_STATUSES, "accounts": accounts_list}

# Load the HTML template (we store it separately — see Step 3.2)
with open("template.html", "r", encoding="utf-8") as f:
    template = f.read()

# Inject the data
built_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
html = template.replace("__DATA_JSON__", json.dumps(db))
html = html.replace("__BUILT_AT__", built_at)
html = html.replace("__TOTAL_RECORDS__", str(len(records)))
html = html.replace("__TOTAL_CREATED__", str(len(created)))

os.makedirs("docs", exist_ok=True)
with open("docs/index.html", "w", encoding="utf-8") as f:
    f.write(html)

print(f"✓ Written docs/index.html ({len(html)//1024} KB) — built at {built_at}")
