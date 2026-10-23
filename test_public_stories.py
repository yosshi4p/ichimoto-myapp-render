from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path


_temporary_directory = tempfile.TemporaryDirectory()
_previous_database_url = os.environ.get("DATABASE_URL")
_previous_public_story_ids = os.environ.get("PUBLIC_STORY_IDS")

database_path = Path(_temporary_directory.name) / "test_stories.db"
os.environ["DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"
os.environ["PUBLIC_STORY_IDS"] = "1"

from app import Story, app, db  # noqa: E402


class PublicStoryVisibilityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True
        with app.app_context():
            db.drop_all()
            db.create_all()
            db.session.add_all([
                Story(
                    id=1,
                    title="公開作品",
                    content="公開作品の本文",
                ),
                Story(
                    id=2,
                    title="非公開作品",
                    content="非公開作品の本文",
                ),
            ])
            db.session.commit()

    @classmethod
    def tearDownClass(cls):
        with app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()

        if _previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = _previous_database_url

        if _previous_public_story_ids is None:
            os.environ.pop("PUBLIC_STORY_IDS", None)
        else:
            os.environ["PUBLIC_STORY_IDS"] = _previous_public_story_ids

        _temporary_directory.cleanup()

    def setUp(self):
        os.environ["PUBLIC_STORY_IDS"] = "1"
        self.client = app.test_client()

    def test_stories_page_shows_only_public_story(self):
        response = self.client.get("/stories")

        self.assertEqual(response.status_code, 200)
        self.assertIn("公開作品", response.get_data(as_text=True))
        self.assertNotIn("非公開作品", response.get_data(as_text=True))

    def test_api_returns_only_public_story(self):
        response = self.client.get("/api/stories")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            [{
                "id": 1,
                "title": "公開作品",
                "excerpt": "公開作品の本文",
            }],
        )

    def test_api_allows_sakura_origin(self):
        origin = "https://ichimoto-yoshio.com"

        response = self.client.get(
            "/api/stories",
            headers={"Origin": origin},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Origin"),
            origin,
        )
        self.assertIn("Origin", response.vary)

    def test_api_allows_render_origin(self):
        origin = "https://www.ichimoto-yoshio.com"

        response = self.client.get(
            "/api/stories",
            headers={"Origin": origin},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Origin"),
            origin,
        )
        self.assertIn("Origin", response.vary)

    def test_api_does_not_allow_unapproved_origin(self):
        response = self.client.get(
            "/api/stories",
            headers={"Origin": "https://example.com"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)

    def test_cors_is_not_added_to_non_api_routes(self):
        response = self.client.get(
            "/stories",
            headers={"Origin": "https://ichimoto-yoshio.com"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)

    def test_public_story_detail_is_available(self):
        response = self.client.get("/stories/1")

        self.assertEqual(response.status_code, 200)
        self.assertIn("公開作品の本文", response.get_data(as_text=True))

    def test_private_story_detail_returns_not_found(self):
        response = self.client.get("/stories/2")

        self.assertEqual(response.status_code, 404)

    def test_admin_list_still_shows_all_stories(self):
        with self.client.session_transaction() as session:
            session["admin_logged_in"] = True

        response = self.client.get("/admin/list")
        response_text = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("公開作品", response_text)
        self.assertIn("非公開作品", response_text)

    def test_invalid_or_empty_public_ids_publish_nothing(self):
        for public_ids in ("", "invalid, -2"):
            with self.subTest(public_ids=public_ids):
                os.environ["PUBLIC_STORY_IDS"] = public_ids

                stories_response = self.client.get("/stories")
                api_response = self.client.get("/api/stories")
                detail_response = self.client.get("/stories/1")

                self.assertNotIn(
                    "公開作品",
                    stories_response.get_data(as_text=True),
                )
                self.assertEqual(api_response.get_json(), [])
                self.assertEqual(detail_response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
