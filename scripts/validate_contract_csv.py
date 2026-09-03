#!/usr/bin/env python3
import csv
import sys
from datetime import date

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


def main(path: str) -> None:
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f, delimiter=";"))

    # CVP export may contain PHP warning rows consisting only of semicolons.
    while rows and all(cell.strip() == "" for cell in rows[0]):
        rows.pop(0)

    if not rows:
        raise RuntimeError("CSV tuščias.")

    if rows[0] != EXPECTED_HEADER:
        raise RuntimeError(
            "Netikėta CSV antraštė. Gauta: " + ";".join(rows[0])
        )

    data = [r for r in rows[1:] if any(cell.strip() for cell in r)]
    if not data:
        raise RuntimeError("CSV neturi duomenų eilučių.")
    if any(len(r) < 15 for r in data):
        raise RuntimeError("Bent viena CSV duomenų eilutė turi mažiau nei 15 stulpelių.")

    today = date(2026, 9, 3)
    valid = 0
    monitored = 0
    for row in data:
        code = row[6].strip()
        if code not in {
            "191635156", "191634816", "191094715", "290140580", "191846114",
            "191642688", "190140622", "191828963", "191829150", "195096037",
            "290136920", "190136734", "190135785", "190138938", "190139278",
            "190138219", "190134345", "190137455", "190138176", "190139997",
            "190140775", "191824947", "190138742", "191816085", "191824228",
            "190137074", "190134498", "190135970", "190138361", "190136168",
            "190138023", "191090994", "190136549", "190134530", "295093070",
            "190133777", "190139463", "290134150", "190133962", "190139659",
            "191825091", "190136353", "190136691", "290133810", "190137989",
            "190135447", "300594100", "190138557", "191090841", "190139844",
            "190134683", "190138895", "190135828", "190136887", "190983430",
            "290983050", "190797479",
        }:
            continue
        monitored += 1
        try:
            expiry = date.fromisoformat(row[11].strip())
        except ValueError:
            continue
        if expiry >= today:
            valid += 1

    if monitored == 0:
        raise RuntimeError("CSV neturi nė vienos iš 57 stebimų juridinių kodų eilučių.")
    if valid == 0:
        raise RuntimeError("CSV nėra nė vienos šiandien galiojančios stebimos sutarties.")

    print(f"PASS: rows={len(data)} monitored={monitored} valid={valid} columns={len(rows[0])}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Naudojimas: python scripts/validate_contract_csv.py <csv>")
    main(sys.argv[1])
