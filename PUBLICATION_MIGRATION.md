# 公開状態のDB移行手順

この移行は、従来の `PUBLIC_STORY_IDS` を `story.is_public` 列へ一度だけコピーします。
PostgreSQLとSQLiteの両方に対応しています。列が既にある場合は何も更新しないため、再実行しても管理画面で変更した公開状態は上書きされません。

## 本番反映前

1. 本番DBをバックアップする。
2. 現在の本番環境変数 `PUBLIC_STORY_IDS` の値を確認する。
3. 値に含まれる作品IDと、現在公開されている作品が一致することを確認する。
4. `DATABASE_URL` と `PUBLIC_STORY_IDS` を設定した環境で、アプリの新バージョンを起動する前に次を実行する。

```shell
python migrate_publication_status.py
```

`PUBLIC_STORY_IDS` が未設定の場合や不正なIDを含む場合、スクリプトはDBを変更せず終了します。公開作品が0件の場合も、未設定にはせず空文字列として明示してください。

## 実行後の確認

1. スクリプトの成功メッセージを確認する。
2. `story` テーブルに `is_public` 列が追加されたことを確認する。
3. 従来の `PUBLIC_STORY_IDS` に含まれる作品だけが公開状態になっていることを確認する。
4. アプリをデプロイし、管理一覧、`/stories`、`/api/stories`、公開作品と非公開作品の個別URLを確認する。

アプリのデプロイ後は `PUBLIC_STORY_IDS` を参照しません。移行と動作確認が完了するまでは、切り戻しに備えて環境変数を削除しないでください。

## ローカルSQLiteでの事前確認例

本番DBではなく、バックアップから作成した検証用SQLiteファイルを指定してください。

```shell
set DATABASE_URL=sqlite:///検証用ファイル.db
set PUBLIC_STORY_IDS=1,2,3
python migrate_publication_status.py
```

本番DBへの移行はこのPRのマージやデプロイとは別作業です。この手順を確認したうえで明示的に実行してください。
