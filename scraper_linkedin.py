"""
scraper_linkedin.py — LinkedIn Job Scraper (SeleniumBase UC Mode)
Scrapes public job listings from linkedin.com/jobs
No login required for basic listings.
"""

import time
import urllib.parse
from datetime import datetime
from seleniumbase import SB


def build_url(keyword: str, location: str) -> str:
    q = urllib.parse.quote_plus(keyword)
    l = urllib.parse.quote_plus(location)
    return f"https://www.linkedin.com/jobs/search/?keywords={q}&location={l}&f_TPR=r86400"


def scrape(keywords: list[str], locations: list[str], driver_version: str = "145") -> list[dict]:
    """
    Scrape LinkedIn Jobs (public listings only) for given keywords and locations.
    Returns a list of job dicts.
    """
    all_jobs = []

    for keyword in keywords:
        for location in locations:
            url = build_url(keyword, location)
            print(f"  [LinkedIn] Scraping: {url}")

            try:
                with SB(uc=True, headless=True) as sb:
                    sb.open(url)
                    time.sleep(5)

                    # Scroll to load more jobs
                    for _ in range(3):
                        sb.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                        time.sleep(2)

                    jobs = _parse_jobs(sb, keyword, location)
                    print(f"  [LinkedIn] Found {len(jobs)} job(s) for '{keyword}' in '{location}'")
                    all_jobs.extend(jobs)

            except Exception as e:
                print(f"  [LinkedIn] Error: {e}")

    return all_jobs


def _parse_jobs(sb, keyword: str, location: str) -> list[dict]:
    jobs = []

    try:
        cards = sb.find_elements("div.base-card, li.jobs-search-results__list-item")
    except Exception:
        return jobs

    print(f"  [LinkedIn] {len(cards)} card(s) found on page.")

    for card in cards:
        title = company = loc = job_id = job_type = salary = url = "N/A"

        try:
            title = card.find_element("css selector", "h3.base-search-card__title, h3.job-card-list__title").text.strip()
        except Exception:
            pass

        try:
            company = card.find_element("css selector", "h4.base-search-card__subtitle, a.job-card-container__company-name").text.strip()
        except Exception:
            pass

        try:
            loc = card.find_element("css selector", "span.job-search-card__location, li.job-card-container__metadata-item").text.strip()
        except Exception:
            pass

        try:
            link_el = card.find_element("css selector", "a.base-card__full-link, a.job-card-list__title")
            url = link_el.get_attribute("href").split("?")[0]
            # Extract job ID from URL  e.g. /jobs/view/1234567890/
            parts = url.rstrip("/").split("/")
            job_id = parts[-1] if parts[-1].isdigit() else "N/A"
        except Exception:
            pass

        try:
            job_type = card.find_element("css selector", "span.job-search-card__job-insight, li.job-card-container__metadata-item--workplace-type").text.strip()
        except Exception:
            pass

        try:
            salary = card.find_element("css selector", "span.job-search-card__salary-info").text.strip()
        except Exception:
            pass

        if title != "N/A":
            jobs.append({
                "title": title,
                "company": company,
                "location": loc,
                "job_id": f"li_{job_id}",
                "job_type": job_type,
                "salary": salary,
                "url": url,
                "source": "LinkedIn",
                "keyword": keyword,
                "search_location": location,
                "date_scraped": datetime.utcnow().isoformat(),
            })

    return jobs
