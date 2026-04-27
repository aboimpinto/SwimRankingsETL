# Importing SwimRankings Data for SophiaWalkerSwim

This ETL repo can import SwimRankings LENEX data into more than one local
PostgreSQL database. For the SophiaWalkerSwim website, always import into the
database configured by the website, not the ETL scratch database.

## Database Targets

The website configuration lives at:

`C:\myWork\SophiaWalkerSwim\WebSite\.env`

As of 2026-04-27 it points to:

- Website app database:
  `postgresql://<website-db-user>:<password>@localhost:5432/SophiaWalkerSwimDb?schema=public`
- Website SwimRankings source database:
  `postgresql://<website-db-user>:<password>@localhost:5432/swimrankingsdb?schema=public`

Use the `swimrankingsdb` URL for ETL imports. The website then copies selected
Sophia Walker meet results from `swimrankingsdb` into `SophiaWalkerSwimDb`
through the admin import action.

Do not use this database for website-visible imports:

`postgresql://<etl-user>:<password>@localhost:5433/swimrankings`

That is the `hush-postgres-local` ETL database and the website does not read it.

## Correct April Import Command

From `C:\myWork\SwimRankingsETL`:

```powershell
$db = "postgresql://<website-db-user>:<password>@localhost:5432/swimrankingsdb"
python scripts\import_live_swimrankings_month.py --year 2026 --month 4 --through-date 2026-04-27 --db-url $db
```

The website's Prisma URL contains `?schema=public`, but the Python importer uses
`psycopg2`, which rejects that query parameter. Omit it for ETL commands.

The importer is idempotent:

- Meets with existing result rows are skipped.
- Source files already processed with zero result rows are skipped.
- Missing public LENEX files are reported as failed without stopping other meets.

## Verify Source Import

Check that the target website SwimRankings database contains the meet:

```powershell
docker exec myPostgreSQL psql -U HushNetworkDb_USER -d swimrankingsdb -c "select id, meet_id, name, start_date, country_code, city, pool_length from meets where name ilike '%Nachwuchs-Cup Final%';"
```

Check Sophia Walker results in the source database:

```powershell
docker exec myPostgreSQL psql -U HushNetworkDb_USER -d swimrankingsdb -c "select m.id, m.name, e.distance, e.stroke, r.time_seconds from results r join meets m on m.id = r.meet_id join swimmers s on s.id = r.swimmer_id join events e on e.id = r.event_id where s.first_name = 'Sophia' and s.last_name = 'Walker' and m.name ilike '%Nachwuchs-Cup Final%';"
```

## Make The Meet Visible On The Website

The website admin page reads available source meets from `swimrankingsdb`, then
imports selected meets into `SophiaWalkerSwimDb`.

1. Start or refresh the SophiaWalkerSwim website.
2. Open the admin events page.
3. Look under `Available Meets from SwimRankings`.
4. Click `Import` for the desired meet.
5. The meet should move to `Imported Meets`.

For direct verification after admin import:

```powershell
docker exec myPostgreSQL psql -U HushNetworkDb_USER -d SophiaWalkerSwimDb -c "select id, name, location, date, course, ""sourceMeetPk"" from ""Meet"" where name ilike '%Nachwuchs-Cup Final%';"
```

## Current Known Pitfall

If a meet appears in the ETL database on port `5433` but not in the website,
it was imported into the wrong local database. Re-run the import with
`--db-url` pointing to `localhost:5432/swimrankingsdb`.
