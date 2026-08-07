import os
import sys
import time
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from dotenv import load_dotenv

# Load local environment variables from .env file
load_dotenv()

LOGIN_URL = "https://portal.brasiljunior.org.br/"
REPORTS_URL = "https://portal.brasiljunior.org.br/federacoes/8/relatorios"
EMAIL = os.getenv("PORTAL_EMAIL")
PASSWORD = os.getenv("PORTAL_PASSWORD")

# Dynamically resolve download directory
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(PROJECT_DIR, "downloads")

REPORTS_CONFIG = [
    {
        "id": "monitoramento_geral",
        "section": "Monitoramento",
        "search_name": "Geral v2.0",
        "index": 0, # First 'Geral v2.0' on the page is Monitoramento -> Geral v2.0 Beta
        "dest_filename": "monitoramento_geral_v2.xlsx"
    },
    {
        "id": "monitoramento_acumulado",
        "section": "Monitoramento",
        "search_name": "Acumulado v2.0",
        "index": 0, # First 'Acumulado v2.0' on the page is Monitoramento -> Acumulado v2.0 Beta
        "dest_filename": "monitoramento_acumulado_v2.xlsx"
    },
    {
        "id": "empresas_juniores_geral",
        "section": "Empresas Juniores",
        "search_name": "Geral v2.0",
        "index": 1, # Second 'Geral v2.0' on the page is Empresas Juniores -> Geral v2.0 Beta
        "dest_filename": "empresas_juniores_geral_v2.xlsx"
    }
]

def run():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    with sync_playwright() as p:
        print("Launching headless browser...")
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True, viewport={"width": 1280, "height": 1000})
        page = context.new_page()

        print(f"Navigating to login: {LOGIN_URL}...")
        page.goto(LOGIN_URL)
        
        print("Entering credentials...")
        page.fill("input[type='email'], input[name='email'], input[id*='email'], input[type='text']", EMAIL)
        page.fill("input[type='password'], input[name='password'], input[id*='password']", PASSWORD)
        
        print("Submitting login form...")
        page.click("button[type='submit'], button:has-text('Login'), button:has-text('Entrar'), input[type='submit']")
        
        print("Waiting for portal dashboard to load (authenticating)...")
        try:
            # Wait for URL redirect back to portal dashboard (robust and independent of browser language/locale!)
            page.wait_for_url("https://portal.brasiljunior.org.br/**", timeout=30000)
            print("Login complete.")
        except PlaywrightTimeoutError as te:
            print("   -> LOGIN TIMEOUT: Failed to redirect back to portal dashboard.")
            err_screenshot_path = os.path.join(PROJECT_DIR, "login_error_screenshot.png")
            try:
                page.screenshot(path=err_screenshot_path, full_page=True)
                print(f"   [Diagnostic] Login error screenshot saved to: {err_screenshot_path}")
                print(f"   [Diagnostic] Page URL: {page.url}")
                print(f"   [Diagnostic] Page Title: {page.title()}")
            except Exception as ex:
                print(f"   [Diagnostic] Failed to save screenshot: {ex}")
            sys.exit(1)
        except Exception as e:
            print(f"   -> LOGIN ERROR: {e}")
            err_screenshot_path = os.path.join(PROJECT_DIR, "login_error_screenshot.png")
            try:
                page.screenshot(path=err_screenshot_path, full_page=True)
                print(f"   [Diagnostic] Login error screenshot saved to: {err_screenshot_path}")
            except:
                pass
            sys.exit(1)

        print(f"Navigating to reports page: {REPORTS_URL}...")
        page.goto(REPORTS_URL)
        page.wait_for_timeout(5000) # Wait 5 seconds for React to render
        page.wait_for_load_state('networkidle')
        print("Reports page loaded.")

        success_count = 0
        for r_cfg in REPORTS_CONFIG:
            rep_id = r_cfg["id"]
            sec = r_cfg["section"]
            name = r_cfg["search_name"]
            idx = r_cfg["index"]
            dest_file = r_cfg["dest_filename"]
            
            print(f"\n=== Processing: {sec} -> {name} (Index: {idx}) ===")
            
            try:
                # 1. Locate heading
                print(f"1. Locating heading for '{name}' (occurrence index {idx})...")
                heading = page.locator("h3").filter(has_text=name).nth(idx)
                
                # Wait dynamically up to 30 seconds for the heading to appear (robust against API lag!)
                heading.wait_for(state="visible", timeout=30000)
                
                # 2. Get card container (depth 2 parent)
                print("2. Resolving card container (depth 2)...")
                row_locator = heading.locator("xpath=./../..")
                card_text = repr(row_locator.inner_text().strip())
                print(f"   Resolved card: {card_text[:120]}...")
                
                # 3. Trigger update
                print("3. Clicking 'Atualizar' button...")
                atualizar_btn = row_locator.locator("button:has-text('Atualizar'), a:has-text('Atualizar')").first
                atualizar_btn.click()
                print("   Update triggered! Waiting 5 seconds before checking download button...")
                time.sleep(5)
                
                # 4. Wait for Baixar button
                print("4. Waiting for 'Baixar' button to become visible and active...")
                baixar_btn = row_locator.locator("a:has-text('Baixar'), button:has-text('Baixar')").first
                baixar_btn.wait_for(state="visible", timeout=120000) # Wait up to 2 minutes
                
                # Wait if button gets disabled class (sometimes React disables button during download)
                for _ in range(60):
                    classes = baixar_btn.get_attribute("class") or ""
                    if "disabled" not in classes:
                        break
                    print("   Download button currently disabled, waiting 1s...")
                    time.sleep(1)
                
                # 5. Download file
                print("5. Button active! Clicking 'Baixar' and downloading...")
                with page.expect_download(timeout=120000) as download_info:
                    baixar_btn.click()
                
                download = download_info.value
                dest_path = os.path.join(DOWNLOAD_DIR, dest_file)
                download.save_as(dest_path)
                print(f"   -> SUCCESS! Saved to {dest_path}")
                success_count += 1
                
            except PlaywrightTimeoutError:
                print(f"   -> TIMEOUT ERROR: Failed to generate/download '{name}' within limit.")
                # Diagnostic: Capture a screenshot of the error page to see if it is blocked/Cloudflare!
                err_screenshot_path = os.path.join(PROJECT_DIR, f"error_screenshot_{rep_id}.png")
                try:
                    page.screenshot(path=err_screenshot_path, full_page=True)
                    print(f"   [Diagnostic] Error screenshot saved to: {err_screenshot_path}")
                    print(f"   [Diagnostic] Page URL: {page.url}")
                    print(f"   [Diagnostic] Page Title: {page.title()}")
                except Exception as ex:
                    print(f"   [Diagnostic] Failed to save screenshot: {ex}")
            except Exception as e:
                print(f"   -> ERROR: {e}")
                err_screenshot_path = os.path.join(PROJECT_DIR, f"error_screenshot_{rep_id}.png")
                try:
                    page.screenshot(path=err_screenshot_path, full_page=True)
                    print(f"   [Diagnostic] Error screenshot saved to: {err_screenshot_path}")
                except:
                    pass

        # If any of the required downloads failed, exit with a non-zero code!
        if success_count < len(REPORTS_CONFIG):
            print(f"\nERROR: Only {success_count}/{len(REPORTS_CONFIG)} reports downloaded successfully!")
            sys.exit(1)

        print("\nAll downloads finished. Closing browser.")
        browser.close()

if __name__ == "__main__":
    run()
