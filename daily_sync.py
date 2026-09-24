import subprocess
import sys
import os

# Dynamically resolve the project directory (works both on your Mac and on GitHub Actions!)
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

def main():
    print("=== STARTING DAILY SYNC ===")
    os.chdir(PROJECT_DIR)
    
    # 1. Run the download script using the active Python interpreter (sys.executable)
    print("\n--- Phase 1: Downloading reports from Portal BJ ---")
    download_res = subprocess.run([sys.executable, "test_exact_downloads.py"], capture_output=True, text=True)
    print(download_res.stdout)
    if download_res.stderr:
        print("Download Stderr:", download_res.stderr)
        
    if download_res.returncode != 0:
        print("ERROR: Download phase failed! Aborting sync.")
        sys.exit(1)
        
    # 2. Run the update script using the active Python interpreter (sys.executable)
    print("\n--- Phase 2: Updating Google Sheets ---")
    update_res = subprocess.run([sys.executable, "update_sheets.py"], capture_output=True, text=True)
    print(update_res.stdout)
    if update_res.stderr:
        print("Update Stderr:", update_res.stderr)
        
    if update_res.returncode != 0:
        print("ERROR: Update phase failed!")
        sys.exit(1)
        
    # 3. Distribute the master data to each EJ's individual spreadsheet
    print("\n--- Phase 3: Updating the individual EJ spreadsheets ---")
    ejs_res = subprocess.run([sys.executable, "sync_planilhas_ejs.py"], capture_output=True, text=True)
    print(ejs_res.stdout)
    if ejs_res.stderr:
        print("EJ Sync Stderr:", ejs_res.stderr)

    if ejs_res.returncode != 0:
        print("ERROR: EJ spreadsheets phase finished with errors (see the access tab in the master).")
        sys.exit(1)

    print("\n=== DAILY SYNC COMPLETED SUCCESSFULLY ===")

if __name__ == "__main__":
    main()
