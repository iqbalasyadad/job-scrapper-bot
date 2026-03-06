"""
bot.py — Telegram Job Scraper Bot
Runs forever. Users can manually trigger scraping, view DB, and export results.

Requirements:
    pip install "python-telegram-bot[job-queue]>=20.0,<21.0" seleniumbase pyyaml

Run:
    python bot.py
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

import yaml
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

import db
import scraper_indeed
import scraper_linkedin

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)


# ── Config ────────────────────────────────────────────────────────────────────
def load_config(path: str = "config.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


CONFIG = load_config()
TOKEN = CONFIG["telegram"]["bot_token"]
CHAT_ID = str(CONFIG["telegram"]["chat_id"])
KEYWORDS = CONFIG.get("keywords", ["geophysics"])
LOCATIONS = CONFIG.get("location", ["Indonesia"])
DRIVER_VERSION = str(CONFIG.get("driver_version", "145"))
AUTO_INTERVAL_HOURS = float(CONFIG.get("auto_scrape_interval_hours", 6))

SCRAPERS = {
    "Indeed": scraper_indeed,
    "LinkedIn": scraper_linkedin,
}


# ── Helpers ───────────────────────────────────────────────────────────────────
def fmt_job(job: dict, idx: int) -> str:
    title = job.get("title", "N/A")
    company = job.get("company", "N/A")
    location = job.get("location", "N/A")
    salary = job.get("salary", "N/A")
    job_type = job.get("job_type", "N/A")
    source = job.get("source", "N/A")
    keyword = job.get("keyword", "N/A")
    date_scraped = job.get("date_scraped", "N/A")[:10]
    url = job.get("url", "N/A")

    lines = [
        f"*#{idx} — {title}*",
        f"🏢 {company}",
        f"📍 {location}",
        f"💼 {job_type}  |  💰 {salary}",
        f"🔍 Keyword: `{keyword}`  |  🌐 {source}",
        f"📅 Scraped: {date_scraped}",
    ]
    if url and url != "N/A":
        lines.append(f"🔗 [View Job]({url})")
    return "\n".join(lines)


async def send_long(update_or_msg, text: str, parse_mode: str = "Markdown"):
    """Send a message that may exceed Telegram's 4096-char limit."""
    MAX = 4000
    chunks = [text[i:i+MAX] for i in range(0, len(text), MAX)]
    for chunk in chunks:
        if hasattr(update_or_msg, "reply_text"):
            await update_or_msg.reply_text(chunk, parse_mode=parse_mode, disable_web_page_preview=True)
        else:
            await update_or_msg.message.reply_text(chunk, parse_mode=parse_mode, disable_web_page_preview=True)


# ── Scrape logic ──────────────────────────────────────────────────────────────
async def run_scrape(notify_target=None, source_filter: str = None) -> str:
    """
    Run scraper(s) in a thread pool (blocking Selenium), return summary string.
    notify_target: a message object to send progress updates to.
    source_filter: scrape only this source name (None = all).
    """
    loop = asyncio.get_event_loop()

    results_summary = []
    total_added = 0

    scrapers_to_run = {
        name: mod for name, mod in SCRAPERS.items()
        if source_filter is None or name.lower() == source_filter.lower()
    }

    for name, mod in scrapers_to_run.items():
        if notify_target:
            await notify_target.reply_text(f"⏳ Scraping *{name}*...", parse_mode="Markdown")

        def _run():
            return mod.scrape(KEYWORDS, LOCATIONS, DRIVER_VERSION)

        try:
            jobs = await loop.run_in_executor(None, _run)
            stats = db.add_jobs(jobs)
            summary = (
                f"✅ *{name}*: {stats['added']} new | "
                f"{stats['duplicates']} dupes"
            )
            total_added += stats["added"]
        except Exception as e:
            summary = f"❌ *{name}*: Error — {e}"
            log.exception(f"Scraper {name} failed")

        results_summary.append(summary)

    db_stats = db.stats()
    summary_text = (
        "📊 *Scrape Complete*\n\n"
        + "\n".join(results_summary)
        + f"\n\n📁 Total in DB: *{db_stats['total']}* jobs"
    )
    return summary_text, total_added


# ── Command Handlers ──────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔍 Scrape All", callback_data="scrape_all"),
         InlineKeyboardButton("📋 View Latest 10", callback_data="view_10")],
        [InlineKeyboardButton("📥 Export JSON", callback_data="export_json"),
         InlineKeyboardButton("📊 DB Stats", callback_data="db_stats")],
        [InlineKeyboardButton("🌐 Scrape Indeed", callback_data="scrape_Indeed"),
         InlineKeyboardButton("🔷 Scrape LinkedIn", callback_data="scrape_LinkedIn")],
        [InlineKeyboardButton("🔎 View All", callback_data="view_all"),
         InlineKeyboardButton("🗑️ Clear DB", callback_data="clear_confirm")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = (
        "👷 *Job Scraper Bot*\n\n"
        f"Keywords: `{', '.join(KEYWORDS)}`\n"
        f"Locations: `{', '.join(LOCATIONS)}`\n"
        f"Sources: `{', '.join(SCRAPERS.keys())}`\n"
        f"Auto-scrape: every `{AUTO_INTERVAL_HOURS}h`\n\n"
        "Choose an action:"
    )
    await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode="Markdown")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "*Available Commands:*\n\n"
        "/start — Show main menu\n"
        "/scrape — Scrape all sources now\n"
        "/latest — Show latest 10 jobs\n"
        "/all — Show all jobs in DB\n"
        "/stats — Show DB statistics\n"
        "/export — Export DB to JSON file\n"
        "/help — Show this help\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_scrape(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Starting scrape for all sources...")
    summary, added = await run_scrape(notify_target=update.message)
    await update.message.reply_text(summary, parse_mode="Markdown")

    if added > 0:
        jobs = db.get_all(limit=added)
        await update.message.reply_text(f"🆕 *{added} new job(s) found:*", parse_mode="Markdown")
        for i, job in enumerate(jobs[:added], 1):
            await send_long(update.message, fmt_job(job, i))


async def cmd_latest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    jobs = db.get_all(limit=10)
    if not jobs:
        await update.message.reply_text("📭 No jobs in DB yet. Run /scrape first.")
        return
    await update.message.reply_text(f"📋 *Latest {len(jobs)} job(s):*", parse_mode="Markdown")
    for i, job in enumerate(jobs, 1):
        await send_long(update.message, fmt_job(job, i))


async def cmd_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    jobs = db.get_all()
    if not jobs:
        await update.message.reply_text("📭 No jobs in DB yet. Run /scrape first.")
        return
    await update.message.reply_text(f"📋 *All {len(jobs)} job(s) in DB:*", parse_mode="Markdown")
    for i, job in enumerate(jobs, 1):
        await send_long(update.message, fmt_job(job, i))
        if i % 20 == 0:
            await asyncio.sleep(1)  # avoid flood limits


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = db.stats()
    by_src = "\n".join(f"  • {k}: {v}" for k, v in s["by_source"].items()) or "  (none)"
    by_kw = "\n".join(f"  • {k}: {v}" for k, v in s["by_keyword"].items()) or "  (none)"
    text = (
        f"📊 *Database Stats*\n\n"
        f"Total jobs: *{s['total']}*\n\n"
        f"By source:\n{by_src}\n\n"
        f"By keyword:\n{by_kw}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    path = db.export_json("jobs_export.json")
    await update.message.reply_text(f"💾 Exporting...")
    try:
        with open(path, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=f"jobs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                caption=f"📥 DB export — {db.count()} job(s)",
            )
    except Exception as e:
        await update.message.reply_text(f"❌ Export failed: {e}")


# ── Inline Button Callbacks ───────────────────────────────────────────────────
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "scrape_all":
        await query.message.reply_text("⏳ Starting scrape for all sources...")
        summary, added = await run_scrape(notify_target=query.message)
        await query.message.reply_text(summary, parse_mode="Markdown")
        if added > 0:
            jobs = db.get_all(limit=added)
            await query.message.reply_text(f"🆕 *{added} new job(s):*", parse_mode="Markdown")
            for i, job in enumerate(jobs[:added], 1):
                await send_long(query.message, fmt_job(job, i))

    elif data.startswith("scrape_"):
        source = data.replace("scrape_", "")
        await query.message.reply_text(f"⏳ Scraping *{source}*...", parse_mode="Markdown")
        summary, added = await run_scrape(notify_target=query.message, source_filter=source)
        await query.message.reply_text(summary, parse_mode="Markdown")
        if added > 0:
            jobs = db.get_all(limit=added)
            await query.message.reply_text(f"🆕 *{added} new job(s):*", parse_mode="Markdown")
            for i, job in enumerate(jobs[:added], 1):
                await send_long(query.message, fmt_job(job, i))

    elif data == "view_10":
        jobs = db.get_all(limit=10)
        if not jobs:
            await query.message.reply_text("📭 No jobs yet. Scrape first!")
            return
        await query.message.reply_text(f"📋 *Latest {len(jobs)} jobs:*", parse_mode="Markdown")
        for i, job in enumerate(jobs, 1):
            await send_long(query.message, fmt_job(job, i))

    elif data == "view_all":
        jobs = db.get_all()
        if not jobs:
            await query.message.reply_text("📭 No jobs yet. Scrape first!")
            return
        await query.message.reply_text(f"📋 *All {len(jobs)} jobs in DB:*", parse_mode="Markdown")
        for i, job in enumerate(jobs, 1):
            await send_long(query.message, fmt_job(job, i))
            if i % 20 == 0:
                await asyncio.sleep(1)

    elif data == "db_stats":
        s = db.stats()
        by_src = "\n".join(f"  • {k}: {v}" for k, v in s["by_source"].items()) or "  (none)"
        by_kw = "\n".join(f"  • {k}: {v}" for k, v in s["by_keyword"].items()) or "  (none)"
        text = (
            f"📊 *Database Stats*\n\n"
            f"Total: *{s['total']}*\n\n"
            f"By source:\n{by_src}\n\n"
            f"By keyword:\n{by_kw}"
        )
        await query.message.reply_text(text, parse_mode="Markdown")

    elif data == "export_json":
        path = db.export_json("jobs_export.json")
        try:
            with open(path, "rb") as f:
                await query.message.reply_document(
                    document=f,
                    filename=f"jobs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                    caption=f"📥 DB export — {db.count()} job(s)",
                )
        except Exception as e:
            await query.message.reply_text(f"❌ Export failed: {e}")

    elif data == "clear_confirm":
        total = db.count()
        if total == 0:
            await query.edit_message_text("📭 DB is already empty.")
            return
        keyboard = [[
            InlineKeyboardButton("✅ Yes, delete all", callback_data="clear_execute"),
            InlineKeyboardButton("❌ Cancel", callback_data="clear_cancel"),
        ]]
        await query.edit_message_text(
            f"⚠️ *Are you sure?*\n\nThis will permanently delete *{total}* job(s) from the database.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )

    elif data == "clear_execute":
        removed = db.clear_all()
        await query.edit_message_text(
            f"🗑️ *Done.* Removed *{removed}* job(s). DB is now empty.",
            parse_mode="Markdown",
        )

    elif data == "clear_cancel":
        await query.edit_message_text("↩️ Cancelled. DB unchanged.")


async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total = db.count()
    if total == 0:
        await update.message.reply_text("📭 DB is already empty.")
        return
    keyboard = [[
        InlineKeyboardButton("✅ Yes, delete all", callback_data="clear_execute"),
        InlineKeyboardButton("❌ Cancel", callback_data="clear_cancel"),
    ]]
    await update.message.reply_text(
        f"⚠️ *Are you sure?*\n\nThis will permanently delete *{total}* job(s) from the database.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


# ── Auto-scrape Job ───────────────────────────────────────────────────────────
async def auto_scrape(context: ContextTypes.DEFAULT_TYPE):
    log.info("Auto-scrape triggered.")
    summary, added = await run_scrape()
    msg = f"🤖 *Auto-Scrape*\n\n{summary}"
    if added > 0:
        msg += f"\n\n🆕 {added} new job(s) found and saved!"
    try:
        await context.bot.send_message(
            chat_id=CHAT_ID,
            text=msg,
            parse_mode="Markdown",
        )
    except Exception as e:
        log.error(f"Failed to send auto-scrape notification: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    log.info("Starting Job Scraper Bot...")
    app = Application.builder().token(TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("scrape", cmd_scrape))
    app.add_handler(CommandHandler("latest", cmd_latest))
    app.add_handler(CommandHandler("all", cmd_all))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(CommandHandler("clear", cmd_clear))

    # Inline buttons
    app.add_handler(CallbackQueryHandler(callback_handler))

    # Auto-scrape scheduler
    if AUTO_INTERVAL_HOURS > 0:
        interval_seconds = int(AUTO_INTERVAL_HOURS * 3600)
        app.job_queue.run_repeating(
            auto_scrape,
            interval=interval_seconds,
            first=60,  # first run 60s after startup
        )
        log.info(f"Auto-scrape scheduled every {AUTO_INTERVAL_HOURS}h")

    log.info("Bot is running. Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()