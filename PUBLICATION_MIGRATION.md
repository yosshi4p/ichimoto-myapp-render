# 公開状態のDB移行手順

## 先に確認すること

この移行は `story.is_public` 列を追加し、**移行時点に存在する全作品を公開**します。移行後に作成する作品は非公開が既定値です。

旧版は Render Web Service の `PUBLIC_STORY_IDS` に含まれるIDだけを公開していました。そのため、現在の値が全作品IDを含んでいない場合、移行直後は公開作品が増えます。現在の値を記録し、全作品公開でよいと確認できるまで移行しないでください。

スクリプトが行う処理は次の2つだけです。

1. `story.is_public BOOLEAN NOT NULL DEFAULT FALSE` を追加する。
2. 既存の `story` 行を `UPDATE story SET is_public = TRUE` で全件公開する。

列追加と全件更新は1トランザクションです。作品行を削除せず、`id`、`title`、`content` を更新しません。`is_public` 列が既にあれば何も変更しないため、再実行で管理画面の設定を上書きしません。

## 中止条件

次のどれかに該当する場合は、本番移行を開始しません。

- 復元可能なバックアップを取得していない。
- バックアップを別の空DBへ復元し、内容を確認していない。
- 現在の `PUBLIC_STORY_IDS` を記録していない。
- 「既存作品をすべて公開する」ことを確認できていない。
- 移行前スナップショットのCSVとSHA-256を保存していない。
- 接続先が本番DBであることを、DB名とホスト名で再確認していない。

## 1. Renderのバックアップと復元

### 推奨: RenderのPoint-in-Time Recovery（PITR）

有料のRender Postgresでは、Dashboardの対象DBにある **Recovery** ページから復元時刻を指定できます。PITRは元DBを上書きせず、新しいDBインスタンスを作ります。復元後は新しいDBの `PSQL Command` で件数と内容を確認します。

利用できる復元期間はワークスペースプランにより異なり、FreeのDBではPITRを利用できません。移行直前の時刻が復元可能範囲に入っていることをDashboardで確認してください。

### 持ち出し可能な論理バックアップ

有料DBでは、対象DBの **Recovery** ページで **Create export** を実行し、完成した `.dir.tar.gz` をローカルへダウンロードします。Render上のエクスポート保持期間だけに頼らず、安全な場所へ保管してください。

Free DB、または手元でもバックアップを保持する場合は、対象DBのExternal Database URLをローカル端末だけで環境変数へ設定し、カスタム形式で取得します。URLをこの文書、Git、チャット、画面共有、CIログへ貼り付けないでください。

```powershell
$secureUrl = Read-Host "External Database URL" -AsSecureString
$credential = [pscredential]::new("unused", $secureUrl)
$env:ICHIMOTO_DATABASE_URL = $credential.GetNetworkCredential().Password
Remove-Variable secureUrl, credential

pg_dump --dbname="$env:ICHIMOTO_DATABASE_URL" --schema=public --format=custom --no-owner --no-acl --file=publication-before.dump
pg_restore --list publication-before.dump | Out-File -Encoding utf8 publication-before.list.txt
Get-Item publication-before.dump
Get-FileHash -Algorithm SHA256 publication-before.dump
```

`publication-before.dump`、一覧、後述のCSVは機密データです。リポジトリ外へ保存し、Gitへ追加しません。

### 復元テスト（必須）

復元先には、使い捨ての**空の**PostgreSQLデータベースを用意します。本番DBを復元先に指定してはいけません。Renderの論理エクスポートを復元する場合は、アーカイブを展開して `pg_restore --format=directory` を使用します。上記のカスタム形式を復元する例は次のとおりです。

```powershell
$secureRestoreUrl = Read-Host "Empty restore-test database URL" -AsSecureString
$restoreCredential = [pscredential]::new("unused", $secureRestoreUrl)
$env:ICHIMOTO_RESTORE_URL = $restoreCredential.GetNetworkCredential().Password
Remove-Variable secureRestoreUrl, restoreCredential

pg_restore --dbname="$env:ICHIMOTO_RESTORE_URL" --verbose --no-owner --no-privileges --format=custom publication-before.dump
psql "$env:ICHIMOTO_RESTORE_URL" -c "SELECT COUNT(*) AS story_count FROM story;"
psql "$env:ICHIMOTO_RESTORE_URL" -c "SELECT id, title, length(content) AS content_length FROM story ORDER BY id;"
```

復元が成功し、件数と代表的な作品が確認できたら復元テスト完了です。復元先に既存データがある場合は実行せず、空DBを作り直してください。

## 2. 現在の公開設定との差を確認

よっちんがRender DashboardでWeb Serviceの `PUBLIC_STORY_IDS` を開き、値を安全なローカルメモへ記録します。値そのものをGitHubやチャットへ貼り付ける必要はありません。

本番DBを読み取り専用で確認し、全作品IDを保存します。

```powershell
psql "$env:ICHIMOTO_DATABASE_URL" -c "SELECT id, title FROM story ORDER BY id;"
```

- 現在公開: `PUBLIC_STORY_IDS` に含まれるIDだけ。
- 移行直後: `story` に存在するIDすべて。
- 差分: `story` の全IDから `PUBLIC_STORY_IDS` を除いたもの。これらが新たに公開されます。

下書き、テスト投稿、個人情報を含む作品が差分に1件でもあれば、全件公開仕様のまま移行してよいか判断するまで中止します。

## 3. 移行前スナップショット

移行直前に、比較対象をCSVへ保存します。本文を含むため、ファイルはGitへ追加しません。

```powershell
psql "$env:ICHIMOTO_DATABASE_URL" -c "\copy (SELECT id, title, content FROM story ORDER BY id) TO 'story-before.csv' WITH (FORMAT csv, HEADER true)"
psql "$env:ICHIMOTO_DATABASE_URL" -c "SELECT COUNT(*) AS story_count, MIN(id) AS min_id, MAX(id) AS max_id FROM story;"
Get-FileHash -Algorithm SHA256 story-before.csv
```

CSVのSHA-256値と件数をローカルメモへ記録します。この時点では読み取りだけで、DBは変更しません。

## 4. 本番移行（今回は実施しない）

バックアップ取得、別DBへの復元テスト、公開差分の承認、移行前スナップショットがすべて完了した後にだけ実施します。

```powershell
$env:DATABASE_URL = $env:ICHIMOTO_DATABASE_URL
python migrate_publication_status.py
Remove-Item Env:DATABASE_URL
```

`DATABASE_URL` が未設定ならスクリプトは変更せず終了します。エラー時はPostgreSQLのトランザクションにより列追加と全件更新がロールバックされます。移行は同時に複数端末から実行しません。

## 5. 移行後の照合（今回は実施しない）

```powershell
psql "$env:ICHIMOTO_DATABASE_URL" -c "\copy (SELECT id, title, content FROM story ORDER BY id) TO 'story-after.csv' WITH (FORMAT csv, HEADER true)"
Get-FileHash -Algorithm SHA256 story-after.csv
Compare-Object (Get-Content story-before.csv) (Get-Content story-after.csv)

psql "$env:ICHIMOTO_DATABASE_URL" -c "SELECT COUNT(*) AS story_count, MIN(id) AS min_id, MAX(id) AS max_id FROM story;"
psql "$env:ICHIMOTO_DATABASE_URL" -c "SELECT COUNT(*) AS private_count FROM story WHERE is_public IS NOT TRUE;"
```

合格条件は次のとおりです。

- `story-before.csv` と `story-after.csv` のSHA-256が一致する。
- `Compare-Object` が何も出力しない。
- 移行前後の件数、最小ID、最大IDが一致する。
- `private_count` が `0` である。

さらに移行スクリプトを再実行し、「既に存在します」と表示されることを確認します。その後、もう一度CSVと公開状態を照合し、変化がないことを確認します。

## 6. 担当分け

### よっちんが実施する操作

- RenderのプランとRecoveryページでPITR／論理バックアップの利用可否を確認する。
- **Create export**、バックアップのダウンロード、空DBへの復元テストを行う。
- Render Web Serviceの現在の `PUBLIC_STORY_IDS` を安全に確認する。
- 新たに公開される作品を確認し、全件公開でよいか判断する。
- 本番DBのExternal Database URLを、共有せずローカル端末へ入力する。
- バックアップと復元を確認した後、別の依頼として本番移行の実行を明示的に承認する。

### Codexに任せられる操作

- 移行スクリプト、照合SQL、手順書、テストのレビューと修正。
- GitHub Actions上の使い捨てPostgreSQLを使った移行テスト。
- よっちんが共有した**件数や伏せた差分結果**の判定補助。
- 明示的な承認後の移行コマンド支援。ただし認証情報はチャットへ貼らない。

バックアップと復元テストの確認が完了するまでは、本番DB移行、PRのマージ、Renderへのデプロイを行いません。旧バージョンへ切り戻す可能性がある間は `PUBLIC_STORY_IDS` も削除しません。

## Render公式資料

- [Render Postgres Recovery and Backups](https://render.com/docs/postgresql-backups)
- [Create and Connect to Render Postgres](https://render.com/docs/postgresql-creating-connecting)
