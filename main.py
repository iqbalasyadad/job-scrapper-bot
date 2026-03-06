import sqlite3
import yaml
import hashlib
import logging
import requests

from scraper import scrape_all


# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("job_bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


# ── Database ──────────────────────────────────────────────────────────────────

def init_db(db_path: str = "jobs.db"):
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            title           TEXT,
            company         TEXT,
            location        TEXT,
            salary          TEXT,
            job_type        TEXT,
            link            TEXT,
            source          TEXT,
            keyword         TEXT,
            search_location TEXT,
            hash            TEXT UNIQUE,
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
    logger.info("✅ Database ready.")


def job_hash(title: str, company: str, location: str) -> str:
    text = f"{title.lower().strip()}{company.lower().strip()}{location.lower().strip()}"
    return hashlib.sha1(text.encode()).hexdigest()


def save_job(job: dict, db_path: str = "jobs.db") -> bool:
    """Insert job into DB. Returns True if new, False if duplicate."""
    h    = job_hash(job["title"], job["company"], job["location"])
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("""
            INSERT INTO jobs
                (title, company, location, salary, job_type, link, source, keyword, search_location, hash)
            VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            job["title"],
            job["company"],
            job["location"],
            job.get("salary", ""),
            job.get("job_type", ""),
            job["link"],
            job.get("source", "Indeed"),
            job.get("keyword", ""),
            job.get("search_location", ""),
            h,
        ))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False  # duplicate
    except Exception as e:
        logger.error(f"DB insert error: {e}")
        return False
    finally:
        conn.close()


# ── Telegram ──────────────────────────────────────────────────────────────────

def send_telegram(msg: str, token: str, chat_id: str, retries: int = 3):
    """Send message via Telegram Bot API with retry on failure."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(
                url,
                data={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
                timeout=10,
            )
            if resp.ok:
                return
            logger.warning(f"Telegram error ({resp.status_code}): {resp.text}")
        except requests.RequestException as e:
            logger.warning(f"Telegram attempt {attempt} failed: {e}")
    logger.error("Failed to send Telegram message after all retries.")


# ── Formatters ────────────────────────────────────────────────────────────────

def format_job(job: dict) -> str:
    """Per-job Telegram message (sent immediately when a new job is found)."""
    salary_line  = f"\n💰 Salary   : {job['salary']}"          if job.get("salary")   else ""
    type_line    = f"\n🏢 Job Type : {job['job_type']}"         if job.get("job_type") else ""
    keyword_line = f"\n🔍 Keyword  : {job.get('keyword', '')}"

    return (
        f"📌 <b>New Job Alert</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 Title    : {job['title']}\n"
        f"🏬 Company  : {job['company']}\n"
        f"📍 Location : {job['location']}"
        f"{salary_line}"
        f"{type_line}"
        f"{keyword_line}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 <a href='{job['link']}'>Apply Here</a>"
    )


def format_summary(new_jobs: list, total_scraped: int) -> str:
    """End-of-run summary Telegram message listing all new jobs."""
    lines = [
        f"🏁 <b>Scrape Complete</b>",
        f"━━━━━━━━━━━━━━━━━━━━━━",
        f"📊 Scraped : {total_scraped} total",
        f"🆕 New     : {len(new_jobs)} new jobs",
        f"━━━━━━━━━━━━━━━━━━━━━━",
    ]

    if not new_jobs:
        lines.append("✅ No new jobs — DB already up to date.")
    else:
        for i, job in enumerate(new_jobs, 1):
            salary_part  = f" | 💰 {job['salary']}"   if job.get("salary")   else ""
            type_part    = f" | 🏢 {job['job_type']}" if job.get("job_type") else ""
            lines.append(
                f"\n{i}. <b>{job['title']}</b>\n"
                f"   🏬 {job['company']} — 📍 {job['location']}"
                f"{salary_part}{type_part}\n"
                f"   🔍 {job.get('keyword', '')} | "
                f"🔗 <a href='{job['link']}'>Apply</a>"
            )

    return "\n".join(lines)


def print_summary(new_jobs: list, total_scraped: int):
    """Print a formatted summary table to the console."""
    divider = "═" * 70
    print(f"\n{divider}")
    print(f"  🏁  SCRAPE COMPLETE")
    print(f"  📊  Scraped : {total_scraped}   |   🆕  New : {len(new_jobs)}")
    print(divider)

    if not new_jobs:
        print("  ✅  No new jobs — database is already up to date.")
    else:
        for i, job in enumerate(new_jobs, 1):
            salary  = f"   💰 {job['salary']}"   if job.get("salary")   else ""
            jobtype = f"   🏢 {job['job_type']}" if job.get("job_type") else ""
            print(f"\n  [{i:>2}] {job['title']}")
            print(f"        Company  : {job['company']}")
            print(f"        Location : {job['location']}{salary}{jobtype}")
            print(f"        Keyword  : {job.get('keyword', '')}")
            print(f"        Link     : {job['link']}")

    print(f"{divider}\n")


def print_db(db_path: str = "jobs.db"):
    """Print every row currently stored in the database."""
    conn = sqlite3.connect(db_path)
    rows = conn.execute("""
        SELECT id, title, company, location, salary, job_type, keyword, search_location, created_at
        FROM jobs
        ORDER BY created_at DESC, id DESC
    """).fetchall()
    conn.close()

    divider = "─" * 70
    header  = "═" * 70
    print(f"\n{header}")
    print(f"  🗄️  DATABASE CONTENTS  ({len(rows)} total jobs)")
    print(header)

    if not rows:
        print("  (empty)")
    else:
        for row in rows:
            id_, title, company, location, salary, job_type, keyword, search_loc, created = row
            salary_str   = f"   💰 {salary}"     if salary   else ""
            jobtype_str  = f"   🏢 {job_type}"   if job_type else ""
            keyword_str  = f"   🔍 {keyword}"    if keyword  else ""
            loc_str      = f"   📍 {search_loc}" if search_loc else ""
            print(f"\n  [{id_:>3}] {title}")
            print(f"         Company   : {company}")
            print(f"         Location  : {location}{salary_str}{jobtype_str}")
            print(f"         Stored at : {created}{keyword_str}{loc_str}")
        print()

    print(f"{header}\n")


# ── Config ────────────────────────────────────────────────────────────────────

def load_config(path: str = "config.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    config    = load_config()
    keywords  = config.get("keywords", [])
    locations = config.get("location", [""])
    token     = config["telegram"]["bot_token"]
    chat_id   = config["telegram"]["chat_id"]
    driver_v  = config.get("driver_version", "145")

    init_db()

    # ── Scrape ────────────────────────────────────────────────────────────────
    jobs = scrape_all(
        keywords       = keywords,
        locations      = locations,
        driver_version = driver_v,
    )

    # ── Save + notify per job + collect new jobs ───────────────────────────────
    new_jobs = []
    for job in jobs:
        if save_job(job):
            new_jobs.append(job)
            send_telegram(format_job(job), token, chat_id)
            logger.info(f"  📨 Sent: {job['title']} @ {job['company']} [{job.get('keyword')}]")

    # ── Print summary to console ──────────────────────────────────────────────
    print_summary(new_jobs, total_scraped=len(jobs))

    # ── Send summary to Telegram ──────────────────────────────────────────────
    send_telegram(format_summary(new_jobs, total_scraped=len(jobs)), token, chat_id)
    logger.info(f"📬 Summary sent to Telegram.")

    # ── Print all DB rows ─────────────────────────────────────────────────────
    print_db()


if __name__ == "__main__":
    main()