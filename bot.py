"""
bot.py — Telegram Job Scraper Bot

Requirements:
    pip install "python-telegram-bot[job-queue]>=20.0,<21.0" seleniumbase pyyaml python-dotenv

Run:
    python bot.py
"""

import asyncio
import logging
import os
from datetime import datetime

import yaml
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

import db
import scraper_indeed
import scraper_linkedin

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

# ── Secrets from .env ─────────────────────────────────────────────────────────
load_dotenv()
TOKEN   = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

# ── Config ────────────────────────────────────────────────────────────────────
CONFIG_PATH = "config.yaml"

def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)

def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

def reload_globals():
    global CONFIG, KEYWORDS, LOCATIONS, DRIVER_VERSION, AUTO_INTERVAL_HOURS
    CONFIG               = load_config()
    KEYWORDS             = CONFIG.get("keywords", ["geophysics"])
    LOCATIONS            = CONFIG.get("location", ["Indonesia"])
    DRIVER_VERSION       = str(CONFIG.get("driver_version", "145"))
    AUTO_INTERVAL_HOURS  = float(CONFIG.get("auto_scrape_interval_hours", 0))

CONFIG              = load_config()
KEYWORDS            = CONFIG.get("keywords", ["geophysics"])
LOCATIONS           = CONFIG.get("location", ["Indonesia"])
DRIVER_VERSION      = str(CONFIG.get("driver_version", "145"))
AUTO_INTERVAL_HOURS = float(CONFIG.get("auto_scrape_interval_hours", 0))

SCRAPERS = {"Indeed": scraper_indeed, "LinkedIn": scraper_linkedin}

# user_data key used to track which field is being edited
EDITING_KEY = "editing_field"

# Config field metadata
CFG_FIELDS = {
    "cfg_keywords": {
        "label": "Keywords",
        "hint":  "Send a comma-separated list.\nExample: `geophysics, seismic, geology`",
        "key":   "keywords",
        "type":  "list",
    },
    "cfg_locations": {
        "label": "Locations",
        "hint":  "Send a comma-separated list.\nExample: `Indonesia, Malaysia`",
        "key":   "location",
        "type":  "list",
    },
    "cfg_driver": {
        "label": "Driver Version",
        "hint":  "Send your Chrome version number.\nExample: `145`",
        "key":   "driver_version",
        "type":  "str",
    },
    "cfg_interval": {
        "label": "Auto-scrape Interval (hours)",
        "hint":  "Send a number. Use `0` to disable.\nExample: `6`",
        "key":   "auto_scrape_interval_hours",
        "type":  "float",
    },
}


# ── UI helpers ────────────────────────────────────────────────────────────────
def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Scrape All",       callback_data="scrape_all"),
         InlineKeyboardButton("📋 View Latest 10",   callback_data="view_10")],
        [InlineKeyboardButton("📥 Export JSON",      callback_data="export_json"),
         InlineKeyboardButton("📊 DB Stats",         callback_data="db_stats")],
        [InlineKeyboardButton("🌐 Scrape Indeed",    callback_data="scrape_Indeed"),
         InlineKeyboardButton("🔷 Scrape LinkedIn",  callback_data="scrape_LinkedIn")],
        [InlineKeyboardButton("🔎 View All",         callback_data="view_all"),
         InlineKeyboardButton("🗑️ Clear DB",         callback_data="clear_confirm")],
        [InlineKeyboardButton("⚙️ Edit Config",      callback_data="config_menu")],
    ])

def main_menu_text():
    return (
        "👷 *Job Scraper Bot*\n\n"
        f"Keywords: `{', '.join(KEYWORDS)}`\n"
        f"Locations: `{', '.join(LOCATIONS)}`\n"
        f"Sources: `{', '.join(SCRAPERS.keys())}`\n"
        f"Auto-scrape: every `{AUTO_INTERVAL_HOURS}h`\n\n"
        "Choose an action:"
    )

def config_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 Keywords",          callback_data="cfg_keywords"),
         InlineKeyboardButton("📍 Locations",         callback_data="cfg_locations")],
        [InlineKeyboardButton("🖥️ Driver Version",    callback_data="cfg_driver"),
         InlineKeyboardButton("⏱️ Auto-scrape (hrs)", callback_data="cfg_interval")],
        [InlineKeyboardButton("↩️ Back to Menu",       callback_data="main_menu")],
    ])

def config_summary() -> str:
    cfg = load_config()
    kw  = ", ".join(cfg.get("keywords", []))
    loc = ", ".join(cfg.get("location", []))
    dv  = cfg.get("driver_version", "N/A")
    ai  = cfg.get("auto_scrape_interval_hours", 0)
    return (
        "⚙️ *Config Settings*\n\n"
        f"🔑 Keywords: `{kw}`\n"
        f"📍 Locations: `{loc}`\n"
        f"🖥️ Driver version: `{dv}`\n"
        f"⏱️ Auto-scrape interval: `{ai}h`\n\n"
        "Tap a field to edit it:"
    )

def fmt_job(job: dict, idx: int) -> str:
    lines = [
        f"*#{idx} — {job.get('title','N/A')}*",
        f"🏢 {job.get('company','N/A')}",
        f"📍 {job.get('location','N/A')}",
        f"💼 {job.get('job_type','N/A')}  |  💰 {job.get('salary','N/A')}",
        f"🔍 Keyword: `{job.get('keyword','N/A')}`  |  🌐 {job.get('source','N/A')}",
        f"📅 Scraped: {job.get('date_scraped','N/A')[:10]}",
    ]
    url = job.get("url", "N/A")
    if url and url != "N/A":
        lines.append(f"🔗 [View Job]({url})")
    return "\n".join(lines)

async def send_long(msg, text: str, parse_mode: str = "Markdown"):
    for chunk in [text[i:i+4000] for i in range(0, len(text), 4000)]:
        await msg.reply_text(chunk, parse_mode=parse_mode, disable_web_page_preview=True)


# ── Scrape logic ──────────────────────────────────────────────────────────────
async def run_scrape(notify_target=None, source_filter: str = None):
    loop = asyncio.get_event_loop()
    results_summary, total_added = [], 0

    scrapers_to_run = {
        n: m for n, m in SCRAPERS.items()
        if source_filter is None or n.lower() == source_filter.lower()
    }

    for name, mod in scrapers_to_run.items():
        if notify_target:
            await notify_target.reply_text(f"⏳ Scraping *{name}*...", parse_mode="Markdown")

        def _run(m=mod):
            return m.scrape(KEYWORDS, LOCATIONS, DRIVER_VERSION)

        try:
            jobs  = await loop.run_in_executor(None, _run)
            stats = db.add_jobs(jobs)
            results_summary.append(f"✅ *{name}*: {stats['added']} new | {stats['duplicates']} dupes")
            total_added += stats["added"]
        except Exception as e:
            results_summary.append(f"❌ *{name}*: Error — {e}")
            log.exception(f"Scraper {name} failed")

    summary_text = (
        "📊 *Scrape Complete*\n\n"
        + "\n".join(results_summary)
        + f"\n\n📁 Total in DB: *{db.stats()['total']}* jobs"
    )
    return summary_text, total_added


# ── Command handlers ──────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop(EDITING_KEY, None)
    await update.message.reply_text(main_menu_text(), reply_markup=main_menu_keyboard(), parse_mode="Markdown")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*Commands:*\n\n"
        "/start — Main menu\n/scrape — Scrape all now\n/latest — Latest 10 jobs\n"
        "/all — All jobs\n/stats — DB stats\n/export — Export JSON\n"
        "/config — View & edit config\n/clear — Clear DB\n/cancel — Cancel editing\n/help — Help",
        parse_mode="Markdown",
    )

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
            await asyncio.sleep(1)

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = db.stats()
    by_src = "\n".join(f"  • {k}: {v}" for k, v in s["by_source"].items())  or "  (none)"
    by_kw  = "\n".join(f"  • {k}: {v}" for k, v in s["by_keyword"].items()) or "  (none)"
    await update.message.reply_text(
        f"📊 *Database Stats*\n\nTotal: *{s['total']}*\n\nBy source:\n{by_src}\n\nBy keyword:\n{by_kw}",
        parse_mode="Markdown",
    )

async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    path = db.export_json("jobs_export.json")
    try:
        with open(path, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=f"jobs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                caption=f"📥 DB export — {db.count()} job(s)",
            )
    except Exception as e:
        await update.message.reply_text(f"❌ Export failed: {e}")

async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total = db.count()
    if total == 0:
        await update.message.reply_text("📭 DB is already empty.")
        return
    await update.message.reply_text(
        f"⚠️ *Are you sure?*\n\nThis will permanently delete *{total}* job(s).",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Yes, delete all", callback_data="clear_execute"),
            InlineKeyboardButton("❌ Cancel",          callback_data="clear_cancel"),
        ]]),
        parse_mode="Markdown",
    )

async def cmd_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop(EDITING_KEY, None)
    await update.message.reply_text(config_summary(), reply_markup=config_menu_keyboard(), parse_mode="Markdown")

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.pop(EDITING_KEY, None):
        await update.message.reply_text(
            "↩️ Edit cancelled.",
            reply_markup=config_menu_keyboard(),
        )
    else:
        await update.message.reply_text("Nothing to cancel.")


# ── Config value receiver (plain message handler) ─────────────────────────────
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Catches free-text replies when the user is editing a config field."""
    field_key = context.user_data.get(EDITING_KEY)
    if not field_key:
        return  # not in an editing session — ignore

    meta = CFG_FIELDS[field_key]
    text = update.message.text.strip()
    cfg  = load_config()

    try:
        if meta["type"] == "list":
            value = [v.strip() for v in text.split(",") if v.strip()]
            if not value:
                raise ValueError("List cannot be empty.")
        elif meta["type"] == "float":
            value = float(text)
            if value < 0:
                raise ValueError("Must be >= 0.")
        else:
            value = text

        cfg[meta["key"]] = value
        save_config(cfg)
        reload_globals()
        context.user_data.pop(EDITING_KEY, None)

        display = ", ".join(value) if isinstance(value, list) else str(value)
        await update.message.reply_text(
            f"✅ *{meta['label']}* updated to:\n`{display}`",
            parse_mode="Markdown",
        )
        # Show refreshed config summary
        await update.message.reply_text(
            config_summary(),
            reply_markup=config_menu_keyboard(),
            parse_mode="Markdown",
        )

    except Exception as e:
        await update.message.reply_text(
            f"❌ Invalid value: {e}\n\nTry again or send /cancel.",
            parse_mode="Markdown",
        )


# ── Callback handler ──────────────────────────────────────────────────────────
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data

    if data == "main_menu":
        reload_globals()
        await query.edit_message_text(main_menu_text(), reply_markup=main_menu_keyboard(), parse_mode="Markdown")

    elif data == "scrape_all":
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
        # await query.message.reply_text(f"⏳ Scraping *{source}*...", parse_mode="Markdown")
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
        s      = db.stats()
        by_src = "\n".join(f"  • {k}: {v}" for k, v in s["by_source"].items())  or "  (none)"
        by_kw  = "\n".join(f"  • {k}: {v}" for k, v in s["by_keyword"].items()) or "  (none)"
        await query.message.reply_text(
            f"📊 *Database Stats*\n\nTotal: *{s['total']}*\n\nBy source:\n{by_src}\n\nBy keyword:\n{by_kw}",
            parse_mode="Markdown",
        )

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
            await query.answer("📭 DB is already empty.", show_alert=True)
            return
        await query.message.reply_text(
            f"⚠️ *Are you sure?*\n\nThis will permanently delete *{total}* job(s).",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Yes, delete all", callback_data="clear_execute"),
                InlineKeyboardButton("❌ Cancel",          callback_data="clear_cancel"),
            ]]),
            parse_mode="Markdown",
        )

    elif data == "clear_execute":
        removed = db.clear_all()
        await query.message.delete()
        await query.message.reply_text(
            f"🗑️ *Done.* Removed *{removed}* job(s). DB is now empty.",
            parse_mode="Markdown",
        )

    elif data == "clear_cancel":
        await query.message.delete()

    elif data == "config_menu":
        context.user_data.pop(EDITING_KEY, None)
        await query.edit_message_text(config_summary(), reply_markup=config_menu_keyboard(), parse_mode="Markdown")

    elif data in CFG_FIELDS:
        # Store which field is being edited, then prompt
        context.user_data[EDITING_KEY] = data
        meta = CFG_FIELDS[data]
        await query.edit_message_text(
            f"✏️ *Edit {meta['label']}*\n\n{meta['hint']}\n\nSend /cancel to abort.",
            parse_mode="Markdown",
        )


# ── Auto-scrape ───────────────────────────────────────────────────────────────
async def auto_scrape(context: ContextTypes.DEFAULT_TYPE):
    log.info("Auto-scrape triggered.")
    summary, added = await run_scrape()
    msg = f"🤖 *Auto-Scrape*\n\n{summary}"
    if added > 0:
        msg += f"\n\n🆕 {added} new job(s) found and saved!"
    try:
        await context.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
    except Exception as e:
        log.error(f"Auto-scrape notify failed: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    log.info("Starting Job Scraper Bot...")
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("help",   cmd_help))
    app.add_handler(CommandHandler("scrape", cmd_scrape))
    app.add_handler(CommandHandler("latest", cmd_latest))
    app.add_handler(CommandHandler("all",    cmd_all))
    app.add_handler(CommandHandler("stats",  cmd_stats))
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(CommandHandler("clear",  cmd_clear))
    app.add_handler(CommandHandler("config", cmd_config))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CallbackQueryHandler(callback_handler))
    # Free-text handler for config editing — must be last
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    if AUTO_INTERVAL_HOURS > 0:
        app.job_queue.run_repeating(auto_scrape, interval=int(AUTO_INTERVAL_HOURS * 3600), first=60)
        log.info(f"Auto-scrape scheduled every {AUTO_INTERVAL_HOURS}h")

    log.info("Bot is running. Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()