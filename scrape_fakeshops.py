import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import os
import re
import sys
import random
import json
from datetime import datetime
from fake_useragent import UserAgent, FakeUserAgentError

URL = "https://www.gold.de/fakeshop-blacklist/"
OUTPUT_FILE = "blocklist.txt"
DEBUG_FILE = "debug/blacklist.txt"
THRESHOLD_PERCENT = 0.8  # 80 %

# Array for Logs
process_logs = []


def log(level, message):
    formatted_msg = f"{level:<9} {message}"
    print(formatted_msg)
    process_logs.append(formatted_msg)


def get_random_user_agent():
    try:
        ua = UserAgent(browsers=["chrome", "firefox", "edge"])
        return ua.random
    except FakeUserAgentError:
        # Fallback list – current, real User‑Agents (May 2026)
        fallback_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:145.0) Gecko/20100101 Firefox/145.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.1 Safari/605.1.15",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36 Edg/147.0.0.0",
        ]
        return random.choice(fallback_agents)


def fetch_and_parse(url):
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": get_random_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "de,en-US;q=0.7,en;q=0.3",
            "Accept-Encoding": "gzip, deflate, br",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
    )

    retry_strategy = Retry(
        total=5,
        backoff_factor=0.5, # Wait: 0.5s, 1s, 2s, 4s, 8s
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    log("[SYSTEM]", "Initializing fetch and parse process...")
    log("[INFO]", f"Connecting to target URL: {url}")

    try:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        log("[ERROR]", f"Failed to fetch target URL after retries: {e}")
        sys.exit(1)

    soup = BeautifulSoup(resp.text, "html.parser")

    container = soup.select_one("div.h250scroll")
    if not container:
        # Save the HTML for later analysis
        os.makedirs("debug", exist_ok=True)
        with open("debug/failed_page.html", "w", encoding="utf-8") as f:
            f.write(resp.text)
        log("[ERROR]", "Container div.h250scroll not found – HTML saved to debug/failed_page.html")
        sys.exit(1)

    log("[SUCCESS]", "Located target domain container (div.h250scroll).")

    items = container.select("ul.list-unstyled li")
    log("[INFO]", f"Discovered {len(items)} raw list items to parse.")

    seen_domains = set()
    valid_domains = []
    invalid_entries = []
    duplicate_entries = []

    for li in items:
        text = li.get_text(strip=True).lower()

        # Hotfix START
        if text == "gold321.deeinfach-feingold.de":
            for fixed_domain in ["gold321.de", "einfach-feingold.de"]:
                if fixed_domain not in seen_domains:
                    seen_domains.add(fixed_domain)
                    valid_domains.append(fixed_domain)
            continue
        # Hotfix END

        if text.startswith("www."):
            text = text[4:]

        if not text:
            invalid_entries.append("[Empty line]")
            continue

        if text in seen_domains:
            duplicate_entries.append(text)
            continue

        try:
            punycode_domain = text.encode("idna").decode("ascii")
            if re.fullmatch(r"^(?:[a-z0-9-]+\.)+[a-z]{2,}$", punycode_domain):
                seen_domains.add(text)
                valid_domains.append(punycode_domain)
            else:
                invalid_entries.append(text)
        except Exception:
            invalid_entries.append(f"{text} (Punycode error)")

    log("[INFO]", "Domain validation and normalization complete.")

    valid_domains = sorted(valid_domains)
    duplicate_entries = sorted(duplicate_entries)
    invalid_entries = sorted(invalid_entries)

    log("[STATS]", f"Total entries parsed:     {len(items)}")
    log("[STATS]", f"Invalid lines filtered:   {len(invalid_entries)}")
    log("[STATS]", f"Duplicate lines removed:  {len(duplicate_entries)}")
    log("[STATS]", f"Valid, unique domains:    {len(valid_domains)}")

    return valid_domains, invalid_entries, duplicate_entries


def read_existing_domains():
    log("[INFO]", f"Checking local baseline: {OUTPUT_FILE}")
    if not os.path.exists(OUTPUT_FILE):
        log("[SYSTEM]", "No existing blocklist found. Proceeding with fresh run.")
        return []

    existing = []
    with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("["):
                clean_domain = line.replace("||", "").replace("^", "").lower()
                existing.append(clean_domain)
    log("[INFO]", f"Loaded {len(existing)} historical domains from local file.")
    return sorted(existing)


def write_output_files(domains, invalid_entries, duplicate_entries):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")

    # AdBlock format (blocklist.txt) – with full metadata header
    with open('blocklist.txt', 'w', encoding='utf-8') as f:
        f.write(f"[Adblock Plus 2.0]\n")
        f.write(f"# Pi-hole DNS Blocklist: GOLD.DE Fakeshops\n")
        f.write(f"# Source: {URL}\n")
        f.write(f"# Pi-hole Source: https://github.com/nice42q/gold-de-fakeshops\n")
        f.write(f"# Last update: {now}\n")
        f.write(f"#\n")
        f.write(f"# --- Analysis statistics for this update ---\n")
        f.write(f"# Total valid domains:       {len(domains)}\n")
        f.write(f"# Duplicate entries removed: {len(duplicate_entries)}\n")
        f.write(f"# Invalid lines filtered:    {len(invalid_entries)}\n")
        f.write(f"# {'-'*43}\n#\n")
        for domain in domains:
            f.write(f"||{domain}^\n")

    # Hosts format (minimal header)
    with open('blocklist-hosts.txt', 'w', encoding='utf-8') as f:
        f.write("# Gold.de Fakeshop Blocklist – Hosts Format\n")
        for domain in domains:
            f.write(f"0.0.0.0 {domain}\n")

    # Plain domain list
    with open('blocklist-domains.txt', 'w', encoding='utf-8') as f:
        for domain in domains:
            f.write(f"{domain}\n")

    log("[SUCCESS]", "All pipeline assets compiled and saved successfully.")


def write_debug_file(invalid_entries, duplicate_entries):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    log("[SYSTEM]", f"Writing enhanced debug report to {DEBUG_FILE}...")

    if os.path.dirname(DEBUG_FILE):
        os.makedirs(os.path.dirname(DEBUG_FILE), exist_ok=True)

    with open(DEBUG_FILE, "w", encoding="utf-8") as f:
        # --- HEADER & EXECUTION LOG ---
        f.write(f"# {'='*78}\n")
        f.write(f"# GOLD.DE FAKESHOP BLACKLIST – REPORT & DEBUG LOG\n")
        
        # Removed the dynamic timestamp from the debug log to prevent
        # Git from triggering empty commits every 6 hours when the actual
        # domain data hasn't changed.
        #f.write(f"# Generated on: {now}\n")
        
        f.write(f"# {'='*78}\n")
        f.write(f"#\n")
        f.write(f"# -- RUNTIME PROCESS LOG --\n")
        for log_line in process_logs:
            f.write(f"# {log_line}\n")
        f.write(f"#\n")

        # --- DUPLICATE ENTRIES ---
        f.write(f"# {'-'*78}\n")
        f.write(f"# REMOVED DUPLICATE ENTRIES ({len(duplicate_entries)})\n")
        f.write(f"# These domains were present multiple times within the source HTML list.\n")
        f.write(f"# {'-'*78}\n")
        if duplicate_entries:
            for entry in duplicate_entries:
                f.write(f"{entry}\n")
        else:
            f.write("# (no duplicates found)\n")

        # --- INVALID ENTRIES ---
        f.write(f"# {'-'*78}\n")
        f.write(f"# FILTERED INVALID ENTRIES ({len(invalid_entries)})\n")
        f.write(f"# These entries did not match a valid cryptographic/standard domain schema.\n")
        f.write(f"# {'-'*78}\n")
        if invalid_entries:
            for entry in invalid_entries:
                f.write(f"{entry}\n")
        else:
            f.write("# (no invalid entries found)\n")


if __name__ == "__main__":
    log("[SYSTEM]", "Pipeline execution triggered.")

    old_shops = read_existing_domains()
    new_shops, invalid_entries, duplicate_entries = fetch_and_parse(URL)

    if len(new_shops) == 0:
        log("[ERROR]", "Empty list protection triggered: 0 valid domains found. Aborting.")
        sys.exit(1)

    if len(old_shops) > 0:
        ratio = len(new_shops) / len(old_shops)
        if ratio < THRESHOLD_PERCENT:
            log(
                "[ERROR]",
                f"Threshold protection: New list ({len(new_shops)}) is < {THRESHOLD_PERCENT*100}% of old list ({len(old_shops)}). Aborting.",
            )
            sys.exit(1)

    write_debug_file(invalid_entries, duplicate_entries)

    def write_stats_json(count):
        badge_data = {
            "schemaVersion": 1,
            "label": "Blocklist entries",
            "message": str(count),
            "color": "red"
        }
        with open("stats.json", "w", encoding="utf-8") as f:
            json.dump(badge_data, f, indent=2)
        log("[SYSTEM]", "Stats JSON badge data updated.")

    if new_shops == old_shops:
        log("[SUCCESS]", "Integrity check: No updates on source page. Local blocklist is up-to-date.")
        
        if not os.path.exists("stats.json"):
            log("[INFO]", "stats.json is missing. Re-creating template.")
            write_stats_json(len(new_shops))
    else:
        log("[SYSTEM]", "Delta detected or assets missing. Writing all blocklist files...")
        write_output_files(new_shops, invalid_entries, duplicate_entries)
        write_stats_json(len(new_shops))
