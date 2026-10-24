from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from migrate_publication_status import (
    migrate_publication_status,
    parse_public_story_ids,
)


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

    def test_migration_preserves_legacy_visibility_and_is_idempotent(self):
        self.assertTrue(migrate_publication_status(self.engine, {1}))
        self.assertIn(
            "is_public",
            {column["name"] for column in inspect(self.engine).get_columns("story")},
        )
        with self.engine.connect() as connection:
            rows = connection.execute(text(
                "SELECT id, is_public FROM story ORDER BY id"
            )).all()
        self.assertEqual(rows, [(1, 1), (2, 0)])

        with self.engine.begin() as connection:
            connection.execute(text(
                "UPDATE story SET is_public = FALSE WHERE id = 1"
            ))
            connection.execute(text(
                "UPDATE story SET is_public = TRUE WHERE id = 2"
            ))

        self.assertFalse(migrate_publication_status(self.engine, {1}))
        with self.engine.connect() as connection:
            rows_after_rerun = connection.execute(text(
                "SELECT id, is_public FROM story ORDER BY id"
            )).all()
        self.assertEqual(rows_after_rerun, [(1, 0), (2, 1)])

    def test_parser_accepts_empty_and_rejects_invalid_ids(self):
        self.assertEqual(parse_public_story_ids(""), set())
        self.assertEqual(parse_public_story_ids(" 1, 2,1 "), {1, 2})
        for invalid_value in ("one", "1,-2", "0"):
            with self.subTest(invalid_value=invalid_value):
                with self.assertRaises(ValueError):
                    parse_public_story_ids(invalid_value)


if __name__ == "__main__":
    unittest.main()
