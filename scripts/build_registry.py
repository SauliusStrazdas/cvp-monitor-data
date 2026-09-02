#!/usr/bin/env python3

import csv
import io
import re
import sys
import zipfile
import hashlib
import urllib.request
from pathlib import Path
from datetime import datetime, timezone


# ============================================================
# CVP MONITOR – AUTOMATINIS REGISTRAS
# ============================================================

SOURCE_URL = (
    "https://www.geoportal.lt/download/opendata/"
    "svietimo_istaigos/LT_svietimo_istaigos.zip"
)

TARGET_FILE = Path("config/target_scope.csv")

OUT_ENTITIES = Path("output/registry_entities.csv")
OUT_BRANCHES = Path("output/registry_branches.csv")
HASH_FILE = Path("output/source.sha256")


# ============================================================
# TEKSTO NORMALIZAVIMAS
# ============================================================

def norm(value):
    text = str(value or "").lower()

    replacements = {
        "\ufeff": "",
        "„": "",
        "“": "",
        '"': "",
        "'": "",
        "ą": "a",
        "č": "c",
        "ę": "e",
        "ė": "e",
        "į": "i",
        "š": "s",
        "ų": "u",
        "ū": "u",
        "ž": "z",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    text = re.sub(r"[\*\u00a0]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    return text


def code(value):
    return re.sub(r"\D", "", str(value or ""))


def clean(value):
    if value is None:
        return ""
    return str(value).strip()


def norm_header(value):
    return norm(value).replace(" ", "_").replace("-", "_")


# ============================================================
# STULPELIŲ PAIEŠKA
# ============================================================

def find_col(headers, aliases):

    normalized_headers = [
        norm_header(h)
        for h in headers
    ]

    normalized_aliases = [
        norm_header(a)
        for a in aliases
    ]

    # Pirmiausia – tikslus sutapimas
    for alias in normalized_aliases:
        if alias in normalized_headers:
            return normalized_headers.index(alias)

    # Tada – dalinis sutapimas
    for index, header in enumerate(normalized_headers):
        for alias in normalized_aliases:

            if not alias:
                continue

            if alias in header:
                return index

    return None


# ============================================================
# TARGET_SCOPE
# ============================================================

def load_targets():

    with TARGET_FILE.open(
        encoding="utf-8-sig",
        newline=""
    ) as f:

        rows = list(
            csv.DictReader(f)
        )

    if len(rows) != 57:

        raise RuntimeError(
            "config/target_scope.csv turi turėti "
            f"57 įrašus, rasta {len(rows)}."
        )

    required = {
        "Kategorija",
        "Juridinis_kodas",
        "Pavadinimas",
    }

    missing = required - set(rows[0].keys())

    if missing:

        raise RuntimeError(
            "target_scope.csv trūksta stulpelių: "
            + ", ".join(sorted(missing))
        )

    for index, row in enumerate(
        rows,
        start=1
    ):

        juridinis = code(
            row.get("Juridinis_kodas")
        )

        pavadinimas = clean(
            row.get("Pavadinimas")
        )

        if not juridinis:

            raise RuntimeError(
                f"target_scope.csv eilutėje {index} "
                "trūksta Juridinis_kodas."
            )

        if not pavadinimas:

            raise RuntimeError(
                f"target_scope.csv eilutėje {index} "
                "trūksta Pavadinimas."
            )

    return rows


# ============================================================
# CSV IŠVEDIMAS
# ============================================================

def write_csv(
    path,
    headers,
    rows
):

    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with path.open(
        "w",
        encoding="utf-8-sig",
        newline=""
    ) as f:

        writer = csv.writer(f)

        writer.writerow(headers)

        writer.writerows(rows)


# ============================================================
# ŠALTINIO ATSISIUNTIMAS
# ============================================================

def download_source():

    request = urllib.request.Request(
        SOURCE_URL,
        headers={
            "User-Agent":
                "cvp-monitor-data/1.0 "
                "(GitHub Actions)"
        }
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=180
        ) as response:

            raw = response.read()

    except Exception as exc:

        raise RuntimeError(
            "Nepavyko atsisiųsti oficialaus "
            "šaltinio: "
            f"{exc}"
        ) from exc

    if not raw:

        raise RuntimeError(
            "Oficialus šaltinis grąžino "
            "tuščią atsakymą."
        )

    # ZIP failo parašas
    if not raw.startswith(b"PK"):

        preview = (
            raw[:300]
            .decode(
                "utf-8",
                errors="replace"
            )
        )

        raise RuntimeError(
            "Oficialus URL negrąžino ZIP failo. "
            "Atsakymo pradžia: "
            + repr(preview)
        )

    return raw


# ============================================================
# SHAPEFILE SKAITYMAS
# ============================================================

def read_shapefile_from_zip(
    raw_zip
):

    try:

        import shapefile

    except ImportError:

        import subprocess

        print(
            "PyShp nerastas. "
            "Diegiamas automatiškai..."
        )

        subprocess.check_call(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--quiet",
                "pyshp",
            ]
        )

        import shapefile

    zip_buffer = io.BytesIO(
        raw_zip
    )

    with zipfile.ZipFile(
        zip_buffer,
        "r"
    ) as archive:

        names = archive.namelist()

        lower_map = {
            name.lower(): name
            for name in names
        }

        shp_candidates = [
            name
            for name in names
            if name.lower().endswith(
                ".shp"
            )
        ]

        if not shp_candidates:

            raise RuntimeError(
                "ZIP faile nerastas .shp failas."
            )

        selected = None

        for shp_name in shp_candidates:

            base = shp_name[:-4]

            shx_name = lower_map.get(
                (base + ".shx").lower()
            )

            dbf_name = lower_map.get(
                (base + ".dbf").lower()
            )

            if shx_name and dbf_name:

                selected = (
                    shp_name,
                    shx_name,
                    dbf_name,
                )

                break

        if selected is None:

            raise RuntimeError(
                "ZIP faile nerastas pilnas "
                "SHP + SHX + DBF rinkinys."
            )

        shp_name, shx_name, dbf_name = selected

        shp_bytes = io.BytesIO(
            archive.read(shp_name)
        )

        shx_bytes = io.BytesIO(
            archive.read(shx_name)
        )

        dbf_bytes = io.BytesIO(
            archive.read(dbf_name)
        )

    last_error = None

    # Lietuvos DBF failams bandome kelias koduotes
    for encoding in (
        "utf-8",
        "cp1257",
        "cp1252",
        "latin1",
    ):

        try:

            shp_bytes.seek(0)
            shx_bytes.seek(0)
            dbf_bytes.seek(0)

            reader = shapefile.Reader(
                shp=shp_bytes,
                shx=shx_bytes,
                dbf=dbf_bytes,
                encoding=encoding,
            )

            headers = [
                field[0]
                for field in reader.fields[1:]
            ]

            rows = [
                list(record)
                for record in reader.iterRecords()
            ]

            print(
                "SHP encoding:",
                encoding
            )

            print(
                "SHP file:",
                shp_name
            )

            print(
                "SHP rows:",
                len(rows)
            )

            return headers, rows

        except Exception as exc:

            last_error = exc

    raise RuntimeError(
        "Nepavyko perskaityti SHP/DBF. "
        f"Paskutinė klaida: {last_error}"
    )


# ============================================================
# PAGRINDINĖ LOGIKA
# ============================================================

def main():

    print("=" * 70)

    print(
        "CVP MONITOR – REGISTRO ATNAUJINIMAS"
    )

    print("=" * 70)

    # --------------------------------------------------------
    # 1. Mūsų 57 tikslinės įstaigos
    # --------------------------------------------------------

    targets = load_targets()

    print(
        "TARGETS=57"
    )

    # --------------------------------------------------------
    # 2. Oficialus šaltinis
    # --------------------------------------------------------

    print(
        "SOURCE_URL="
        + SOURCE_URL
    )

    raw = download_source()

    print(
        "SOURCE_BYTES="
        + str(len(raw))
    )

    # --------------------------------------------------------
    # 3. SHA-256
    # --------------------------------------------------------

    digest = hashlib.sha256(
        raw
    ).hexdigest()

    old_hash = (
        HASH_FILE.read_text(
            encoding="utf-8"
        ).strip()
        if HASH_FILE.exists()
        else ""
    )

    if (
        digest == old_hash
        and OUT_ENTITIES.exists()
        and OUT_BRANCHES.exists()
    ):

        print(
            "SOURCE_UNCHANGED=1"
        )

        return

    # --------------------------------------------------------
    # 4. SHP
    # --------------------------------------------------------

    headers, data = (
        read_shapefile_from_zip(
            raw
        )
    )

    if not data:

        raise RuntimeError(
            "Oficialiame SHP nėra duomenų."
        )

    print(
        "SHP_HEADERS="
        + repr(headers)
    )

    print(
        "SOURCE_ROWS="
        + str(len(data))
    )

    # --------------------------------------------------------
    # 5. Oficialaus šaltinio laukų aptikimas
    # --------------------------------------------------------

    juridinis_col = find_col(
        headers,
        [
            "JAR kodas",
            "JAR_KODAS",
            "JAR",
            "Juridinio asmens kodas",
            "Juridinis kodas",
            "Kodas",
            "Įmonės kodas",
            "Imones kodas",
        ]
    )

    name_col = find_col(
        headers,
        [
            "Įstaigos pavadinimas",
            "Institucijos pavadinimas",
            "Pavadinimas",
            "Švietimo įstaigos pavadinimas",
            "Istaigos pavadinimas",
        ]
    )

    address_col = find_col(
        headers,
        [
            "Adresas",
            "Įstaigos adresas",
            "Buveinės adresas",
            "Adreso tekstas",
        ]
    )

    type_col = find_col(
        headers,
        [
            "Įstaigos tipas",
            "Institucijos tipas",
            "Tipas",
            "Įstaigos tipo pavadinimas",
        ]
    )

    municipality_col = find_col(
        headers,
        [
            "Savivaldybė",
            "Savivaldybes pavadinimas",
            "Savivaldybės pavadinimas",
        ]
    )

    unit_col = find_col(
        headers,
        [
            "ŠMIR kodas",
            "SMIR kodas",
            "ŠMIR",
            "SMIR",
            "Padalinio kodas",
            "Padalinio ID",
            "ISTAIGOS_KODAS",
        ]
    )

    print("=" * 70)

    print(
        "DETECTED COLUMNS"
    )

    print(
        "Juridinis/JAR:",
        juridinis_col
    )

    print(
        "Pavadinimas:",
        name_col
    )

    print(
        "Adresas:",
        address_col
    )

    print(
        "Tipas:",
        type_col
    )

    print(
        "Savivaldybė:",
        municipality_col
    )

    print(
        "Padalinio/ŠMIR ID:",
        unit_col
    )

    print("=" * 70)

    if (
        juridinis_col is None
        or name_col is None
    ):

        raise RuntimeError(
            "Nepavyko nustatyti juridinio kodo "
            "ir pavadinimo laukų. "
            f"Oficialaus šaltinio laukai: {headers}"
        )

    # --------------------------------------------------------
    # 6. Mūsų 57 tikslinių įstaigų žemėlapiai
    # --------------------------------------------------------

    by_code = {
        code(
            target["Juridinis_kodas"]
        ): target
        for target in targets
    }

    by_name = {
        norm(
            target["Pavadinimas"]
        ): target
        for target in targets
    }

    found = {
        code(
            target["Juridinis_kodas"]
        ): []
        for target in targets
    }

    # --------------------------------------------------------
    # 7. Oficialaus šaltinio eilučių atitikimas
    # --------------------------------------------------------

    for row in data:

        source_code = code(
            row[juridinis_col]
            if juridinis_col < len(row)
            else ""
        )

        source_name = clean(
            row[name_col]
            if name_col < len(row)
            else ""
        )

        target = None

        # Pirmas prioritetas – juridinis kodas
        if source_code:

            target = by_code.get(
                source_code
            )

        # Antras prioritetas – pavadinimas
        if (
            target is None
            and source_name
        ):

            target = by_name.get(
                norm(source_name)
            )

        if target is None:

            continue

        target_code = code(
            target["Juridinis_kodas"]
        )

        address = clean(
            row[address_col]
            if (
                address_col is not None
                and address_col < len(row)
            )
            else ""
        )

        institution_type = clean(
            row[type_col]
            if (
                type_col is not None
                and type_col < len(row)
            )
            else ""
        )

        municipality = clean(
            row[municipality_col]
            if (
                municipality_col is not None
                and municipality_col < len(row)
            )
            else ""
        )

        unit_id = clean(
            row[unit_col]
            if (
                unit_col is not None
                and unit_col < len(row)
            )
            else ""
        )

        found[
            target_code
        ].append(
            {
                "source_code":
                    source_code,

                "name":
                    source_name,

                "address":
                    address,

                "type":
                    institution_type,

                "municipality":
                    municipality,

                "unit_id":
                    unit_id,
            }
        )

    # --------------------------------------------------------
    # 8. CSV eilučių sudarymas
    # --------------------------------------------------------

    entities = []

    branches = []

    source_date = (
        datetime.now(
            timezone.utc
        )
        .date()
        .isoformat()
    )

    for index, target in enumerate(
        targets,
        start=1
    ):

        target_code = code(
            target["Juridinis_kodas"]
        )

        hits = found[
            target_code
        ]

        # Tikslaus kodo atvejai turi prioritetą
        exact = [
            hit
            for hit in hits
            if hit["source_code"]
            == target_code
        ]

        selected = (
            exact
            if exact
            else hits
        )

        primary = (
            selected[0]
            if selected
            else None
        )

        if primary:

            current_code = (
                primary["source_code"]
                or target_code
            )

            name = (
                primary["name"]
                or target["Pavadinimas"]
            )

            institution_type = (
                primary["type"]
            )

            municipality = (
                primary["municipality"]
                or "Kaunas"
            )

            address = (
                primary["address"]
            )

            check = "TAIP"

            status = "Aktyvi"

            note = (
                "Kodas pasikeitė"
                if current_code
                != target_code
                else ""
            )

        else:

            current_code = target_code

            name = (
                target["Pavadinimas"]
            )

            institution_type = ""

            municipality = "Kaunas"

            address = ""

            check = "NE"

            status = "Nerasta"

            note = (
                "Šaltinyje nerasta"
            )

        entities.append(
            [
                index,
                target["Kategorija"],
                current_code,
                name,
                institution_type,
                municipality,
                address,
                check,
                status,
                (
                    "Oficialus Lietuvos "
                    "švietimo įstaigų "
                    "duomenų rinkinys"
                ),
                source_date,
                note,
            ]
        )

        # Visi atitikę šaltinio įrašai
        # keliauja į padalinių lentelę
        for hit in hits:

            branches.append(
                [
                    target["Kategorija"],
                    (
                        hit["source_code"]
                        or target_code
                    ),
                    (
                        hit["name"]
                        or target["Pavadinimas"]
                    ),
                    hit["type"],
                    (
                        hit["municipality"]
                        or "Kaunas"
                    ),
                    hit["address"],
                    hit["unit_id"],
                    target_code,
                    target["Pavadinimas"],
                    source_date,
                ]
            )

    # --------------------------------------------------------
    # 9. Apsaugos prieš rašymą
    # --------------------------------------------------------

    found_count = sum(
        1
        for hits in found.values()
        if hits
    )

    not_found_count = (
        57 - found_count
    )

    print("=" * 70)

    print(
        "FOUND="
        + str(found_count)
    )

    print(
        "NOT_FOUND="
        + str(not_found_count)
    )

    print(
        "ENTITY_ROWS="
        + str(len(entities))
    )

    print(
        "BRANCH_ROWS="
        + str(len(branches))
    )

    print("=" * 70)

    if len(entities) != 57:

        raise RuntimeError(
            "Programos klaida: "
            "entities eilučių skaičius "
            f"yra {len(entities)}, "
            "turėjo būti 57."
        )

    if found_count == 0:

        raise RuntimeError(
            "Nė viena iš 57 tikslinių įstaigų "
            "nerasta oficialiame šaltinyje."
        )

    if not branches:

        raise RuntimeError(
            "Nesugeneruota nė viena "
            "registry_branches.csv eilutė."
        )

    # --------------------------------------------------------
    # 10. registry_entities.csv
    # --------------------------------------------------------

    write_csv(
        OUT_ENTITIES,

        [
            "Nr",
            "Kategorija",
            "Juridinis_kodas",
            "Mokykla",
            "Istaigos_tipas",
            "Savivaldybe",
            "Adresas",
            "Tikrinti",
            "Istaigos_statusas",
            "Aptikimo_saltinis",
            "Aptikimo_data",
            "Pastabos",
        ],

        entities,
    )

    # --------------------------------------------------------
    # 11. registry_branches.csv
    # --------------------------------------------------------

    write_csv(
        OUT_BRANCHES,

        [
            "Kategorija",
            "Juridinis_kodas",
            "Padalinio_pavadinimas",
            "Istaigos_tipas",
            "Savivaldybe",
            "Adresas",
            "Padalinio_ID",
            "Tikslinis_kodas",
            "Tikslinis_pavadinimas",
            "Saltinio_data",
        ],

        branches,
    )

    # --------------------------------------------------------
    # 12. Šaltinio hash
    # --------------------------------------------------------

    HASH_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    HASH_FILE.write_text(
        digest + "\n",
        encoding="utf-8"
    )

    # --------------------------------------------------------
    # 13. Galutinis rezultatas
    # --------------------------------------------------------

    print(
        "REGISTRY BUILD SUCCESS"
    )

    print(
        f"TARGETS=57 "
        f"FOUND={found_count} "
        f"NOT_FOUND={not_found_count} "
        f"ENTITY_ROWS={len(entities)} "
        f"BRANCH_ROWS={len(branches)}"
    )


if __name__ == "__main__":
    main()
