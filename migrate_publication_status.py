from __future__ import annotations

import os

from sqlalchemy import bindparam, create_engine, inspect, text
from sqlalchemy.engine import Engine


def parse_public_story_ids(raw_value: str) -> set[int]:
    """PUBLIC_STORY_IDSを厳密に解析し、不正値で移行しないようにする。"""
    public_ids: set[int] = set()
    for raw_id in raw_value.split(","):
        value = raw_id.strip()
        if not value:
            continue
        if not value.isdigit() or int(value) <= 0:
            raise ValueError(f"PUBLIC_STORY_IDSに不正な値があります: {value!r}")
        public_ids.add(int(value))
    return public_ids


def migrate_publication_status(engine: Engine, public_story_ids: set[int]) -> bool:
    """公開状態列を初回だけ追加し、従来の公開IDを引き継ぐ。"""
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
        if public_story_ids:
            publish_existing = text(
                "UPDATE story SET is_public = TRUE WHERE id IN :public_ids"
            ).bindparams(bindparam("public_ids", expanding=True))
            connection.execute(
                publish_existing,
                {"public_ids": sorted(public_story_ids)},
            )

    return True


def _normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgres://"):
        return "postgresql://" + database_url[len("postgres://"):]
    return database_url


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URLが未設定です。移行先DBを明示してください。")

    raw_public_ids = os.environ.get("PUBLIC_STORY_IDS")
    if raw_public_ids is None:
        raise SystemExit(
            "PUBLIC_STORY_IDSが未設定です。現在の本番値を確認してから実行してください。"
        )

    try:
        public_story_ids = parse_public_story_ids(raw_public_ids)
    except ValueError as error:
        raise SystemExit(str(error)) from error

    engine = create_engine(_normalize_database_url(database_url))
    try:
        migrated = migrate_publication_status(engine, public_story_ids)
    finally:
        engine.dispose()

    if migrated:
        print("is_public列を追加し、PUBLIC_STORY_IDSの公開状態を引き継ぎました。")
    else:
        print("is_public列は既に存在します。公開状態は変更していません。")


if __name__ == "__main__":
    main()
