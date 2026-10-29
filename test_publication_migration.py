from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import SQLAlchemyError

import migrate_publication_status as migration
from migrate_publication_status import (
    migrate_publication_status,
    parse_public_story_ids,
)


LEGACY_STORIES = [
    {"id": 2, "title": "公開対象A", "content": "本文A"},
    {"id": 7, "title": "非公開対象", "content": "本文B"},
    {"id": 11, "title": "公開対象B", "content": "本文C"},
]
INITIAL_PUBLIC_IDS = {2, 11}


def create_legacy_story_table(engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS story"))
        connection.execute(text(
            "CREATE TABLE story ("
            "id INTEGER PRIMARY KEY, title VARCHAR(200), content TEXT NOT NULL)"
        ))
        connection.execute(
            text(
                "INSERT INTO story (id, title, content) "
                "VALUES (:id, :title, :content)"
            ),
            LEGACY_STORIES,
        )


def story_snapshot(engine):
    with engine.connect() as connection:
        rows = connection.execute(text(
            "SELECT id, title, content FROM story ORDER BY id"
        )).all()
        count = connection.execute(text(
            "SELECT COUNT(*) FROM story"
        )).scalar_one()
    return rows, count


class PublicationMigrationContractMixin:
    engine = None

    def test_selected_stories_are_published_without_changing_legacy_data(self):
        rows_before, count_before = story_snapshot(self.engine)

        self.assertTrue(
            migrate_publication_status(self.engine, INITIAL_PUBLIC_IDS)
        )
        self.assertIn(
            "is_public",
            {
                column["name"]
                for column in inspect(self.engine).get_columns("story")
            },
        )

        rows_after, count_after = story_snapshot(self.engine)
        with self.engine.connect() as connection:
            publication_rows = connection.execute(text(
                "SELECT id, is_public FROM story ORDER BY id"
            )).all()

        self.assertEqual(rows_after, rows_before)
        self.assertEqual(count_after, count_before)
        self.assertEqual(count_after, len(LEGACY_STORIES))
        self.assertEqual(
            [
                (story_id, bool(is_public))
                for story_id, is_public in publication_rows
            ],
            [(2, True), (7, False), (11, True)],
        )

    def test_rerun_does_not_overwrite_current_publication_settings(self):
        self.assertTrue(
            migrate_publication_status(self.engine, INITIAL_PUBLIC_IDS)
        )
        with self.engine.begin() as connection:
            connection.execute(text(
                "UPDATE story SET is_public = FALSE WHERE id = 2"
            ))
            connection.execute(text(
                "UPDATE story SET is_public = TRUE WHERE id = 7"
            ))

        rows_before, count_before = story_snapshot(self.engine)
        with self.engine.connect() as connection:
            settings_before = connection.execute(text(
                "SELECT id, is_public FROM story ORDER BY id"
            )).all()

        self.assertFalse(
            migrate_publication_status(self.engine, {7, 11})
        )

        rows_after, count_after = story_snapshot(self.engine)
        with self.engine.connect() as connection:
            settings_after = connection.execute(text(
                "SELECT id, is_public FROM story ORDER BY id"
            )).all()

        self.assertEqual(rows_after, rows_before)
        self.assertEqual(count_after, count_before)
        self.assertEqual(settings_after, settings_before)

    def test_unknown_public_story_id_aborts_before_adding_column(self):
        rows_before, count_before = story_snapshot(self.engine)

        with self.assertRaises(RuntimeError):
            migrate_publication_status(self.engine, {2, 999})

        self.assertNotIn(
            "is_public",
            {
                column["name"]
                for column in inspect(self.engine).get_columns("story")
            },
        )
        rows_after, count_after = story_snapshot(self.engine)
        self.assertEqual(rows_after, rows_before)
        self.assertEqual(count_after, count_before)

    def test_out_of_range_public_story_id_aborts_before_adding_column(self):
        rows_before, count_before = story_snapshot(self.engine)

        with self.assertRaises(ValueError):
            migrate_publication_status(self.engine, {10**100})

        self.assertNotIn(
            "is_public",
            {
                column["name"]
                for column in inspect(self.engine).get_columns("story")
            },
        )
        rows_after, count_after = story_snapshot(self.engine)
        self.assertEqual(rows_after, rows_before)
        self.assertEqual(count_after, count_before)

    def test_failure_after_column_add_rolls_back_schema_and_data(self):
        rows_before, count_before = story_snapshot(self.engine)

        def fail_publication_update(
            connection,
            cursor,
            statement,
            parameters,
            context,
            executemany,
        ):
            if statement.lstrip().startswith("UPDATE story SET is_public"):
                raise RuntimeError("forced migration failure")

        event.listen(
            self.engine,
            "before_cursor_execute",
            fail_publication_update,
        )
        try:
            with self.assertRaisesRegex(RuntimeError, "forced migration failure"):
                migrate_publication_status(self.engine, INITIAL_PUBLIC_IDS)
        finally:
            event.remove(
                self.engine,
                "before_cursor_execute",
                fail_publication_update,
            )

        self.assertNotIn(
            "is_public",
            {
                column["name"]
                for column in inspect(self.engine).get_columns("story")
            },
        )
        rows_after, count_after = story_snapshot(self.engine)
        self.assertEqual(rows_after, rows_before)
        self.assertEqual(count_after, count_before)


class SQLitePublicationMigrationTest(
    PublicationMigrationContractMixin,
    unittest.TestCase,
):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "legacy.db"
        self.engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        create_legacy_story_table(self.engine)

    def tearDown(self):
        self.engine.dispose()
        self.temporary_directory.cleanup()

    def test_migration_requires_story_table(self):
        empty_engine = create_engine("sqlite:///:memory:")
        try:
            with self.assertRaisesRegex(RuntimeError, "storyテーブル"):
                migrate_publication_status(empty_engine, INITIAL_PUBLIC_IDS)
        finally:
            empty_engine.dispose()


@unittest.skipUnless(
    os.environ.get("TEST_POSTGRES_URL"),
    "TEST_POSTGRES_URL is required for PostgreSQL migration tests",
)
class PostgreSQLPublicationMigrationTest(
    PublicationMigrationContractMixin,
    unittest.TestCase,
):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(os.environ["TEST_POSTGRES_URL"])

    @classmethod
    def tearDownClass(cls):
        with cls.engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS story"))
        cls.engine.dispose()

    def setUp(self):
        create_legacy_story_table(self.engine)


class PublicStoryIdsParserTest(unittest.TestCase):
    def test_parses_comma_separated_positive_ids(self):
        self.assertEqual(
            parse_public_story_ids(" 2,11, 2 "),
            {2, 11},
        )

    def test_rejects_missing_empty_and_invalid_values(self):
        invalid_values = (
            None,
            "",
            "   ",
            "invalid",
            "2,invalid",
            "0",
            "-1",
            "+2",
            "2,,11",
            ",2",
            "2,",
            "9" * 20,
        )

        for raw_value in invalid_values:
            with self.subTest(value_type=type(raw_value).__name__):
                with self.assertRaises(ValueError):
                    parse_public_story_ids(raw_value)


class PublicationMigrationMainTest(unittest.TestCase):
    def test_main_requires_database_url(self):
        invalid_values = (None, "", "   ")

        for raw_value in invalid_values:
            environment = {"PUBLIC_STORY_IDS": "2,11"}
            if raw_value is not None:
                environment["DATABASE_URL"] = raw_value

            with self.subTest(value_type=type(raw_value).__name__):
                with (
                    patch.dict(os.environ, environment, clear=True),
                    patch.object(
                        migration,
                        "create_engine",
                    ) as create_engine_mock,
                ):
                    with self.assertRaises(SystemExit):
                        migration.main()

                create_engine_mock.assert_not_called()

    def test_main_requires_public_story_ids_before_connecting(self):
        invalid_values = (None, "", "   ", "invalid")

        for raw_value in invalid_values:
            environment = {"DATABASE_URL": "sqlite:///:memory:"}
            if raw_value is not None:
                environment["PUBLIC_STORY_IDS"] = raw_value

            with self.subTest(value_type=type(raw_value).__name__):
                with (
                    patch.dict(os.environ, environment, clear=True),
                    patch.object(
                        migration,
                        "create_engine",
                    ) as create_engine_mock,
                ):
                    with self.assertRaises(SystemExit):
                        migration.main()

                create_engine_mock.assert_not_called()

    def test_main_passes_explicit_database_and_public_ids_to_migration(self):
        engine = Mock()
        with (
            patch.dict(
                os.environ,
                {
                    "DATABASE_URL": "sqlite:///:memory:",
                    "PUBLIC_STORY_IDS": "2,11",
                },
                clear=True,
            ),
            patch.object(
                migration,
                "create_engine",
                return_value=engine,
            ) as create_engine_mock,
            patch.object(
                migration,
                "migrate_publication_status",
                return_value=False,
            ) as migrate_mock,
        ):
            migration.main()

        create_engine_mock.assert_called_once_with(
            "sqlite:///:memory:",
            hide_parameters=True,
        )
        migrate_mock.assert_called_once_with(engine, {2, 11})
        engine.dispose.assert_called_once_with()

    def test_main_hides_database_error_details(self):
        with (
            patch.dict(
                os.environ,
                {
                    "DATABASE_URL": "postgresql://example.invalid/test",
                    "PUBLIC_STORY_IDS": "2,11",
                },
                clear=True,
            ),
            patch.object(
                migration,
                "create_engine",
                side_effect=SQLAlchemyError("sensitive connection details"),
            ),
        ):
            with self.assertRaises(SystemExit) as raised:
                migration.main()

        self.assertNotIn("sensitive connection details", str(raised.exception))
        self.assertNotIn("example.invalid", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
