"""
Background job scheduler using APScheduler.

Runs two periodic tasks:
  1. Scan all users for recurring patterns — every 6 hours
  2. Auto-create confirmed recurring transactions — daily at midnight
"""

import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from database import SessionLocal
from models import User
from recurring import scan_recurring_patterns, auto_create_recurring_transactions

logger = logging.getLogger("scheduler")

scheduler = AsyncIOScheduler()


def _scan_all_users():
    """Scan every active user for recurring transaction patterns."""
    db: Session = SessionLocal()
    try:
        users = db.query(User).filter(User.is_active.is_(True)).all()
        total_new = 0
        for user in users:
            try:
                new = scan_recurring_patterns(db, user.id)
                total_new += len(new)
            except Exception as exc:
                logger.warning("Recurring scan failed for user %s: %s", user.id, exc)
        if total_new:
            logger.info("Recurring scan complete — %d new patterns found.", total_new)
    except Exception as exc:
        logger.error("Recurring scan job failed: %s", exc)
    finally:
        db.close()


def _auto_create_job():
    """Auto-create transactions for confirmed recurring patterns."""
    db: Session = SessionLocal()
    try:
        count = auto_create_recurring_transactions(db)
        if count:
            logger.info("Auto-created %d recurring transactions.", count)
    except Exception as exc:
        logger.error("Auto-create job failed: %s", exc)
    finally:
        db.close()


def start_scheduler():
    """Register jobs and start the scheduler."""
    scheduler.add_job(
        _scan_all_users,
        trigger=IntervalTrigger(hours=6),
        id="scan_recurring",
        name="Scan recurring patterns",
        replace_existing=True,
    )
    scheduler.add_job(
        _auto_create_job,
        trigger=CronTrigger(hour=0, minute=0),
        id="auto_create_recurring",
        name="Auto-create recurring transactions",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("📅 Scheduler started with recurring scan (6h) + auto-create (midnight).")


def stop_scheduler():
    """Gracefully shut down the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("📅 Scheduler stopped.")
