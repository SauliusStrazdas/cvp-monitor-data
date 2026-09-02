function main(
  workbook: ExcelScript.Workbook,
  entitiesCsv: string,
  branchesCsv: string,
  todayIso: string
): object {
  const reg = workbook.getTable("tblRegistracija");
  const branch = workbook.getTable("tblPadaliniai");

  function parseCsv(text: string): string[][] {
    const rows: string[][] = [];
    let row: string[] = [];
    let field = "";
    let quoted = false;
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      if (quoted) {
        if (ch === '"') {
          if (i + 1 < text.length && text[i + 1] === '"') {
            field += '"'; i++;
          } else {
            quoted = false;
          }
        } else {
          field += ch;
        }
      } else {
        if (ch === '"') quoted = true;
        else if (ch === ",") { row.push(field); field = ""; }
        else if (ch === "\n") { row.push(field); rows.push(row); row = []; field = ""; }
        else if (ch !== "\r") field += ch;
      }
    }
    row.push(field);
    if (row.length > 1 || row[0] !== "") rows.push(row);
    return rows;
  }

  function idx(headers: string[], name: string): number {
    return headers.findIndex(h => h.trim() === name);
  }

  function clearData(t: ExcelScript.Table) {
    const r = t.getRangeBetweenHeaderAndTotal();
    if (r.getRowCount() > 0) r.clear(ExcelScript.ClearApplyTo.contents);
  }

  const e = parseCsv(entitiesCsv);
  const b = parseCsv(branchesCsv);
  if (e.length < 1 || b.length < 1) throw new Error("Registro CSV tuščias.");

  const eh = e[0], bh = b[0];

  const ei = {
    nr: idx(eh,"Nr"), cat: idx(eh,"Kategorija"), code: idx(eh,"Juridinis_kodas"),
    name: idx(eh,"Mokykla"), type: idx(eh,"Istaigos_tipas"), municipality: idx(eh,"Savivaldybe"),
    address: idx(eh,"Adresas"), check: idx(eh,"Tikrinti"), status: idx(eh,"Istaigos_statusas"),
    source: idx(eh,"Aptikimo_saltinis"), date: idx(eh,"Aptikimo_data"), notes: idx(eh,"Pastabos")
  };

  const bi = {
    cat: idx(bh,"Kategorija"), code: idx(bh,"Juridinis_kodas"), name: idx(bh,"Padalinio_pavadinimas"),
    type: idx(bh,"Istaigos_tipas"), municipality: idx(bh,"Savivaldybe"), address: idx(bh,"Adresas"),
    unit: idx(bh,"Padalinio_ID"), targetCode: idx(bh,"Tikslinis_kodas"), targetName: idx(bh,"Tikslinis_pavadinimas")
  };

  if (ei.code < 0 || ei.name < 0 || ei.check < 0) {
    throw new Error("entitiesCsv trūksta Juridinis_kodas, Mokykla arba Tikrinti.");
  }
  if (bi.code < 0 || bi.address < 0 || bi.targetCode < 0) {
    throw new Error("branchesCsv trūksta Juridinis_kodas, Adresas arba Tikslinis_kodas.");
  }

  const entityRows = e.slice(1).filter(r => r.length > 1);
  const branchRows = b.slice(1).filter(r => r.length > 1);

  clearData(reg);
  clearData(branch);

  if (entityRows.length) reg.addRows(-1, entityRows.map(r => [
    r[ei.nr], r[ei.code], r[ei.name], r[ei.type], r[ei.municipality], r[ei.address],
    r[ei.check], r[ei.status], r[ei.source], r[ei.date], r[ei.notes]
  ]));

  if (branchRows.length) branch.addRows(-1, branchRows.map(r => [
    r[bi.code], r[bi.name], r[bi.address], r[bi.type], r[bi.municipality],
    r[bi.unit], r[bi.targetCode], r[bi.targetName], todayIso
  ]));

  return {
    status: "OK",
    registrationRows: entityRows.length,
    branchRows: branchRows.length,
    updated: todayIso
  };
}
