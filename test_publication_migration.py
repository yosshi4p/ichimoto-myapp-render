from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from migrate_publication_status import migrate_publication_status


class PublicationMigrationTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "legacy.db"
        self.engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        with self.engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE story ("
                "id INTEGER PRIMARY KEY, title VARCHAR(200), content TEXT NOT NULL)"
            ))
            connection.execute(text(
                "INSERT INTO story (id, title, content) VALUES "
                "(1, '公開作品', '本文1'), (2, '非公開作品', '本文2')"
            ))

    def tearDown(self):
        self.engine.dispose()
        self.temporary_directory.cleanup()

    def test_migration_preserves_rows_publishes_existing_and_is_idempotent(self):
        with self.engine.connect() as connection:
            rows_before = connection.execute(text(
                "SELECT id, title, content FROM story ORDER BY id"
            )).all()

        self.assertTrue(migrate_publication_status(self.engine))
        self.assertIn(
            "is_public",
            {column["name"] for column in inspect(self.engine).get_columns("story")},
        )
        with self.engine.connect() as connection:
            rows = connection.execute(text(
                "SELECT id, title, content, is_public FROM story ORDER BY id"
            )).all()
        self.assertEqual(
            rows,
            [(*row, 1) for row in rows_before],
        )

        with self.engine.begin() as connection:
            connection.execute(text(
                "UPDATE story SET is_public = FALSE WHERE id = 1"
            ))
            connection.execute(text(
                "UPDATE story SET is_public = TRUE WHERE id = 2"
            ))

        self.assertFalse(migrate_publication_status(self.engine))
        with self.engine.connect() as connection:
            rows_after_rerun = connection.execute(text(
                "SELECT id, is_public FROM story ORDER BY id"
            )).all()
        self.assertEqual(rows_after_rerun, [(1, 0), (2, 1)])

    def test_migration_requires_story_table(self):
        empty_engine = create_engine("sqlite:///:memory:")
        try:
            with self.assertRaisesRegex(RuntimeError, "storyテーブル"):
                migrate_publication_status(empty_engine)
        finally:
            empty_engine.dispose()


if __name__ == "__main__":
    unittest.main()
