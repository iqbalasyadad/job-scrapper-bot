# Job Scraper Telegram Bot

Scrapes job listings from **Indeed** and **LinkedIn**, stores them in a JSON database, and delivers them via Telegram bot.

---

## 📁 File Structure

```
├── bot.py               ← Main Telegram bot (run this)
├── scraper_indeed.py    ← Indeed scraper module
├── scraper_linkedin.py  ← LinkedIn scraper module
├── db.py                ← JSON database manager
├── config.yaml          ← All settings (keywords, locations, Telegram, etc.)
├── jobs_db.json         ← Auto-created job database
└── requirements.txt     ← Python dependencies
```

---

## ⚙️ Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure `config.yaml`
```yaml
keywords:
  - geophysics
  - seismic

location:
  - Indonesia

company_blacklist:
  - "some company to ignore"

auto_scrape_interval_hours: 6   # set 0 to disable

telegram:
  bot_token: "YOUR_BOT_TOKEN"
  chat_id: "YOUR_CHAT_ID"
```

### 3. Run the bot
```bash
python bot.py
```

---

## 🤖 Telegram Commands

| Command | Description |
|---------|-------------|
| `/start` | Show main menu with buttons |
| `/scrape` | Manually trigger scrape (all sources) |
| `/latest` | Show latest 10 jobs from DB |
| `/all` | Show all jobs in DB |
| `/stats` | Show DB statistics |
| `/export` | Download DB as JSON file |
| `/help` | Show command list |

### Inline Menu Buttons
- **🔍 Scrape All** — Scrape all sources now
- **🌐 Scrape Indeed** — Scrape Indeed only
- **🔷 Scrape LinkedIn** — Scrape LinkedIn only
- **📋 View Latest 10** — Show newest 10 jobs
- **🔎 View All** — Show entire DB
- **📊 DB Stats** — Summary by source/keyword
- **📥 Export JSON** — Download full DB

---

## ➕ Adding a New Scraper Source

1. Create `scraper_yoursite.py` with this interface:
```python
def scrape(keywords: list[str], locations: list[str], driver_version: str) -> list[dict]:
    # return list of job dicts with these fields:
    # title, company, location, job_id, job_type, salary, url,
    # source, keyword, search_location, date_scraped
    ...
```

2. Register it in `bot.py`:
```python
import scraper_yoursite

SCRAPERS = {
    "Indeed": scraper_indeed,
    "LinkedIn": scraper_linkedin,
    "YourSite": scraper_yoursite,   # ← add here
}
```

3. Optionally add a button in `cmd_start()`:
```python
InlineKeyboardButton("🆕 Scrape YourSite", callback_data="scrape_YourSite")
```

---

## 🗄️ Database (`jobs_db.json`)

Each job entry looks like:
```json
{
  "title": "Geophysicist",
  "company": "PT Example",
  "location": "Jakarta, Indonesia",
  "job_id": "abc123",
  "job_type": "Full-time",
  "salary": "N/A",
  "url": "https://...",
  "source": "Indeed",
  "keyword": "geophysics",
  "search_location": "Indonesia",
  "date_scraped": "2025-01-15T08:30:00",
  "_uid": "Indeed::abc123"
}
```

Duplicates are detected by `_uid` (source + job_id, or a fingerprint of title+company+source).

---

## 🔧 Notes

- Uses **SeleniumBase UC mode** to bypass bot detection on Indeed
- LinkedIn scrapes public listings (no login required)
- The bot runs forever — use `screen`, `tmux`, or `systemd` to keep it alive on a server
- All files must be in the **same directory**
