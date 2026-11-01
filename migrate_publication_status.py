from __future__ import annotations

import os
from collections.abc import Iterable

from sqlalchemy import bindparam, create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError


_ID_BATCH_SIZE = 500
_MAX_STORY_ID = 9_223_372_036_854_775_807


class PublicationMigrationError(RuntimeError):
    """公開状態の移行を安全に完了できない場合の例外。"""


def _invalid_public_story_ids() -> ValueError:
    return ValueError(
        "PUBLIC_STORY_IDSの形式が不正です。"
        "正の整数をカンマ区切りで指定してください。"
    )


def parse_public_story_ids(raw_value: str | None) -> frozenset[int]:
    """PUBLIC_STORY_IDSを、空でない正の整数IDの集合として厳格に読む。"""
    if raw_value is None or not raw_value.strip():
        raise ValueError(
            "PUBLIC_STORY_IDSが未設定または空です。公開IDを明示してください。"
        )

    tokens = raw_value.split(",")
    if any(not token.strip() for token in tokens):
        raise ValueError(
            "PUBLIC_STORY_IDSの形式が不正です。空の要素を含めないでください。"
        )

    public_story_ids: set[int] = set()
    for token in tokens:
        normalized_token = token.strip()
        if (
            not normalized_token.isascii()
            or not normalized_token.isdecimal()
            or len(normalized_token) > 19
        ):
            raise _invalid_public_story_ids()

        try:
            story_id = int(normalized_token)
        except ValueError:
            raise _invalid_public_story_ids() from None
        if story_id <= 0 or story_id > _MAX_STORY_ID:
            raise _invalid_public_story_ids()
        public_story_ids.add(story_id)

    return frozenset(public_story_ids)


def _validated_public_story_ids(
    public_story_ids: Iterable[int],
) -> tuple[int, ...]:
    try:
        normalized_ids = set(public_story_ids)
    except TypeError:
        raise ValueError("公開IDには1件以上の正の整数を指定してください。") from None

    if not normalized_ids or any(
        type(story_id) is not int
        or story_id <= 0
        or story_id > _MAX_STORY_ID
        for story_id in normalized_ids
    ):
        raise ValueError("公開IDには1件以上の正の整数を指定してください。")

    return tuple(sorted(normalized_ids))


def _id_batches(story_ids: tuple[int, ...]):
    for start in range(0, len(story_ids), _ID_BATCH_SIZE):
        yield story_ids[start:start + _ID_BATCH_SIZE]


def migrate_publication_status(
    engine: Engine,
    public_story_ids: Iterable[int],
) -> bool:
    """初回だけ公開状態列を追加し、指定された既存作品だけを公開する。"""
    normalized_ids = _validated_public_story_ids(public_story_ids)

    requested_ids = set(normalized_ids)
    find_existing_ids = text(
        "SELECT id FROM story WHERE id IN :public_story_ids"
    ).bindparams(bindparam("public_story_ids", expanding=True))
    update_public_stories = text(
        "UPDATE story SET is_public = TRUE "
        "WHERE id IN :public_story_ids"
    ).bindparams(bindparam("public_story_ids", expanding=True))

    with engine.connect() as connection:
        try:
            if connection.dialect.name == "sqlite":
                # sqlite3のlegacy transaction modeでもDDLを確実にrollback可能にする。
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                connection.begin()

            inspector = inspect(connection)
            if not inspector.has_table("story"):
                raise PublicationMigrationError(
                    "storyテーブルが見つかりません。移行先DBを確認してください。"
                )

            if connection.dialect.name == "postgresql":
                connection.execute(text(
                    "LOCK TABLE story IN SHARE ROW EXCLUSIVE MODE"
                ))

            existing_requested_ids: set[int] = set()
            for batch in _id_batches(normalized_ids):
                existing_requested_ids.update(connection.execute(
                    find_existing_ids,
                    {"public_story_ids": batch},
                ).scalars())
            if existing_requested_ids != requested_ids:
                raise PublicationMigrationError(
                    "PUBLIC_STORY_IDSに移行先DBに存在しない作品IDが含まれています。"
                    "DBは変更していません。"
                )

            column_names = {
                column["name"]
                for column in inspector.get_columns("story")
            }
            if "is_public" in column_names:
                connection.commit()
                return False

            connection.execute(text(
                "ALTER TABLE story "
                "ADD COLUMN is_public BOOLEAN NOT NULL DEFAULT FALSE"
            ))

            for batch in _id_batches(normalized_ids):
                connection.execute(
                    update_public_stories,
                    {"public_story_ids": batch},
                )

            actual_public_ids = set(connection.execute(text(
                "SELECT id FROM story WHERE is_public IS TRUE"
            )).scalars())
            if actual_public_ids != requested_ids:
                raise PublicationMigrationError(
                    "公開状態を安全に引き継げなかったため、移行を中止しました。"
                )

            connection.commit()
        except Exception:
            connection.rollback()
            raise

    return True


def _normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgres://"):
        return "postgresql://" + database_url[len("postgres://"):]
    return database_url


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if database_url is None or not database_url.strip():
        raise SystemExit("DATABASE_URLが未設定です。移行先DBを明示してください。")

    try:
        public_story_ids = parse_public_story_ids(os.environ.get("PUBLIC_STORY_IDS"))
    except ValueError as error:
        raise SystemExit(str(error)) from None

    engine: Engine | None = None
    try:
        engine = create_engine(
            _normalize_database_url(database_url.strip()),
            hide_parameters=True,
        )
        migrated = migrate_publication_status(engine, public_story_ids)
    except PublicationMigrationError as error:
        raise SystemExit(str(error)) from None
    except SQLAlchemyError:
        raise SystemExit(
            "移行先DBへの接続または移行処理に失敗しました。"
            "機密値を表示せず接続先とDB状態を確認してください。"
        ) from None
    finally:
        if engine is not None:
            engine.dispose()

    if migrated:
        print(
            "is_public列を追加し、PUBLIC_STORY_IDSに指定された"
            "既存作品だけを公開状態にしました。"
        )
    else:
        print("is_public列は既に存在します。公開状態は変更していません。")


if __name__ == "__main__":
    main()
