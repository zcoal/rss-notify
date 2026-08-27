"""
REST API blueprint.
"""
import json, math, os
from flask import Blueprint, jsonify, request, session
from app.db import SessionLocal, now, hash_password, check_password
from app.models import Feed, FeedItem, User
from app import login_required, poll_feeds, _poll_one_feed, _send_push, _match_keywords

api_bp = Blueprint("api", __name__)

CONFIG_PATH = os.environ.get("CONFIG_PATH", "/data/config.json")


def _load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {}


def _save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG_PATH) or ".", exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def _feed_dict(f):
    return {
        "id": f.id, "name": f.name, "url": f.url,
        "description": f.description or "",
        "enabled": f.enabled, "poll_interval": f.poll_interval,
        "white_keywords": f.white_keywords or "",
        "black_keywords": f.black_keywords or "",
        "notify_urls": f.notify_urls or "",
        "created_at": f.created_at.isoformat() if f.created_at else None,
        "updated_at": f.updated_at.isoformat() if f.updated_at else None,
        "last_polled_at": f.last_polled_at.isoformat() if f.last_polled_at else None,
        "last_error": f.last_error or "",
    }


def _item_dict(it):
    matched_keywords = [w.strip() for w in (getattr(it, "matched_keywords", "") or "").splitlines() if w.strip()]
    if not matched_keywords and it.feed:
        _matched, matched_keywords = _match_keywords(
            it.title or "", it.body_text or "", it.feed.white_keywords or "", it.feed.black_keywords or ""
        )
    return {
        "id": it.id, "feed_id": it.feed_id,
        "feed_name": it.feed.name if it.feed else "",
        "title": it.title, "link": it.link,
        "description": (it.description or "")[:2000],
        "body_text": (it.body_text or "")[:1000],
        "pub_date": it.pub_date.isoformat() if it.pub_date else None,
        "received_at": it.received_at.isoformat() if it.received_at else None,
        "matched": it.matched, "matched_keywords": matched_keywords, "notified": it.notified,
    }


# ─── Auth ──────────────────────────────────────────────────────────────────────

@api_bp.route("/api/login", methods=["POST"])
def login():
    data = request.json or {}
    db = SessionLocal()
    try:
        u = db.query(User).filter_by(username=data.get("username", "")).first()
        if not u or not check_password(data.get("password", ""), u.password_hash):
            return jsonify({"error": "用户名或密码错误"}), 401
        session["user_id"] = u.id
        session["username"] = u.username
        return jsonify({"ok": True, "user": u.username})
    finally:
        db.close()


@api_bp.route("/api/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    return jsonify({"ok": True})


@api_bp.route("/api/me", methods=["GET"])
@login_required
def me():
    return jsonify({"user": session.get("username")})


@api_bp.route("/api/password", methods=["PUT"])
@login_required
def change_password():
    data = request.json or {}
    new = data.get("new_password", "")
    confirm = data.get("confirm_password", "")
    if not new or len(new) < 4:
        return jsonify({"error": "密码太短（至少4位）"}), 400
    if new != confirm:
        return jsonify({"error": "两次输入的新密码不一致"}), 400
    db = SessionLocal()
    try:
        u = db.query(User).filter_by(username=session["username"]).first()
        if not u or not check_password(data.get("old_password", ""), u.password_hash):
            return jsonify({"error": "旧密码错误"}), 401
        u.password_hash = hash_password(new)
        db.commit()
        return jsonify({"ok": True})
    finally:
        db.close()


@api_bp.route("/api/username", methods=["PUT"])
@login_required
def change_username():
    data = request.json or {}
    new_username = (data.get("new_username") or "").strip()
    password = data.get("password", "")
    if not new_username:
        return jsonify({"error": "新用户名不能为空"}), 400
    if len(new_username) < 2 or len(new_username) > 80:
        return jsonify({"error": "用户名长度需为 2-80 个字符"}), 400
    db = SessionLocal()
    try:
        u = db.query(User).filter_by(id=session.get("user_id")).first()
        if not u or not check_password(password, u.password_hash):
            return jsonify({"error": "当前密码错误"}), 401
        exists = db.query(User).filter(User.username == new_username, User.id != u.id).first()
        if exists:
            return jsonify({"error": "用户名已存在"}), 400
        u.username = new_username
        db.commit()
        session["username"] = new_username
        return jsonify({"ok": True, "user": new_username})
    finally:
        db.close()


@api_bp.route("/api/profile", methods=["PUT"])
@login_required
def update_profile():
    data = request.json or {}
    username = (data.get("username") or "").strip()
    current_password = data.get("current_password", "")
    new_password = data.get("new_password", "") or ""
    confirm_password = data.get("confirm_password", "") or ""

    if not username:
        return jsonify({"error": "用户名不能为空"}), 400
    if len(username) < 2 or len(username) > 80:
        return jsonify({"error": "用户名长度需为 2-80 个字符"}), 400
    if new_password or confirm_password:
        if len(new_password) < 4:
            return jsonify({"error": "密码太短（至少4位）"}), 400
        if new_password != confirm_password:
            return jsonify({"error": "两次输入的新密码不一致"}), 400

    db = SessionLocal()
    try:
        u = db.query(User).filter_by(id=session.get("user_id")).first()
        if not u:
            return jsonify({"error": "用户不存在"}), 404

        username_changed = username != u.username
        password_changed = bool(new_password)
        if (username_changed or password_changed) and not check_password(current_password, u.password_hash):
            return jsonify({"error": "当前密码错误"}), 401

        if username_changed:
            exists = db.query(User).filter(User.username == username, User.id != u.id).first()
            if exists:
                return jsonify({"error": "用户名已存在"}), 400
            u.username = username
            session["username"] = username

        if password_changed:
            u.password_hash = hash_password(new_password)

        db.commit()
        return jsonify({"ok": True, "user": u.username, "username_changed": username_changed, "password_changed": password_changed})
    finally:
        db.close()


# ─── Feeds CRUD ───────────────────────────────────────────────────────────────

@api_bp.route("/api/feeds", methods=["GET"])
@login_required
def list_feeds():
    db = SessionLocal()
    try:
        feeds = db.query(Feed).order_by(Feed.id.desc()).all()
        return jsonify({"feeds": [_feed_dict(f) for f in feeds]})
    finally:
        db.close()


@api_bp.route("/api/feeds", methods=["POST"])
@login_required
def create_feed():
    data = request.json or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "URL 不能为空"}), 400
    f = Feed(
        name=(data.get("name") or url)[:200], url=url,
        description=(data.get("description") or "")[:500],
        poll_interval=max(1, int(data.get("poll_interval") or 60)),
        white_keywords=(data.get("white_keywords") or "").strip(),
        black_keywords=(data.get("black_keywords") or "").strip(),
        notify_urls=(data.get("notify_urls") or "").strip(),
        enabled=data.get("enabled", True),
    )
    db = SessionLocal()
    try:
        db.add(f); db.commit(); db.refresh(f)
        return jsonify(_feed_dict(f)), 201
    finally:
        db.close()


@api_bp.route("/api/feeds/<int:fid>", methods=["PUT"])
@login_required
def update_feed(fid):
    data = request.json or {}
    db = SessionLocal()
    try:
        f = db.get(Feed, fid)
        if not f:
            return jsonify({"error": "not found"}), 404
        for k in ("name", "url", "description", "white_keywords", "black_keywords", "notify_urls"):
            if k in data:
                setattr(f, k, str(data[k])[:2000].strip())
        if "poll_interval" in data:
            f.poll_interval = max(1, int(data["poll_interval"] or 60))
        if "enabled" in data:
            f.enabled = bool(data["enabled"])
        f.updated_at = now()
        db.commit(); db.refresh(f)
        return jsonify(_feed_dict(f))
    finally:
        db.close()


@api_bp.route("/api/feeds/<int:fid>", methods=["DELETE"])
@login_required
def delete_feed(fid):
    db = SessionLocal()
    try:
        f = db.get(Feed, fid)
        if not f:
            return jsonify({"error": "not found"}), 404
        db.delete(f); db.commit()
        return jsonify({"ok": True})
    finally:
        db.close()


@api_bp.route("/api/feeds/<int:fid>/toggle", methods=["POST"])
@login_required
def toggle_feed(fid):
    db = SessionLocal()
    try:
        f = db.get(Feed, fid)
        if not f:
            return jsonify({"error": "not found"}), 404
        f.enabled = not f.enabled; f.updated_at = now()
        db.commit()
        return jsonify({"ok": True, "enabled": f.enabled})
    finally:
        db.close()


# ─── Feed export / import ─────────────────────────────────────────────────────

@api_bp.route("/api/feeds/export", methods=["GET"])
@login_required
def export_feeds():
    db = SessionLocal()
    try:
        feeds = db.query(Feed).all()
        data = []
        for f in feeds:
            data.append({
                "name": f.name, "url": f.url, "description": f.description or "",
                "enabled": f.enabled, "poll_interval": f.poll_interval,
                "white_keywords": f.white_keywords or "",
                "black_keywords": f.black_keywords or "",
                "notify_urls": f.notify_urls or "",
            })
        return jsonify({"feeds": data})
    finally:
        db.close()


@api_bp.route("/api/feeds/import", methods=["POST"])
@login_required
def import_feeds():
    data = request.json or {}
    feeds = data.get("feeds", [])
    if not isinstance(feeds, list):
        return jsonify({"error": "格式错误"}), 400
    db = SessionLocal()
    try:
        created = 0
        for fd in feeds:
            url = (fd.get("url") or "").strip()
            if not url:
                continue
            f = Feed(
                name=(fd.get("name") or url)[:200], url=url,
                description=(fd.get("description") or "")[:500],
                poll_interval=max(1, int(fd.get("poll_interval") or 60)),
                white_keywords=(fd.get("white_keywords") or "").strip(),
                black_keywords=(fd.get("black_keywords") or "").strip(),
                notify_urls=(fd.get("notify_urls") or "").strip(),
                enabled=fd.get("enabled", True),
            )
            db.add(f)
            created += 1
        db.commit()
        return jsonify({"ok": True, "created": created})
    finally:
        db.close()


# ─── Poll ──────────────────────────────────────────────────────────────────────

@api_bp.route("/api/poll", methods=["POST"])
@login_required
def trigger_poll():
    data = request.json or {}
    fid = data.get("feed_id")
    log = []
    if fid:
        db = SessionLocal()
        try:
            f = db.get(Feed, fid)
            if f:
                db2 = SessionLocal()
                try:
                    _poll_one_feed(db2, f, log)
                    db2.commit()
                finally:
                    db2.close()
            else:
                log.append(f"[ERR] feed {fid} not found")
        finally:
            db.close()
    else:
        poll_feeds(log)
    return jsonify({"log": log})


# ─── Items ─────────────────────────────────────────────────────────────────────

@api_bp.route("/api/items", methods=["GET"])
@login_required
def list_items():
    db = SessionLocal()
    try:
        page = max(1, int(request.args.get("page", 1)))
        limit = min(500, max(1, int(request.args.get("limit", 50))))
        keyword = (request.args.get("keyword") or "").strip()
        filt = request.args.get("filter", "all")
        feed_id = request.args.get("feed_id", type=int)

        q = db.query(FeedItem).join(Feed, Feed.id == FeedItem.feed_id)
        if feed_id:
            q = q.filter(FeedItem.feed_id == feed_id)
        if filt == "matched":
            q = q.filter(FeedItem.matched == True)
        elif filt == "notified":
            q = q.filter(FeedItem.notified == True)
        elif filt == "unread":
            q = q.filter(FeedItem.notified == False, FeedItem.matched == True)
        if keyword:
            q = q.filter(FeedItem.body_text.ilike(f"%{keyword}%"))

        total = q.count()
        pages = max(1, math.ceil(total / limit))
        items = q.order_by(FeedItem.received_at.desc()).limit(limit).offset((page - 1) * limit).all()
        return jsonify({"items": [_item_dict(i) for i in items], "total": total, "page": page, "pages": pages})
    finally:
        db.close()


@api_bp.route("/api/items/<int:iid>", methods=["GET"])
@login_required
def get_item(iid):
    db = SessionLocal()
    try:
        it = db.get(FeedItem, iid)
        if not it:
            return jsonify({"error": "not found"}), 404
        return jsonify(_item_dict(it))
    finally:
        db.close()


@api_bp.route("/api/items/<int:iid>/push", methods=["POST"])
@login_required
def manual_push(iid):
    db = SessionLocal()
    try:
        it = db.get(FeedItem, iid)
        if not it:
            return jsonify({"error": "not found"}), 404
        feed = db.get(Feed, it.feed_id)
        if not feed or not feed.notify_urls:
            return jsonify({"error": "未配置通知 URL"}), 400
        _send_push(feed, it)
        it.notified = True
        db.commit()
        return jsonify({"ok": True})
    finally:
        db.close()


# ─── Stats ─────────────────────────────────────────────────────────────────────

@api_bp.route("/api/stats", methods=["GET"])
@login_required
def stats():
    db = SessionLocal()
    try:
        return jsonify({
            "feeds_total": db.query(Feed).count(),
            "feeds_enabled": db.query(Feed).filter_by(enabled=True).count(),
            "feeds_err": db.query(Feed).filter(Feed.last_error != "").count(),
            "items_total": db.query(FeedItem).count(),
            "items_matched": db.query(FeedItem).filter_by(matched=True).count(),
            "items_notified": db.query(FeedItem).filter_by(notified=True).count(),
        })
    finally:
        db.close()


# ─── Settings ─────────────────────────────────────────────────────────────────

@api_bp.route("/api/settings", methods=["GET"])
@login_required
def get_settings():
    cfg = _load_config()
    return jsonify({"message_limit": cfg.get("message_limit", 5000)})


@api_bp.route("/api/settings", methods=["PUT"])
@login_required
def update_settings():
    data = request.json or {}
    cfg = _load_config()
    if "message_limit" in data:
        v = int(data["message_limit"])
        cfg["message_limit"] = max(100, v) if v > 0 else 0
    _save_config(cfg)
    return jsonify({"ok": True})


@api_bp.route("/api/settings/cleanup", methods=["POST"])
@login_required
def manual_cleanup():
    """Manually trigger message cleanup."""
    from app import cleanup_old_items
    removed = cleanup_old_items()
    return jsonify({"ok": True, "removed": removed})


# ─── Health ────────────────────────────────────────────────────────────────────

@api_bp.route("/api/health", methods=["GET"])
def health():
    return jsonify({"ok": True})
