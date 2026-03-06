from playwright.sync_api import sync_playwright

URL = "https://id.indeed.com/jobs?q=seismic&l=indonesia&from=searchOnDesktopSerp"

def scrape_jobs():

    jobs = []

    with sync_playwright() as p:

        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto(URL, timeout=60000)

        page.wait_for_selector("span[data-testid='company-name']")

        cards = page.query_selector_all("div.job_seen_beacon")

        for card in cards:

            title_el = card.query_selector("span[id^='jobTitle']")
            company_el = card.query_selector("span[data-testid='company-name']")
            location_el = card.query_selector("div[data-testid='text-location']")

            if title_el and company_el and location_el:

                title = title_el.inner_text().strip()
                company = company_el.inner_text().strip()
                location = location_el.inner_text().strip()

                jobs.append((title, company, location))

        browser.close()

    return jobs


if __name__ == "__main__":

    jobs = scrape_jobs()

    for job in jobs:
        print("Title:", job[0])
        print("Company:", job[1])
        print("Location:", job[2])
        print("-" * 40)