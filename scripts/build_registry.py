#!/usr/bin/env python3
import csv
import hashlib
import io
import re
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

SOURCE_URL = "https://www.geoportal.lt/download/opendata/svietimo_istaigos/LT_svietimo_istaigos.zip"
TARGET_FILE = Path("config/target_scope.csv")
OUT_ENTITIES = Path("output/registry_entities.csv")
OUT_BRANCHES = Path("output/registry_branches.csv")
HASH_FILE = Path("output/source.sha256")


def norm(value):
    text = str(value or "").lower()
    for old, new in {
        "\ufeff": "", "„": "", "“": "", '"': "", "'": "",
        "ą": "a", "č": "c", "ę": "e", "ė": "e", "į": "i",
        "š": "s", "ų": "u", "ū": "u", "ž": "z",
    }.items():
        text = text.replace(old, new)
    text = re.sub(r"[\*\u00a0]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def code(value):
    return re.sub(r"\D", "", str(value or ""))


def clean(value):
    return "" if value is None else str(value).strip()


def norm_header(value):
    return norm(value).replace(" ", "_").replace("-", "_")


def find_col(headers, aliases):
    nh = [norm_header(h) for h in headers]
    na = [norm_header(a) for a in aliases]
    for alias in na:
        if alias in nh:
            return nh.index(alias)
    for i, header in enumerate(nh):
        if any(alias and alias in header for alias in na):
            return i
    return None


def load_targets():
    with TARGET_FILE.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if len(rows) != 57:
        raise RuntimeError(f"config/target_scope.csv turi turėti 57 įrašus, rasta {len(rows)}.")
    required = {"Kategorija", "Juridinis_kodas", "Pavadinimas"}
    if not rows or not required.issubset(rows[0].keys()):
        raise RuntimeError("target_scope.csv trūksta privalomų stulpelių.")
    for i, row in enumerate(rows, 1):
        if not code(row.get("Juridinis_kodas")):
            raise RuntimeError(f"target_scope.csv eilutėje {i} trūksta Juridinis_kodas.")
        if not clean(row.get("Pavadinimas")):
            raise RuntimeError(f"target_scope.csv eilutėje {i} trūksta Pavadinimas.")
    return rows


def download_source():
    req = urllib.request.Request(
        SOURCE_URL,
        headers={"User-Agent": "cvp-monitor-data/1.0 (GitHub Actions)"}
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            raw = response.read()
    except Exception as exc:
        raise RuntimeError(f"Nepavyko atsisiųsti oficialaus šaltinio: {exc}") from exc
    if not raw.startswith(b"PK"):
        raise RuntimeError("Oficialus Geoportal URL negrąžino ZIP failo.")
    return raw


def read_shp(raw_zip):
    try:
        import shapefile
    except ImportError:
        import subprocess
        subprocess.check_call(["python", "-m", "pip", "install", "--quiet", "pyshp"])
        import shapefile

    with zipfile.ZipFile(io.BytesIO(raw_zip), "r") as archive:
        names = archive.namelist()
        lower = {n.lower(): n for n in names}
        selected = None
        for shp in [n for n in names if n.lower().endswith(".shp")]:
            base = shp[:-4]
            shx = lower.get((base + ".shx").lower())
            dbf = lower.get((base + ".dbf").lower())
            if shx and dbf:
                selected = (shp, shx, dbf)
                break
        if not selected:
            raise RuntimeError("ZIP faile nerastas pilnas SHP + SHX + DBF rinkinys.")
        parts = [io.BytesIO(archive.read(x)) for x in selected]

    last_error = None
    for encoding in ("utf-8", "cp1257", "cp1252", "latin1"):
        try:
            for part in parts:
                part.seek(0)
            reader = shapefile.Reader(shp=parts[0], shx=parts[1], dbf=parts[2], encoding=encoding)
            headers = [field[0] for field in reader.fields[1:]]
            rows = [list(record) for record in reader.iterRecords()]
            print(f"SHP encoding={encoding} rows={len(rows)}")
            return headers, rows
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"Nepavyko perskaityti SHP/DBF: {last_error}")


def write_csv(path, headers, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)


def main():
    targets = load_targets()
    raw = download_source()
    digest = hashlib.sha256(raw).hexdigest()
    old_hash = HASH_FILE.read_text(encoding="utf-8").strip() if HASH_FILE.exists() else ""

    if digest == old_hash and OUT_ENTITIES.exists() and OUT_BRANCHES.exists():
        print("SOURCE_UNCHANGED=1")
        return

    headers, data = read_shp(raw)
    if not data:
        raise RuntimeError("Oficialiame šaltinyje nėra duomenų.")

    # Geoportal SHP schema verified in the failed run:
    # Inst_kodas, ..., Tipas, Pav_LT, ..., Adresas, Sav_kodas, ..., JAR_kod_1, JAR_kod_2, ...
    jar1_col = find_col(headers, ["JAR_kod_1", "JAR kodas", "Juridinio asmens kodas", "Juridinis kodas"])
    jar2_col = find_col(headers, ["JAR_kod_2"])
    name_col = find_col(headers, ["Pav_LT", "Įstaigos pavadinimas", "Institucijos pavadinimas", "Pavadinimas"])
    address_col = find_col(headers, ["Adresas", "Įstaigos adresas", "Buveinės adresas"])
    type_col = find_col(headers, ["Tipas", "Įstaigos tipas", "Institucijos tipas"])
    municipality_col = find_col(headers, ["Savivaldybė", "Savivaldybės pavadinimas"])
    unit_col = find_col(headers, ["Inst_kodas", "ŠMIR kodas", "SMIR kodas", "Padalinio kodas", "Padalinio ID"])

    if jar1_col is None or name_col is None:
        raise RuntimeError(f"Nepavyko nustatyti JAR kodo ir pavadinimo laukų. Oficialaus šaltinio laukai: {headers}")

    by_code = {code(t["Juridinis_kodas"]): t for t in targets}
    by_name = {norm(t["Pavadinimas"]): t for t in targets}
    found = {code(t["Juridinis_kodas"]): [] for t in targets}
    source_date = datetime.now(timezone.utc).date().isoformat()

    for row in data:
        candidates = []
        for col in (jar1_col, jar2_col):
            if col is not None and col < len(row):
                value = code(row[col])
                if value and value not in candidates:
                    candidates.append(value)
        name = clean(row[name_col]) if name_col < len(row) else ""
        target = next((by_code[c] for c in candidates if c in by_code), None)
        if target is None and name:
            target = by_name.get(norm(name))
        if target is None:
            continue

        target_code = code(target["Juridinis_kodas"])
        current_code = next((c for c in candidates if c), target_code)
        address = clean(row[address_col]) if address_col is not None and address_col < len(row) else ""
        inst_type = clean(row[type_col]) if type_col is not None and type_col < len(row) else ""
        municipality = clean(row[municipality_col]) if municipality_col is not None and municipality_col < len(row) else "Kaunas"
        unit_id = clean(row[unit_col]) if unit_col is not None and unit_col < len(row) else ""
        found[target_code].append({
            "code": current_code, "name": name, "address": address,
            "type": inst_type, "municipality": municipality or "Kaunas", "unit_id": unit_id,
        })

    found_count = sum(1 for hits in found.values() if hits)
    if found_count == 0:
        raise RuntimeError("Nė viena iš 57 tikslinių įstaigų nerasta oficialiame šaltinyje.")

    entities, branches = [], []
    for i, target in enumerate(targets, 1):
        tc = code(target["Juridinis_kodas"])
        hits = found[tc]
        exact = [h for h in hits if h["code"] == tc]
        primary = (exact or hits)[0] if hits else None

        if primary:
            entities.append([
                i, target["Kategorija"], primary["code"], primary["name"] or target["Pavadinimas"],
                primary["type"], primary["municipality"], primary["address"], "TAIP", "Aktyvi",
                "VDA Švietimo ir mokslo institucijų duomenys", source_date,
                "Kodas pasikeitė" if primary["code"] != tc else ""
            ])
        else:
            entities.append([
                i, target["Kategorija"], tc, target["Pavadinimas"], "", "Kaunas", "", "NE", "Nerasta",
                "VDA Švietimo ir mokslo institucijų duomenys", source_date, "Šaltinyje nerasta"
            ])

        for h in hits:
            branches.append([
                target["Kategorija"], h["code"], h["name"] or target["Pavadinimas"], h["type"],
                h["municipality"], h["address"], h["unit_id"], tc, target["Pavadinimas"], source_date
            ])

    if len(entities) != 57:
        raise RuntimeError(f"Programos klaida: entities eilučių skaičius {len(entities)}, turėjo būti 57.")
    if not branches:
        raise RuntimeError("Nesugeneruota nė viena registry_branches.csv eilutė.")

    write_csv(OUT_ENTITIES, [
        "Nr", "Kategorija", "Juridinis_kodas", "Mokykla", "Istaigos_tipas", "Savivaldybe",
        "Adresas", "Tikrinti", "Istaigos_statusas", "Aptikimo_saltinis", "Aptikimo_data", "Pastabos"
    ], entities)
    write_csv(OUT_BRANCHES, [
        "Kategorija", "Juridinis_kodas", "Padalinio_pavadinimas", "Istaigos_tipas", "Savivaldybe",
        "Adresas", "Padalinio_ID", "Tikslinis_kodas", "Tikslinis_pavadinimas", "Saltinio_data"
    ], branches)
    HASH_FILE.parent.mkdir(parents=True, exist_ok=True)
    HASH_FILE.write_text(digest + "\n", encoding="utf-8")

    print(f"REGISTRY BUILD SUCCESS TARGETS=57 FOUND={found_count} NOT_FOUND={57-found_count} ENTITY_ROWS={len(entities)} BRANCH_ROWS={len(branches)}")


if __name__ == "__main__":
    main()
