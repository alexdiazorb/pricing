import csv
import time
import os
import re
import itertools
from datetime import datetime
from urllib.parse import urlparse
from collections import deque

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager


# Logging helpers
def print_info(message):
    print("[INFO]", message)

def print_warning(message):
    print("[WARNING]", message)

def print_error(message):
    print("[ERROR]", message)

def setup_driver():
    chrome_options = Options()
    # Uncomment for debugging (non-headless):
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)

def login(driver, username, password, login_url, retries=5):
    for attempt in range(retries):
        driver.get(login_url)
        print_info("Opened login page...")
        try:
            username_input = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.ID, "login-email"))
            )
            username_input.clear()
            username_input.send_keys(username)
            password_input = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.ID, "login-password"))
            )
            password_input.clear()
            password_input.send_keys(password)
            password_input.send_keys(Keys.RETURN)
            print_info("Attempting to log in...")
            WebDriverWait(driver, 10).until(
                EC.invisibility_of_element_located((By.ID, "login-email"))
            )
            print_info("Login successful!")
            return True
        except Exception as e:
            print_warning(f"Login attempt {attempt+1} failed: {e}")
            time.sleep(5)  # Wait a few seconds before retrying
    print_error("All login attempts failed.")
    return False

def extract_product_name(driver):
    try:
        title_elem = WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located(
                (By.CSS_SELECTOR,
                 "div.product-details-full-main-content-mid h1.product-details-full-content-header-title, "
                 "div.product-details-full-main-content-mid h4.product-details-full-content-header-title")
            )
        )
        product_title = title_elem.text.strip()
        product_title = re.sub(r"[®™]", "", product_title).strip()
        return product_title
    except Exception as e:
        print_warning(f"Primary title extraction failed: {e}")
        try:
            fallback_elem = WebDriverWait(driver, 10).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, "li.global-views-breadcrumb-item-active"))
            )
            fallback_title = fallback_elem.text.strip()
            fallback_title = re.sub(r"[®™]", "", fallback_title).strip()
            return fallback_title
        except Exception as ex:
            print_warning(f"Fallback title extraction failed: {ex}")
            return "N/A"

def get_product_image_url(driver):
    try:
        li = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.XPATH, "//li[contains(@class, 'product-details-image-gallery-container') and not(contains(@class, 'bx-clone'))]")
            )
        )
        img = li.find_element(By.TAG_NAME, "img")
        return img.get_attribute("src")
    except Exception as e:
        print_warning(f"Product image URL extraction failed: {e}")
        return ""

def process_pricing_data(driver, url, product_name):
    try:
        container = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.quantity-pricing-expander-body-container"))
        )
        table = container.find_element(By.TAG_NAME, "table")
        tbody = table.find_element(By.TAG_NAME, "tbody")
        rows = tbody.find_elements(By.TAG_NAME, "tr")
        if rows:
            quantities = []
            prices = []
            for row in rows:
                cells = row.find_elements(By.TAG_NAME, "td")
                if len(cells) >= 2:
                    quantities.append(cells[0].text.strip())
                    prices.append(cells[1].text.strip())
            if quantities and prices:
                print_info(f"Extracted pricing table for {product_name}")
                return (quantities, prices)
        else:
            print_warning(f"Pricing table exists but is empty for {product_name}")
            try:
                total_price_element = driver.find_element(By.CSS_SELECTOR,
                    "p.total-price-lead.accessories-price-label span[data-type='updated-price']")
                total_price_text = total_price_element.text.strip()
                print_info(f"Extracted total price for {product_name}: {total_price_text}")
                return total_price_text
            except Exception as e:
                print_warning(f"Failed to extract total price for {product_name}: {e}")
    except Exception as e:
        print_warning(f"No valid pricing table found for {product_name} or error: {e}")
    
    try:
        price_element = WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, "span.product-price"))
        )
        single_price = price_element.text.strip()
        print_info(f"Extracted fallback price for {product_name}: {single_price}")
        return single_price
    except Exception as e:
        print_warning(f"Failed to extract price for {product_name} at {url}: {e}")
        return "N/A"

def is_product_page(driver):
    current_url = driver.current_url
    if "?" in current_url:
        print_info("URL contains '?' - not a product page.")
        return False
    if "/newReview" in current_url:
        print_info("URL contains '/newReview' - not a product page.")
        return False
    if "?display=" in current_url.lower():
        print_info("URL contains '?display=' - not a product page.")
        return False
    exclusion_ids = ["facet-browse", "cms-landing-page", "home-page"]
    for eid in exclusion_ids:
        try:
            WebDriverWait(driver, 3).until(
                EC.presence_of_element_located((By.ID, eid))
            )
            print_info(f"Exclusion element with id '{eid}' found. Not a product page.")
            return False
        except TimeoutException:
            pass
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "ProductDetails.Full.View"))
        )
        return True
    except TimeoutException:
        return False

def is_logged_in(driver):
    try:
        WebDriverWait(driver, 3).until(
            EC.presence_of_element_located((By.CLASS_NAME, "header-profile-welcome-link"))
        )
        print_info("User is logged in (welcome link found).")
        return True
    except TimeoutException:
        print_info("Welcome link not found - user is not logged in.")
        return False

def crawl_site(driver, base_url, max_pages=10000, skip_urls=None):
    excluded_patterns = [
        "https://www.wsdisplay.com/cart",
        "https://www.wsdisplay.com/webstore",
        "https://www.wsdisplay.com/webs-tore",
        "https://www.wsdisplay.com/search?",
        "#"
    ]
    download_extensions = [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar", ".7z", ".exe", ".tar", ".gz", ".mp3", ".mp4", ".dwg"]

    if skip_urls is None:
        skip_urls = set()

    visited = set()
    product_urls = set()
    to_visit = deque([base_url])
    base_domain = urlparse(base_url).netloc

    while to_visit and len(visited) < max_pages:
        current_url = to_visit.popleft()
        if current_url in visited:
            continue
        if any(pattern in current_url for pattern in excluded_patterns) or \
           any(current_url.lower().endswith(ext) for ext in download_extensions) or "?display=" in current_url.lower():
            print_info(f"Skipping excluded/download URL: {current_url}")
            visited.add(current_url)
            continue

        print_info(f"Checking URL: {current_url}")
        try:
            driver.get(current_url)
        except Exception as e:
            print_warning(f"Error loading {current_url}: {e}")
            continue
        visited.add(current_url)
        # Only add if it is a product page and not already scraped
        if current_url != base_url and is_product_page(driver) and current_url not in skip_urls:
            print_info(f"Product page found: {current_url}")
            product_urls.add(current_url)
        elif current_url == base_url:
            print_info(f"Base URL reached: {current_url} (used for gathering links)")
        else:
            print_info(f"Not a product page: {current_url}")
        
        if ("/newReview" in current_url) or ("?display=" in current_url.lower()):
            print_info("Skipping link extraction for current URL due to '/newReview' or '?display='.")
            continue
        
        try:
            href_list = driver.execute_script(
                "return Array.from(document.querySelectorAll('a'))"
                ".filter(a => !a.closest('div[data-view=\"Facets.FacetedNavigationItems\"]'))"
                ".map(a => a.href);"
            )
            for href in href_list:
                if any(pattern in href for pattern in excluded_patterns):
                    continue
                if any(href.lower().endswith(ext) for ext in download_extensions):
                    continue
                if "?display=" in href.lower():
                    continue
                parsed = urlparse(href)
                if parsed.netloc == base_domain:
                    normalized = href.split("#")[0]
                    if normalized not in visited and normalized not in skip_urls:
                        to_visit.append(normalized)
            print_info(f"Finished extracting links from {current_url}. {len(to_visit)} URLs left to crawl.")
        except Exception as e:
            print_warning(f"Error extracting links from {current_url}: {e}")
    
    print_info(f"Finished crawling. URLs crawled: {len(visited)}, Product pages found: {len(product_urls)}")
    return list(product_urls)

def fix_qty_value(qty):
    if re.match(r"^\d+\s*-\s*\d+$", qty):
        return "'" + qty.replace(" ", "")
    return qty

def generate_final_rows(option_data):
    # Fix quantity values for each entry
    for entry in option_data:
        entry['qtys'] = [fix_qty_value(q) for q in entry['qtys']]
    max_qty_cols = max((len(entry['qtys']) for entry in option_data if entry['qtys']), default=1)
    final_rows = []
    for entry in option_data:
        prod = entry['product']
        option_text = entry['option'].strip() if entry['option'].strip() else "N/A"
        qtys = entry['qtys'] + [""] * (max_qty_cols - len(entry['qtys']))
        prices = entry['prices'] + [""] * (max_qty_cols - len(entry['prices']))
        if prices:
            if entry['first']:
                row_qty = [prod[0], prod[1], prod[2], option_text] + qtys
            else:
                row_qty = ["", "", "", option_text] + qtys
            row_price = ["", "", "", ""] + prices
            final_rows.extend([row_qty, row_price])
        else:
            if entry['first']:
                row = [prod[0], prod[1], prod[2], option_text] + qtys + [""] * max_qty_cols
            else:
                row = ["", "", "", option_text] + qtys + [""] * max_qty_cols
            final_rows.append(row)
    return final_rows

def save_csv(option_data, csv_filename):
    final_rows = generate_final_rows(option_data)
    with open(csv_filename, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(final_rows)
    print_info(f"Incremental save complete. Data written to {csv_filename}")

def read_known_urls(file_path):
    """Read previously scraped product URLs from a text file."""
    known = set()
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                url = line.strip()
                if url:
                    known.add(url)
        print_info(f"Loaded {len(known)} known URLs from {file_path}.")
    else:
        print_warning(f"File {file_path} not found. Proceeding without known URLs.")
    return known

def update_known_urls(file_path, new_urls):
    """Append new product URLs to the known URLs file."""
    if new_urls:
        with open(file_path, "a", encoding="utf-8") as f:
            for url in new_urls:
                f.write(url + "\n")
        print_info(f"Added {len(new_urls)} new URLs to {file_path}.")

def process_product_page(driver, url, option_data, username, password, login_url):
    """Scrape product data from a single product page."""
    print_info(f"Processing product URL: {url}")
    if not is_logged_in(driver):
        print_info("User is logged out, logging in now.")
        if not login(driver, username, password, login_url):
            print_error("Skipping product due to login failure.")
            return
    try:
        driver.get(url)
    except Exception as e:
        print_warning(f"Error accessing {url}: {e}")
        return
    try:
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    except TimeoutException:
        print_warning(f"Body did not load for {url}, skipping")
        return

    product_name = extract_product_name(driver)
    image_url = get_product_image_url(driver)
    product_details = (product_name, url, image_url)
    
    dropdown_elems = driver.find_elements(By.CSS_SELECTOR, ".product-details-options-selector-option-container .product-views-option-dropdown-select")
    if dropdown_elems and len(dropdown_elems) > 1:
        options_lists = []
        for dropdown in dropdown_elems:
            select_obj = Select(dropdown)
            valid_opts = [(opt.get_attribute("value").strip(), opt.text.strip())
                          for opt in select_obj.options
                          if opt.get_attribute("value").strip() and opt.text.strip() != "- Select -" and not opt.get_attribute("disabled")]
            options_lists.append(valid_opts)
        all_combinations = list(itertools.product(*options_lists))
        dropdown_ids = [dropdown.get_attribute("id") for dropdown in dropdown_elems]
        first_option = True
        for combo in all_combinations:
            valid_combo = True
            for j, (val, txt) in enumerate(combo):
                try:
                    dropdown = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.ID, dropdown_ids[j]))
                    )
                except Exception as e:
                    print_warning(f"Could not re-find dropdown with id {dropdown_ids[j]}: {e}")
                    valid_combo = False
                    break
                select_obj = Select(dropdown)
                try:
                    select_obj.select_by_value(val)
                except Exception as e:
                    print_warning(f"Could not select option {txt} for {product_name}: {e}")
                    valid_combo = False
                    break
            if not valid_combo:
                continue
            time.sleep(2)
            pricing_data = process_pricing_data(driver, url, product_name)
            if isinstance(pricing_data, tuple):
                qtys, prices = pricing_data
            else:
                qtys, prices = [pricing_data], []
            option_combo_text = ", ".join([txt for (val, txt) in combo])
            option_data.append({
                'product': product_details,
                'option': option_combo_text,
                'qtys': qtys,
                'prices': prices,
                'first': first_option
            })
            first_option = False
    else:
        option_list = []
        try:
            select_elem = driver.find_element(By.CSS_SELECTOR, ".product-details-options-selector-option-container .product-views-option-dropdown-select")
            select_obj = Select(select_elem)
            option_list = [(opt.get_attribute("value").strip(), opt.text.strip())
                           for opt in select_obj.options
                           if opt.get_attribute("value").strip() and opt.text.strip() != "- Select -" and not opt.get_attribute("disabled")]
        except Exception as e:
            print_warning(f"No selectable options found for {product_name}: {e}")
        if option_list:
            first_option = True
            for opt_value, opt_text in option_list:
                select_elem = driver.find_element(By.CSS_SELECTOR, ".product-details-options-selector-option-container .product-views-option-dropdown-select")
                select_obj = Select(select_elem)
                try:
                    select_obj.select_by_value(opt_value)
                except Exception as e:
                    print_warning(f"Could not select option {opt_text} for {product_name}: {e}")
                    continue
                time.sleep(2)
                pricing_data = process_pricing_data(driver, url, product_name)
                if isinstance(pricing_data, tuple):
                    qtys, prices = pricing_data
                else:
                    qtys, prices = [pricing_data], []
                option_data.append({
                    'product': product_details,
                    'option': opt_text,
                    'qtys': qtys,
                    'prices': prices,
                    'first': first_option
                })
                first_option = False
        else:
            pricing_data = process_pricing_data(driver, url, product_name)
            if isinstance(pricing_data, tuple):
                qtys, prices = pricing_data
            else:
                qtys, prices = [pricing_data], []
            option_data.append({
                'product': product_details,
                'option': "N/A",
                'qtys': qtys,
                'prices': prices,
                'first': True
            })

def main():
    USERNAME = "mmcginnis@trinitydisplays.com"
    PASSWORD = "signs123"
    LOGIN_URL = "https://www.wsdisplay.com/webstore/checkout.ssp?is=login&login=T&fragment=login-register#login-register"
    BASE_URL = "https://www.wsdisplay.com/"

    driver = setup_driver()
    option_data = []
    start_time = time.time()

    # Setup output folder and CSV filename for incremental saving.
    folder_name = "ws"
    if not os.path.exists(folder_name):
        os.makedirs(folder_name)
        print_info(f"Folder '{folder_name}' created.")
    else:
        print_info(f"Folder '{folder_name}' exists.")
    timestamp = datetime.now().strftime("%-m-%-d-%y")
    csv_filename = os.path.join(folder_name, f"wsdisplay_{timestamp}.csv")
    known_urls_file = "ws_products.txt"

    try:
        # Read known product URLs from file.
        known_urls = read_known_urls(known_urls_file)

        # Process known product URLs first.
        if known_urls:
            print_info("Starting to process known product URLs...")
            for i, url in enumerate(known_urls):
                print_info(f"Processing known product URL ({i+1}/{len(known_urls)}).")
                process_product_page(driver, url, option_data, USERNAME, PASSWORD, LOGIN_URL)
                # Incremental save every 10 products.
                if (i + 1) % 10 == 0:
                    save_csv(option_data, csv_filename)
            # Save CSV after processing known URLs.
            save_csv(option_data, csv_filename)
        else:
            print_info("No known product URLs found. Skipping this step.")

        # Now crawl the site for new product URLs, skipping those already scraped.
        print_info("Starting site crawl for new product URLs...")
        product_urls = crawl_site(driver, BASE_URL, skip_urls=known_urls)
        print_info(f"Crawl complete. Found {len(product_urls)} product URLs.")

        # Process only new URLs (exclude any that were in the known list).
        new_product_urls = [url for url in product_urls if url not in known_urls]
        print_info(f"Found {len(new_product_urls)} new product URLs after filtering known URLs.")

        # Append the new product URLs to the known URLs file.
        update_known_urls(known_urls_file, new_product_urls)

        total_products = len(new_product_urls)
        for i, url in enumerate(new_product_urls):
            remaining = total_products - i - 1
            print_info(f"Processing new product URL ({i+1}/{total_products}); {remaining} remaining.")
            process_product_page(driver, url, option_data, USERNAME, PASSWORD, LOGIN_URL)
            if (i + 1) % 10 == 0:
                save_csv(option_data, csv_filename)

        # Final save after processing all products.
        save_csv(option_data, csv_filename)
        print_info(f"Final product data saved to {csv_filename}")
    finally:
        driver.quit()
        elapsed = time.time() - start_time
        print_info(f"Process completed in {elapsed:.2f} seconds.")

if __name__ == "__main__":
    main()
