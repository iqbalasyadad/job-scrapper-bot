"""
scraper_indeed.py — Indeed Job Scraper (SeleniumBase UC Mode)
Scrapes job listings from id.indeed.com
"""

import time
from datetime import datetime
from seleniumbase import SB


def build_url(keyword: str, location: str) -> str:
    import urllib.parse
    q = urllib.parse.quote_plus(keyword)
    l = urllib.parse.quote_plus(location)
    return f"https://id.indeed.com/jobs?q={q}&l={l}&from=searchOnDesktopSerp"


def scrape(keywords: list[str], locations: list[str], driver_version: str = "145") -> list[dict]:
    """
    Scrape Indeed for given keywords and locations.
    Returns a list of job dicts.
    """
    all_jobs = []

    for keyword in keywords:
        for location in locations:
            url = build_url(keyword, location)
            print(f"  [Indeed] Scraping: {url}")

            try:
                with SB(uc=True, headless=True) as sb:
                    sb.open(url)
                    time.sleep(3)

                    # Dismiss consent banners
                    for selector in [
                        "button#onetrust-accept-btn-handler",
                        "button[id*='accept']",
                        "button[class*='consent']",
                    ]:
                        try:
                            sb.click(selector, timeout=3)
                            time.sleep(1)
                            break
                        except Exception:
                            pass

                    # Scroll to trigger lazy loading
                    sb.execute_script("window.scrollTo(0, document.body.scrollHeight / 2);")
                    time.sleep(1)
                    sb.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(1)

                    jobs = _parse_jobs(sb, keyword, location)
                    print(f"  [Indeed] Found {len(jobs)} job(s) for '{keyword}' in '{location}'")
                    all_jobs.extend(jobs)

            except Exception as e:
                print(f"  [Indeed] Error: {e}")

    return all_jobs


def _parse_jobs(sb, keyword: str, location: str) -> list[dict]:
    jobs = []
    time.sleep(10)

    cards = sb.find_elements("li.css-5lfssm, li[class*='job_seen_beacon'], div.job_seen_beacon")
    print(f"  [Indeed] {len(cards)} card(s) found on page.")

    for card in cards:
        title = company = loc = job_id = job_type = salary = "N/A"

        try:
            title = card.find_element("css selector", "span[id^='jobTitle-']").text.strip()
        except Exception:
            try:
                title = card.query_selector("span[id^='jobTitle']").text
            except Exception:
                pass

        try:
            company = card.query_selector("[data-testid='company-name']").text
        except Exception:
            pass

        try:
            loc = card.query_selector("[data-testid='text-location']").text
        except Exception:
            pass

        try:
            job_id = card.query_selector("a.jcs-JobTitle").get_attribute("data-jk")
        except Exception:
            pass

        try:
            job_type = card.query_selector("[data-testid='attribute_snippet_testid'] span").text
        except Exception:
            pass

        try:
            salary = card.query_selector("[data-testid*='salary-snippet-container'] span").text
        except Exception:
            pass

        if title != "N/A":
            jobs.append({
                "title": title,
                "company": company,
                "location": loc,
                "job_id": job_id,
                "job_type": job_type,
                "salary": salary,
                "url": f"https://www.indeed.com/viewjob?jk={job_id}" if job_id != "N/A" else "N/A",
                "source": "Indeed",
                "keyword": keyword,
                "search_location": location,
                "date_scraped": datetime.utcnow().isoformat(),
            })

    return jobs
