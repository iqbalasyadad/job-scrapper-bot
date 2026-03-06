from seleniumbase import SB
import time
import random
import logging
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)


# ── Cloudflare ────────────────────────────────────────────────────────────────

def is_blocked(sb) -> bool:
    try:
        src   = sb.get_page_source().lower()
        title = sb.get_title().lower()
        return (
            any(k in title for k in ["just a moment", "verify", "checking", "attention"])
            or "ray id" in src
        )
    except Exception:
        return False


def wait_for_cloudflare(sb, timeout: int = 60) -> bool:
    logger.info("⏳ Cloudflare detected — attempting to solve...")
    try:
        sb.uc_gui_click_captcha()
        time.sleep(3)
    except Exception:
        pass

    deadline = time.time() + timeout
    while time.time() < deadline:
        if not is_blocked(sb):
            logger.info("✅ Cloudflare cleared.")
            return True
        remaining = int(deadline - time.time())
        logger.info(f"  🔄 Still on challenge... ({remaining}s left — solve manually if needed)")
        time.sleep(3)

    logger.warning("❌ Cloudflare not cleared within timeout.")
    return False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_text(card, selectors: list, default: str = "") -> str:
    """Try multiple CSS selectors, return first match."""
    for sel in selectors:
        try:
            return card.find_element("css selector", sel).text.strip()
        except Exception:
            continue
    return default


def _human_scroll(sb):
    """Scroll page gradually to mimic reading."""
    try:
        total_h = sb.execute_script("return document.body.scrollHeight")
        for step in range(1, 6):
            sb.execute_script(f"window.scrollTo(0, {total_h * step // 5});")
            time.sleep(random.uniform(0.3, 0.7))
    except Exception:
        pass


# ── URL Navigation ────────────────────────────────────────────────────────────

def open_search_url(sb, keyword: str, location: str) -> bool:
    """
    Navigate directly to Indeed search URL with keyword + location.
    e.g. https://id.indeed.com/jobs?q=geophysics&l=indonesia&from=searchOnDesktopSerp
    """
    url = (
        f"https://id.indeed.com/jobs"
        f"?q={quote_plus(keyword)}"
        f"&l={quote_plus(location)}"
        f"&from=searchOnDesktopSerp"
    )
    logger.info(f"  🌐 {url}")
    sb.open(url)
    time.sleep(3)

    if is_blocked(sb):
        if not wait_for_cloudflare(sb, timeout=60):
            logger.error("  Blocked and could not clear Cloudflare.")
            return False

    return True


# ── Parser ────────────────────────────────────────────────────────────────────

def parse_jobs(sb) -> list[dict]:
    """Extract all job cards visible on the current page."""
    if not sb.is_element_present(".job_seen_beacon"):
        logger.info("  ⚠ No job cards found on this page.")
        return []

    cards = sb.find_elements(".job_seen_beacon")
    logger.info(f"  Found {len(cards)} cards")
    jobs  = []

    for card in cards:
        try:
            title    = _get_text(card, ["h2.jobTitle span[id^='jobTitle-']", "h2.jobTitle span[title]", "h2.jobTitle span"], "Unknown Title")
            # company  = _get_text(card, ["[data-testid='company-name']", ".companyName"], "Unknown")
            company = _get_text(
                card,
                [
                    'span[data-testid="company-name"]',
                    '[data-testid="company-name"]',   # fallback
                ],
            )
            print(company)
            # company = sb.get_text('span[data-testid="company-name"]')
            location = _get_text(card, ["[data-testid='text-location']", ".companyLocation"])
            salary   = _get_text(card, [".salary-snippet-container", "[data-testid*='salary']", ".estimated-salary"])
            job_type = _get_text(card, ["[data-testid='attribute_snippet_testid']:not([data-testid*='salary'])", ".attribute_snippet"])

            link, job_id = "", ""
            try:
                link_el = card.find_element("css selector", "h2 a")
                href    = link_el.get_attribute("href") or ""
                job_id  = link_el.get_attribute("data-jk") or ""
                link    = href if href.startswith("http") else f"https://id.indeed.com{href}"
            except Exception:
                pass

            jobs.append({
                "title":    title,
                "company":  company,
                "location": location,
                "salary":   salary,
                "job_type": job_type,
                "link":     link,
                "job_id":   job_id,
                "source":   "Indeed",
            })
            logger.debug(f"    📄 {title} | {company} | {location} | {job_type} | {salary}")
            # print(title, company, location, link)
            print(company)


        except Exception as e:
            logger.warning(f"  Card parse error: {e}")

    return jobs


# ── Main Orchestrator ─────────────────────────────────────────────────────────

def scrape_all(
    keywords: list,
    locations: list,
    driver_version: str = "145",
) -> list[dict]:
    """
    Single browser session, no login required.
    Iterates every keyword × location pair via direct URL navigation.
    Without login, Indeed only serves page 1 (~15 jobs per search).

    Args:
        keywords:       e.g. ["geophysicist", "seismic"]
        locations:      e.g. ["Indonesia", "Singapore"]
        driver_version: Must match your installed Chrome version

    Returns:
        List of job dicts, each tagged with "keyword" and "search_location"
    """
    all_jobs: list = []
    seen_ids: set  = set()
    pairs          = [(kw, loc) for kw in keywords for loc in locations]

    with SB(uc=True, headless=False, driver_version=driver_version) as sb:

        logger.info(
            f"\n📋 {len(pairs)} searches queued "
            f"({len(keywords)} keywords × {len(locations)} locations, page 1 only)\n"
        )

        for idx, (keyword, location) in enumerate(pairs, 1):
            logger.info(f"\n{'═'*55}")
            logger.info(f"[{idx}/{len(pairs)}] '{keyword}' | '{location}'")
            logger.info(f"{'═'*55}")

            if not open_search_url(sb, keyword, location):
                logger.warning("  Navigation failed — skipping.")
                continue

            if is_blocked(sb):
                if not wait_for_cloudflare(sb, timeout=60):
                    logger.warning("  Could not clear Cloudflare — skipping.")
                    continue
                time.sleep(2)

            time.sleep(random.uniform(1, 2))
            _human_scroll(sb)

            jobs     = parse_jobs(sb)
            new_jobs = [j for j in jobs if j["job_id"] not in seen_ids]
            seen_ids.update(j["job_id"] for j in new_jobs if j["job_id"])

            for job in new_jobs:
                job["keyword"]         = keyword
                job["search_location"] = location

            all_jobs.extend(new_jobs)
            logger.info(f"  ✅ +{len(new_jobs)} new | overall: {len(all_jobs)}")

            if idx < len(pairs):
                pause = random.uniform(3, 6)
                logger.info(f"  ⏳ Next search in {pause:.1f}s...")
                time.sleep(pause)

    logger.info(f"\n🏁 Scraping complete. Total jobs: {len(all_jobs)}")
    return all_jobs