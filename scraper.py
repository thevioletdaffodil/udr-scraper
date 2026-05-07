"""
scraper.py — Udaipur travel blog & news scraper
Targets: udaipurtimes.com and udaipurtourism.co.in
Stores results to Azure Cosmos DB.
"""

import os
import logging
import requests
import hashlib
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from azure.cosmos import CosmosClient, PartitionKey, exceptions

# ── Cosmos DB config from App Settings / env vars ──────────────────────────────
COSMOS_ENDPOINT   = os.environ["COSMOS_ENDPOINT"]          # e.g. https://<acct>.documents.azure.com:443/
COSMOS_KEY        = os.environ["COSMOS_KEY"]               # Primary key from Azure portal
DATABASE_NAME     = "udaipur_db"
CONTAINER_NAME    = "spots"
PARTITION_KEY     = "/category"

# ── Scrape targets ──────────────────────────────────────────────────────────────
SOURCES = [
    {
        "name": "Udaipur Times",
        "url":  "https://www.udaipurtimes.com/",
        "type": "news",
    },
    {
        "name": "Udaipur Tourism",
        "url":  "https://www.udaipurtourism.co.in/",
        "type": "tourism",
    },
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# ── Cosmos helpers ──────────────────────────────────────────────────────────────

def get_cosmos_container():
    """Return (or create) the Cosmos DB container."""
    client = CosmosClient(COSMOS_ENDPOINT, COSMOS_KEY)
    db = client.create_database_if_not_exists(id=DATABASE_NAME)
    container = db.create_container_if_not_exists(
        id=CONTAINER_NAME,
        partition_key=PartitionKey(path=PARTITION_KEY)
    )
    return container


def save_item(container, item: dict) -> bool:
    """Upsert a single item; return True on success."""
    try:
        container.upsert_item(item)
        return True
    except exceptions.CosmosHttpResponseError as exc:
        logging.error("Cosmos upsert failed for '%s': %s", item.get("title"), exc)
        return False


# ── Scraping helpers ────────────────────────────────────────────────────────────

def fetch_page(url: str) -> BeautifulSoup | None:
    """GET a page and return a BeautifulSoup object, or None on error."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException as exc:
        logging.error("HTTP error fetching %s: %s", url, exc)
        return None


def classify_category(title: str, excerpt: str) -> str:
    """
    Cheap keyword-based classifier.
    Returns one of: events | festivals | food | heritage | nature | hotels | general
    """
    text = (title + " " + excerpt).lower()
    if any(w in text for w in ["festival", "mela", "fair", "celebration", "garba", "diwali",
                                "holi", "navratri", "gangaur"]):
        return "festivals"
    if any(w in text for w in ["concert", "event", "show", "exhibition", "performance"]):
        return "events"
    if any(w in text for w in ["restaurant", "food", "eat", "dal baati", "cuisine", "cafe"]):
        return "food"
    if any(w in text for w in ["palace", "fort", "temple", "haveli", "museum", "heritage",
                                "city palace", "udaipur lake", "pichola", "jagdish"]):
        return "heritage"
    if any(w in text for w in ["trek", "hill", "nature", "garden", "sajjangarh",
                                "jungle", "wildlife", "birds"]):
        return "nature"
    if any(w in text for w in ["lake", "pichola", "fateh sagar", "badi", "ghat", "doodh talai", "swaroop sagar", "amati"]):
        return "lakes"
    if any(w in text for w in ["hotel", "resort", "stay", "accommodation", "hostel"]):
        return "hotels"
    return "general"

def generate_deterministic_id(url: str) -> str:
    """Creates a consistent, unique ID based on the URL."""
    return hashlib.md5(url.encode('utf-8')).hexdigest()

def build_item(title: str, url: str, excerpt: str, source: str) -> dict:
    category = classify_category(title, excerpt)
    return {
        "id":         generate_deterministic_id(url), # CHANGED THIS LINE
        "title":      title,
        "url":        url,
        "excerpt":    excerpt[:500],
        "source":     source,
        "category":   category,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Per-site scrapers ───────────────────────────────────────────────────────────

def scrape_udaipur_times(base_url: str, source_name: str) -> list[dict]:
    soup = fetch_page(base_url)
    if not soup: return []

    items = []
    # Combined CSS selector: finds ALL jeg_posts, articles, and generic post classes at once
    candidates = soup.select(".jeg_post, article, .post-block, .td-block-span12")

    for art in candidates:
        title_tag = art.find(["h1", "h2", "h3"])
        link_tag  = art.find("a", href=True)
        para      = art.find(["p", "div"], class_=["jeg_post_excerpt", "excerpt"])

        if title_tag and link_tag:
            title = title_tag.get_text(strip=True)
            link = link_tag["href"]
            if link.startswith("/"): link = base_url.rstrip("/") + link
            excerpt = para.get_text(strip=True) if para else ""
            
            # Use deterministic ID to prevent duplicates in Cosmos
            item = build_item(title, link, excerpt, source_name)
            item["id"] = generate_id(link) 
            items.append(item)

    return items[:25] # Increased limit for more variety

def scrape_udaipur_tourism(base_url: str, source_name: str) -> list[dict]:
    """Scrape attraction / place listings from udaipurtourism.co.in using robust CSS selectors."""
    soup = fetch_page(base_url)
    if not soup:
        return []

    items = []
    
    # The comma acts as an "AND", putting ALL matching elements into one giant list
    candidates = soup.select(".attraction-card, .place-card, .item, .listing-item, [class*='card']")

    seen_links = set()
    for block in candidates[:50]: 
        title_tag = block.find(["h1", "h2", "h3", "h4"])
        link_tag  = block.find("a", href=True)
        
        # If a block doesn't have a title and a link, skip it
        if not title_tag or not link_tag:
            continue

        link = link_tag["href"]
        
        # Prevent processing the exact same link twice on the same page
        if link in seen_links: 
            continue
        seen_links.add(link)

        title = title_tag.get_text(strip=True)
        if not title:
            continue
            
        if link.startswith("/"): 
            link = base_url.rstrip("/") + link
            
        excerpt = ""
        p_tag = block.find("p")
        if p_tag: 
            excerpt = p_tag.get_text(strip=True)

        # Build the item and add the deterministic ID (prevents Cosmos DB duplicates)
        item = build_item(title, link, excerpt, source_name)
        item["id"] = generate_id(link) 
        items.append(item)

    logging.info("udaipurtourism.co.in → %d items", len(items))
    return items


# ── Router ──────────────────────────────────────────────────────────────────────

_SCRAPERS = {
    "Udaipur Times":   scrape_udaipur_times,
    "Udaipur Tourism": scrape_udaipur_tourism,
}


def scrape_source(source: dict) -> list[dict]:
    scraper_fn = _SCRAPERS.get(source["name"], scrape_udaipur_times)
    return scraper_fn(source["url"], source["name"])


# ── Entry point called by function_app.py ──────────────────────────────────────

def main_logic():
    """Scrape all sources and persist results to Cosmos DB."""
    logging.info("Udaipur scraper starting — %s", datetime.now(timezone.utc).isoformat())

    container   = get_cosmos_container()
    total_saved = 0
    total_items = 0

    for source in SOURCES:
        logging.info("Scraping: %s (%s)", source["name"], source["url"])
        items = scrape_source(source)
        total_items += len(items)

        for item in items:
            if save_item(container, item):
                total_saved += 1

    logging.info(
        "Scrape complete: %d scraped, %d saved to Cosmos DB",
        total_items, total_saved,
    )
