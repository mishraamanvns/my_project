# district_nextday_watcher.py
import subprocess
import time
import re
import requests
from bs4 import BeautifulSoup
import winsound
from datetime import datetime, timedelta

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

BASE_LISTING = "https://www.district.in/movies/mumbai-movie-tickets"
MOVIE_NAME = "De De Pyaar De 2"
CHROME_DEBUG_PORT = 9222
CHROME_USER_DATA = r"C:\ChromeDebug"   # keep same as you used before
REFRESH_SECONDS = 20
PAGE_WAIT = 4

def beep():
    try:
        winsound.Beep(1500, 700)
    except Exception:
        print("[alert] beep (winsound unsupported)")

def find_movie_link_from_listpage(movie_name: str):
    """Use requests + bs4 to find the movie url on the listing page."""
    try:
        r = requests.get(BASE_LISTING, timeout=15)
        r.raise_for_status()
    except Exception as e:
        print("Failed to fetch listing page:", e)
        return None

    soup = BeautifulSoup(r.text, "html.parser")
    # Find anchors that likely point to a movie page and contain the movie name text
    anchors = soup.find_all("a", href=True)
    movie_name_lower = movie_name.lower()
    for a in anchors:
        txt = " ".join(a.stripped_strings).lower()
        if movie_name_lower in txt:
            href = a["href"]
            # Make absolute if relative
            if href.startswith("/"):
                href = "https://www.district.in" + href
            # skip anchors that go to search or fragments
            if href.startswith("https://www.district.in/movies/") or "/movie-" in href or "/movies/" in href:
                return href
    return None

def start_chrome_debug():
    """Open Chrome with remote debugging if not already open."""
    subprocess.Popen(
        rf'start chrome --remote-debugging-port={CHROME_DEBUG_PORT} --user-data-dir="{CHROME_USER_DATA}"',
        shell=True
    )
    # give chrome time to start
    time.sleep(3)

def attach_selenium():
    options = Options()
    options.add_experimental_option("debuggerAddress", f"127.0.0.1:{CHROME_DEBUG_PORT}")
    # create driver that attaches to existing chrome
    driver = webdriver.Chrome(options=options)
    return driver

def attempt_click_by_text(driver, texts):
    """Try to find clickable element by visible text (case-insensitive)."""
    for t in texts:
        xpath = f"//*[contains(translate(normalize-space(string(.)), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{t.lower()}')]"
        try:
            elems = driver.find_elements(By.XPATH, xpath)
            for e in elems:
                # ensure it's clickable-ish
                try:
                    if e.is_displayed() and e.is_enabled():
                        e.click()
                        time.sleep(1)
                        return True
                except Exception:
                    continue
        except Exception:
            continue
    return False

def click_second_date_button(driver):
    """If the page has a date list, try to click the second date element."""
    # Many sites render date buttons as lists of buttons/divs - try common patterns:
    possible_selectors = [
        "//ul[contains(@class,'date') or contains(@class,'dates')]/li[2]",
        "//div[contains(@class,'date') or contains(@class,'dates')]//button[2]",
        "(//button[contains(@class,'date') or contains(@aria-label,'date')])[2]",
        "(//li[contains(@class,'date') or contains(@data-test,'date')])[2]",
        "(//div[contains(@class,'day')])[2]"
    ]
    for sel in possible_selectors:
        try:
            elems = driver.find_elements(By.XPATH, sel)
            if elems:
                el = elems[0]
                if el.is_displayed() and el.is_enabled():
                    try:
                        el.click()
                        time.sleep(1.5)
                        return True
                    except Exception:
                        # try JavaScript click
                        driver.execute_script("arguments[0].click();", el)
                        time.sleep(1.5)
                        return True
        except Exception:
            continue
    return False

time_regex = re.compile(r'\b(?:[01]?\d|2[0-3]):[0-5]\d\b')  # matches times like 9:30, 09:30, 18:45

def next_day_weekday_strings():
    tomorrow = datetime.now() + timedelta(days=1)
    day_full = tomorrow.strftime("%A")    # e.g., "Wednesday"
    day_short = tomorrow.strftime("%a")   # e.g., "Wed"
    # also prepare numeric date forms: "25 Nov" or "25 Nov 2025"
    date_d_m = tomorrow.strftime("%d %b")     # e.g., "25 Nov"
    date_full = tomorrow.strftime("%d %b %Y")
    return [ "tomorrow", day_full, day_short, date_d_m, date_full ]

def check_next_day_showtimes(driver, movie_url):
    """Open movie page and try several methods to show next-day showtimes."""
    driver.get(movie_url)
    time.sleep(PAGE_WAIT)

    # 1) Try clicking a button labeled "Tomorrow"
    texts = next_day_weekday_strings()
    if attempt_click_by_text(driver, ["tomorrow"]):
        time.sleep(1.5)
    else:
        # 2) Try clicking the weekday name (e.g., "Wednesday")
        if attempt_click_by_text(driver, [texts[1], texts[2]]):
            time.sleep(1.5)
        else:
            # 3) Try clicking the second date button broadly
            clicked = click_second_date_button(driver)
            if clicked:
                time.sleep(1.5)

    # 4) After attempts to select next day, try to find showtime-like patterns in visible anchors/spans
    # Gather visible text from likely containers
    candidates = driver.find_elements(By.XPATH, "//a | //button | //div | //span | //li")
    found_times = []
    for c in candidates:
        try:
            if not c.is_displayed():
                continue
            txt = c.text.strip()
            if not txt:
                continue
            # check for time patterns
            for m in time_regex.findall(txt):
                found_times.append(m)
        except Exception:
            continue

    # Deduplicate and return True if we found any showtimes
    found_times = sorted(set(found_times))
    if found_times:
        print("Found showtimes (examples):", found_times[:8])
        return True

    # 5) Fallback: check page source for time pattern
    src = driver.page_source
    if time_regex.search(src):
        print("Found showtime in page source.")
        return True

    return False

def main():
    print("Starting District.in next-day watcher for:", MOVIE_NAME)
    start_chrome_debug()
    driver = attach_selenium()

    movie_url = None
    while True:
        try:
            if not movie_url:
                print("Searching listing page for movie link...")
                movie_url = find_movie_link_from_listpage(MOVIE_NAME)
                if movie_url:
                    print("Movie link found:", movie_url)
                else:
                    print("Movie not found on listing page yet. Retrying in", REFRESH_SECONDS, "s")
                    time.sleep(REFRESH_SECONDS)
                    continue

            print("Checking movie page for next-day showtimes...")
            ok = check_next_day_showtimes(driver, movie_url)
            if ok:
                print("\n🎉 NEXT-DAY SHOWTIMES AVAILABLE! PLEASE CHECK & BOOK! 🎉")
                beep(); beep()
                break
            else:
                print("No next-day showtimes yet. Will retry in", REFRESH_SECONDS, "s")
        except Exception as e:
            print("Error:", repr(e))
            # if driver died, reattach
            try:
                driver.quit()
            except Exception:
                pass
            time.sleep(2)
            driver = attach_selenium()

        time.sleep(REFRESH_SECONDS)

if __name__ == "__main__":
    main()


