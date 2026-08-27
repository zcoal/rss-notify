import importlib
import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load_app_with_temp_db():
    tmpdir = tempfile.TemporaryDirectory()
    os.environ["DB_PATH"] = os.path.join(tmpdir.name, "test.db")
    os.environ["CONFIG_PATH"] = os.path.join(tmpdir.name, "config.json")
    os.environ["ADMIN_USER"] = "admin"
    os.environ["ADMIN_PASS"] = "changeme"
    os.environ["APP_SECRET_KEY"] = "test-secret"

    import app.db as dbmod
    import app.models as models
    import app.api as apimod
    import app as appmod

    importlib.reload(dbmod)
    importlib.reload(models)
    importlib.reload(appmod)
    importlib.reload(apimod)
    flask_app = appmod.create_app()
    flask_app.config.update(TESTING=True)
    return flask_app, tmpdir


def _login(client):
    return client.post("/api/login", json={"username": "admin", "password": "changeme"})


def test_change_username_requires_password_and_updates_session():
    flask_app, tmpdir = _load_app_with_temp_db()
    try:
        client = flask_app.test_client()
        assert _login(client).status_code == 200

        bad = client.put("/api/username", json={"new_username": "root", "password": "wrong"})
        assert bad.status_code == 401

        ok = client.put("/api/username", json={"new_username": "root", "password": "changeme"})
        assert ok.status_code == 200
        assert ok.get_json()["user"] == "root"

        me = client.get("/api/me")
        assert me.status_code == 200
        assert me.get_json()["user"] == "root"

        client.post("/api/logout")
        assert client.post("/api/login", json={"username": "admin", "password": "changeme"}).status_code == 401
        assert client.post("/api/login", json={"username": "root", "password": "changeme"}).status_code == 200
    finally:
        tmpdir.cleanup()


def test_feed_interval_can_be_less_than_five_minutes():
    flask_app, tmpdir = _load_app_with_temp_db()
    try:
        client = flask_app.test_client()
        assert _login(client).status_code == 200
        created = client.post(
            "/api/feeds",
            json={"name": "Test", "url": "https://example.com/rss.xml", "poll_interval": 1},
        )
        assert created.status_code == 201
        assert created.get_json()["poll_interval"] == 1

        feed_id = created.get_json()["id"]
        updated = client.put(f"/api/feeds/{feed_id}", json={"poll_interval": 2})
        assert updated.status_code == 200
        assert updated.get_json()["poll_interval"] == 2
    finally:
        tmpdir.cleanup()


def test_item_response_includes_matched_keyword_tags_and_manual_push_does_not_change_match_state():
    flask_app, tmpdir = _load_app_with_temp_db()
    try:
        client = flask_app.test_client()
        assert _login(client).status_code == 200

        from app.db import SessionLocal
        from app.models import Feed, FeedItem

        db = SessionLocal()
        try:
            feed = Feed(
                name="Test Feed",
                url="https://example.com/rss.xml",
                white_keywords="alpha\nbeta",
                notify_urls="json://localhost",
            )
            db.add(feed)
            db.commit()
            db.refresh(feed)

            matched_item = FeedItem(
                feed_id=feed.id,
                guid="matched-1",
                title="Alpha and beta news",
                body_text="Alpha and beta news",
                matched=True,
                matched_keywords="alpha\nbeta",
                notified=False,
            )
            manual_item = FeedItem(
                feed_id=feed.id,
                guid="manual-1",
                title="Manual push only",
                body_text="Manual push only",
                matched=False,
                matched_keywords="",
                notified=False,
            )
            db.add_all([matched_item, manual_item])
            db.commit()
            db.refresh(manual_item)
            manual_id = manual_item.id
        finally:
            db.close()

        items = client.get("/api/items").get_json()["items"]
        matched = next(i for i in items if i["title"] == "Alpha and beta news")
        assert matched["matched_keywords"] == ["alpha", "beta"]

        pushed = client.post(f"/api/items/{manual_id}/push")
        assert pushed.status_code == 200

        db = SessionLocal()
        try:
            item = db.get(FeedItem, manual_id)
            assert item.notified is True
            assert item.matched is False
            assert item.matched_keywords == ""
        finally:
            db.close()
    finally:
        tmpdir.cleanup()
