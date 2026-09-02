# CVP Monitor – automatic registry source

This repository is the free auxiliary source layer for the CVP Monitor.

Power Automate remains the main orchestration engine. This GitHub repository only refreshes public source data and publishes two CSV files that Power Automate downloads into OneDrive.

## Official source

The workflow reads the public State Data Agency dataset "Švietimo ir mokslo institucijų duomenys". The dataset provides institution names, JAR codes, addresses and information about institutions and their subdivisions.

CSV endpoint:
https://get.data.gov.lt/datasets/gov/lsd/svietimo_istaigos/SvietimoIstaiga/:format/csv

## Files

config/target_scope.csv
- 57 monitoring targets.
- This is business configuration, not an automatically changing data table.

output/registry_entities.csv
- One row per target legal entity.
- Names, JAR codes, address and status are refreshed from the official source.

output/registry_branches.csv
- All source rows for matched target entities.
- Keeps multiple addresses/subdivisions for the same JAR code.

## Refresh

GitHub Actions checks the official source daily and only commits output changes when the source content changed.

## Compliance

Rekvizitai.lt is not scraped automatically. Its current rules prohibit copying website information without written permission. It can remain a manual verification source when needed. Official open data is used as the automated source of record.


## Required Excel tables

Keep the existing `tblRegistracija` table with columns:
Nr, Juridinis_kodas, Mokykla, Įstaigos_tipas, Savivaldybė, Adresas, Tikrinti, Įstaigos_statusas, Aptikimo_šaltinis, Aptikimo_data, Pastabos

Create one additional table in a new worksheet:
- worksheet: PADALINIAI
- table: tblPadaliniai
- columns:
  Juridinis_kodas, Padalinio_pavadinimas, Adresas, Įstaigos_tipas, Savivaldybė, Padalinio_ID, Tikslinis_kodas, Tikslinis_pavadinimas, Saltinio_data

The Power Automate flow uploads the two generated CSV files to OneDrive and the Office Script overwrites these two tables in bulk.

Do not delete `tblRegistroSaltinisVisi`; it remains as the original supplied reference dataset/audit source. It is not the live source used by the automation.
