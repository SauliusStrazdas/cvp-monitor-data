import csv
import json
import os
import re
import urllib.request
from datetime import date, datetime

API_URL = "https://viesiejipirkimai.lt/epps-integration/api/cft-details-export"
OUTPUT_DIR = "output"
OUT_HEADERS = [
    "Sutarties_ID", "Sutarties_numeris", "Objektas", "Pirkimo_numeris", "BVPZ_kodas", "Mokykla",
    "Juridinis_kodas", "Tiekejas", "Tiekejo_kodas", "Verte", "Pasirasymo_data", "Galioja_iki",
    "Paskelbimo_data", "Paskutinio_redagavimo_data"
]

def norm(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())

def clean(value):
    return str(value or "").strip()

def parse_date(value):
    text = clean(value)
    if not text:
        return None
    for candidate in (text, text[:10]):
        for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%d.%m.%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(candidate, fmt).date()
            except ValueError:
                pass
    return None

def find_value(record, aliases):
    alias_set = {norm(a) for a in aliases}
    def walk(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if norm(key) in alias_set and not isinstance(value, (dict, list)):
                    return clean(value)
            for value in obj.values():
                found = walk(value)
                if found != "":
                    return found
        elif isinstance(obj, list):
            for value in obj:
                found = walk(value)
                if found != "":
                    return found
        return ""
    return walk(record)

def extract_records(payload):
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("content", "items", "data", "results", "records", "contracts", "result"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = extract_records(value)
            if nested:
                return nested
    for value in payload.values():
        if isinstance(value, list) and value and all(isinstance(x, dict) for x in value):
            return value
        if isinstance(value, dict):
            nested = extract_records(value)
            if nested:
                return nested
    return []

def map_record(record, canonical_by_juridical):
    juridical = find_value(record, ["Juridinis_kodas", "Juridinis kodas", "juridinisKodas", "jarCode", "jarcode", "JAR_kodas", "JAR kodas", "contractingAuthorityLegalEntityCode"])
    juridical = re.sub(r"\D", "", juridical)
    if not juridical or juridical not in canonical_by_juridical:
        return None
    contract_id = find_value(record, ["Sutarties_ID", "Sutarties ID", "sutartiesUnikalusId", "contractId", "contractUniqueId", "DOK_ID", "dokId"])
    if not contract_id:
        return None
    authority = find_value(record, ["Mokykla", "Pirkimo vykdytojo pavadinimas", "perkančioji organizacija", "contractingAuthorityName", "contractingAuthority", "organizationName", "DOK_PERKANCIOSIOS_ORGANIZACIJOS_PAVADINIMAS"]) or canonical_by_juridical[juridical]
    return [
        contract_id,
        find_value(record, ["Sutarties_numeris", "Sutarties numeris", "contractNumber", "DOK_REG_NR"]),
        find_value(record, ["Objektas", "Pavadinimas", "Aprašymas", "description", "object"]),
        find_value(record, ["Pirkimo_numeris", "Viešojo pirkimo numeris", "pirkimo numeris", "procurementNumber"]),
        find_value(record, ["BVPZ_kodas", "BVPŽ kodai", "BVPZ kodas", "cpvCode", "cpvCodes"]),
        authority,
        juridical,
        find_value(record, ["Tiekejas", "Tiekėjas", "supplierName", "winnerName"]),
        find_value(record, ["Tiekejo_kodas", "Tiekėjo kodas", "supplierCode", "winnerCode"]),
        find_value(record, ["Verte", "Vertė", "contractValue", "value"]),
        find_value(record, ["Pasirasymo_data", "Pasirašymo data", "Sutarties sudarymo data", "contractConclusionDate", "DOK_SUDARYMO_DATA"]),
        find_value(record, ["Galioja_iki", "Galioja iki", "contractEndDate", "expirationDate", "DOK_SUT_GALIOJIMO_DATA"]),
        find_value(record, ["Paskelbimo_data", "Paskelbimo data", "publicationDate", "DOK_SYS_REG_DATA"]),
        find_value(record, ["Paskutinio_redagavimo_data", "Paskutinio redagavimo data", "lastModifiedDate", "updatedAt"]),
    ]

def request_page(api_key, page, page_size=1000, timeout=120):
    body = json.dumps({"pageSize": page_size, "pageNum": page}).encode("utf-8")
    request = urllib.request.Request(API_URL, data=body, method="POST", headers={"Accept": "application/json", "Content-Type": "application/json", "apiKey": api_key})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))

def main():
    api_key = os.environ.get("CVP_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("CVP_API_KEY secret is missing")
    today_iso = date.today().isoformat()
    targets = {}
    with open("config/target_scope.csv", "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            code = re.sub(r"\D", "", clean(row.get("Juridinis_kodas")))
            name = clean(row.get("Pavadinimas"))
            if code:
                targets[code] = name
    if not targets:
        raise RuntimeError("No monitored legal entities found in config/target_scope.csv")
    rows_by_id = {}
    total_api_records = 0
    pages_read = 0
    for page in range(1, 5001):
        payload = request_page(api_key, page)
        records = extract_records(payload)
        pages_read += 1
        total_api_records += len(records)
        if not records:
            break
        for record in records:
            mapped = map_record(record, targets)
            if not mapped:
                continue
            expiry = parse_date(mapped[11])
            if expiry is None or expiry < date.fromisoformat(today_iso):
                continue
            previous = rows_by_id.get(mapped[0])
            if previous is None or mapped[13] > previous[13]:
                rows_by_id[mapped[0]] = mapped
        if len(records) < 1000:
            break
    rows = list(rows_by_id.values())
    rows.sort(key=lambda r: (r[6], r[0]))
    if not rows:
        raise RuntimeError(f"CVP API returned {total_api_records} records across {pages_read} pages, but no valid watched contracts remained.")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, f"sutartys_{today_iso}.csv")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        writer.writerow(OUT_HEADERS)
        writer.writerows(rows)
    meta = {"date": today_iso, "pagesRead": pages_read, "totalApiRecords": total_api_records, "rowsWritten": len(rows), "monitoredEntities": len(targets)}
    with open(os.path.join(OUTPUT_DIR, "contract_snapshot_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(json.dumps(meta, ensure_ascii=False))

if __name__ == "__main__":
    main()
