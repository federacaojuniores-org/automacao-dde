"""Aplica o layout do modelo nas planilhas existentes sem trocar arquivos ou abas."""
import argparse
import copy
import json
import os
import time

import sync_planilhas_ejs as S

ABAS = {
    "Visão Geral": (),
    "Premiação": (),
    "Simulador": (
        "Faturamento adicional até 31/12",
        "Faturamento colaborativo adicional até 31/12",
        "CSAT",
        "Engajamento com o MEJ (ECM)",
        "PI aprovado?",
    ),
    "Monitoramento Geral": (),
    "Monitoramento Acumulado": (),
}
COLUNAS_PRESERVADAS = {"Simulador": (1, 7)}
DADOS_DINAMICOS = {"Monitoramento Geral": 1000, "Monitoramento Acumulado": 16}
MAX_RANGE = "A1:ZZ1000"
CELL_FIELDS = "userEnteredValue,userEnteredFormat,dataValidation,note,textFormatRuns"


def celula(valor):
    if isinstance(valor, bool):
        return {"userEnteredValue": {"boolValue": valor}}
    if isinstance(valor, (int, float)):
        return {"userEnteredValue": {"numberValue": valor}}
    if isinstance(valor, str) and valor.startswith("="):
        return {"userEnteredValue": {"formulaValue": valor}}
    return {"userEnteredValue": {"stringValue": str(valor)}}


def dimensoes(values):
    return len(values), max((len(row) for row in values), default=1)


def a1(titulo, linhas, colunas):
    return f"'{titulo.replace(chr(39), chr(39) * 2)}'!A1:{S.letra(colunas - 1)}{linhas}"


def mapa_rotulos(values, rotulo_col, valor_col, permitidos=None):
    out = {}
    permitidos = {S.norm(x) for x in permitidos} if permitidos else None
    for i, row in enumerate(values):
        rotulo = str(row[rotulo_col]).strip() if len(row) > rotulo_col else ""
        if not rotulo or permitidos is not None and S.norm(rotulo) not in permitidos:
            continue
        valor = row[valor_col] if len(row) > valor_col else ""
        out[S.norm(rotulo)] = (i, valor)
    return out


def remapear_sheet_ids(obj, ids):
    if isinstance(obj, list):
        return [remapear_sheet_ids(x, ids) for x in obj]
    if not isinstance(obj, dict):
        return obj
    out = {}
    for key, value in obj.items():
        out[key] = ids.get(value, value) if key == "sheetId" else remapear_sheet_ids(value, ids)
    return out


def requests_dimensao(sheet_id, tipo, metadata):
    requests = []
    inicio, anterior = 0, None
    for i, item in enumerate([*metadata, {}]):
        props = {k: item[k] for k in ("pixelSize", "hiddenByUser") if k in item}
        if props != anterior:
            if anterior:
                requests.append({"updateDimensionProperties": {
                    "range": {"sheetId": sheet_id, "dimension": tipo,
                              "startIndex": inicio, "endIndex": i},
                    "properties": anterior,
                    "fields": ",".join(anterior),
                }})
            inicio, anterior = i, props
    return requests


def requests_formatos_dinamicos(sheet_id, source_rows, colunas, linhas):
    template = source_rows[7].get("values", []) if len(source_rows) > 7 else []
    requests = []
    inicio, anterior = 0, None
    for i in range(colunas + 1):
        fmt = copy.deepcopy(template[i].get("userEnteredFormat")) if i < len(template) else None
        if fmt != anterior:
            if anterior is not None:
                requests.append({"repeatCell": {
                    "range": {"sheetId": sheet_id, "startRowIndex": 7, "endRowIndex": 7 + linhas,
                              "startColumnIndex": inicio, "endColumnIndex": i},
                    "cell": {"userEnteredFormat": anterior},
                    "fields": "userEnteredFormat",
                }})
            inicio, anterior = i, fmt
    return requests


def fonte(service, modelo_id):
    v = service.spreadsheets().values()
    valores = {}
    ranges = []
    for titulo in ABAS:
        rows = S.com_retry(v.get(spreadsheetId=modelo_id, range=f"'{titulo}'!{MAX_RANGE}",
                                 valueRenderOption="FORMULA")).get("values", [])
        valores[titulo] = rows
        h, w = dimensoes(rows)
        ranges.append(a1(titulo, max(h, 1), max(w, 1)))
    fields = ("sheets(properties(sheetId,title,gridProperties(frozenRowCount,frozenColumnCount,hideGridlines)),"
              "data(rowData(values(userEnteredValue,userEnteredFormat,dataValidation,note,textFormatRuns)),"
              "rowMetadata(pixelSize,hiddenByUser),columnMetadata(pixelSize,hiddenByUser)),"
              "merges,conditionalFormats,charts(chartId,spec,position))")
    meta = S.com_retry(service.spreadsheets().get(
        spreadsheetId=modelo_id, ranges=ranges, includeGridData=True, fields=fields))
    sheets = {x["properties"]["title"]: x for x in meta["sheets"]}
    objetos = S.com_retry(service.spreadsheets().get(
        spreadsheetId=modelo_id, includeGridData=False,
        fields="sheets(properties(sheetId,title),merges,conditionalFormats,charts(chartId,spec,position))"))
    for sheet in objetos["sheets"]:
        if sheet["properties"]["title"] in sheets:
            for key in ("merges", "conditionalFormats", "charts"):
                sheets[sheet["properties"]["title"]][key] = sheet.get(key, [])
    return valores, sheets


def metadata_destino(service, sid):
    fields = ("sheets(properties(sheetId,title,gridProperties(rowCount,columnCount,frozenRowCount,frozenColumnCount,hideGridlines)),"
              "merges,conditionalFormats,charts(chartId))")
    meta = S.com_retry(service.spreadsheets().get(spreadsheetId=sid, fields=fields))
    return {x["properties"]["title"]: x for x in meta["sheets"]}


def valores_destino(service, sid):
    ranges = [f"'{titulo}'!{MAX_RANGE}" for titulo in ABAS]
    result = S.com_retry(service.spreadsheets().values().batchGet(
        spreadsheetId=sid, ranges=ranges, valueRenderOption="FORMULA"))["valueRanges"]
    return {titulo: item.get("values", []) for titulo, item in zip(ABAS, result)}


def planejar_aba(titulo, src, src_values, dst, dst_values, id_map):
    src_id, dst_id = src["properties"]["sheetId"], dst["properties"]["sheetId"]
    src_h, src_w = dimensoes(src_values)
    dst_h, dst_w = dimensoes(dst_values)
    linhas_dinamicas = DADOS_DINAMICOS.get(titulo, 0)
    h = max(src_h, dst_h, 7 + linhas_dinamicas, 1)
    w = max(src_w, dst_w, 1)
    requests = []
    grid = dst["properties"]["gridProperties"]
    if grid["rowCount"] < h:
        requests.append({"appendDimension": {"sheetId": dst_id, "dimension": "ROWS", "length": h - grid["rowCount"]}})
    if grid["columnCount"] < w:
        requests.append({"appendDimension": {"sheetId": dst_id, "dimension": "COLUMNS", "length": w - grid["columnCount"]}})
    for merge in dst.get("merges", []):
        if merge.get("startRowIndex", 0) < h and merge.get("startColumnIndex", 0) < w:
            requests.append({"unmergeCells": {"range": merge}})
    for i in reversed(range(len(dst.get("conditionalFormats", [])))):
        requests.append({"deleteConditionalFormatRule": {"sheetId": dst_id, "index": i}})
    for chart in dst.get("charts", []):
        requests.append({"deleteEmbeddedObject": {"objectId": chart["chartId"]}})

    source_rows = (src.get("data") or [{}])[0].get("rowData", [])
    rows = []
    linhas_copiadas = src_h if linhas_dinamicas else h
    for i in range(linhas_copiadas):
        values = copy.deepcopy(source_rows[i].get("values", [])) if i < len(source_rows) else []
        values = [{k: cell[k] for k in ("userEnteredValue", "userEnteredFormat", "dataValidation", "note", "textFormatRuns") if k in cell}
                  for cell in values]
        rows.append({"values": values + [{} for _ in range(w - len(values))]})
    requests.append({"updateCells": {
        "range": {"sheetId": dst_id, "startRowIndex": 0, "endRowIndex": linhas_copiadas,
                  "startColumnIndex": 0, "endColumnIndex": w},
        "rows": rows,
        "fields": CELL_FIELDS,
    }})
    if linhas_dinamicas and h > src_h:
        requests.append({"repeatCell": {
            "range": {"sheetId": dst_id, "startRowIndex": src_h, "endRowIndex": h,
                      "startColumnIndex": 0, "endColumnIndex": w},
            "cell": {},
            "fields": "userEnteredValue",
        }})
        requests += requests_formatos_dinamicos(dst_id, source_rows, src_w, linhas_dinamicas)

    preserve = COLUNAS_PRESERVADAS.get(titulo)
    if preserve:
        label_col, value_col = preserve
        allowed = ABAS[titulo]
        old = mapa_rotulos(dst_values, label_col, value_col, allowed)
        new = mapa_rotulos(src_values, label_col, value_col, allowed)
        for label, (_, value) in old.items():
            if label in new:
                row = new[label][0]
                requests.append({"updateCells": {
                    "range": {"sheetId": dst_id, "startRowIndex": row, "endRowIndex": row + 1,
                              "startColumnIndex": value_col, "endColumnIndex": value_col + 1},
                    "rows": [{"values": [celula(value)]}],
                    "fields": "userEnteredValue",
                }})

    data = (src.get("data") or [{}])[0]
    requests += requests_dimensao(dst_id, "ROWS", data.get("rowMetadata", [])[:h])
    requests += requests_dimensao(dst_id, "COLUMNS", data.get("columnMetadata", [])[:w])
    gp = src["properties"].get("gridProperties", {})
    props = {k: gp[k] for k in ("frozenRowCount", "frozenColumnCount", "hideGridlines") if k in gp}
    if props:
        requests.append({"updateSheetProperties": {
            "properties": {"sheetId": dst_id, "gridProperties": props},
            "fields": ",".join(f"gridProperties.{k}" for k in props),
        }})
    for merge in src.get("merges", []):
        requests.append({"mergeCells": {"range": remapear_sheet_ids(merge, id_map), "mergeType": "MERGE_ALL"}})
    for rule in src.get("conditionalFormats", []):
        requests.append({"addConditionalFormatRule": {"rule": remapear_sheet_ids(rule, id_map), "index": 0}})
    for chart in src.get("charts", []):
        chart = {k: copy.deepcopy(chart[k]) for k in ("spec", "position") if k in chart}
        requests.append({"addChart": {"chart": remapear_sheet_ids(chart, id_map)}})
    return requests


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ej", action="append", help="ID da EJ (pode repetir)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from dotenv import load_dotenv
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    load_dotenv()
    cfg = json.load(open(S.CONFIG_PATH, encoding="utf-8"))
    cred = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "dde-projeto-9ed22179e048.json")
    cred = cred if os.path.isabs(cred) else os.path.join(S.PROJECT_DIR, cred)
    creds = service_account.Credentials.from_service_account_file(
        cred, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    tables = S.mapear_tabelas(service)
    snap = {"acessos": S.ler_acessos(service, cfg, tables),
            "acessos_inicio": tables[S.TABELAS_MESTRE["acessos"]][1].get("startRowIndex", 0)}
    targets = S.acessos(snap, cfg)
    if args.ej:
        targets = [x for x in targets if x["id"] in set(args.ej)]

    src_values, src_sheets = fonte(service, cfg["modelo_id"])
    src_ids = {x["properties"]["title"]: x["properties"]["sheetId"] for x in src_sheets.values()}
    failures = 0
    for target in targets:
        try:
            if not args.dry_run:
                S.garantir_grade_dados(service, target["planilha"])
            dst_sheets = metadata_destino(service, target["planilha"])
            missing = [x for x in ABAS if x not in dst_sheets]
            if missing:
                raise ValueError("abas ausentes: " + ", ".join(missing))
            dst_values = valores_destino(service, target["planilha"])
            dst_ids = {x["properties"]["title"]: x["properties"]["sheetId"] for x in dst_sheets.values()}
            id_map = {src_ids[name]: dst_ids[name] for name in src_ids if name in dst_ids}
            requests = []
            for titulo in ABAS:
                requests += planejar_aba(titulo, src_sheets[titulo], src_values[titulo],
                                         dst_sheets[titulo], dst_values[titulo], id_map)
            print(f"{target['id']:>5} {target['ej']}: {len(requests)} alterações planejadas")
            if not args.dry_run:
                S.com_retry(service.spreadsheets().batchUpdate(
                    spreadsheetId=target["planilha"], body={"requests": requests}))
                time.sleep(S.PAUSA_ENTRE_EJS)
        except Exception as exc:
            failures += 1
            print(f"{target['id']:>5} {target['ej']}: ERRO: {type(exc).__name__}: {str(exc)[:300]}")
    print(f"Concluído: {len(targets) - failures} ok, {failures} com erro")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
