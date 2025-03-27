import csv
import re
import time
from datetime import datetime
from collections import deque  # Re-enabled for full-site crawling.
from urllib.parse import urlparse
import os

from selenium import webdriver
from selenium.webdriver.common.keys import Keys  # Correct import
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

def setup_driver():
    chrome_options = Options()
    # Uncomment the next line to run in headless mode if desired:
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver

def login(driver, username, password, login_url):
    driver.get(login_url)
    print("Opened login page...")
    try:
        login_popup_button = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "button.header-GlobalAccountFlyout-flyout-link[data-toggle='modal'][data-target='#responsive']")
            )
        )
        login_popup_button.click()
        print("Clicked login popup button, waiting for login form to appear...")
        
        username_input = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.ID, "login-username"))
        )
        username_input.clear()
        username_input.send_keys(username)
        
        password_input = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.ID, "login-password"))
        )
        password_input.clear()
        password_input.send_keys(password)
        password_input.send_keys(Keys.RETURN)
        
        print("Attempting to log in...")
        WebDriverWait(driver, 15).until(
            EC.invisibility_of_element_located((By.ID, "responsive"))
        )
        print("Login successful! The login modal has closed.")
    except Exception as e:
        try:
            error_message = driver.find_element(By.CLASS_NAME, "messages").text
            print(f"Login failed: {error_message}")
        except Exception:
            print("Login failed: Unknown error. Check credentials or site changes.")
        driver.quit()
        raise SystemExit("Exiting script due to login failure.")

def is_product_page(driver):
    """
    Returns True if the page contains both the 'product-detail-container'
    and 'title-breadcrumb' elements, indicating a product page.
    Waits for up to 5 seconds for these elements; otherwise, returns False.
    """
    try:
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".product-detail-container"))
        )
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CLASS_NAME, "title-breadcrumb"))
        )
        return True
    except Exception:
        return False

def crawl_site(driver, base_url, already_scraped=None, max_pages=5000):
    """
    Crawl the entire site starting from base_url, following only internal links.
    Skips any URL that is either in the 'already_scraped' set or matches the excluded patterns.
    Returns a list of new product page URLs.
    """
    if already_scraped is None:
        already_scraped = set()
    
    excluded_patterns = [
        "https://www.showdowndisplays.com/cdn",
        "https://www.showdowndisplays.com/Account",
        "https://www.showdowndisplays.com/Cart",
        "https://www.showdowndisplays.com/ProductSearch",
        "&navCode="
    ]
    download_extensions = [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar", ".7z", ".exe", ".tar", ".gz", ".mp3", ".mp4"]

    visited = set()
    product_urls = set()
    to_visit = deque([base_url])
    base_domain = urlparse(base_url).netloc

    while to_visit and len(visited) < max_pages:
        current_url = to_visit.popleft()
        if current_url in visited or current_url in already_scraped:
            continue
        
        if any(pattern in current_url for pattern in excluded_patterns):
            print(f"Skipping excluded URL: {current_url}")
            visited.add(current_url)
            continue
        
        if any(current_url.lower().endswith(ext) for ext in download_extensions):
            print(f"Skipping download URL: {current_url}")
            visited.add(current_url)
            continue

        print(f"Checking URL: {current_url}")
        try:
            driver.get(current_url)
        except Exception as e:
            print(f"Error loading {current_url}: {e}")
            continue
        
        visited.add(current_url)
        
        if current_url != base_url and is_product_page(driver):
            print(f"Product page found: {current_url}")
            product_urls.add(current_url)
        elif current_url == base_url:
            print(f"Base URL reached: {current_url} (not a product page, but used for gathering links)")
        else:
            print(f"Not a product page: {current_url}")
        
        try:
            links = driver.find_elements(By.TAG_NAME, "a")
            for link in links:
                href = link.get_attribute("href")
                if href:
                    if any(pattern in href for pattern in excluded_patterns):
                        continue
                    if any(href.lower().endswith(ext) for ext in download_extensions):
                        continue
                    parsed = urlparse(href)
                    if parsed.netloc == base_domain:
                        normalized = href.split("#")[0]
                        if normalized not in visited and normalized not in already_scraped:
                            to_visit.append(normalized)
        except Exception as e:
            print(f"Error extracting links from {current_url}: {e}")
    
    return list(product_urls)

def extract_product_name(driver):
    try:
        product_name_elem = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CLASS_NAME, "title-breadcrumb"))
        )
        return product_name_elem.text.strip()
    except Exception as ex:
        print("Could not retrieve product name:", ex)
        return "N/A"

def extract_product_image(driver):
    """
    Extracts the product image URL from the page.
    Looks for an element with class 'zoomWindow' and parses its style attribute.
    """
    try:
        zoom_elem = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.zoomWindow"))
        )
        style_attr = zoom_elem.get_attribute("style")
        match = re.search(r'background-image:\s*url\(["\']?(.*?)["\']?\)', style_attr)
        if match:
            return match.group(1)
        else:
            return "N/A"
    except Exception as e:
        print("Could not retrieve product image URL:", e)
        return "N/A"

def parse_price_table(driver):
    """
    Parses the pricing table from the current product page.
    Returns three lists: qty_headers, retail_prices, your_prices.
    """
    try:
        table = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "USpriceTable"))
        )
    except Exception as e:
        print("Price table not found:", e)
        return None, None, None

    try:
        header_row = table.find_element(By.TAG_NAME, "thead").find_element(By.TAG_NAME, "tr")
        # Remove "QTY" from header cell texts to keep consistency.
        header_cells = header_row.find_elements(By.TAG_NAME, "th")
        qty_headers = [cell.text.strip().replace("QTY", "").strip() for cell in header_cells][1:]
        
        tbody = table.find_element(By.TAG_NAME, "tbody")
        rows = tbody.find_elements(By.TAG_NAME, "tr")
        if len(rows) < 2:
            print("Not enough rows in the price table")
            return qty_headers, None, None

        retail_prices = [cell.text.strip() for cell in rows[0].find_elements(By.TAG_NAME, "td")][1:]
        your_prices = [cell.text.strip() for cell in rows[1].find_elements(By.TAG_NAME, "td")][1:]
        
        return qty_headers, retail_prices, your_prices
    except Exception as e:
        print("Error parsing pricing table:", e)
        return None, None, None

def read_scraped_urls(file_path):
    """Read previously scraped product URLs from the given file."""
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            urls = {line.strip() for line in f if line.strip()}
        return urls
    else:
        return set()

def update_scraped_urls(file_path, scraped_urls):
    """Update the file with the union of previously and newly scraped product URLs."""
    with open(file_path, "w", encoding="utf-8") as f:
        for url in scraped_urls:
            f.write(url + "\n")

def main():
    USERNAME = "mmcginnis@trinitydisplays.com"
    PASSWORD = "Trinity3!!"
    BASE_URL = "https://www.showdowndisplays.com/"
    
    driver = setup_driver()
    products = []  # List to hold tuples: (product_name, product_url, [row_qty, row_retail, row_your])
    processed_urls = set()  # To store all scraped URLs (from file and new ones)
    
    start_time = time.time()  # Start timing the process.
    
    # Create folder "sd" if it does not exist.
    folder_name = "sd"
    if not os.path.exists(folder_name):
        os.makedirs(folder_name)
        print(f"Folder '{folder_name}' created.")
    else:
        print(f"Folder '{folder_name}' already exists.")
    
    # Prepare CSV filepath using the current date.
    date_str = datetime.now().strftime("%-m-%-d-%y").lower()
    csv_filename = f"showdown_{date_str}.csv"
    csv_filepath = os.path.join(folder_name, csv_filename)
    
    # File that contains URLs of previously scraped products.
    scraped_file = "sd_products.txt"
    already_scraped = read_scraped_urls(scraped_file)
    print(f"Found {len(already_scraped)} previously scraped product URLs.")
    
    try:
        login(driver, USERNAME, PASSWORD, BASE_URL)
        
        # First, process previously scraped product URLs.
        for url in already_scraped:
            print(f"Processing previously scraped product URL: {url}")
            try:
                driver.get(url)
            except Exception as e:
                print(f"Error loading {url}: {e}")
                continue
            
            product_name = extract_product_name(driver)
            product_image = extract_product_image(driver)
            print(f"Product: {product_name}")
            
            qty_headers, retail_prices, your_prices = parse_price_table(driver)
            if qty_headers and retail_prices and your_prices:
                qty_headers_fixed = ["'" + q for q in qty_headers]
                row_qty = [product_name, url, product_image] + qty_headers_fixed
                row_retail = ["", "", "Retail Price"] + retail_prices
                row_your = ["", "", "Your Price"] + your_prices
                products.append((product_name, url, [row_qty, row_retail, row_your]))
                processed_urls.add(url)
            else:
                print(f"No pricing data found for product at {url}")
        
        # Save CSV with previously scraped product data before crawling for new URLs.
        if products:
            print("Saving CSV file with previously scraped products...")
            all_data = []
            for _, _, rows in products:
                all_data.extend(rows)
            with open(csv_filepath, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerows(all_data)
            print(f"CSV file saved to {csv_filepath}.")
        
        # Now, crawl the site for new product URLs while skipping already scraped ones.
        new_product_urls = crawl_site(driver, BASE_URL, already_scraped=processed_urls)
        print(f"\nFound {len(new_product_urls)} new product pages.\n")
        
        # Process each new product URL.
        for i, url in enumerate(new_product_urls, 1):
            print(f"Processing new product URL ({i}/{len(new_product_urls)}): {url}")
            try:
                driver.get(url)
            except Exception as e:
                print(f"Error loading {url}: {e}")
                continue
            
            product_name = extract_product_name(driver)
            product_image = extract_product_image(driver)
            print(f"Product: {product_name}")
            
            qty_headers, retail_prices, your_prices = parse_price_table(driver)
            if qty_headers and retail_prices and your_prices:
                qty_headers_fixed = ["'" + q for q in qty_headers]
                row_qty = [product_name, url, product_image] + qty_headers_fixed
                row_retail = ["", "", "Retail Price"] + retail_prices
                row_your = ["", "", "Your Price"] + your_prices
                products.append((product_name, url, [row_qty, row_retail, row_your]))
                processed_urls.add(url)
            else:
                print(f"No pricing data found for product at {url}")
            
            # Save intermediate CSV file after every 10 new products.
            if i % 10 == 0:
                print("Saving intermediate CSV file...")
                all_data = []
                for _, _, rows in products:
                    all_data.extend(rows)
                with open(csv_filepath, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerows(all_data)
                print(f"Intermediate data saved to {csv_filepath}")
        
        # Save final CSV file.
        print("Saving final CSV file...")
        all_data = []
        for _, _, rows in products:
            all_data.extend(rows)
        with open(csv_filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerows(all_data)
        print(f"\nPricing data saved to {csv_filepath}")
        
        # Update the scraped products file with all processed URLs.
        update_scraped_urls(scraped_file, processed_urls)
        print(f"Updated scraped URLs saved to {scraped_file}")
        
    finally:
        driver.quit()
        elapsed = time.time() - start_time
        print(f"\nProcess completed in {elapsed:.2f} seconds.")

if __name__ == "__main__":
    main()
