#!/usr/bin/env python3
import csv, io, re, sys, urllib.request, hashlib
from pathlib import Path
from datetime import datetime, timezone

SOURCE_URL = "https://get.data.gov.lt/datasets/gov/lsd/svietimo_istaigos/SvietimoIstaiga/:format/csv"
TARGET_FILE = Path("config/target_scope.csv")
OUT_ENTITIES = Path("output/registry_entities.csv")
OUT_BRANCHES = Path("output/registry_branches.csv")
HASH_FILE = Path("output/source.sha256")

def norm(s):
    s = str(s or "").lower()
    s = s.replace("„","").replace("“","").replace('"',"").replace("'","")
    s = re.sub(r"[\*\u00a0]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def code(s):
    return re.sub(r"\D", "", str(s or ""))

def find_col(headers, aliases):
    nh = [norm(h).replace(" ", "_") for h in headers]
    for a in aliases:
        k = norm(a).replace(" ", "_")
        if k in nh:
            return nh.index(k)
    for i,h in enumerate(nh):
        if any(norm(a).replace(" ","_") in h for a in aliases):
            return i
    return None

def read_csv(raw):
    text = raw.decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:20000], delimiters=";,")
    except csv.Error:
        class D: delimiter = ";"
        dialect = D()
    return list(csv.reader(io.StringIO(text), dialect))

def load_targets():
    with TARGET_FILE.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if len(rows) != 57:
        raise RuntimeError(f"config/target_scope.csv turi turėti 57 eilutes, rasta {len(rows)}")
    for r in rows:
        if not code(r["Juridinis_kodas"]) or not r["Pavadinimas"].strip():
            raise RuntimeError("Kiekviena target_scope eilutė turi turėti Juridinis_kodas ir Pavadinimas.")
    return rows

def write_csv(path, headers, rows):
    path.parent.mkdir(exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f); w.writerow(headers); w.writerows(rows)

def main():
    targets = load_targets()

    raw = urllib.request.urlopen(SOURCE_URL, timeout=90).read()
    digest = hashlib.sha256(raw).hexdigest()

    old_hash = HASH_FILE.read_text().strip() if HASH_FILE.exists() else ""
    if digest == old_hash and OUT_ENTITIES.exists() and OUT_BRANCHES.exists():
        print("SOURCE_UNCHANGED=1")
        return

    rows = read_csv(raw)
    if len(rows) < 2:
        raise RuntimeError("Oficialus švietimo įstaigų CSV tuščias.")

    headers, data = rows[0], rows[1:]

    ic = find_col(headers, [
        "JAR kodas","Juridinio asmens kodas","Juridinis kodas","JAR","Kodas","Įmonės kodas"
    ])
    inn = find_col(headers, [
        "Įstaigos pavadinimas","Institucijos pavadinimas","Pavadinimas"
    ])
    ia = find_col(headers, ["Adresas","Įstaigos adresas","Buveinės adresas"])
    it = find_col(headers, ["Įstaigos tipas","Institucijos tipas","Tipas"])
    im = find_col(headers, ["Savivaldybė","Savivaldybės pavadinimas"])
    iu = find_col(headers, ["ŠMIR kodas","Padalinio kodas","Padalinio ID","ŠMIR"])

    if ic is None or inn is None:
        raise RuntimeError("Nepavyko nustatyti JAR kodo ir pavadinimo stulpelių. Rasti: " + repr(headers))

    by_code = {code(t["Juridinis_kodas"]): t for t in targets}
    by_name = {norm(t["Pavadinimas"]): t for t in targets}
    found = {code(t["Juridinis_kodas"]): [] for t in targets}
    branches = []

    for r in data:
        c = code(r[ic] if ic < len(r) else "")
        n = norm(r[inn] if inn < len(r) else "")
        t = by_code.get(c) or by_name.get(n)
        if not t:
            continue

        target_code = code(t["Juridinis_kodas"])
        current_code = c or target_code
        name = (r[inn] if inn < len(r) else "").strip()
        addr = (r[ia] if ia is not None and ia < len(r) else "").strip()
        typ = (r[it] if it is not None and it < len(r) else "").strip()
        mun = (r[im] if im is not None and im < len(r) else "").strip()
        unit = (r[iu] if iu is not None and iu < len(r) else "").strip()

        found[target_code].append((current_code, name, addr, typ, mun, unit))

        branches.append([
            t["Kategorija"], current_code, name, typ, mun, addr, unit,
            target_code, t["Pavadinimas"]
        ])

    entities = []
    for i, t in enumerate(targets, start=1):
        tc = code(t["Juridinis_kodas"])
        hits = found[tc]

        # Prefer exact JAR code hit; otherwise name-based hit.
        exact = [h for h in hits if h[0] == tc]
        hit = (exact or hits[:1])
        if hit:
            current_code, name, addr, typ, mun, unit = hit[0]
            status = "Aktyvi"
            check = "TAIP"
            note = "Kodas pasikeitė" if current_code != tc else ""
        else:
            current_code = tc
            name = ""
            addr = ""
            typ = ""
            mun = ""
            status = "Nerasta"
            check = "NE"
            note = "Šaltinyje nerasta"

        entities.append([
            i, t["Kategorija"], current_code, name or t["Pavadinimas"],
            typ, mun or "Kaunas", addr, check, status,
            "VDA Švietimo ir mokslo institucijų duomenys",
            datetime.now(timezone.utc).date().isoformat(), note
        ])

    write_csv(OUT_ENTITIES, [
        "Nr","Kategorija","Juridinis_kodas","Mokykla","Istaigos_tipas",
        "Savivaldybe","Adresas","Tikrinti","Istaigos_statusas",
        "Aptikimo_saltinis","Aptikimo_data","Pastabos"
    ], entities)

    write_csv(OUT_BRANCHES, [
        "Kategorija","Juridinis_kodas","Padalinio_pavadinimas","Istaigos_tipas",
        "Savivaldybe","Adresas","Padalinio_ID","Tikslinis_kodas","Tikslinis_pavadinimas"
    ], branches)

    HASH_FILE.write_text(digest + "\n", encoding="utf-8")
    found_count = sum(1 for x in found.values() if x)
    print(f"SOURCE_UNCHANGED=0 TARGETS=57 FOUND={found_count} BRANCH_ROWS={len(branches)}")

if __name__ == "__main__":
    main()
