import subprocess
import sys
import time
import os

from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ── Config ────────────────────────────────────────────────────────────────────
FIREFOX_PROFILE_PATH = (
    "/Users/bencloyd/Library/Application Support/Firefox/Profiles/"
    "o1n4dthj.default-release"
)
# Changed to the main My Activity URL to match your 3-step click flow
DELETE_URL = "https://myactivity.google.com/myactivity"
LOAD_TIMEOUT = 20  # seconds to wait for page elements


# ── Google Activity Deletion ──────────────────────────────────────────────────
def delete_google_activity():
    """
    Open myactivity.google.com in the signed-in Firefox profile and delete
    all activity for all time using a 3-step click flow.
    """
    print("  [delete] Launching browser...")
    options = Options()
    options.add_argument("-profile")
    options.add_argument(FIREFOX_PROFILE_PATH)

    driver = webdriver.Firefox(options=options)
    wait = WebDriverWait(driver, LOAD_TIMEOUT)

    def click_button_by_text(text, step_name):
        """Helper to find and click a button by its text content."""
        xpaths = [
            f"//button[.//span[normalize-space()='{text}']]",
            f"//button[normalize-space()='{text}']",
            f"//*[@role='button' and contains(normalize-space(), '{text}')]",
            f"//button[contains(normalize-space(), '{text}')]",
            f"//div[@role='menuitem' and contains(normalize-space(), '{text}')]",
            f"//*[contains(text(), '{text}')]",
        ]

        for xpath in xpaths:
            try:
                btn = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
                btn.click()
                print(f"  [delete] Step {step_name}: Clicked '{text}'.")
                return True
            except Exception:
                continue

        print(f"  [delete] WARNING: Could not find '{text}' for Step {step_name}.")
        return False

    try:
        driver.get(DELETE_URL)
        print("  [delete] Navigated to Google My Activity page.")

        # Give the page a moment to fully render
        time.sleep(3)

        # ── Step 1: Click the initial "Delete" button ──────
        if not click_button_by_text("Delete", 1):
            time.sleep(5)
            return

        time.sleep(2)  # Brief pause for dropdown/modal to appear

        # ── Step 2: Click "Delete all time" ──────
        if not click_button_by_text("Delete all time", 2):
            time.sleep(5)
            return

        time.sleep(2)  # Brief pause for confirmation modal to appear

        # ── Step 3: Click the final "Delete" button to confirm ──────
        if not click_button_by_text("Delete", 3):
            time.sleep(5)
            return

        # Give Google a moment to process the deletion
        time.sleep(3)
        print("  [delete] Activity deletion complete.")

    except Exception as e:
        print(f"  [delete] ERROR during activity deletion: {e}")
    finally:
        driver.quit()


# ── Helpers ───────────────────────────────────────────────────────────────────
def run_script(label, script_path):
    """Run a Python script as a subprocess and wait for it to finish."""
    print(f"\n  [{label}] Starting: {script_path}")
    result = subprocess.run(
        [sys.executable, script_path],
        cwd=os.path.dirname(os.path.abspath(script_path)),
    )
    if result.returncode != 0:
        print(f"  [{label}] WARNING: script exited with code {result.returncode}")
    else:
        print(f"  [{label}] Finished successfully.")


# ── Main Loop ─────────────────────────────────────────────────────────────────
def main():
    # Resolve script paths relative to this file's location
    base = os.path.dirname(os.path.abspath(__file__))
    training_script = os.path.join(base, "training", "main.py")
    explore_script = os.path.join(base, "explore", "main.py")

    iteration = 1
    print("Starting loop — press Ctrl+C to stop.\n")

    try:
        while True:
            print(f"{'='*60}")
            print(f"  LOOP ITERATION {iteration}")
            print(f"{'='*60}")

            # 1. Training
            run_script("training", training_script)

            # 2. Explore
            run_script("explore", explore_script)

            # 3. Delete Google activity
            print("\n  [delete] Deleting Google activity for all time...")
            delete_google_activity()

            print(f"\n  Iteration {iteration} complete. Starting next...\n")
            iteration += 1

    except KeyboardInterrupt:
        print(
            f"\n\nLoop cancelled by user after {iteration - 1} completed iteration(s)."
        )


if __name__ == "__main__":
    main()
