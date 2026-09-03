#!/usr/bin/env python3
"""Build daily CVP contract snapshot for the 57 monitored legal entities.

The API key is supplied only through the GitHub Actions secret CVP_API_KEY.
The output is the same 14-column semicolon CSV shape consumed by the Excel
CVP_Import_to_Table_V2_OfficeScript.
"""
import csv
import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_URL = "https://viesiejipirkimai.lt/epps-integration/api/cft-details-export"
TARGET_FILE = Path("config/target_scope.csv")
OUT_DIR = Path("output")
PAGE_SIZE = 1000
MAX_PAGES = 10000

HEADERS = [
    "Sutarties_ID", "Sutarties_numeris", "Objektas", "Pirkimo_numeris",
    "BVPZ_kodas", "Mokykla", "Juridinis_kodas", "Tiekejas",
    "Tiekejo_kodas", "Verte", "Pasirasymo_data", "Galioja_iki",
    "Paskelbimo_data", "Paskutinio_redagavimo_data",
]

ALIASES = {
    "Sutarties_ID": ["Sutarties_ID", "DOK_ID", "DOK_SUT_ID", "contractId", "contractID"],
    "Sutarties_numeris": ["Sutarties_numeris", "DOK_REG_NR", "DOK_SUT_NUMERIS", "contractNumber", "registrationNumber"],
    "Objektas": ["Objektas", "DOK_OBJ_PAV", "DOK_PIRK_OBJ_PAV", "description", "purchaseObject", "object"],
    "Pirkimo_numeris": ["Pirkimo_numeris", "DOK_PIRKIMO_KODAS", "purchaseNumber", "purchaseCode", "cftNumber"],
    "BVPZ_kodas": ["BVPZ_kodas", "BVPZ", "DOK_BVPZ", "cpv", "cpvCode", "cpvCodes"],
    "Mokykla": ["Mokykla", "PV_PAV", "Pirkimo_vykdytojas", "Pirkimo vykdytojas", "contractingAuthority", "contractAuthorityName"],
    "Juridinis_kodas": ["Juridinis_kodas", "PV_KODAS", "JAR_KODAS", "JAR_kodas", "contractingAuthorityCode"],
    "Tiekejas": ["Tiekejas", "TIEK_PAV", "supplier", "supplierName"],
    "Tiekejo_kodas": ["Tiekejo_kodas", "TIEK_KODAS", "supplierCode", "supplierJarCode"],
    "Verte": ["Verte", "DOK_SUT_VERTĖ", "DOK_SUT_VERTE", "contractValue", "value", "amount"],
    "Pasirasymo_data": ["Pasirasymo_data", "DOK_SUDARYMO_DATA", "contractConclusionDate", "contractDate", "agreementDate"],
    "Galioja_iki": ["Galioja_iki", "DOK_SUT_GALIOJIMO_DATA", "contractExpirationDate", "expirationDate", "endDate", "validTo"],
    "Paskelbimo_data": ["Paskelbimo_data", "DOK_SYS_REG_DATA", "publicationDate", "publishedDate", "systemRegistrationDate"],
    "Paskutinio_redagavimo_data": ["Paskutinio_redagavimo_data", "lastModifiedDate", "lastEditDate", "updatedAt", "modificationDate"],
}


def norm_key(value):
    return re.sub(r"[^a-z0-9ąčęėįšųūž]+", "", str(value or "").lower().strip())


def clean(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value).strip()


def code(value):
    return re.sub(r"\D", "", clean(value))


def date_value(value):
    text = clean(value)
    if not text:
        return ""
    m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if m:
        return m.group(1)
    m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", text)
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""


def recursive_dicts(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from recursive_dicts(item)
    elif isinstance(value, list):
        for item in value:
            yield from recursive_dicts(item)


def get_field(record, names):
    wanted = {norm_key(n) for n in names}
    for obj in recursive_dicts(record):
        for key, value in obj.items():
            if norm_key(key) in wanted:
                return value
    return ""


def extract_records(payload):
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("content", "items", "data", "results", "records", "contracts", "result"):
        value = payload.get(key)
        if isinstance(value, list):
            rows = [x for x in value if isinstance(x, dict)]
            if rows:
                return rows
        if isinstance(value, dict):
            rows = extract_records(value)
            if rows:
                return rows
    return []


def load_targets():
    with TARGET_FILE.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if len(rows) != 57:
        raise RuntimeError(f"target_scope.csv turi turėti 57 įrašus, rasta {len(rows)}")
    return {code(r.get("Juridinis_kodas")): clean(r.get("Pavadinimas")) for r in rows if code(r.get("Juridinis_kodas"))}


def request_page(api_key, page_num):
    payload = json.dumps({"pageSize": PAGE_SIZE, "pageNum": page_num}).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=payload,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "apiKey": api_key,
            "User-Agent": "cvp-monitor-contract-refresh/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def map_record(record):
    item = {name: get_field(record, aliases) for name, aliases in ALIASES.items()}
    return [
        clean(item["Sutarties_ID"]), clean(item["Sutarties_numeris"]), clean(item["Objektas"]),
        clean(item["Pirkimo_numeris"]), clean(item["BVPZ_kodas"]), clean(item["Mokykla"]),
        code(item["Juridinis_kodas"]), clean(item["Tiekejas"]), code(item["Tiekejo_kodas"]),
        clean(item["Verte"]), date_value(item["Pasirasymo_data"]), date_value(item["Galioja_iki"]),
        date_value(item["Paskelbimo_data"]), date_value(item["Paskutinio_redagavimo_data"]),
    ]


def main():
    api_key = os.environ.get("CVP_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Trūksta GitHub Actions secret CVP_API_KEY.")
    watched = load_targets()
    today = datetime.now(timezone.utc).date().isoformat()
    seen = set()
    rows = []
    diagnostics = {"status": "OK", "date": today, "apiPages": 0, "apiRecords": 0, "watchedRecords": 0, "validRows": 0, "expiredSkipped": 0, "missingExpirySkipped": 0, "missingIdSkipped": 0}

    for page in range(1, MAX_PAGES + 1):
        payload = request_page(api_key, page)
        records = extract_records(payload)
        diagnostics["apiPages"] = page
        if not records:
            break
        diagnostics["apiRecords"] += len(records)
        for record in records:
            row = map_record(record)
            if not row[0]:
                diagnostics["missingIdSkipped"] += 1
                continue
            if row[6] not in watched:
                continue
            diagnostics["watchedRecords"] += 1
            if not row[11]:
                diagnostics["missingExpirySkipped"] += 1
                continue
            if row[11] < today:
                diagnostics["expiredSkipped"] += 1
                continue
            if row[0] in seen:
                continue
            seen.add(row[0])
            if not row[5]:
                row[5] = watched[row[6]]
            rows.append(row)
        if len(records) < PAGE_SIZE:
            break

    if not rows:
        raise RuntimeError("Nė vienos galiojančios stebimos sutarties. " + json.dumps(diagnostics, ensure_ascii=False))

    rows.sort(key=lambda r: (r[6], r[11], r[0]))
    out = OUT_DIR / f"sutartys_{today}.csv"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(HEADERS)
        writer.writerows(rows)

    diagnostics["validRows"] = len(rows)
    diagnostics["file"] = out.name
    (OUT_DIR / "contract_snapshot_meta.json").write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(diagnostics, ensure_ascii=False))


if __name__ == "__main__":
    main()
