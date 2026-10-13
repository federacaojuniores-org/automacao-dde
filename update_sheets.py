import os
from datetime import datetime, timedelta
import socket
import time

# Set a generous global socket timeout to prevent httplib2 from dropping stale connections 
# after the long Playwright download phase
socket.setdefaulttimeout(120)

# Dynamically resolve project directory
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

# Get credentials file path (resolve relative path to project directory)
credentials_filename = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "dde-projeto-9ed22179e048.json")
if os.path.isabs(credentials_filename):
    CREDENTIALS_PATH = credentials_filename
else:
    CREDENTIALS_PATH = os.path.join(PROJECT_DIR, credentials_filename)

SPREADSHEET_ID = os.getenv("GOOGLE_SPREADSHEET_ID", "163X5ADTJkHXK4INVs4KPdAXveUXhz0sYEoDGIdHWdOM")
DOWNLOAD_DIR = os.path.join(PROJECT_DIR, "downloads")

REPORTS_TO_UPDATE = [
    {
        "filename": "monitoramento_geral_v2.xlsx",
        "sheet_name": "[MONITORAMENTO] Geral v2.0",
        "required_headers": ["ID", "EMPRESA_JUNIOR", "FATURAMENTO", "DATA_DE_ASSINATURA"]
    },
    {
        "filename": "monitoramento_acumulado_v2.xlsx",
        "sheet_name": "[MONITORAMENTO] Acumulado v2.0",
        "required_headers": ["ID", "EMPRESA_JUNIOR", "MES", "FATURAMENTO"]
    },
    {
        "filename": "empresas_juniores_geral_v2.xlsx",
        "sheet_name": "[EMPRESAS JUNIORES] Geral v2.0",
        "required_headers": ["ID", "EMPRESA_JUNIOR", "FEDERACAO", "CLUSTER_2026"]
    }
]

def format_value(val):
    if val is None:
        return ""
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d %H:%M:%S")
    return val

def validar_cabecalhos(raw_headers, obrigatorios, origem):
    headers = list(raw_headers)
    while headers and headers[-1] is None:
        headers.pop()
    if not headers:
        raise ValueError(f"{origem}: arquivo vazio ou sem cabeçalho")
    vazios = [i + 1 for i, value in enumerate(headers) if value is None or not str(value).strip()]
    nomes = [str(value).strip() for value in headers]
    normalizados = [value.upper() for value in nomes]
    duplicados = sorted({value for value in normalizados if normalizados.count(value) > 1})
    faltando = [value for value in obrigatorios if value.upper() not in normalizados]
    problemas = []
    if vazios:
        problemas.append("cabeçalho vazio nas colunas " + ", ".join(map(str, vazios)))
    if duplicados:
        problemas.append("cabeçalhos duplicados: " + ", ".join(duplicados))
    if faltando:
        problemas.append("colunas obrigatórias ausentes: " + ", ".join(faltando))
    if problemas:
        raise ValueError(f"{origem}: " + "; ".join(problemas))
    return nomes, normalizados


def update_sheet_auto_aligned(service, filename, sheet_name, required_headers):
    import openpyxl
    excel_path = os.path.join(DOWNLOAD_DIR, filename)
    print(f"\n--- Reading Excel file: {filename} ---")
    
    # 1. Load Excel headers and data in streaming read_only mode
    wb_excel = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)
    sheet_excel = wb_excel.active
    
    # Get Excel headers (first row)
    excel_rows = sheet_excel.iter_rows(values_only=True)
    try:
        raw_excel_headers, excel_headers = validar_cabecalhos(next(excel_rows), required_headers, filename)
    except StopIteration:
        wb_excel.close()
        raise ValueError(f"{filename}: arquivo vazio ou sem cabeçalho")
        
    print(f"  Excel active sheet: '{sheet_excel.title}'")
    print(f"  Found {len(excel_headers)} headers in Excel.")
    
    # Read all remaining data rows from Excel
    excel_data = []
    for row in excel_rows:
        excel_data.append([format_value(val) for val in row])
    wb_excel.close()
    print(f"  Loaded {len(excel_data)} data rows from Excel.")

    # 2. Load ORIGINAL headers from the restored Google Sheet
    print(f"  Reading original headers from Google Sheet tab: '{sheet_name}'...")
    sheet_metadata = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{sheet_name}'!A1:ZZ1"
    ).execute()
    
    gs_rows = sheet_metadata.get("values", [])
    if not gs_rows:
        raise ValueError(f"{sheet_name}: cabeçalho ausente na planilha mestre")
    gs_headers, _ = validar_cabecalhos(gs_rows[0], (), sheet_name)
    print(f"  Found {len(gs_headers)} original headers in Google Sheet.")

    # Find new Excel headers that are not in the Google Sheet (case-insensitive check)
    gs_headers_upper = {h.strip().upper() for h in gs_headers}
    new_headers = []
    for raw_h in raw_excel_headers:
        if raw_h.strip().upper() not in gs_headers_upper:
            new_headers.append(raw_h)
            
    if new_headers:
        print(f"  [New Columns Detected] Appending {len(new_headers)} new columns at the end of the sheet: {new_headers}")
        gs_headers.extend(new_headers)

    # 3. Build the aligned upload matrix
    aligned_values = [gs_headers] # First row is always the original Google Sheet headers (NEVER renamed!)
    
    # Pre-map Excel header positions for O(1) lookups
    excel_header_map = {name: idx for idx, name in enumerate(excel_headers)}
    
    print("  Aligning Excel columns with Google Sheet structure by name...")
    for row_idx, excel_row in enumerate(excel_data):
        aligned_row = []
        for gs_h in gs_headers:
            gs_h_upper = gs_h.strip().upper()
            if gs_h_upper in excel_header_map:
                excel_idx = excel_header_map[gs_h_upper]
                # Extract value from Excel row at that index
                if excel_idx < len(excel_row):
                    aligned_row.append(excel_row[excel_idx])
                else:
                    aligned_row.append("")
            else:
                # If column doesn't exist in Excel, write empty (allows Table formula propagation)
                aligned_row.append("")
        aligned_values.append(aligned_row)

    # 4. Check and expand Grid Capacity if needed!
    print(f"  Checking grid capacity for '{sheet_name}'...")
    spreadsheet_info = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    sheet_id = None
    current_rows = 0
    for s in spreadsheet_info.get('sheets', []):
        if s.get("properties", {}).get("title") == sheet_name:
            sheet_id = s.get("properties", {}).get("sheetId")
            current_rows = s.get("properties", {}).get("gridProperties", {}).get("rowCount", 0)
            break
            
    required_rows = len(aligned_values)
    if sheet_id is not None and required_rows > current_rows:
        rows_to_add = required_rows - current_rows + 500  # Add 500 extra buffer rows
        print(f"  [Capacity Expansion] Sheet has {current_rows} rows. Appending {rows_to_add} new rows...")
        service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={
                "requests": [{
                    "appendDimension": {
                        "sheetId": sheet_id,
                        "dimension": "ROWS",
                        "length": rows_to_add
                    }
                }]
            }
        ).execute()

    # 5. Write first; only clear obsolete trailing rows after every chunk succeeds.
    chunk_size = 500
    print(f"  Writing aligned values in chunks of {chunk_size} rows in tab: '{sheet_name}'...")
    
    for i in range(0, len(aligned_values), chunk_size):
        chunk = aligned_values[i : i + chunk_size]
        start_row = i + 1
        end_row = i + len(chunk)
        print(f"    Writing rows {start_row} to {end_row}...")
        
        # Add retry loop for socket timeouts
        max_retries = 3
        for attempt in range(max_retries):
            try:
                service.spreadsheets().values().update(
                    spreadsheetId=SPREADSHEET_ID,
                    range=f"'{sheet_name}'!A{start_row}",
                    valueInputOption="USER_ENTERED",
                    body={"values": chunk}
                ).execute()
                break # Success, exit retry loop
            except Exception as e:
                print(f"      [Warning] Chunk write failed (Attempt {attempt+1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    raise e
                time.sleep(5) # Wait before retrying

    if required_rows < current_rows:
        service.spreadsheets().values().clear(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{sheet_name}'!A{required_rows + 1}:ZZ{current_rows}"
        ).execute()
    
    print(f"  SUCCESS: Updated {len(aligned_values)} rows in Google Sheets!")

def main():
    global CREDENTIALS_PATH, SPREADSHEET_ID
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from dotenv import load_dotenv
    load_dotenv()
    credentials_filename = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "dde-projeto-9ed22179e048.json")
    CREDENTIALS_PATH = credentials_filename if os.path.isabs(credentials_filename) else os.path.join(PROJECT_DIR, credentials_filename)
    SPREADSHEET_ID = os.getenv("GOOGLE_SPREADSHEET_ID", "163X5ADTJkHXK4INVs4KPdAXveUXhz0sYEoDGIdHWdOM")
    print("Authenticating with Google Sheets API...")
    creds = service_account.Credentials.from_service_account_file(
        CREDENTIALS_PATH,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    service = build("sheets", "v4", credentials=creds)
    print("Authentication complete.")
    
    for report in REPORTS_TO_UPDATE:
        update_sheet_auto_aligned(service, report["filename"], report["sheet_name"], report["required_headers"])
        
    # Final Step: Automatically update the Dashboard reference date in C3 to Brasília today's date!
    now_brasilia = datetime.utcnow() - timedelta(hours=3)
    today_str = now_brasilia.strftime("%d/%m/%Y")
    print(f"\n--- Updating reference date in '[REDE] Dashboard'!C3 to Brasília date: {today_str} ---")
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range="'[REDE] Dashboard'!C3",
        valueInputOption="USER_ENTERED",
        body={"values": [[today_str]]}
    ).execute()
    print("Dashboard reference date updated successfully!")
    
    # Update the last updated log in B4 (merged B-H4) to: "Dados atualizados pela última vez em: dd/MM/yy - hh:mm" (Brasília Time!)
    now_str = now_brasilia.strftime("%d/%m/%y - %H:%M")
    timestamp_text = f"Dados atualizados pela última vez em: {now_str}"
    print(f"--- Updating last updated log in '[REDE] Dashboard'!B4 to: '{timestamp_text}' ---")
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range="'[REDE] Dashboard'!B4",
        valueInputOption="USER_ENTERED",
        body={"values": [[timestamp_text]]}
    ).execute()
    print("Dashboard last updated log updated successfully!")
    
    print("\nAll 3 destination sheets and the Dashboard reference date have been successfully updated with self-aligned columns!")

if __name__ == "__main__":
    main()
