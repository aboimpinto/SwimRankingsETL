# Additive Sharks meet performance log

Related: LimmatSharks issue 37; ETL issue 14.

Ranking exports contain best swims and can lag meet imports. Retain every valid
individual Sharks performance from saved LENEX files, independently of the
current managed roster. Exclude relays, invalid swims, future dates, unsupported
courses/events and other clubs. Age rankings use the calendar year of each race.

```bash
python3 scripts/club_meet_performances.py export --directory ./data --output /private/club-meets.json
python3 scripts/club_meet_performances.py apply --package /private/club-meets.json --db-config /private/writer.json
python3 scripts/club_meet_performances.py apply --package /private/club-meets.json --db-config /private/writer.json --commit
```

Export reports rejected files; review those before claiming coverage. Dry run
rolls back all writes. Apply retains source hashes and original evidence in
`club_meet_imports`, with deduplicated races in `club_meet_performances`. Replaying
packages is a no-op. Race keys include athlete name/birth year, event/course/
gender, date, time, meet/city and round/heat. A SUI nationality revision updates
the matching race's preferred display entry; original imports remain intact.
Canonical results, ranking populations and application archives are untouched.

Transfer the exact package plus these scripts to AWS using the existing SSH
release process. Grant the app reader SELECT on `club_meet_performances` after
creation. Use the private writer config already installed on AWS, first dry run,
then commit and replay. Existing website refresh invalidates the source cache;
otherwise the new log is read within one minute. Standard future LENEX meet
imports already carry per-race `club_name` and `club_source` evidence, also read
by the club overlay. This recovery command can be rerun when older files arrive.

22 September local validation: 14 saved sources, 2,345 distinct performances,
86 SUI metadata reconciliations; retry zero changes. The specific September/
November 2025 Sophia files are not in the local cache. Do not derive missing
club-at-meet evidence from current swimmer membership. Complete historical
ranking acquisition remains issue 11, pending source access.
