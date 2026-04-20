import time
import os
import sys
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ── Config ────────────────────────────────────────────────────────────────────
FIREFOX_PROFILE_PATH = "/Users/bencloyd/Library/Application Support/Firefox/Profiles/o1n4dthj.default-release"
DELETE_URL = "https://myactivity.google.com/myactivity"


def delete_google_activity():
    print("  [delete] Launching Firefox...")
    options = Options()
    options.add_argument("-profile")
    options.add_argument(FIREFOX_PROFILE_PATH)

    driver = webdriver.Firefox(options=options)
    wait = WebDriverWait(driver, 15)

    def robust_click(text_list, step_label, in_dialog=False):
        """
        Attempts to click a button based on a list of possible text matches.
        in_dialog: If True, specifically looks for buttons inside a popup/modal.
        """
        if isinstance(text_list, str):
            text_list = [text_list]

        for text in text_list:
            # If in_dialog is True, we look for buttons inside the 'c-wiz' or 'dialog' containers
            # to avoid clicking buttons that are hidden in the background.
            prefix = "//div[@role='dialog']" if in_dialog else ""

            xpaths = [
                f"{prefix}//button[contains(., '{text}')]",
                f"{prefix}//span[contains(text(), '{text}')]/ancestor::button",
                f"{prefix}//div[@role='button'][contains(., '{text}')]",
                f"//*[text()='{text}']",
            ]

            for xpath in xpaths:
                try:
                    # 1. Wait for element
                    element = wait.until(
                        EC.presence_of_element_located((By.XPATH, xpath))
                    )

                    # 2. Check if it's actually visible/displayed
                    if not element.is_displayed():
                        continue

                    # 3. Force scroll and click
                    driver.execute_script(
                        "arguments[0].scrollIntoView({block: 'center'});", element
                    )
                    time.sleep(0.5)
                    driver.execute_script("arguments[0].click();", element)

                    print(f"  [success] {step_label}: Clicked '{text}'")
                    return True
                except:
                    continue
        return False

    try:
        driver.get(DELETE_URL)
        time.sleep(5)

        # 1. Open the "Delete" menu (Background button)
        if not robust_click("Delete", "Step 1 (Menu)"):
            return

        # 2. Select "All time" (Dropdown option)
        time.sleep(2)
        if not robust_click(["Delete all time", "All time"], "Step 2 (Selection)"):
            return

        # 3. The "Next" Button (Product Selection Screen)
        # This is the step that was likely being skipped. It is NOT optional.
        time.sleep(3)
        if not robust_click(["Next", "Continue"], "Step 3 (Next)"):
            print("  [warning] 'Next' not found, attempting to proceed anyway...")

        # 4. THE FINAL DELETE (Confirmation Screen)
        # We use in_dialog=True here to make sure we hit the button in the FOREGROUND modal.
        time.sleep(3)
        if not robust_click("Delete", "Step 4 (Final Confirm)", in_dialog=True):
            # Fallback if dialog detection fails
            if not robust_click("Delete", "Step 4 (Final Confirm Fallback)"):
                return

        # 5. Dismiss "Deleted" success message
        time.sleep(2)
        robust_click(["Got it", "OK"], "Step 5 (Done)", in_dialog=True)

        print("\n  [test] Activity successfully wiped!")
        time.sleep(2)

    except Exception as e:
        print(f"  [error] Flow interrupted: {e}")
    finally:
        driver.quit()


if __name__ == "__main__":
    delete_google_activity()
