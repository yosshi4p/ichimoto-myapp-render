from __future__ import annotations

import os

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine


def migrate_publication_status(engine: Engine) -> bool:
    """公開状態列を初回だけ追加し、既存作品をすべて公開する。"""
    inspector = inspect(engine)
    if not inspector.has_table("story"):
        raise RuntimeError("storyテーブルが見つかりません。移行先DBを確認してください。")

    column_names = {column["name"] for column in inspector.get_columns("story")}
    if "is_public" in column_names:
        return False

    with engine.begin() as connection:
        connection.execute(text(
            "ALTER TABLE story "
            "ADD COLUMN is_public BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        connection.execute(text("UPDATE story SET is_public = TRUE"))

    return True


def _normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgres://"):
        return "postgresql://" + database_url[len("postgres://"):]
    return database_url


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URLが未設定です。移行先DBを明示してください。")

    engine = create_engine(_normalize_database_url(database_url))
    try:
        migrated = migrate_publication_status(engine)
    finally:
        engine.dispose()

    if migrated:
        print("is_public列を追加し、既存作品をすべて公開状態にしました。")
    else:
        print("is_public列は既に存在します。公開状態は変更していません。")


if __name__ == "__main__":
    main()
