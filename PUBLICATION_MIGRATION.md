# 公開状態のDB移行手順

この移行は `story.is_public` 列を追加し、移行時点の既存作品をすべて公開状態にします。移行後に作成する作品はアプリ側の既定値により非公開です。
PostgreSQLとSQLiteの両方に対応しています。列が既にある場合は何も更新しないため、再実行しても管理画面で変更した公開状態は上書きされません。作品行を削除するSQLは実行しません。

## 本番反映前

1. Render PostgreSQLのリカバリ／バックアップが利用可能なら、最新の復元ポイントを確認する。
2. RenderのDB画面からExternal Database URLを一時的に取得し、ローカルでカスタム形式のバックアップを作る（URLやバックアップファイルはGitに追加しない）。

```shell
pg_dump --format=custom --no-owner --no-acl --file=publication-before.dump "<External Database URL>"
pg_restore --list publication-before.dump
```

3. PR #2のブランチをローカルにチェックアウトしたまま、本番 `DATABASE_URL` を一時的に設定し、PRをマージする前に次を実行する。

```shell
python migrate_publication_status.py
```

作業ディレクトリが親リポジトリのルートの場合は `python myapp/migrate_publication_status.py` とします。`DATABASE_URL` が未設定ならDBを変更せず終了します。実行中にエラーが起きた場合、PostgreSQLでは列追加と全件更新が同じトランザクションとしてロールバックされます。接続URLはシェル履歴やログへ残さず、作業後に環境変数から除去してください。

## 実行後の確認

1. スクリプトの成功メッセージを確認する。
2. `story` テーブルに `is_public` 列が追加されたことを確認する。
3. 移行前後の `SELECT COUNT(*) FROM story;` が一致することを確認する。
4. `SELECT COUNT(*) FROM story WHERE is_public IS NOT TRUE;` が `0` であることを確認する。
5. 同じ移行コマンドをもう一度実行し、「既に存在します」と表示され、件数と公開状態が変わらないことを確認する。
6. PR #2をマージする。RenderのAuto-Deployが有効なら、マージがそのままデプロイ開始の合図になる。
7. Auto-Deployが無効なら、Webサービスの「Deploy latest commit」を実行する。
8. 管理一覧、`/stories`、`/api/stories`、公開作品と非公開作品の個別URLを確認する。

有料WebサービスでPre-Deploy Commandを利用できる場合は、`python migrate_publication_status.py` を設定してからマージする方法も安全です。ビルド後・新コードの起動前に移行が実行され、失敗したデプロイは公開されません。このスクリプトは再実行可能なので、以後のデプロイで実行されても公開状態を上書きしません。

旧バージョンへ切り戻す可能性がある間は、従来の `PUBLIC_STORY_IDS` 環境変数を削除しないでください。

## ローカルSQLiteでの事前確認例

本番DBではなく、バックアップから作成した検証用SQLiteファイルを指定してください。

```shell
$env:DATABASE_URL = "sqlite:///検証用ファイル.db"
python migrate_publication_status.py
```

本番DBの変更、PRのマージ、Renderへのデプロイはそれぞれ別作業です。手動移行の場合は必ず「バックアップ → DB移行 → DB検証 → マージ → Render反映」の順で、各段階を確認して進めてください。
