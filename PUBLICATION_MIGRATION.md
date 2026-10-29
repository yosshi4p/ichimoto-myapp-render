# 公開状態のDB移行手順

## 移行仕様

この移行は、既存の `story` テーブルへ初回だけ
`is_public BOOLEAN NOT NULL DEFAULT FALSE` 列を追加します。

初回移行時の公開状態は次のとおりです。

- `PUBLIC_STORY_IDS` に含まれ、かつ `story` テーブルに存在する作品だけを
  `is_public = TRUE` にする。
- それ以外の既存作品は `is_public = FALSE` のままにする。
- 作品行を追加・削除せず、`id`、`title`、`content` を更新しない。
- 入力の構文と対象IDの存在確認に成功したうえで `is_public` 列が既にある場合は、
  何も更新しない。管理画面などで変更された公開設定も上書きしない。

移行先は `DATABASE_URL`、引き継ぐ公開IDは `PUBLIC_STORY_IDS` として、
**両方を実行時に明示的に指定**します。アプリの既定値や別環境の値を推測して
使用しません。

`PUBLIC_STORY_IDS` は、64-bit符号付き整数の範囲に収まる正の整数をカンマで
区切った空でない値だけを受け付けます。
未設定、空文字、空白だけ、空の要素、正の整数以外を含む値は不正です。また、
指定されたIDが1件でも移行先DBの `story` テーブルに存在しなければ中止します。
入力の構文とIDの存在確認はDDLより前に完了し、不正時は
`is_public` 列を追加しません。

対象IDの存在確認、列確認、列追加、公開状態の更新、更新結果の照合は、1本の
トランザクション内で行います。SQLiteでは明示的なwrite transaction、PostgreSQLでは
テーブルの書き込みロックを使用し、途中で失敗した場合は列追加を含めてロールバックします。
移行は同時に複数のプロセスから実行しません。

接続情報、`PUBLIC_STORY_IDS` の実値、本文を含むスナップショットは機密情報です。
GitHub、Issue／PR、チャット、CIログ、画面共有、シェルのデバッグ出力へ載せません。
移行スクリプトの正常終了メッセージとエラーにも、接続情報や公開IDの実値を
含めません。

## 中止条件

次のどれかに該当する場合は移行を開始しません。

- 復元可能なバックアップを取得していない。
- バックアップを別の空DBへ復元し、内容を確認していない。
- 移行先DBの接続情報を今回の実行用として明示していない。
- 現在使用中の `PUBLIC_STORY_IDS` を安全なローカル環境で確認していない。
- `PUBLIC_STORY_IDS` が未設定、空、または構文不正である。
- 指定された公開IDが1件でも移行先DBに存在しない。
- 移行前の `id`、`title`、`content`、作品件数を保存していない。
- 接続先のDB名とホスト名を、対象環境と照合していない。

このPRの作業では、本番DBの移行、既存バックアップの変更、PRのマージ、
Renderへのデプロイを行いません。以下の本番向け手順は、バックアップと復元テストを
完了し、別途明示的な実行承認を得た将来の作業用です。

## 1. Renderのバックアップと復元

既存のバックアップ、Renderのexport、PITR復元ポイントを削除・置換・上書きしません。
追加のバックアップが必要な場合は、既存ファイルとは別の新しい名前と保存場所を使います。
バックアップ方式や保持方針そのものは、この移行では変更しません。

### 推奨: RenderのPoint-in-Time Recovery（PITR）

有料のRender Postgresでは、Dashboardの対象DBにある **Recovery** ページから
復元時刻を指定できます。PITRは元DBを上書きせず、新しいDBインスタンスを作ります。
復元後は新しいDBの `PSQL Command` で件数と内容を確認します。

利用できる復元期間はワークスペースプランにより異なり、FreeのDBではPITRを
利用できません。移行直前の時刻が復元可能範囲に入っていることをDashboardで
確認してください。

### 持ち出し可能な論理バックアップ

有料DBでは、対象DBの **Recovery** ページで **Create export** を実行し、完成した
`.dir.tar.gz` をローカルへダウンロードします。既存のexportは残し、今回のものを
別のバックアップとして保管します。

Free DB、または手元でもバックアップを保持する場合は、対象DBのExternal Database URLを
ローカル端末だけで環境変数へ設定し、カスタム形式で取得します。次の例を実行する前に、
`publication-before.dump` が存在しない新しい非公開作業ディレクトリへ移動してください。

```powershell
$secureUrl = Read-Host "External Database URL" -AsSecureString
$credential = [pscredential]::new("unused", $secureUrl)
$env:ICHIMOTO_DATABASE_URL = $credential.GetNetworkCredential().Password
Remove-Variable secureUrl, credential

if (
    (Test-Path -LiteralPath "publication-before.dump") -or
    (Test-Path -LiteralPath "publication-before.list.txt")
) {
    throw "既存バックアップを上書きしないため中止しました。新しい作業ディレクトリを使用してください。"
}

pg_dump --dbname="$env:ICHIMOTO_DATABASE_URL" --schema=public --format=custom --no-owner --no-acl --file=publication-before.dump
pg_restore --list publication-before.dump | Out-File -Encoding utf8 publication-before.list.txt
Get-Item publication-before.dump
Get-FileHash -Algorithm SHA256 publication-before.dump
```

`publication-before.dump`、一覧、後述のCSVは機密データです。リポジトリ外の
アクセス制限された場所へ保存し、Gitへ追加しません。

### 復元テスト（必須）

復元先には、使い捨ての**空の**PostgreSQLデータベースを用意します。本番DBを
復元先に指定してはいけません。Renderの論理エクスポートを復元する場合は、
アーカイブを展開して `pg_restore --format=directory` を使用します。
上記のカスタム形式を復元する例は次のとおりです。

```powershell
$secureRestoreUrl = Read-Host "Empty restore-test database URL" -AsSecureString
$restoreCredential = [pscredential]::new("unused", $secureRestoreUrl)
$env:ICHIMOTO_RESTORE_URL = $restoreCredential.GetNetworkCredential().Password
Remove-Variable secureRestoreUrl, restoreCredential

pg_restore --dbname="$env:ICHIMOTO_RESTORE_URL" --verbose --no-owner --no-privileges --format=custom publication-before.dump
psql "$env:ICHIMOTO_RESTORE_URL" -c "SELECT COUNT(*) AS story_count FROM story;"
```

復元が成功し、作品件数を確認できたら復元テスト完了です。タイトルや本文をCIログ、
共有ログ、チャットへ出力しません。復元先に既存データがある場合は実行せず、
新しい空DBを用意してください。

## 2. 移行入力を安全に準備

以下は共有や記録をしていないローカルPowerShellで実行します。
`Read-Host -AsSecureString` を使い、入力値を画面へ表示しません。

```powershell
$secureDatabaseUrl = Read-Host "Migration target database URL" -AsSecureString
$databaseCredential = [pscredential]::new("unused", $secureDatabaseUrl)
$env:ICHIMOTO_DATABASE_URL = $databaseCredential.GetNetworkCredential().Password
Remove-Variable secureDatabaseUrl, databaseCredential

$securePublicIds = Read-Host "Current PUBLIC_STORY_IDS" -AsSecureString
$publicIdsCredential = [pscredential]::new("unused", $securePublicIds)
$env:ICHIMOTO_PUBLIC_STORY_IDS = $publicIdsCredential.GetNetworkCredential().Password
Remove-Variable securePublicIds, publicIdsCredential

if ([string]::IsNullOrWhiteSpace($env:ICHIMOTO_DATABASE_URL)) {
    throw "移行先DBが未指定のため中止しました。"
}
if ([string]::IsNullOrWhiteSpace($env:ICHIMOTO_PUBLIC_STORY_IDS)) {
    throw "PUBLIC_STORY_IDSが未指定または空のため中止しました。"
}
```

`Get-ChildItem Env:`、`Write-Output`、PowerShell transcript、デバッグトレースなど、
環境変数の内容を表示・記録する操作は行いません。ここでの空チェックに加え、
構文とDB内のID存在確認は移行スクリプトがDDL前に実施します。

## 3. 移行前スナップショット

移行直前に `id`、`title`、`content` をCSVへ保存し、そのSHA-256と作品件数を
ローカル変数へ記録します。CSVはリポジトリ外の非公開作業ディレクトリへ保存します。
次のパスは実際の安全な保存先へ置き換えてください。既存ファイルがある場合は
上書きせず、新しいディレクトリを使用します。

```powershell
$snapshotDirectory = Read-Host "New private snapshot directory"
if (Test-Path -LiteralPath $snapshotDirectory) {
    throw "既存ファイルを上書きしないため中止しました。新しいディレクトリを指定してください。"
}
New-Item -ItemType Directory -Path $snapshotDirectory | Out-Null

$beforeCsv = (Join-Path $snapshotDirectory "story-before.csv").Replace("\", "/")
psql "$env:ICHIMOTO_DATABASE_URL" -c "\copy (SELECT id, title, content FROM story ORDER BY id) TO '$beforeCsv' WITH (FORMAT csv, HEADER true)"
if ($LASTEXITCODE -ne 0) {
    throw "移行前スナップショットの作成に失敗したため中止しました。"
}

$beforeHash = (Get-FileHash -Algorithm SHA256 $beforeCsv).Hash
$beforeCount = psql "$env:ICHIMOTO_DATABASE_URL" -tA -c "SELECT COUNT(*) FROM story;"
if ($LASTEXITCODE -ne 0) {
    throw "移行前件数の取得に失敗したため中止しました。"
}
```

CSVそのものや中身をコンソールへ出力しません。SHA-256と件数だけで、移行後の
同じ形式のスナップショットと照合します。

## 4. 移行の実行（今回は実施しない）

バックアップ、別DBへの復元テスト、入力の安全な取得、移行前スナップショットが
すべて完了した後にだけ実施します。移行先DBと公開IDの両方を、今回のプロセスへ
明示的に渡します。

```powershell
$env:DATABASE_URL = $env:ICHIMOTO_DATABASE_URL
$env:PUBLIC_STORY_IDS = $env:ICHIMOTO_PUBLIC_STORY_IDS

try {
    python migrate_publication_status.py
    if ($LASTEXITCODE -ne 0) {
        throw "移行は完了していません。DBを変更せず中止したことを確認してください。"
    }
}
finally {
    Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
    Remove-Item Env:PUBLIC_STORY_IDS -ErrorAction SilentlyContinue
}
```

次の場合、スクリプトはDDLを実行せず終了します。

- `DATABASE_URL` が未設定または空。
- `PUBLIC_STORY_IDS` が未設定、空、または構文不正。
- `story` テーブルがない。
- 指定された公開IDが1件でも `story` テーブルに存在しない。

入力の構文と対象IDの存在確認に成功したうえで `is_public` 列が既にある場合は、
正常なno-opとして終了し、既存の公開設定を一切変更しません。処理結果には
接続情報、公開IDの実値、作品データを表示しません。

## 5. 移行後のデータ照合（今回は実施しない）

移行前と同じ列・並び順でスナップショットを作り、ハッシュと件数を照合します。
不一致時もCSVの差分をコンソールやログへ表示しません。

```powershell
$afterCsv = (Join-Path $snapshotDirectory "story-after.csv").Replace("\", "/")
if (Test-Path -LiteralPath $afterCsv) {
    throw "既存スナップショットを上書きしないため中止しました。"
}

psql "$env:ICHIMOTO_DATABASE_URL" -c "\copy (SELECT id, title, content FROM story ORDER BY id) TO '$afterCsv' WITH (FORMAT csv, HEADER true)"
if ($LASTEXITCODE -ne 0) {
    throw "移行後スナップショットの作成に失敗しました。"
}

$afterHash = (Get-FileHash -Algorithm SHA256 $afterCsv).Hash
$afterCount = psql "$env:ICHIMOTO_DATABASE_URL" -tA -c "SELECT COUNT(*) FROM story;"
if ($LASTEXITCODE -ne 0) {
    throw "移行後件数の取得に失敗しました。"
}

if ($beforeHash -ne $afterHash) {
    throw "移行前後でID、タイトル、本文のいずれかが変化しています。内容をログへ出さず調査してください。"
}
if ($beforeCount -ne $afterCount) {
    throw "移行前後で作品件数が変化しています。"
}
```

合格条件は次のとおりです。

- `story-before.csv` と `story-after.csv` のSHA-256が一致する。
- 移行前後の作品件数が一致する。
- したがって、順序付きCSVに含まれる全作品の `id`、`title`、`content` と
  作品件数が変化していない。

公開状態は、実値を出力しない次のローカル検証で照合できます。出力は不一致件数だけです。

```powershell
$env:DATABASE_URL = $env:ICHIMOTO_DATABASE_URL
$env:PUBLIC_STORY_IDS = $env:ICHIMOTO_PUBLIC_STORY_IDS

try {
@'
import os
import sys

from sqlalchemy import create_engine, text

from migrate_publication_status import (
    _normalize_database_url,
    parse_public_story_ids,
)

try:
    expected = parse_public_story_ids(os.environ["PUBLIC_STORY_IDS"])
    engine = create_engine(_normalize_database_url(os.environ["DATABASE_URL"]))
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text("SELECT id, is_public FROM story")
            ).all()
    finally:
        engine.dispose()

    existing = {row.id for row in rows}
    mismatch_count = len(expected - existing)
    mismatch_count += sum(
        bool(row.is_public) != (row.id in expected)
        for row in rows
    )
    print(f"publication_mismatch_count={mismatch_count}")
    raise SystemExit(0 if mismatch_count == 0 else 1)
except Exception:
    print(
        "公開状態の照合に失敗しました。機密値を表示せず入力と接続先を確認してください。",
        file=sys.stderr,
    )
    raise SystemExit(2)
'@ | python -

    if ($LASTEXITCODE -ne 0) {
        throw "公開状態がPUBLIC_STORY_IDSと一致しないか、照合に失敗しました。"
    }
}
finally {
    Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
    Remove-Item Env:PUBLIC_STORY_IDS -ErrorAction SilentlyContinue
}
```

`publication_mismatch_count=0` のときだけ合格です。IDの一覧、タイトル、本文は
出力しません。

## 6. 再実行の確認

再実行では公開設定を上書きしません。自動テストでは、初回移行後に公開状態を変更して
から再実行し、その変更が保持されることをSQLiteとPostgreSQLの両方で確認します。

手動確認は本番DBではなく、復元テスト用DBで行います。再実行前後に
`SELECT id, is_public FROM story ORDER BY id` を非公開ファイルへ書き出し、
ファイルのSHA-256が一致することを確認します。差分やID一覧をログへ表示しません。
本番DBの公開状態をテスト目的で変更してはいけません。

## 7. テスト

ローカルのSQLiteテストは次で実行します。

```powershell
python -m unittest discover -v
```

PostgreSQLテストは使い捨てDBの `TEST_POSTGRES_URL` を明示して実行します。
本番DBのURLや本番の `PUBLIC_STORY_IDS` をテストへ渡しません。GitHub Actionsでは
サービスコンテナのPostgreSQLを使い、SQLiteとPostgreSQLの両方について次を検証します。

- 指定された既存作品だけが `is_public = TRUE` になる。
- それ以外の既存作品は `is_public = FALSE` になる。
- 未設定、空、構文不正、DBに存在しないIDではDDL前に中止する。
- 移行前後で `id`、`title`、`content`、作品件数が変わらない。
- 再実行で公開設定を上書きしない。

## 8. 後片付け

作業終了時は、今回設定した環境変数を同じPowerShellセッションから削除します。

```powershell
Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
Remove-Item Env:PUBLIC_STORY_IDS -ErrorAction SilentlyContinue
Remove-Item Env:ICHIMOTO_DATABASE_URL -ErrorAction SilentlyContinue
Remove-Item Env:ICHIMOTO_PUBLIC_STORY_IDS -ErrorAction SilentlyContinue
Remove-Item Env:ICHIMOTO_RESTORE_URL -ErrorAction SilentlyContinue
```

バックアップとスナップショットは削除せず、既存バックアップとは別に安全な場所へ
保管します。Gitへ追加しません。

## 今回の作業範囲

Codexが行うのは、移行スクリプト、テスト、GitHub Actions、手順書、PR本文の更新と
検証までです。今回は次を行いません。

- 本番DBへの接続または変更。
- 既存バックアップ、export、PITR復元ポイントの変更。
- PRのマージ。
- Renderへのデプロイ。
- 本番の `PUBLIC_STORY_IDS` の取得、表示、変更。

## Render公式資料

- [Render Postgres Recovery and Backups](https://render.com/docs/postgresql-backups)
- [Create and Connect to Render Postgres](https://render.com/docs/postgresql-creating-connecting)
