import csv
import re
import time
import itertools
from datetime import datetime
from collections import deque
from urllib.parse import urlparse
import os

from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    ElementClickInterceptedException,
    WebDriverException
)
from webdriver_manager.chrome import ChromeDriverManager

MAX_RETRIES = 5
RETRY_DELAY = 5    # seconds
INTERIM_SAVE_EVERY = 10  # products

def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--window-size=1920,1080")
    return webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=chrome_options
    )

def wait_for_full_load(driver, timeout=15):
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )
    WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )

def load_page_with_retry(driver, url):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            driver.get(url)
            wait_for_full_load(driver)
            return
        except WebDriverException as e:
            print(f"[Attempt {attempt}/{MAX_RETRIES}] Error loading {url}: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
            else:
                raise SystemExit(f"Failed to load {url} after {MAX_RETRIES} attempts.")

def login(driver, username, password, login_url):
    load_page_with_retry(driver, login_url)
    print("Opened login page...")
    user = WebDriverWait(driver, 15).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, 'input[name="email"]'))
    )
    user.clear(); user.send_keys(username)
    pw = WebDriverWait(driver, 15).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, 'input[name="password"]'))
    )
    pw.clear(); pw.send_keys(password); pw.send_keys(Keys.RETURN)
    WebDriverWait(driver, 15).until(
        EC.invisibility_of_element_located((By.ID, "responsive"))
    )
    time.sleep(3)
    wait_for_full_load(driver)
    print("Login successful!")

def is_product_page(driver):
    try:
        WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.ID, "item-view-title")))
        WebDriverWait(driver, 5).until(EC.presence_of_element_located(
            (By.XPATH, "//div[starts-with(@class,'_subtotal_')]")
        ))
        return True
    except TimeoutException:
        return False

def crawl_site(driver, base_url, already_scraped=None, max_pages=5000):
    if already_scraped is None:
        already_scraped = set()
    excluded = [
        "https://www.b2sign.com/user",
        "https://www.b2sign.com/downloadable",
        "https://www.b2sign.com/item/download",
        "https://www.b2sign.com/template-user-guide",
		"https://www.b2sign.com/aluminum-sign",
		"https://www.b2sign.com/reflective-aluminum-sign",
		"https://www.b2sign.com/dry-erase-pvc-board",
		"https://www.b2sign.com/coroplast",
		"https://www.b2sign.com/dry-erase-foamcore",
		"https://www.b2sign.com/reflective-aluminum-sandwich-board",
		"https://www.b2sign.com/dry-erase-magnet",
		"https://www.b2sign.com/reflective-car-magnet",
		"https://www.b2sign.com/reflective-coroplast",
		"https://www.b2sign.com/canvas-wrap",
		"https://www.b2sign.com/pole-banner-set",
		"https://www.b2sign.com/foamcore",
		"https://www.b2sign.com/dry-erase-coroplast",
		"https://www.b2sign.com/pvc-board",
		"https://www.b2sign.com/dry-erase-aluminum-sandwich-board",
		"https://www.b2sign.com/aluminum-sandwich-board"
    ]
    ext_skip = [
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar", ".7z", ".exe",
        ".tar", ".gz", ".mp3", ".mp4", ".png"
    ]

    visited = set()
    products = set()
    queue = deque([base_url])
    domain = urlparse(base_url).netloc

    while queue and len(visited) < max_pages:
        raw = queue.popleft()
        url = raw.split('?', 1)[0]  # strip any query-string

        # skip unwanted URLs based on the *normalized* URL
        if (
            url in visited
            or url in already_scraped
            or any(url.lower().endswith(ext) for ext in ext_skip)
            or any(ex in url for ex in excluded)
        ):
            visited.add(url)
            continue

        print(f"Crawling: {url} | Pages left: {len(queue)} | Products found: {len(products)}")
        try:
            load_page_with_retry(driver, url)
        except SystemExit:
            print(f"Skipping {url} after failed attempts.")
            visited.add(url)
            continue

        visited.add(url)
        if url != base_url and is_product_page(driver):
            products.add(url)

        # find and enqueue internal links, canonicalizing each
        for a in driver.find_elements(By.TAG_NAME, "a"):
            href = a.get_attribute("href") or ""
            if urlparse(href).netloc == domain:
                clean = href.split('#')[0].split('?', 1)[0]
                if clean not in visited and clean not in already_scraped:
                    queue.append(clean)

    return list(products)

def extract_product_name(driver):
    elt = WebDriverWait(driver, 15).until(
        EC.visibility_of_element_located((By.ID, "item-view-title"))
    )
    text = elt.text.strip()
    if not text:
        raise ValueError("Empty product name")
    return text

def extract_product_image(driver):
    img = WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, 'div[class^="_image_"] img'))
    )
    return img.get_attribute("src") or "N/A"

def parse_price_table(driver):
    locator = (By.XPATH, "//div[starts-with(@class,'_subtotal_')]")
    try:
        WebDriverWait(driver, 20, poll_frequency=1).until(
            EC.text_to_be_present_in_element(locator, "$")
        )
        div = driver.find_element(*locator)
        num = re.sub(r'[^0-9.]', '', div.text.strip())
        return float(num) if num else None
    except TimeoutException:
        print("Could not parse price within 20s on", driver.current_url)
        return None

def get_attribute_options(driver):
    options_map = {}
    try:
        cont = driver.find_element(By.CSS_SELECTOR, 'div[class^="_attributes_"]')
    except NoSuchElementException:
        return options_map

    attrs = cont.find_elements(By.XPATH, "./div[starts-with(@class,'_attribute_')]")
    for attr in attrs:
        try:
            name = attr.find_element(By.CSS_SELECTOR, "label span").text.strip()
        except NoSuchElementException:
            raw_id = attr.get_attribute("id") or ""
            name = raw_id.replace("attr-", "").replace("-", " ").replace("_", " ").title()

        vals = []
        # button-group items
        for it in attr.find_elements(By.CSS_SELECTOR, "div[class*='_button_'] div[class*='_item_']"):
            t = it.text.strip()
            if t and t not in vals:
                vals.append(t)
        if vals:
            options_map[name] = vals
            continue

        # MUI selects
        for sc in attr.find_elements(By.CSS_SELECTOR, "div._select_1un5z_155"):
            try:
                btn = WebDriverWait(sc, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "button[role='combobox']"))
                )
                controls = btn.get_attribute("aria-controls")
                driver.execute_script("arguments[0].scrollIntoView(true);", btn)
                driver.execute_script("arguments[0].click();", btn)

                try:
                    r = btn.find_element(By.CSS_SELECTOR, "div[class*='_rich-text_'] p").text.strip()
                    curr = re.sub(r"\s*\(.*\)$", "", r).strip()
                except NoSuchElementException:
                    curr = btn.text.strip()
                if curr and not curr.lower().startswith("please select") and curr not in vals:
                    vals.append(curr)

                ul = WebDriverWait(driver, 10).until(
                    EC.visibility_of_element_located((By.ID, controls))
                )
                for li in ul.find_elements(By.CSS_SELECTOR, "li[role='option']"):
                    try:
                        r = li.find_element(By.CSS_SELECTOR, "div[class*='_rich-text_'] p").text.strip()
                        txt = re.sub(r"\s*\(.*\)$", "", r).strip()
                    except NoSuchElementException:
                        txt = li.text.strip()
                    if txt and not txt.lower().startswith("please select") and txt not in vals:
                        vals.append(txt)

                btn.send_keys(Keys.ESCAPE)
                driver.execute_script("document.body.click();")
                time.sleep(0.3)
            except TimeoutException:
                continue

        # static-text fallback
        for d in attr.find_elements(By.CSS_SELECTOR, "div._static_1un5z_75 div"):
            t = d.text.strip()
            if t and t not in vals:
                vals.append(t)

        if vals:
            options_map[name] = vals

    return options_map

def set_attribute(driver, name, value):
    slug = name.lower().replace(" ", "_")
    xpath_attr = (
        f"//div[starts-with(@class,'_attribute_') and "
        f"(.//label/span[normalize-space()='{name}'] or contains(@id,'{slug}'))]"
    )
    try:
        attr = driver.find_element(By.XPATH, xpath_attr)
    except NoSuchElementException:
        print(f"Attribute block not found for '{name}', skipping")
        return

    # button-group
    for it in attr.find_elements(By.CSS_SELECTOR, "div[class*='_button_'] div[class*='_item_']"):
        if it.text.strip() == value:
            driver.execute_script("arguments[0].scrollIntoView(true);", it)
            driver.execute_script("arguments[0].click();", it)
            time.sleep(1)
            return

    # MUI selects
    for sc in attr.find_elements(By.CSS_SELECTOR, "div._select_1un5z_155"):
        try:
            btn = WebDriverWait(sc, 5).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button[role='combobox']"))
            )
            ctr = btn.get_attribute("aria-controls")
            driver.execute_script("arguments[0].scrollIntoView(true);", btn)
            driver.execute_script("arguments[0].click();", btn)

            ul = WebDriverWait(driver, 5).until(
                EC.visibility_of_element_located((By.ID, ctr))
            )
            for li in ul.find_elements(By.CSS_SELECTOR, "li[role='option']"):
                try:
                    r = li.find_element(By.CSS_SELECTOR, "div[class*='_rich-text_'] p").text.strip()
                    txt = re.sub(r"\s*\(.*\)$", "", r).strip()
                except NoSuchElementException:
                    txt = li.text.strip()
                if txt == value:
                    driver.execute_script("arguments[0].click();", li)
                    time.sleep(1)
                    return

            btn.send_keys(Keys.ESCAPE)
            driver.execute_script("document.body.click();")
            time.sleep(0.3)
        except (TimeoutException, ElementClickInterceptedException):
            try:
                btn.send_keys(Keys.ESCAPE)
                driver.execute_script("document.body.click();")
            except:
                pass
            time.sleep(0.3)
            continue

def write_csv(rows, path):
    grouped = []
    last = None
    for prod, url, img, opts, price in rows:
        if prod != last:
            grouped.append([prod, url, img, opts, price])
            last = prod
        else:
            grouped.append(['', '', '', opts, price])
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(["Product", "URL", "Image", "Options", "Price"])
        w.writerows(grouped)

def main():
    USERNAME = "PATRICK@ORBUS.COM"
    PASSWORD = "orbus"
    BASE_URL = "https://www.b2sign.com/"
    SCRAPED_FILE = "b2_products.txt"

    # load all existing URLs
    initial = []
    if os.path.exists(SCRAPED_FILE):
        with open(SCRAPED_FILE) as f:
            initial = f.read().splitlines()
    processed = set(initial)

    driver = setup_driver()
    all_rows = []
    os.makedirs("b2", exist_ok=True)
    date_str = datetime.now().strftime("%-m-%-d-%y").lower()
    csv_path = os.path.join("b2", f"b2_{date_str}.csv")

    product_count = 0
    new_count = 0
    batch_new = []

    try:
        login(driver, USERNAME, PASSWORD, BASE_URL)

        # SCRAPE EXISTING
        print(f"Processing {len(initial)} existing pages...")
        for idx, url in enumerate(initial, start=1):
            print(f" [{idx}/{len(initial)}] {url}")
            load_page_with_retry(driver, url)

            # skip if attribute container has an input.MuiInput-input
            if driver.find_elements(By.CSS_SELECTOR, 'div[class^="_attributes_"] input.MuiInput-input'):
                print(f"  Skipping {url} (found input.MuiInput-input in attributes)")
                continue

            # attempt to extract name, skip if fails
            try:
                name = extract_product_name(driver)
            except Exception:
                print(f"  Skipping {url} (could not extract product name)")
                continue

            img = extract_product_image(driver)
            attrs = get_attribute_options(driver)
            seen = set()

            if not attrs:
                print("    Scraping default price")
                price = parse_price_table(driver)
                all_rows.append([name, url, img, "", price or ""])
            else:
                for combo in itertools.product(*attrs.values()):
                    opt_str = "; ".join(f"{n}: {v}" for n, v in zip(attrs.keys(), combo))
                    if opt_str in seen:
                        continue
                    seen.add(opt_str)
                    print(f"    Scraping combination: {opt_str}")
                    for n, v in zip(attrs.keys(), combo):
                        set_attribute(driver, n, v)
                    price = parse_price_table(driver)
                    all_rows.append([name, url, img, opt_str, price or ""])

            product_count += 1
            if product_count % INTERIM_SAVE_EVERY == 0:
                print(f"--- Saving interim CSV after {product_count} products ---")
                write_csv(all_rows, csv_path)

        # CRAWL + SCRAPE NEW
        print("Crawling for new product pages…")
        new_urls = crawl_site(driver, BASE_URL, already_scraped=processed, max_pages=5000)
        print(f"Found {len(new_urls)} new pages to scrape.")
        for idx, url in enumerate(new_urls, start=1):
            print(f" [{idx}/{len(new_urls)}] {url}")
            load_page_with_retry(driver, url)

            # skip if attribute container has an input.MuiInput-input
            if driver.find_elements(By.CSS_SELECTOR, 'div[class^="_attributes_"] input.MuiInput-input'):
                print(f"  Skipping {url} (found input.MuiInput-input in attributes)")
                processed.add(url)
                batch_new.append(url)
                new_count += 1
                continue

            try:
                name = extract_product_name(driver)
            except Exception:
                print(f"  Skipping {url} (could not extract product name)")
                processed.add(url)
                batch_new.append(url)
                new_count += 1
                continue

            img = extract_product_image(driver)
            attrs = get_attribute_options(driver)
            seen = set()

            if not attrs:
                print("    Scraping default price")
                price = parse_price_table(driver)
                all_rows.append([name, url, img, "", price or ""])
            else:
                for combo in itertools.product(*attrs.values()):
                    opt_str = "; ".join(f"{n}: {v}" for n, v in zip(attrs.keys(), combo))
                    if opt_str in seen:
                        continue
                    seen.add(opt_str)
                    print(f"    Scraping combination: {opt_str}")
                    for n, v in zip(attrs.keys(), combo):
                        set_attribute(driver, n, v)
                    price = parse_price_table(driver)
                    all_rows.append([name, url, img, opt_str, price or ""])

            processed.add(url)
            batch_new.append(url)
            new_count += 1
            product_count += 1

            if new_count % 10 == 0:
                print(f"--- Appending {len(batch_new)} new URLs to {SCRAPED_FILE} ---")
                with open(SCRAPED_FILE, "a", encoding="utf-8") as f:
                    for u in batch_new:
                        f.write(u + "\n")
                batch_new.clear()

            if product_count % INTERIM_SAVE_EVERY == 0:
                print(f"--- Saving interim CSV after {product_count} products ---")
                write_csv(all_rows, csv_path)

        # FINAL SAVE CSV
        write_csv(all_rows, csv_path)
        print(f"Saved final CSV with {len(all_rows)} rows to {csv_path}")

        # append any leftover new URLs
        if batch_new:
            with open(SCRAPED_FILE, "a", encoding="utf-8") as f:
                for u in batch_new:
                    f.write(u + "\n")

    finally:
        driver.quit()

if __name__ == "__main__":
    main()
