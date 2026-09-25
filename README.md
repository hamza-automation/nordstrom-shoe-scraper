# Nordstrom Men's Shoes Catalog Scraper

A production-grade Python scraper that extracts Nordstrom's men's shoes
catalog — brand, model, pricing, sale status, rating, and reviews — into
a clean, deduplicated CSV and JSON dataset. Fully tested across multiple
runs with reliable error handling throughout.

## Overview

The scraper connects to a real, locally-installed Google Chrome browser
via the Chrome DevTools Protocol (CDP) rather than launching a bundled
automation browser. It progressively scrolls each catalog page to force
Nordstrom's virtualized/lazy-loaded product grid to fully render, then
extracts every product's data directly in the browser via native DOM
queries. Pagination is handled through the site's own "Next" controls
with a direct URL fallback if no clickable control is found. Results are
cleaned, deduplicated, and exported to both CSV and JSON.

## Key Features

- Connects to your own locally-installed Chrome via CDP (remote
  debugging on port 9222) instead of a managed/bundled automation
  browser — works on both **Windows and Linux** Chrome installations.
- Progressively scrolls the page across multiple rounds to hydrate
  virtualized product tiles before extraction, so lazy-loaded cards
  aren't missed.
- Extracts product data via in-browser JavaScript (native DOM queries),
  with fallback selector strategies for brand, model, rating, and review
  count when the primary selector doesn't match.
- Pagination tries the site's own "Next" button (multiple selector
  strategies), and falls back to constructing the next page's URL
  directly from whatever start URL was provided if no button is found —
  this fallback works with any catalog URL, not a fixed one.
- Deduplicates products by product URL.
- Cleans and normalizes brand/model text (strips stray newlines/tabs,
  collapses whitespace, defaults blank values to "Nordstrom").
- Formats prices as currency strings, sale status as "Yes"/"No", ratings
  to one decimal place, and review counts as integers — each with a safe
  "N/A" or default fallback when data is missing.
- Exports CSV with every cell quoted (`QUOTE_ALL`), preventing column
  misalignment in Excel from commas inside values, and JSON with no
  invalid `NaN` tokens.
- Logs progress to the console and to a log file.

## Data Collected

| Field | Description |
|---|---|
| Brand | Product brand name |
| Model | Product name/model |
| Price Min ($) | Lower bound of the listed price |
| Price Max ($) | Upper bound of the listed price |
| On Sale | Whether the listing shows sale/markdown language ("Yes"/"No") |
| Rating | Average star rating |
| Reviews | Number of reviews |
| Product URL | Direct link to the product page |
| Scraped At | UTC timestamp of when the item was captured |

## Technologies

- **Python 3**
- **Playwright** (Python) — connects to Chrome over the DevTools Protocol
- **pandas** — data cleaning and CSV/JSON export
- **Google Chrome** — a real, locally-installed browser instance (not a
  Playwright-managed browser)

## Project Structure

```
nordstrom-shoe-scraper/
├── scraper.py
├── requirements.txt
├── .gitignore
├── LICENSE
├── README.md
└── screenshots/
```

At runtime the script also creates `chrome_nordstrom_profile/` (a local
Chrome user-data directory) and a log file — these are local runtime
artifacts and are excluded via `.gitignore`. The CSV and JSON outputs are
**not** excluded — real sample output is intended to be committed at the
repository root as proof of results (see Sample Output below).

## Installation

Requires **Google Chrome installed** in one of the following locations
(auto-detected by the script):

- Windows: `C:\Program Files\Google\Chrome\Application\chrome.exe`
- Windows: `C:\Program Files (x86)\Google\Chrome\Application\chrome.exe`
- Windows: `%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe`
- Linux: `/usr/bin/google-chrome`
- Linux: `/usr/bin/google-chrome-stable`

```bash
pip install -r requirements.txt
```

## Usage

```bash
python scraper.py --url "https://www.nordstrom.com/browse/men/shoes" --pages 2
```

**Arguments:**

| Argument | Default | Description |
|---|---|---|
| `--url` | `https://www.nordstrom.com/browse/men/shoes` | Catalog starting URL |
| `--pages` | `2` | Number of pages to scrape |

The direct-URL pagination fallback adapts to whatever `--url` you pass,
so this works against any Nordstrom catalog/category page, not just the
default.

## Output

Running the script produces:

- **`nordstrom_catalog.csv`** — cleaned, deduplicated product records with client-facing column headers
- **`nordstrom_catalog.json`** — the same records in JSON format
- **`nordstrom_scraper.log`** — a log of the scraping run (console output is also mirrored here)

Real output from a completed run is included at the repository root
(`nordstrom_catalog.csv` / `nordstrom_catalog.json`) as proof of results
from actual tested runs — visible directly in the repository file list,
viewable and downloadable from GitHub without opening this README.


## Disclaimer

This project is provided for educational and demonstration purposes. It
is your responsibility to ensure that any use of this scraper complies
with Nordstrom's Terms of Use and applicable law before running it
against the live site. This repository does not grant any right to
violate a third party's Terms of Service, and the author assumes no
liability for how this code is used.

## Author

**Hamza**
