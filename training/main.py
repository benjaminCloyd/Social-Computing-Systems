from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time

POLL_INTERVAL = 0.5
LOAD_TIMEOUT = 15


def load_shorts(file_path="shorts.txt"):
    shorts = []
    with open(file_path) as f:
        for line in f:
            parts = line.strip().split(",")
            url = parts[0].strip()
            if url:
                shorts.append(url)
    return shorts


def wait_for_video_to_finish(driver):
    try:
        WebDriverWait(driver, LOAD_TIMEOUT).until(
            EC.presence_of_element_located((By.TAG_NAME, "video"))
        )
    except Exception:
        print("  Warning: video element not found, skipping.")
        return

    deadline = time.time() + LOAD_TIMEOUT
    while time.time() < deadline:
        duration = driver.execute_script(
            "const v = document.querySelector('video'); return v ? v.duration : 0;"
        )
        if duration and duration > 0:
            break
        time.sleep(POLL_INTERVAL)
    else:
        print("  Warning: could not determine video duration, skipping.")
        return

    print(f"  Video duration: {duration:.1f}s")

    while True:
        current = driver.execute_script(
            "const v = document.querySelector('video'); return v ? v.currentTime : 0;"
        )
        if current is not None and current >= duration - 0.5:
            break
        time.sleep(POLL_INTERVAL)


def run(shorts):
    options = Options()

    # Point to your Firefox profile so you stay signed in
    options.add_argument("-profile")
    options.add_argument(
        "/Users/bencloyd/Library/Application Support/Firefox/Profiles/o1n4dthj.default-release"
    )

    driver = webdriver.Firefox(options=options)

    for i, url in enumerate(shorts):
        print(f"[{i+1}/{len(shorts)}] Opening: {url}")
        driver.get(url)
        wait_for_video_to_finish(driver)
        print("  Done.")

    print("All shorts finished.")
    driver.quit()


if __name__ == "__main__":
    shorts = load_shorts()
    run(shorts)
