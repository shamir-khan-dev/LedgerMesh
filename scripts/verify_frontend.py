import os
import sys
from playwright.sync_api import sync_playwright

artifact_dir = r"C:\Users\shami\.gemini\antigravity\brain\71c1c71a-ca53-4ea4-8c13-ebf5fc6edc1f"
os.makedirs(artifact_dir, exist_ok=True)

def verify_frontend():
    console_errors = []
    
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as e:
            print(f"Error launching chromium: {e}")
            return False

        page = browser.new_page(viewport={"width": 1440, "height": 950})

        # Capture console errors and page errors
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: console_errors.append(str(exc)))

        print("1. Navigating to http://127.0.0.1:8000/...")
        page.goto("http://127.0.0.1:8000/", wait_until="networkidle")
        page.wait_for_timeout(1000)

        # 1. Main View Screenshot
        main_shot = os.path.join(artifact_dir, "01_dashboard_main.png")
        page.screenshot(path=main_shot, full_page=False)
        print(f"Captured: {main_shot}")

        # 2. Test Posting a Transaction in Composer
        print("2. Testing Transaction Composer...")
        page.evaluate("document.querySelector('#btn-post-transaction').click()")
        page.wait_for_timeout(800)
        composer_shot = os.path.join(artifact_dir, "02_posted_transaction.png")
        page.screenshot(path=composer_shot, full_page=False)
        print(f"Captured: {composer_shot}")

        # 3. Test OCC Concurrency Tab
        print("3. Testing Concurrency OCC Tab...")
        page.evaluate("document.querySelector(\"button[data-tab='tab-occ']\").click()")
        page.wait_for_timeout(500)
        page.evaluate("document.querySelector('#btn-run-occ').click()")
        page.wait_for_timeout(2000) # Wait for 50 workers to complete
        occ_shot = os.path.join(artifact_dir, "03_occ_concurrency_stress.png")
        page.screenshot(path=occ_shot, full_page=False)
        print(f"Captured: {occ_shot}")

        # 4. Test Audit Chain & Tamper Attack Tab
        print("4. Testing Cryptographic Audit Tab...")
        page.evaluate("document.querySelector(\"button[data-tab='tab-audit']\").click()")
        page.wait_for_timeout(500)
        page.evaluate("document.querySelector('#btn-simulate-tamper').click()")
        page.wait_for_timeout(600)
        audit_shot = os.path.join(artifact_dir, "04_audit_tamper_detected.png")
        page.screenshot(path=audit_shot, full_page=False)
        print(f"Captured: {audit_shot}")

        # 5. Test Idempotency Lab Tab
        print("5. Testing Idempotency Lab Tab...")
        page.evaluate("document.querySelector(\"button[data-tab='tab-idempotency']\").click()")
        page.wait_for_timeout(500)
        # Click 3 times rapidly
        page.evaluate("document.querySelector('#btn-spam-idempotency').click()")
        page.wait_for_timeout(200)
        page.evaluate("document.querySelector('#btn-spam-idempotency').click()")
        page.wait_for_timeout(200)
        page.evaluate("document.querySelector('#btn-spam-idempotency').click()")
        page.wait_for_timeout(600)
        idem_shot = os.path.join(artifact_dir, "05_idempotency_lab.png")
        page.screenshot(path=idem_shot, full_page=False)
        print(f"Captured: {idem_shot}")

        # 6. Test Reconciliation Tab
        print("6. Testing Reconciliation Tab...")
        page.evaluate("document.querySelector(\"button[data-tab='tab-reconciliation']\").click()")
        page.wait_for_timeout(500)
        page.evaluate("document.querySelector('#btn-run-reconciliation').click()")
        page.wait_for_timeout(600)
        rec_shot = os.path.join(artifact_dir, "06_reconciliation_tie_out.png")
        page.screenshot(path=rec_shot, full_page=False)
        print(f"Captured: {rec_shot}")

        browser.close()

    print(f"\nConsole Errors Count: {len(console_errors)}")
    if console_errors:
        for err in console_errors:
            print(f"  [ERROR] {err}")
    else:
        print("[OK] Zero console errors or unhandled exceptions detected.")

    return len(console_errors) == 0

if __name__ == "__main__":
    success = verify_frontend()
    sys.exit(0 if success else 1)
