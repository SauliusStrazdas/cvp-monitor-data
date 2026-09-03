import csv
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import date, datetime

API_URL = "https://viesiejipirkimai.lt/epps-integration/api/cft-details-export"
OUTPUT_DIR = "output"
OUT_HEADERS = [
    "Sutarties_ID","Sutarties_numeris","Objektas","Pirkimo_numeris","BVPZ_kodas","Mokykla","Juridinis_kodas","Tiekejas","Tiekejo_kodas","Verte","Pasirasymo_data","Galioja_iki","Paskelbimo_data","Paskutinio_redagavimo_data"
]

def norm(v):
    return re.sub(r"[^a-z0-9]+", "", str(v or "").lower())

def clean(v):
    return str(v or "").strip()

def parse_date(v):
    text=clean(v)
    if not text: return None
    for candidate in (text,text[:10]):
        for fmt in ("%Y-%m-%d","%Y.%m.%d","%d.%m.%Y","%d-%m-%Y"):
            try: return datetime.strptime(candidate,fmt).date()
            except ValueError: pass
    return None

def find_value(record,aliases):
    aset={norm(a) for a in aliases}
    def walk(obj):
        if isinstance(obj,dict):
            for k,v in obj.items():
                if norm(k) in aset and not isinstance(v,(dict,list)): return clean(v)
            for v in obj.values():
                x=walk(v)
                if x: return x
        elif isinstance(obj,list):
            for v in obj:
                x=walk(v)
                if x: return x
        return ""
    return walk(record)

def extract_records(payload):
    if isinstance(payload,list): return payload
    if not isinstance(payload,dict): return []
    for key in ("content","items","data","results","records","contracts","result"):
        value=payload.get(key)
        if isinstance(value,list): return value
        if isinstance(value,dict):
            nested=extract_records(value)
            if nested: return nested
    for value in payload.values():
        if isinstance(value,list) and value and all(isinstance(x,dict) for x in value): return value
        if isinstance(value,dict):
            nested=extract_records(value)
            if nested: return nested
    return []

def map_record(record,canonical):
    juridical=re.sub(r"\D","",find_value(record,["Juridinis_kodas","Juridinis kodas","juridinisKodas","jarCode","jarcode","JAR_kodas","JAR kodas","contractingAuthorityLegalEntityCode"]))
    if not juridical or juridical not in canonical: return None
    cid=find_value(record,["Sutarties_ID","Sutarties ID","sutartiesUnikalusId","contractId","contractUniqueId","DOK_ID","dokId"])
    if not cid: return None
    authority=find_value(record,["Mokykla","Pirkimo vykdytojo pavadinimas","perkančioji organizacija","contractingAuthorityName","contractingAuthority","organizationName","DOK_PERKANCIOSIOS_ORGANIZACIJOS_PAVADINIMAS"]) or canonical[juridical]
    return [cid,find_value(record,["Sutarties_numeris","Sutarties numeris","contractNumber","DOK_REG_NR"]),find_value(record,["Objektas","Pavadinimas","Aprašymas","description","object"]),find_value(record,["Pirkimo_numeris","Viešojo pirkimo numeris","pirkimo numeris","procurementNumber"]),find_value(record,["BVPZ_kodas","BVPŽ kodai","BVPZ kodas","cpvCode","cpvCodes"]),authority,juridical,find_value(record,["Tiekejas","Tiekėjas","supplierName","winnerName"]),find_value(record,["Tiekejo_kodas","Tiekėjo kodas","supplierCode","winnerCode"]),find_value(record,["Verte","Vertė","contractValue","value"]),find_value(record,["Pasirasymo_data","Pasirašymo data","Sutarties sudarymo data","contractConclusionDate","DOK_SUDARYMO_DATA"]),find_value(record,["Galioja_iki","Galioja iki","contractEndDate","expirationDate","DOK_SUT_GALIOJIMO_DATA"]),find_value(record,["Paskelbimo_data","Paskelbimo data","publicationDate","DOK_SYS_REG_DATA"]),find_value(record,["Paskutinio_redagavimo_data","Paskutinio redagavimo data","lastModifiedDate","updatedAt"])]

def request_page(api_key,page,page_size=20,retries=3,timeout=180):
    body=json.dumps({"pageSize":page_size,"pageNum":page}).encode("utf-8")
    req=urllib.request.Request(API_URL,data=body,method="POST",headers={"Accept":"application/json","Content-Type":"application/json","apiKey":api_key})
    last_error=None
    for attempt in range(1,retries+1):
        try:
            with urllib.request.urlopen(req,timeout=timeout) as response:
                payload=json.loads(response.read().decode("utf-8"))
            print(f"API page {page}: success on attempt {attempt}")
            return payload
        except (urllib.error.URLError,TimeoutError,json.JSONDecodeError) as exc:
            last_error=exc
            print(f"API page {page}: attempt {attempt} failed: {exc}")
            if attempt<retries: time.sleep(5*attempt)
    raise RuntimeError(f"CVP IS API page {page} failed after {retries} attempts: {last_error}")

def main():
    api_key=os.environ.get("CVP_API_KEY","").strip()
    if not api_key: raise RuntimeError("CVP_API_KEY secret is missing")
    today=date.today()
    targets={}
    with open("config/target_scope.csv","r",encoding="utf-8-sig",newline="") as f:
        for row in csv.DictReader(f):
            code=re.sub(r"\D","",clean(row.get("Juridinis_kodas")))
            if code: targets[code]=clean(row.get("Pavadinimas"))
    if not targets: raise RuntimeError("No monitored legal entities found in config/target_scope.csv")
    rows={}; pages=0; total=0; page_size=20
    for page in range(1,5001):
        records=extract_records(request_page(api_key,page,page_size)); pages+=1; total+=len(records)
        if not records: break
        for record in records:
            mapped=map_record(record,targets)
            if mapped is None: continue
            expiry=parse_date(mapped[11])
            if expiry is None or expiry<today: continue
            old=rows.get(mapped[0])
            if old is None or mapped[13]>old[13]: rows[mapped[0]]=mapped
        if len(records)<page_size: break
    out=list(rows.values()); out.sort(key=lambda r:(r[6],r[0]))
    if not out: raise RuntimeError(f"CVP API returned {total} records across {pages} pages, but no valid watched contracts remained.")
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    snapshot=os.path.join(OUTPUT_DIR,f"sutartys_{today.isoformat()}.csv")
    with open(snapshot,"w",encoding="utf-8-sig",newline="") as f:
        w=csv.writer(f,delimiter=";"); w.writerow(OUT_HEADERS); w.writerows(out)
    meta={"date":today.isoformat(),"pagesRead":pages,"totalApiRecords":total,"rowsWritten":len(out),"monitoredEntities":len(targets),"apiPageSize":page_size}
    with open(os.path.join(OUTPUT_DIR,"contract_snapshot_meta.json"),"w",encoding="utf-8") as f: json.dump(meta,f,ensure_ascii=False,indent=2)
    print(json.dumps(meta,ensure_ascii=False))

if __name__=="__main__": main()
