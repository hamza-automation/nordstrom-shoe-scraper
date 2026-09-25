import argparse
import json
import logging
import os
import re
import subprocess
import time
import csv
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import pandas as pd
from playwright.sync_api import sync_playwright

BASE_URL = "https://www.nordstrom.com"
DEFAULT_URL = "https://www.nordstrom.com/browse/men/shoes"
OUTPUT_CSV = "nordstrom_catalog.csv"
OUTPUT_JSON = "nordstrom_catalog.json"
LOG_FILE = "nordstrom_scraper.log"

DISPLAY_COLUMNS = {
    "brand": "Brand",
    "model": "Model",
    "price_min": "Price Min ($)",
    "price_max": "Price Max ($)",
    "is_on_sale": "On Sale",
    "rating": "Rating",
    "review_count": "Reviews",
    "product_url": "Product URL",
    "scraped_at": "Scraped At",
}
ALL_FIELDS = list(DISPLAY_COLUMNS.keys())


def setup_logging():
    logger = logging.getLogger("nordstrom_scraper")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    fh = logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger


log = setup_logging()


def find_chrome_executable() -> str:
    paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
    ]
    for p in paths:
        if os.path.exists(p):
            return p
    raise FileNotFoundError("Google Chrome was not found in standard paths.")


def launch_native_chrome(start_url: str):
    chrome_path = find_chrome_executable()
    profile_dir = os.path.abspath("./chrome_nordstrom_profile")
    cmd = [
        chrome_path,
        "--remote-debugging-port=9222",
        f"--user-data-dir={profile_dir}",
        start_url,
    ]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3.0)


# ===========================================================================
# 1. SCROLL & LAZY LOAD HYDRATION
# ===========================================================================

def dismiss_popups(page):
    popups = [
        "#onetrust-accept-btn-handler",
        "button[aria-label='Close']",
        "button[aria-label='close']",
    ]
    for sel in popups:
        try:
            btn = page.locator(sel).first
            if btn.count() > 0 and btn.is_visible():
                btn.click()
                page.wait_for_timeout(300)
        except Exception:
            pass


def hydrate_grid(page, rounds: int = 5):
    """Progressively scrolls down so virtualized product cards mount in DOM."""
    log.info("Hydrating product grid with smooth scroll...")
    for _ in range(rounds):
        page.evaluate("window.scrollBy({top: 900, behavior: 'smooth'});")
        page.wait_for_timeout(800)
    page.wait_for_timeout(1000)


# ===========================================================================
# 2. IN-BROWSER PRODUCT EXTRACTION (NATIVE JS — ZERO SYNTAX BUGS)
# ===========================================================================

def harvest_products_from_page(page) -> List[Dict]:
    now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    raw_products = page.evaluate("""() => {
        const results = [];
        const seenUrls = new Set();

        // Target cards specifically
        const cards = document.querySelectorAll("article, div[data-test*='product']");

        for (const card of cards) {
            // Find the link that contains the product name (exclude thumbnail image anchors)
            const textLink = card.querySelector("h3 a[href*='/s/'], h4 a[href*='/s/'], a[href*='/s/']:not(:has(img))") 
                          || card.querySelector("a[href*='/s/']");

            if (!textLink) continue;

            const href = textLink.getAttribute("href");
            if (!href || seenUrls.has(href)) continue;
            seenUrls.add(href);

            // 1. Clean Brand
            let brand = "Nordstrom";
            const brandEl = card.querySelector("strong, h3, [class*='brand']");
            if (brandEl && brandEl.innerText.trim().length < 40) {
                brand = brandEl.innerText.trim();
            }

            // 2. Clean Model Name (strip all newlines and badges)
            let model = textLink.innerText || "";
            // Replace any newlines with spaces immediately in browser memory
            model = model.replace(/[\\r\\n\\t]+/g, " ").trim();

            if (!model || model.toLowerCase() === brand.toLowerCase()) {
                const titleEl = card.querySelector("h4, h3, span[class*='title']");
                if (titleEl) model = titleEl.innerText.replace(/[\\r\\n\\t]+/g, " ").trim();
            }
            if (!model) model = "Men's Shoe";

            // 3. Price
            let priceText = null;
            const allElements = card.querySelectorAll("span, div");
            for (const el of allElements) {
                if (el.children.length === 0 && el.innerText.includes("$")) {
                    priceText = el.innerText.replace(/[\\r\\n\\t]+/g, " ").trim();
                    break;
                }
            }

            // 4. Rating
            let rating = null;
            const ratEl = card.querySelector("[aria-label*='stars'], [aria-label*='out of 5']");
            if (ratEl) {
                const label = ratEl.getAttribute("aria-label") || "";
                const m = label.match(/([0-5]\\.?\\d*)/);
                if (m) rating = m[1];
            }

            // 5. Review Count
            let reviewCount = 0;
            const revEl = card.querySelector("[aria-label*='review'], [aria-label*='Review']");
            if (revEl) {
                const label = revEl.getAttribute("aria-label") || revEl.innerText || "";
                const m = label.match(/\\d[\\d,]*/);
                if (m) reviewCount = m[0].replace(/,/g, "");
            } else {
                for (const el of allElements) {
                    if (el.children.length === 0 && /^\\([\\d,]+\\)$/.test(el.innerText.trim())) {
                        reviewCount = el.innerText.replace(/[^\\d]/g, "");
                        break;
                    }
                }
            }

            results.push({
                brand: brand,
                model: model,
                price_raw: priceText,
                rating: rating,
                review_count: reviewCount,
                path: href
            });
        }

        return results;
    }""")

    normalized = []
    for item in raw_products:
        p_min, p_max, is_sale = None, None, False
        raw_p = item.get("price_raw")
        if raw_p:
            clean_p = raw_p.replace("–", "-").replace("$", "").replace(",", "").strip()
            is_sale = any(k in raw_p.lower() for k in ["sale", "now", "was", "off", "clearance"])
            nums = re.findall(r"\b\d+\.?\d*\b", clean_p)
            if nums:
                try:
                    f_nums = [float(n) for n in nums]
                    p_min = min(f_nums)
                    p_max = max(f_nums)
                except Exception:
                    pass

        rat = float(item["rating"]) if item.get("rating") else None
        revs = int(item["review_count"]) if item.get("review_count") else 0
        full_url = urljoin(BASE_URL, item["path"].split("?")[0])

        # Clean model string: Remove any accidental line breaks or carriage returns
        clean_model = re.sub(r"[\r\n\t]+", " ", str(item["model"]))
        clean_model = re.sub(r"\s+", " ", clean_model).strip()

        clean_brand = re.sub(r"[\r\n\t]+", " ", str(item["brand"]))
        clean_brand = re.sub(r"\s+", " ", clean_brand).title().strip()

        normalized.append({
            "brand": clean_brand,
            "model": clean_model,
            "price_min": p_min,
            "price_max": p_max,
            "is_on_sale": is_sale,
            "rating": rat,
            "review_count": revs,
            "product_url": full_url,
            "scraped_at": now_ts,
        })

    return normalized



# ===========================================================================
# 3. PAGINATION
# ===========================================================================

def build_page_url(base_url: str, page_number: int) -> str:
    parsed = urlparse(base_url)
    qs = parse_qs(parsed.query)
    qs["page"] = [str(page_number)]
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{urlencode(qs, doseq=True)}"


def navigate_to_next_page(page, current_page: int, start_url: str) -> bool:
    dismiss_popups(page)
    next_selectors = [
        "a[href*='page=']:has(svg[data-testid*='ChevronRight'])",
        "a[rel='next']",
        "a[aria-label='Next Page']",
    ]

    for sel in next_selectors:
        try:
            btn = page.locator(sel).first
            if btn.count() > 0 and btn.is_visible():
                btn.click()
                page.wait_for_timeout(3500)
                return True
        except Exception:
            pass

    # Direct URL page param fallback
    next_url = build_page_url(start_url, current_page + 1)
    log.info("Direct pagination fallback: %s", next_url)
    try:
        page.goto(next_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)
        return True
    except Exception as e:
        log.error("Failed navigating to page %s: %s", current_page + 1, e)
        return False


# ===========================================================================
# 4. EXPORT
# ===========================================================================


def clean_and_export(catalog: List[Dict]):
    if not catalog:
        log.warning("No products captured to export.")
        return

    df = pd.DataFrame(catalog)
    for col in ALL_FIELDS:
        if col not in df.columns:
            df[col] = None

    # 1. Deduplicate by unique product URL
    df = df.drop_duplicates(subset=["product_url"], keep="first").copy()

    # 2. Clean Text Columns (strip newlines, tabs, and duplicate spaces)
    for col in ["brand", "model"]:
        df[col] = (
            df[col]
            .astype(str)
            .str.replace(r"[\r\n\t]+", " ", regex=True)
            .str.replace(r"\s+", " ", regex=True)
            .str.strip()
            .replace({"None": "Nordstrom", "nan": "Nordstrom", "": "Nordstrom"})
        )

    # 3. Format Currency ($XX.XX or N/A)
    def format_price(val):
        if pd.isna(val) or val is None or str(val).lower() in ["nan", "none", ""]:
            return "N/A"
        try:
            return f"${float(val):,.2f}"
        except (ValueError, TypeError):
            return "N/A"

    df["price_min"] = df["price_min"].apply(format_price)
    df["price_max"] = df["price_max"].apply(format_price)

    # 4. Format Sale Status ("Yes" / "No")
    df["is_on_sale"] = df["is_on_sale"].apply(lambda v: "Yes" if bool(v) else "No")

    # 5. Format Ratings (e.g. "4.6" or "N/A")
    def format_rating(val):
        if pd.isna(val) or val is None or str(val).lower() in ["nan", "none", ""]:
            return "N/A"
        try:
            return f"{float(val):.1f}"
        except (ValueError, TypeError):
            return "N/A"

    df["rating"] = df["rating"].apply(format_rating)

    # 6. Format Review Count (e.g. "124" or "0")
    def format_reviews(val):
        if pd.isna(val) or val is None or str(val).lower() in ["nan", "none", ""]:
            return 0
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return 0

    df["review_count"] = df["review_count"].apply(format_reviews)

    # 7. Map to client-facing column headers
    export_df = df[ALL_FIELDS].rename(columns=DISPLAY_COLUMNS)

    # 8. Export CSV with QUOTE_ALL (Guarantees cells NEVER shift in Excel)
    export_df.to_csv(
        OUTPUT_CSV,
        index=False,
        encoding="utf-8-sig",
        quoting=csv.QUOTE_ALL
    )

    # 9. Export valid JSON (zero invalid NaN tokens)
    clean_json_records = export_df.to_dict(orient="records")
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(clean_json_records, f, indent=2, ensure_ascii=False)

    log.info("=" * 70)
    log.info("CLEAN EXPORT COMPLETE: %s verified products exported!", len(export_df))
    log.info("CSV Path:  %s", os.path.abspath(OUTPUT_CSV))
    log.info("JSON Path: %s", os.path.abspath(OUTPUT_JSON))
    log.info("=" * 70)


# ===========================================================================
# 5. ORCHESTRATOR
# ===========================================================================

def run_scraper(start_url: str, max_pages: int = 2):
    launch_native_chrome(start_url)
   
    log.info("Connecting to Chrome on port 9222...")

    with sync_playwright() as p:
        browser = None
        for _ in range(8):
            try:
                browser = p.chromium.connect_over_cdp("http://localhost:9222")
                break
            except Exception:
                time.sleep(1.0)

        if not browser:
            log.error("Could not connect to Chrome port 9222.")
            return

        context = browser.contexts[0]
        page = context.pages[0] if context.pages else context.new_page()
        page.wait_for_timeout(30000)
        log.info("Connected to Nordstrom tab: %s", page.url)
        page.wait_for_timeout(3500)
        dismiss_popups(page)

        all_products = []

        for current_page in range(1, max_pages + 1):
            log.info("--- Processing Page %s of %s ---", current_page, max_pages)

            hydrate_grid(page, rounds=5)
            products = harvest_products_from_page(page)
            page.wait_for_timeout(20000)
            all_products.extend(products)
            log.info("Page %s harvested %s products (Running total: %s).", current_page, len(products), len(all_products))

            if current_page >= max_pages:
                break
            
            success = navigate_to_next_page(page, current_page, start_url)
            if not success:
                log.info("Pagination boundary reached.")
                break

        clean_and_export(all_products)


def main():
    parser = argparse.ArgumentParser(description="Nordstrom Men's Shoes Scraper")
    parser.add_argument("--url", default=DEFAULT_URL, help="Catalog starting URL")
    parser.add_argument("--pages", type=int, default=2, help="Number of pages to scrape")
    args = parser.parse_args()

    run_scraper(start_url=args.url, max_pages=args.pages)


if __name__ == "__main__":
    main()