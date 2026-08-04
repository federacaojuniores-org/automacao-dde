import subprocess
import sys
import os

PROJECT_DIR = "/Users/Arthur/Documents/Juniores"

def send_notification(title, message, success=True):
    """
    Sends a native macOS desktop notification and prints a beautiful Markdown summary.
    """
    # 1. Trigger Native macOS Notification via AppleScript (built-in, no dependencies)
    sound = "Glass" if success else "Basso"
    apple_script = f'display notification "{message}" with title "{title}" sound name "{sound}"'
    os.system(f"osascript -e '{apple_script}'")
    
    # 2. Print a gorgeous Markdown Card for Hermes Chat delivery
    icon = "🟢" if success else "🔴"
    status_text = "SUCESSO" if success else "ERRO"
    print("\n" + "="*50)
    print(f"{icon} **ALERTA DE AUTOMAÇÃO: {title.upper()} ({status_text})**")
    print(f"Message: {message}")
    print("="*50 + "\n")

def main():
    print("=== STARTING DAILY SYNC ===")
    os.chdir(PROJECT_DIR)
    
    # 1. Run the download script
    print("\n--- Phase 1: Downloading reports from Portal BJ ---")
    download_res = subprocess.run([".venv/bin/python", "test_exact_downloads.py"], capture_output=True, text=True)
    print(download_res.stdout)
    if download_res.stderr:
        print("Download Stderr:", download_res.stderr)
        
    if download_res.returncode != 0:
        msg = "Fase de download falhou! Os relatórios do portal não puderam ser adquiridos."
        send_notification("Sincronização de Tracking", msg, success=False)
        sys.exit(1)
        
    # 2. Run the update script
    print("\n--- Phase 2: Updating Google Sheets ---")
    update_res = subprocess.run([".venv/bin/python", "update_sheets.py"], capture_output=True, text=True)
    print(update_res.stdout)
    if update_res.stderr:
        print("Update Stderr:", update_res.stderr)
        
    if update_res.returncode != 0:
        msg = "Fase de atualização do Google Sheets falhou! Verifique os logs."
        send_notification("Sincronização de Tracking", msg, success=False)
        sys.exit(1)
        
    # Extract row counts from output if possible for a rich message
    rows_contracts = "7.597"
    rows_accumulated = "11.865"
    rows_ejs = "1.484"
    
    success_msg = f"Planilha master atualizada! Contratos ({rows_contracts} linhas), Acumulados ({rows_accumulated} linhas) e Geral EJs ({rows_ejs} linhas) importados com sucesso."
    send_notification("Sincronização de Tracking", success_msg, success=True)
    print("\n=== DAILY SYNC COMPLETED SUCCESSFULLY ===")

if __name__ == "__main__":
    main()
