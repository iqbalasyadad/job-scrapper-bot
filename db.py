"""
db.py — JSON-based Job Database Manager
Handles loading, saving, deduplication, and filtering of job listings.
"""

import json
import os
from datetime import datetime
from typing import Optional


DB_PATH = "jobs_db.json"


def _load() -> list[dict]:
    if not os.path.exists(DB_PATH):
        return []
    try:
        with open(DB_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def _save(jobs: list[dict]) -> None:
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)


def _make_uid(job: dict) -> str:
    """
    Unique ID based on title + company + location (case-insensitive, whitespace-normalised).
    This catches duplicates across sources regardless of job_id differences.
    """
    import hashlib
    title    = " ".join(job.get("title",    "").lower().split())
    company  = " ".join(job.get("company",  "").lower().split())
    location = " ".join(job.get("location", "").lower().split())
    key = f"{title}|{company}|{location}"
    return "uid::" + hashlib.md5(key.encode()).hexdigest()[:16]


def add_jobs(new_jobs: list[dict]) -> dict:
    """
    Add new jobs to the DB, skipping duplicates.
    Returns stats: {added, duplicates}
    """
    existing = _load()
    existing_uids = {_make_uid(j) for j in existing}

    added = 0
    duplicates = 0

    for job in new_jobs:
        uid = _make_uid(job)
        if uid in existing_uids:
            duplicates += 1
            continue

        job["_uid"] = uid
        existing.append(job)
        existing_uids.add(uid)
        added += 1

    _save(existing)
    return {"added": added, "duplicates": duplicates}


def get_all(
    source: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = 0,
) -> list[dict]:
    """Return all jobs, optionally filtered."""
    jobs = _load()
    if source:
        jobs = [j for j in jobs if j.get("source", "").lower() == source.lower()]
    if keyword:
        kw = keyword.lower()
        jobs = [j for j in jobs if kw in j.get("title", "").lower() or kw in j.get("keyword", "").lower()]
    # Sort newest first
    jobs.sort(key=lambda j: j.get("date_scraped", ""), reverse=True)
    if limit:
        return jobs[:limit]
    return jobs


def count() -> int:
    return len(_load())


def stats() -> dict:
    jobs = _load()
    sources = {}
    keywords = {}
    for j in jobs:
        src = j.get("source", "Unknown")
        kw = j.get("keyword", "Unknown")
        sources[src] = sources.get(src, 0) + 1
        keywords[kw] = keywords.get(kw, 0) + 1
    return {
        "total": len(jobs),
        "by_source": sources,
        "by_keyword": keywords,
    }


def export_json(path: str = "jobs_export.json") -> str:
    jobs = _load()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)
    return path


def clear_all() -> int:
    """Delete all jobs from the DB. Returns the number of jobs removed."""
    jobs = _load()
    count_removed = len(jobs)
    _save([])
    return count_removed