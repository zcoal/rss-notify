"""
Flask application factory + poller core.
"""
import os, html, re, hashlib
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify, session
import feedparser
import requests as _requests

from app.db import Base, SessionLocal, init_db, now, hash_password, check_password
from app.models import Feed, FeedItem, User  # noqa – triggers table registration


def _ensure_admin():
    username = os.environ.get("ADMIN_USER", "admin")
    password = os.environ.get("ADMIN_PASS", "admin")
    db = SessionLocal()
    try:
        u = db.query(User).filter_by(username=username).first()
        if not u:
            u = User(username=username, password_hash=hash_password(password))
            db.add(u)
            db.commit()
            print(f"[BOOT] Created admin user: {username}")
    finally:
        db.close()


def create_app():
    app = Flask(__name__)
    secret_key = os.environ.get("APP_SECRET_KEY")
    if not secret_key or secret_key == "change-this-to-a-long-random-string":
        print("[WARN] APP_SECRET_KEY is not set; using a random development secret.", flush=True)
        secret_key = os.urandom(32)
    app.secret_key = secret_key
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    init_db()
    _ensure_admin()

    from app.api import api_bp
    app.register_blueprint(api_bp)

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def spa(path):
        p = os.path.join(os.path.dirname(__file__), "static", "index.html")
        with open(p) as f:
            return f.read()

    return app


def login_required(fn):
    from functools import wraps
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return jsonify({"error": "unauthenticated"}), 401
        return fn(*args, **kwargs)
    return wrapper


# ── Poller ────────────────────────────────────────────────────────────────────
_REQ = None

def _get_req():
    global _REQ
    if _REQ is None:
        _REQ = _requests.Session()
        proxy = os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")
        if proxy:
            _REQ.proxies = {"http": proxy, "https": proxy}
        _REQ.headers.update({"User-Agent": "RssNotify/1.0"})
    return _REQ


def _strip_html(text):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def poll_feeds(log=None):
    db = SessionLocal()
    try:
        feeds = db.query(Feed).filter_by(enabled=True).all()
        log = log if log is not None else []
        log.append(f"[POLL] {len(feeds)} feed(s)")
        for feed in feeds:
            if not _feed_due(feed):
                log.append(f"  [SKIP] {feed.name}: interval not reached")
                continue
            _poll_one_feed(db, feed, log)
        db.commit()
        return log
    finally:
        db.close()


def _feed_due(feed):
    if not feed.last_polled_at:
        return True
    try:
        interval = max(1, int(feed.poll_interval or 60))
    except Exception:
        interval = 60
    return now() - feed.last_polled_at >= timedelta(minutes=interval)


def _poll_one_feed(db, feed, log):
    timeout = int(os.environ.get("FEED_TIMEOUT", "30"))
    try:
        resp = _get_req().get(feed.url, timeout=timeout)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)

        if parsed.bozo and not parsed.entries:
            feed.last_error = str(parsed.bozo_exception)[:500]
            log.append(f"  [ERR] {feed.name}: parse error")
            return

        new_count = 0
        for entry in parsed.entries:
            raw = entry.get("id") or entry.get("link") or entry.get("title", "")
            digest = hashlib.sha256(str(raw).encode()).hexdigest()[:64]
            guid = f"{feed.id}:{digest}"

            if db.query(FeedItem.id).filter_by(feed_id=feed.id, guid=guid).first():
                continue

            title = (entry.get("title") or "").strip() or "(无标题)"
            link = (entry.get("link") or "").strip()
            desc_html = entry.get("summary") or entry.get("description") or ""
            body_text = _strip_html(f"{title} {desc_html}")

            pub_dt = None
            if entry.get("published_parsed"):
                try:
                    pub_dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                except Exception:
                    pass

            matched, matched_keywords = _match_keywords(
                title, body_text, feed.white_keywords or "", feed.black_keywords or ""
            )

            item = FeedItem(
                feed_id=feed.id, guid=guid, title=title, link=link,
                description=desc_html[:10000], body_text=body_text,
                pub_date=pub_dt, received_at=now(), matched=matched,
                matched_keywords="\n".join(matched_keywords),
            )
            db.add(item)
            db.flush()

            if matched:
                _send_push(feed, item)
                item.notified = True
                log.append(f"  [PUSH] {feed.name}: {title[:60]}")

            new_count += 1

        feed.last_polled_at = now()
        feed.last_error = ""
        log.append(f"  [OK] {feed.name}: {new_count} new")
    except Exception as e:
        feed.last_error = str(e)[:500]
        log.append(f"  [ERR] {feed.name}: {e}")


def _keyword_lines(text):
    return [w.strip() for w in (text or "").splitlines() if w.strip()]


def _match_keywords(title, body, white_str, black_str):
    combined = f"{title} {body}".lower()
    black_list = _keyword_lines(black_str)
    if black_list and any(b.lower() in combined for b in black_list):
        return False, []
    white_list = _keyword_lines(white_str)
    if not white_list:
        return True, []
    matched = [w for w in white_list if w.lower() in combined]
    return bool(matched), matched


def _check_keywords(title, body, white_str, black_str):
    return _match_keywords(title, body, white_str, black_str)[0]


def _send_push(feed, item):
    if not feed.notify_urls:
        return
    from apprise import Apprise
    urls = [u.strip() for u in (feed.notify_urls or "").splitlines() if u.strip()]
    if not urls:
        return
    ap = Apprise()
    ap.add(urls)
    title = feed.name
    parts = []
    if item.title:
        parts.append(item.title)
    desc = (item.description or item.body_text or "").strip()
    if desc:
        # strip HTML tags for cleaner push text
        import re as _re
        desc = _re.sub(r"<[^>]+>", "", desc).strip()
        desc = html.unescape(desc)
        if len(desc) > 500:
            desc = desc[:500] + "..."
        parts.append(desc)
    if item.link:
        parts.append(item.link)
    body = "\n\n".join(parts)
    ap.notify(title=title, body=body[:4000])


# ── Message cleanup ───────────────────────────────────────────────────────────
CONFIG_PATH = os.environ.get("CONFIG_PATH", "/data/config.json")


def cleanup_old_items():
    """Delete oldest messages if count exceeds the configured limit."""
    import json
    limit = 5000
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
            limit = int(cfg.get("message_limit", 5000))
    if limit <= 0:
        return 0
    db = SessionLocal()
    try:
        from sqlalchemy import func
        total = db.query(func.count(FeedItem.id)).scalar()
        if total <= limit:
            return 0
        excess = total - limit
        # Delete oldest 'excess' items
        oldest_ids = (
            db.query(FeedItem.id)
            .order_by(FeedItem.received_at.asc())
            .limit(excess)
            .subquery()
        )
        removed = db.query(FeedItem).filter(FeedItem.id.in_(db.query(oldest_ids))).delete(synchronize_session=False)
        db.commit()
        if removed:
            print(f"[CLEANUP] Removed {removed} old messages (limit={limit})", flush=True)
        return removed or 0
    except Exception as e:
        print(f"[CLEANUP] Error: {e}", flush=True)
        return 0
    finally:
        db.close()
