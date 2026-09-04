#!/usr/bin/env python3
import csv
import sys
from datetime import date, datetime

EXPECTED_HEADER = [
    "Sutarties unikalus ID",
    "Sutarties numeris",
    "Sutarties objektas",
    "Pirkimo numeris",
    "BVPŽ kodas",
    "Perkančioji organizacija",
    "Perkančiosios organizacijos kodas",
    "Tiekėjas (-ai)",
    "Tiekėjo kodas",
    "Vertė",
    "Sudarymo data",
    "Galiojimo data",
    "Paskelbimo data",
    "Paskutinio redagavimo data",
    "Tipas",
]

def parse_date(value: str):
    text = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%d.%m.%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            pass
    return None

def main(path: str) -> None:
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        raw = f.read()

    lowered = raw[:4000].lower()
    html_markers = ("<html", "<!doctype", "<br", "<b>notice", "undefined constant", "php")
    if any(marker in lowered for marker in html_markers):
        # Allow only the known CVP export quirk: leading semicolon-only/PHP-warning lines.
        lines = raw.splitlines()
        while lines and (
            not lines[0].strip()
            or all(cell.strip() == "" for cell in lines[0].split(";"))
            or "<br" in lines[0].lower()
            or "<b>notice</b>" in lines[0].lower()
            or "undefined constant" in lines[0].lower()
        ):
            lines.pop(0)
        raw = "\n".join(lines)
        if raw.lstrip().lower().startswith(("<html", "<!doctype", "<br", "<b>notice")):
            raise RuntimeError("Šaltinis grąžino HTML/PHP klaidą vietoje CVP CSV.")

    rows = list(csv.reader(raw.splitlines(), delimiter=";"))
    while rows and all(cell.strip() == "" for cell in rows[0]):
        rows.pop(0)

    if not rows:
        raise RuntimeError("CSV tuščias.")

    header = [cell.strip() for cell in rows[0]]
    if header != EXPECTED_HEADER:
        raise RuntimeError("Netikėta CSV antraštė: " + ";".join(header))

    data = [row for row in rows[1:] if any(cell.strip() for cell in row)]
    if not data:
        raise RuntimeError("CSV neturi duomenų eilučių.")
    if any(len(row) != 15 for row in data):
        bad = next(len(row) for row in data if len(row) != 15)
        raise RuntimeError(f"CSV turi ne 15, o {bad} stulpelių bent vienoje eilutėje.")

    with open("config/target_scope.csv", "r", encoding="utf-8-sig", newline="") as f:
        targets = {
            row["Juridinis_kodas"].strip()
            for row in csv.DictReader(f)
            if row.get("Juridinis_kodas")
        }

    today = date.today()
    monitored = 0
    valid = 0
    invalid_dates = 0

    for row in data:
        code = row[6].strip()
        if code not in targets:
            continue
        monitored += 1
        expiry = parse_date(row[11])
        if expiry is None:
            invalid_dates += 1
            continue
        if expiry >= today:
            valid += 1

    if monitored == 0:
        raise RuntimeError("CSV nerasta nė vienos iš konfigūracijoje stebimų įstaigų.")
    if valid == 0:
        raise RuntimeError("CSV nerasta nė vienos šiandien galiojančios stebimos sutarties.")

    print(
        f"PASS: rows={len(data)} monitored={monitored} valid={valid} "
        f"invalid_dates={invalid_dates} columns={len(header)}"
    )

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Naudojimas: python scripts/validate_contract_csv.py <csv>")
    main(sys.argv[1])
