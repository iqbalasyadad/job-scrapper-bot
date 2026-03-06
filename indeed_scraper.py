"""
Indeed Job Scraper — SeleniumBase Version
Scrapes seismic job listings from id.indeed.com/jobs?q=seismic&l=indonesia

Setup:
    pip install seleniumbase

Run:
    python indeed_scraper_sb.py

SeleniumBase UC (Undetected Chrome) mode is used to bypass Indeed's bot detection.
"""

import json
import time
from seleniumbase import SB

URL = "https://id.indeed.com/jobs?q=seismic&l=indonesia&from=searchOnDesktopSerp"


def parse_jobs(sb) -> list[dict]:
    """Extract job listings from the current page."""
    jobs = []

    # Wait for job cards to load
    # sb.wait_for_element("ul.css-zu9cdh, [data-testid='mosaic-provider-jobcards']", timeout=15)
    time.sleep(10)
    # Grab all job cards
    cards = sb.find_elements("li.css-5lfssm, li[class*='job_seen_beacon'], div.job_seen_beacon")

    if not cards:
        print("not cards")
        # Fallback: find by job title span
        cards = sb.find_elements("span[id^='jobTitle-']")
        print(f"  Fallback: found {len(cards)} title elements directly.")
        for title_el in cards:
            title = title_el.text.strip()
            # Walk up DOM to find sibling company/location
            try:
                card = title_el.find_element("xpath", "./ancestor::li | ./ancestor::div[contains(@class,'result')]")
            except Exception:
                card = None

            company, location, job_id, job_type = "N/A", "N/A", "N/A", "N/A"
            if card:
                try:
                    company = card.query_selector("[data-testid='company-name']").text
                except Exception:
                    pass
                try:
                    location = card.query_selector("[data-testid='text-location']").text
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

            if title:
                jobs.append({"title": title, "company": company, "location": location, "job_type": job_type, "salary": salary})
        return jobs

    print(f"  Found {len(cards)} job card(s) on page.")
    for card in cards:
        # print("/////")
        # print(card)

        title, company, location, job_id, job_type, salary = "N/A", "N/A", "N/A", "N/A", "N/A", "N/A"

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
            location = card.query_selector("[data-testid='text-location']").text
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
            jobs.append({"title": title, "company": company, "location": location, "job_id": job_id, "job_type": job_type, "salary": salary})

    return jobs


def print_jobs(jobs: list[dict]) -> None:
    """Pretty-print scraped jobs."""
    if not jobs:
        print("\n  No jobs found. Try re-running or checking the page manually.\n")
        return

    print(f"\n{'='*70}")
    print(f"  Found {len(jobs)} job(s) — Seismic Jobs in Indonesia")
    print(f"{'='*70}\n")

    for i, job in enumerate(jobs, 1):
        print(f"  Job #{i}")
        print(f"  Title    : {job['title']}")
        print(f"  Company  : {job['company']}")
        print(f"  Location : {job['location']}")
        print(f"  Job ID : {job['job_id']}")
        print(f"  Type     : {job['job_type']}")
        print(f"  Salary     : {job['salary']}")
        print(f"  URL : https://www.indeed.com/viewjob?jk={job['job_id']}")

        print(f"  {'-'*60}")

    with open("indeed_jobs.json", "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)
    print(f"\n  Results saved to: indeed_jobs.json\n")


def main():
    print("\n" + "="*70)
    print("  Indeed Scraper — SeleniumBase UC Mode")
    print("="*70)
    print(f"  URL: {URL}\n")

    # UC (Undetected Chrome) mode bypasses Indeed's bot detection
    with SB(uc=True, headless=True) as sb:
        print("  Opening browser...")
        sb.open(URL)

        # Give JS time to render
        time.sleep(3)

        # Handle potential cookie/consent banner
        for selector in ["button#onetrust-accept-btn-handler", "button[id*='accept']", "button[class*='consent']"]:
            try:
                sb.click(selector, timeout=3)
                print(f"  Dismissed consent banner via: {selector}")
                time.sleep(1)
                break
            except Exception:
                pass

        # Scroll to trigger lazy-loaded content
        sb.execute_script("window.scrollTo(0, document.body.scrollHeight / 2);")
        time.sleep(1)
        sb.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1)

        print("  Parsing jobs...")
        jobs = parse_jobs(sb)

    print_jobs(jobs)


if __name__ == "__main__":
    main()