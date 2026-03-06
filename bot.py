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
from typing import Optional

import yaml
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Message
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
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)

log = logging.getLogger(__name__)

# ── Secrets from .env ─────────────────────────────────────────────────────────
load_dotenv()
TOKEN   = os.environ["BOT_TOKEN"]
CHAT_ID = int(os.environ["CHAT_ID"])  # cast once; used in comparisons

# ── Config ────────────────────────────────────────────────────────────────────
CONFIG_PATH = "config.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def get_runtime_cfg() -> tuple[list, list, str, float]:
    """Return (keywords, locations, driver_version, interval_hours) from disk."""
    cfg = load_config()
    return (
        cfg.get("keywords", ["geophysics"]),
        cfg.get("location", ["Indonesia"]),
        str(cfg.get("driver_version", "145")),
        float(cfg.get("auto_scrape_interval_hours", 0)),
    )


# Initialise globals once at startup
KEYWORDS, LOCATIONS, DRIVER_VERSION, AUTO_INTERVAL_HOURS = get_runtime_cfg()

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


# ── Auth guard ────────────────────────────────────────────────────────────────
def is_authorised(update: Update) -> bool:
    """Reject any message/callback not from the configured CHAT_ID."""
    uid = (
        update.effective_user.id
        if update.effective_user
        else None
    )
    return uid == CHAT_ID


async def reject(update: Update) -> None:
    if update.message:
        await update.message.reply_text("⛔ Unauthorised.")
    elif update.callback_query:
        await update.callback_query.answer("⛔ Unauthorised.", show_alert=True)


# ── UI helpers ────────────────────────────────────────────────────────────────
def main_menu_keyboard() -> InlineKeyboardMarkup:
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


def main_menu_text() -> str:
    kw, loc, _, interval = get_runtime_cfg()
    return (
        "👷 *Job Scraper Bot*\n\n"
        f"Keywords: `{', '.join(kw)}`\n"
        f"Locations: `{', '.join(loc)}`\n"
        f"Sources: `{', '.join(SCRAPERS.keys())}`\n"
        f"Auto-scrape: every `{interval}h`\n\n"
        "Choose an action:"
    )


def config_menu_keyboard() -> InlineKeyboardMarkup:
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
        f"*#{idx} — {job.get('title', 'N/A')}*",
        f"🏢 {job.get('company', 'N/A')}",
        f"📍 {job.get('location', 'N/A')}",
        f"💼 {job.get('job_type', 'N/A')}  |  💰 {job.get('salary', 'N/A')}",
        f"🔍 Keyword: `{job.get('keyword', 'N/A')}`  |  🌐 {job.get('source', 'N/A')}",
        f"📅 Scraped: {str(job.get('date_scraped', 'N/A'))[:10]}",
    ]
    url = job.get("url", "")
    if url and url != "N/A":
        lines.append(f"🔗 [View Job]({url})")
    return "\n".join(lines)


async def send_long(msg: Message, text: str, parse_mode: str = "Markdown") -> None:
    """Split and send text that exceeds Telegram's 4096-char limit."""
    for chunk in [text[i:i + 4000] for i in range(0, len(text), 4000)]:
        await msg.reply_text(chunk, parse_mode=parse_mode, disable_web_page_preview=True)


async def send_jobs(msg: Message, jobs: list, label: str) -> None:
    """Helper to send a labelled list of jobs."""
    await msg.reply_text(label, parse_mode="Markdown")
    for i, job in enumerate(jobs, 1):
        await send_long(msg, fmt_job(job, i))
        if i % 20 == 0:
            await asyncio.sleep(1)  # avoid flood limits on large lists


# ── Scrape logic ──────────────────────────────────────────────────────────────
async def run_scrape(
    notify_target: Optional[Message] = None,
    source_filter: Optional[str] = None,
) -> tuple[str, int]:
    """
    Run scrapers for every (keyword, location) combination.

    Fixes vs original:
    - `_run` closure now captures kw/loc via default args to avoid late-binding.
    - The inner for-loops actually trigger a scrape per pair (was broken before).
    - `jobs` is no longer fetched twice.
    """
    loop = asyncio.get_event_loop()
    results_summary: list[str] = []
    total_added = 0

    kw_list, loc_list, drv_ver, _ = get_runtime_cfg()

    scrapers_to_run = {
        name: mod for name, mod in SCRAPERS.items()
        if source_filter is None or name.lower() == source_filter.lower()
    }

    loading_msg: Optional[Message] = None
    if notify_target:
        loading_msg = await notify_target.reply_text("🔎 Starting scraping...")

    for name, mod in scrapers_to_run.items():
        for kw in kw_list:
            for loc in loc_list:
                if loading_msg:
                    try:
                        await loading_msg.edit_text(
                            f"🔎 Scraping *{name}*\n"
                            f"🔑 Keyword: `{kw}`\n"
                            f"📍 Location: `{loc}`",
                            parse_mode="Markdown",
                        )
                    except Exception:
                        pass  # edit can fail if message is unchanged — safe to ignore

                # FIX: capture loop variables via default args, not by closure
                def _run(m=mod, k=kw, l=loc, d=drv_ver):
                    return m.scrape([k], [l], d)

                try:
                    jobs  = await loop.run_in_executor(None, _run)
                    stats = db.add_jobs(jobs)
                    results_summary.append(
                        f"✅ *{name}* (`{kw}` / `{loc}`): "
                        f"{stats['added']} new | {stats['duplicates']} dupes"
                    )
                    total_added += stats["added"]
                except Exception as e:
                    results_summary.append(f"❌ *{name}* (`{kw}` / `{loc}`): Error — {e}")
                    log.exception("Scraper %s failed for kw=%s loc=%s", name, kw, loc)

    summary_text = (
        "📊 *Scrape Complete*\n\n"
        + "\n".join(results_summary)
        + f"\n\n📁 Total in DB: *{db.stats()['total']}* jobs"
    )

    if loading_msg:
        try:
            await loading_msg.edit_text(
                "✅ Scraping finished!\n\n" + summary_text,
                parse_mode="Markdown",
            )
        except Exception:
            pass

    return summary_text, total_added


# ── Shared scrape-and-report helper ──────────────────────────────────────────
async def do_scrape_and_report(msg: Message, source_filter: Optional[str] = None) -> None:
    summary, added = await run_scrape(notify_target=msg, source_filter=source_filter)
    await msg.reply_text(summary, parse_mode="Markdown")
    if added > 0:
        jobs = db.get_all(limit=added)
        await send_jobs(msg, jobs[:added], f"🆕 *{added} new job(s):*")


# ── Command handlers ──────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorised(update):
        return await reject(update)
    context.user_data.pop(EDITING_KEY, None)
    await update.message.reply_text(
        main_menu_text(), reply_markup=main_menu_keyboard(), parse_mode="Markdown"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorised(update):
        return await reject(update)
    await update.message.reply_text(
        "*Commands:*\n\n"
        "/start — Main menu\n/scrape — Scrape all now\n/latest — Latest 10 jobs\n"
        "/all — All jobs\n/stats — DB stats\n/export — Export JSON\n"
        "/config — View & edit config\n/clear — Clear DB\n/cancel — Cancel editing\n/help — Help",
        parse_mode="Markdown",
    )


async def cmd_scrape(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorised(update):
        return await reject(update)
    await do_scrape_and_report(update.message)


async def cmd_latest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorised(update):
        return await reject(update)
    jobs = db.get_all(limit=10)
    if not jobs:
        await update.message.reply_text("📭 No jobs in DB yet. Run /scrape first.")
        return
    await send_jobs(update.message, jobs, f"📋 *Latest {len(jobs)} job(s):*")


async def cmd_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorised(update):
        return await reject(update)
    jobs = db.get_all()
    if not jobs:
        await update.message.reply_text("📭 No jobs in DB yet. Run /scrape first.")
        return
    await send_jobs(update.message, jobs, f"📋 *All {len(jobs)} job(s) in DB:*")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorised(update):
        return await reject(update)
    await _reply_stats(update.message)


async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorised(update):
        return await reject(update)
    await _reply_export(update.message)


async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorised(update):
        return await reject(update)
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


async def cmd_config(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorised(update):
        return await reject(update)
    context.user_data.pop(EDITING_KEY, None)
    await update.message.reply_text(
        config_summary(), reply_markup=config_menu_keyboard(), parse_mode="Markdown"
    )


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorised(update):
        return await reject(update)
    if context.user_data.pop(EDITING_KEY, None):
        await update.message.reply_text("↩️ Edit cancelled.", reply_markup=config_menu_keyboard())
    else:
        await update.message.reply_text("Nothing to cancel.")


# ── Config value receiver ─────────────────────────────────────────────────────
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Catches free-text replies when the user is editing a config field."""
    if not is_authorised(update):
        return

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

        # Refresh module-level globals after a config save
        global KEYWORDS, LOCATIONS, DRIVER_VERSION, AUTO_INTERVAL_HOURS
        KEYWORDS, LOCATIONS, DRIVER_VERSION, AUTO_INTERVAL_HOURS = get_runtime_cfg()

        context.user_data.pop(EDITING_KEY, None)
        display = ", ".join(value) if isinstance(value, list) else str(value)
        await update.message.reply_text(
            f"✅ *{meta['label']}* updated to:\n`{display}`",
            parse_mode="Markdown",
        )
        await update.message.reply_text(
            config_summary(), reply_markup=config_menu_keyboard(), parse_mode="Markdown"
        )

    except Exception as e:
        await update.message.reply_text(
            f"❌ Invalid value: {e}\n\nTry again or send /cancel.",
            parse_mode="Markdown",
        )


# ── Reusable reply helpers (shared between commands + callbacks) ───────────────
async def _reply_stats(msg: Message) -> None:
    s      = db.stats()
    by_src = "\n".join(f"  • {k}: {v}" for k, v in s["by_source"].items())  or "  (none)"
    by_kw  = "\n".join(f"  • {k}: {v}" for k, v in s["by_keyword"].items()) or "  (none)"
    await msg.reply_text(
        f"📊 *Database Stats*\n\nTotal: *{s['total']}*\n\nBy source:\n{by_src}\n\nBy keyword:\n{by_kw}",
        parse_mode="Markdown",
    )


async def _reply_export(msg: Message) -> None:
    path = db.export_json("jobs_export.json")
    try:
        with open(path, "rb") as f:
            await msg.reply_document(
                document=f,
                filename=f"jobs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                caption=f"📥 DB export — {db.count()} job(s)",
            )
    except Exception as e:
        await msg.reply_text(f"❌ Export failed: {e}")


# ── Callback handler ──────────────────────────────────────────────────────────
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorised(update):
        return await reject(update)

    query = update.callback_query
    await query.answer()
    data  = query.data
    msg   = query.message  # shorthand

    if data == "main_menu":
        await query.edit_message_text(
            main_menu_text(), reply_markup=main_menu_keyboard(), parse_mode="Markdown"
        )

    elif data == "scrape_all":
        await do_scrape_and_report(msg)

    elif data.startswith("scrape_"):
        source = data.removeprefix("scrape_")
        await do_scrape_and_report(msg, source_filter=source)

    elif data == "view_10":
        jobs = db.get_all(limit=10)
        if not jobs:
            await msg.reply_text("📭 No jobs yet. Scrape first!")
            return
        await send_jobs(msg, jobs, f"📋 *Latest {len(jobs)} jobs:*")

    elif data == "view_all":
        jobs = db.get_all()
        if not jobs:
            await msg.reply_text("📭 No jobs yet. Scrape first!")
            return
        await send_jobs(msg, jobs, f"📋 *All {len(jobs)} jobs in DB:*")

    elif data == "db_stats":
        await _reply_stats(msg)

    elif data == "export_json":
        await _reply_export(msg)

    elif data == "clear_confirm":
        total = db.count()
        if total == 0:
            await query.answer("📭 DB is already empty.", show_alert=True)
            return
        await msg.reply_text(
            f"⚠️ *Are you sure?*\n\nThis will permanently delete *{total}* job(s).",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Yes, delete all", callback_data="clear_execute"),
                InlineKeyboardButton("❌ Cancel",          callback_data="clear_cancel"),
            ]]),
            parse_mode="Markdown",
        )

    elif data == "clear_execute":
        removed = db.clear_all()
        try:
            await msg.delete()
        except Exception:
            pass
        await query.message.reply_text(  # msg ref may be stale after delete
            f"🗑️ *Done.* Removed *{removed}* job(s). DB is now empty.",
            parse_mode="Markdown",
        )

    elif data == "clear_cancel":
        try:
            await msg.delete()
        except Exception:
            pass

    elif data == "config_menu":
        context.user_data.pop(EDITING_KEY, None)
        await query.edit_message_text(
            config_summary(), reply_markup=config_menu_keyboard(), parse_mode="Markdown"
        )

    elif data in CFG_FIELDS:
        context.user_data[EDITING_KEY] = data
        meta = CFG_FIELDS[data]
        await query.edit_message_text(
            f"✏️ *Edit {meta['label']}*\n\n{meta['hint']}\n\nSend /cancel to abort.",
            parse_mode="Markdown",
        )


# ── Auto-scrape ───────────────────────────────────────────────────────────────
async def auto_scrape(context: ContextTypes.DEFAULT_TYPE) -> None:
    log.info("Auto-scrape triggered.")
    summary, added = await run_scrape()
    msg = f"🤖 *Auto-Scrape*\n\n{summary}"
    if added > 0:
        msg += f"\n\n🆕 {added} new job(s) found and saved!"
    try:
        await context.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
    except Exception as e:
        log.error("Auto-scrape notify failed: %s", e)


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
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
    # Free-text handler — must come last
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    _, _, _, interval = get_runtime_cfg()
    if interval > 0:
        app.job_queue.run_repeating(
            auto_scrape, interval=int(interval * 3600), first=60
        )
        log.info("Auto-scrape scheduled every %sh", interval)

    log.info("Bot is running. Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()