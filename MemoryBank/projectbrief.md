# Project Brief

SwimRankingsETL supplies the canonical swimming data used by SophiaWalker, Colin
and LimmatSharks. The [project README](../README.md) describes the complete
production workflow; [the delivery runbook](../docs/desktop-incremental-delivery.md)
contains executable commands and recovery procedures.

The desktop downloads SwimRankings data or reads saved LENEX/XML files, resolves
canonical identities, and imports meets, athletes, events, results, points and
splits into localServer PostgreSQL. Authentication and interactive browser
sessions stay on the desktop.

Versioned per-competition packages carry new results and corrections to AWS
PostgreSQL. Publication rebuilds summaries and triggers all three application
refresh endpoints, even for meets without a tracked athlete. Each application
updates current/career rankings and caches while preserving closed archives.
Durable source and consumer receipts support safe retries and identify partial
completion. Include `--publish-config` in publishing pushes; raw delivery alone
does not refresh the websites.

Additional tools collect club records/ranking baselines and retain additive
performance evidence from historical exports and LENEX files. Coverage is limited
to imported evidence; partial historical rankings remain labelled accordingly.

The repository includes operational documentation and PostgreSQL contract tests.
It does not provide a scheduled acquisition service or move browser sessions to
AWS. The application repositories own website presentation, managed rosters,
season closure and prepared profile caches.
