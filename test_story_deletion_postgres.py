from __future__ import annotations

import os
import unittest


POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL")
if POSTGRES_URL:
    os.environ["DATABASE_URL"] = POSTGRES_URL
else:
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from app import Story, app, db  # noqa: E402


@unittest.skipUnless(POSTGRES_URL, "TEST_POSTGRES_URL is not configured")
class PostgreSQLStoryDeletionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True
        with app.app_context():
            db.drop_all()
            db.create_all()

    @classmethod
    def tearDownClass(cls):
        with app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()

    def setUp(self):
        with app.app_context():
            db.session.query(Story).delete()
            db.session.add_all([
                Story(id=1, title="削除対象", content="削除対象本文", is_public=True),
                Story(id=2, title="保持対象", content="保持対象本文", is_public=True),
            ])
            db.session.commit()
        self.client = app.test_client()
        with self.client.session_transaction() as session:
            session["admin_logged_in"] = True
        self.client.get("/admin/list")

    def test_confirm_and_delete_are_persisted_in_postgresql(self):
        confirmation = self.client.get("/admin/delete/1")
        self.assertEqual(confirmation.status_code, 200)
        self.assertIn("削除対象", confirmation.get_data(as_text=True))

        with self.client.session_transaction() as session:
            csrf_token = session["admin_csrf_token"]
        response = self.client.post(
            "/admin/delete/1",
            data={"csrf_token": csrf_token},
        )
        self.assertEqual(response.status_code, 302)

        with app.app_context():
            self.assertIsNone(db.session.get(Story, 1))
            self.assertIsNotNone(db.session.get(Story, 2))
        self.assertEqual(
            [story["id"] for story in self.client.get("/api/stories").get_json()],
            [2],
        )
        self.assertEqual(self.client.get("/stories/1").status_code, 404)


if __name__ == "__main__":
    unittest.main()
