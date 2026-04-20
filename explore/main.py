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
MAX_WATCH_TIME = 60  # Auto-scroll after this many seconds
SHORT_COUNT = 20  # How many real (non-ad) shorts to watch
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
    time.sleep(1.0)

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


def is_ad_playing(driver):
    """Return True if an ad is currently showing."""
    ad_class = driver.execute_script(
        "return document.querySelector('.ad-showing') !== null;"
    )
    if ad_class:
        return True

    ad_indicators = [
        ".ytp-ad-player-overlay",
        ".ytp-ad-simple-ad-badge",
        ".ytp-ad-preview-container",
        "ytd-reel-player-overlay-renderer .ytd-ad-slot-renderer",
    ]
    for selector in ad_indicators:
        try:
            el = driver.find_element(By.CSS_SELECTOR, selector)
            if el.is_displayed():
                return True
        except Exception:
            continue

    return False


def log_entry(log_file, url, channel, index, total, duration, capped):
    """Append a watched short's details to the log file, flushing immediately."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    note = f" [capped at {MAX_WATCH_TIME}s]" if capped else ""
    with open(log_file, "a") as f:
        f.write(
            f"[{timestamp}] [{index}/{total}] {channel} | {url} ({duration:.1f}s{note})\n"
        )
        f.flush()
        os.fsync(f.fileno())


def wait_for_video(driver):
    """
    Watch the current short up to MAX_WATCH_TIME seconds.
    Returns (duration, was_capped).
    """
    try:
        WebDriverWait(driver, LOAD_TIMEOUT).until(
            EC.presence_of_element_located((By.TAG_NAME, "video"))
        )
    except Exception:
        print("  Warning: video element not found, skipping.")
        return 0, False

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
        return 0, False

    capped = duration > MAX_WATCH_TIME
    watch_until = min(duration, MAX_WATCH_TIME)
    print(
        f"  Video duration: {duration:.1f}s{' — will scroll at 60s' if capped else ''}"
    )

    while True:
        current = driver.execute_script(
            "const v = document.querySelector('video'); return v ? v.currentTime : 0;"
        )
        if current is not None and current >= watch_until - 0.5:
            break
        time.sleep(POLL_INTERVAL)

    return duration, capped


def scroll_to_next(driver):
    """Press the down arrow key to advance to the next short."""
    body = driver.find_element(By.TAG_NAME, "body")
    body.send_keys(Keys.ARROW_DOWN)
    time.sleep(1.5)


def run(short_count):
    options = Options()
    options.add_argument("-profile")
    options.add_argument(FIREFOX_PROFILE_PATH)

    log_file = get_log_filename(FIREFOX_PROFILE_PATH)
    print(f"Logging watched shorts to: {log_file}")

    driver = webdriver.Firefox(options=options)
    driver.get(SHORTS_START_URL)

    print("Loading YouTube Shorts feed...")
    try:
        WebDriverWait(driver, LOAD_TIMEOUT).until(
            EC.presence_of_element_located((By.TAG_NAME, "video"))
        )
    except Exception:
        print("Warning: timed out waiting for first short to load.")

    watched = 0
    while watched < short_count:
        if is_ad_playing(driver):
            print("  Ad detected — scrolling past...")
            scroll_to_next(driver)
            continue

        current_url = driver.current_url
        channel = get_channel_name(driver)
        print(f"[{watched+1}/{short_count}] {channel} | {current_url}")

        # Snapshot url/channel before waiting — page state can shift mid-watch
        duration, capped = 0, False
        try:
            duration, capped = wait_for_video(driver)
        except Exception as e:
            print(f"  Warning: exception while watching video: {e}")
        finally:
            # Always log, even if wait_for_video threw
            log_entry(
                log_file,
                current_url,
                channel,
                watched + 1,
                short_count,
                duration,
                capped,
            )
            print("  Done.")
            watched += 1

        if watched < short_count:
            scroll_to_next(driver)

    print(f"Finished watching {short_count} shorts.")
    print(f"Log saved to: {log_file}")
    driver.quit()


if __name__ == "__main__":
    run(SHORT_COUNT)
