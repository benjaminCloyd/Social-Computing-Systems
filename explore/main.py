from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
import time
import os

POLL_INTERVAL = 0.5
LOAD_TIMEOUT = 15
SHORT_COUNT = 21  # How many shorts to watch (first videos url cant be saved)
SHORTS_START_URL = "https://www.youtube.com/shorts"
FIREFOX_PROFILE_PATH = "/Users/bencloyd/Library/Application Support/Firefox/Profiles/o1n4dthj.default-release"


def get_log_filename(profile_path):
    """Extract the profile folder name and build the log filename."""
    profile_name = os.path.basename(profile_path.rstrip("/"))
    return f"exploreshorts({profile_name}).txt"


def get_channel_name(driver):
    """
    Wait for the Shorts overlay to settle, then try multiple strategies
    to pull the channel name out of the DOM.
    """
    # Give the overlay a moment to finish rendering
    time.sleep(1.0)

    # Strategy 1: explicit CSS selectors, most-specific first
    selectors = [
        "ytd-reel-player-overlay-renderer ytd-channel-name yt-formatted-string#text a",
        "ytd-reel-player-overlay-renderer ytd-channel-name yt-formatted-string#text",
        "ytd-reel-player-overlay-renderer #channel-name yt-formatted-string",
        "ytd-reel-player-header-renderer #channel-name yt-formatted-string",
        "#channel-name yt-formatted-string",
        "ytd-channel-name yt-formatted-string",
    ]
    for selector in selectors:
        try:
            el = driver.find_element(By.CSS_SELECTOR, selector)
            name = el.text.strip()
            if name:
                return name
        except Exception:
            continue

    # Strategy 2: JavaScript — walk every ytd-channel-name in the page
    # and return the first non-empty text we find
    name = driver.execute_script(
        """
        const nodes = document.querySelectorAll('ytd-channel-name');
        for (const node of nodes) {
            const text = node.innerText.trim();
            if (text) return text;
        }
        return null;
    """
    )
    if name:
        return name.strip()

    # Strategy 3: look for any anchor inside the overlay that points to a /@ channel URL
    name = driver.execute_script(
        """
        const links = document.querySelectorAll('a[href^="/@"]');
        for (const a of links) {
            const text = a.innerText.trim();
            if (text) return text;
        }
        return null;
    """
    )
    if name:
        return name.strip()

    return "unknown channel"


def log_entry(log_file, url, channel, index, total, duration):
    """Append a watched short's details to the log file."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(log_file, "a") as f:
        f.write(
            f"[{timestamp}] [{index}/{total}] {channel} | {url} ({duration:.1f}s)\n"
        )


def wait_for_video_to_finish(driver):
    """Wait for the current short to finish playing. Returns duration in seconds, or 0 on failure."""
    try:
        WebDriverWait(driver, LOAD_TIMEOUT).until(
            EC.presence_of_element_located((By.TAG_NAME, "video"))
        )
    except Exception:
        print("  Warning: video element not found, skipping.")
        return 0

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
        return 0

    print(f"  Video duration: {duration:.1f}s")

    while True:
        current = driver.execute_script(
            "const v = document.querySelector('video'); return v ? v.currentTime : 0;"
        )
        if current is not None and current >= duration - 0.5:
            break
        time.sleep(POLL_INTERVAL)

    return duration


def scroll_to_next(driver):
    """Press the down arrow key to advance to the next short."""
    body = driver.find_element(By.TAG_NAME, "body")
    body.send_keys(Keys.ARROW_DOWN)

    # Wait briefly for the new short to begin loading
    time.sleep(1.5)


def run(short_count):
    options = Options()

    # Point to your Firefox profile so you stay signed in
    options.add_argument("-profile")
    # You will have to customize this to be the path on your machine, can be found by opening firefox and typing in about:profiles
    options.add_argument(FIREFOX_PROFILE_PATH)

    log_file = get_log_filename(FIREFOX_PROFILE_PATH)
    print(f"Logging watched shorts to: {log_file}")

    driver = webdriver.Firefox(options=options)
    driver.get(SHORTS_START_URL)

    # Give the page a moment to fully load before we start
    print("Loading YouTube Shorts feed...")
    try:
        WebDriverWait(driver, LOAD_TIMEOUT).until(
            EC.presence_of_element_located((By.TAG_NAME, "video"))
        )
    except Exception:
        print("Warning: timed out waiting for first short to load.")

    for i in range(short_count):
        current_url = driver.current_url
        channel = get_channel_name(driver)
        print(f"[{i+1}/{short_count}] {channel} | {current_url}")
        duration = wait_for_video_to_finish(driver)
        log_entry(log_file, current_url, channel, i + 1, short_count, duration)
        print("  Done.")

        if i < short_count - 1:
            scroll_to_next(driver)

    print(f"Finished watching {short_count} shorts.")
    print(f"Log saved to: {log_file}")
    driver.quit()


if __name__ == "__main__":
    run(SHORT_COUNT)
