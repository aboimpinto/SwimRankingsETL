"""Rebuild derived points tables atomically; the publication caller owns commit.

Season aggregates use race session dates (September through August). Invalid,
undated and relay races do not enter individual comparison populations.
Meet aggregates are split at the season boundary. The complete available source
history is retained; this version rebuilds summaries globally once per batch.
"""

import time

VALID_STROKES = ("FREE", "BACK", "BREAST", "FLY", "MEDLEY")

# Comparison populations: country (SUI | ALL) x age mode (AGE | OPEN).
# AGE = age-grouped comparison; OPEN = open class (all ages combined).
POPULATIONS = [
    ("SUI", "AGE"),
    ("ALL", "AGE"),
    ("SUI", "OPEN"),
    ("ALL", "OPEN"),
]

SEASON_EXPR = (
    "extract(year from r.result_date)::int"
    " + CASE WHEN extract(month from r.result_date) >= 9 THEN 1 ELSE 0 END"
)
COURSE_EXPR = "CASE WHEN e.pool_length = 25 THEN 'SCM' ELSE 'LCM' END"


def rebuild_summary(conn, country: str = "SUI", population_threshold: int = 0) -> dict:
    """Recalculate athlete_season_points and season_percentile_bands."""
    cur = conn.cursor()
    start = time.time()
    steps = [
        "rank event rows",
        "rank overall rows",
        "percentile bands",
        "percentile ranks",
        "log",
    ]

    def step(name: str) -> None:
        print(f"  [{time.time() - start:6.0f}s] {name}", flush=True)

    cur.execute("SET LOCAL statement_timeout = '3600s'")
    cur.execute(
        "TRUNCATE athlete_season_points, season_percentile_bands, athlete_percentile_ranks, athlete_meet_points, race_points_bands"
    )

    # ---- 1. Event-level rows: top 3 per (swimmer, season, course, event) ----
    cur.execute(
        f"""
        WITH ranked AS MATERIALIZED (
            SELECT r.swimmer_id,
                   s.birth_year,
                   {SEASON_EXPR} AS season_end_year,
                   {COURSE_EXPR} AS course,
                   e.distance,
                   e.stroke,
                   r.points_fina,
                   row_number() OVER (
                       PARTITION BY r.swimmer_id, {SEASON_EXPR}, {COURSE_EXPR},
                                    e.distance, e.stroke
                       ORDER BY r.points_fina DESC, r.time_seconds ASC
                   ) AS rn
              FROM results r
              JOIN meets m    ON m.id = r.meet_id
              JOIN events e   ON e.id = r.event_id
              JOIN swimmers s ON s.id = r.swimmer_id
             WHERE r.time_seconds > 0
               AND (r.status IS NULL OR btrim(r.status) = '')
               AND r.points_fina BETWEEN 1 AND 1500
               AND COALESCE(r.is_relay, false) = false
               AND r.result_date IS NOT NULL
               AND e.pool_length IN (25, 50)
               AND e.stroke = ANY(%s)
        ),
        top3 AS MATERIALIZED (
            SELECT swimmer_id, season_end_year, course, distance, stroke,
                   max(birth_year) AS birth_year,
                   avg(points_fina) FILTER (WHERE rn <= 3) AS top3_avg,
                   max(points_fina) FILTER (WHERE rn = 1) AS best1,
                   max(points_fina) FILTER (WHERE rn = 2) AS best2,
                   max(points_fina) FILTER (WHERE rn = 3) AS best3,
                   count(*) AS race_count
              FROM ranked
             GROUP BY swimmer_id, season_end_year, course, distance, stroke
        )
        INSERT INTO athlete_season_points
            (season_end_year, swimmer_id, course, distance, stroke, age_group,
             best1_points, best2_points, best3_points, top3_avg_points, race_count)
        SELECT season_end_year, swimmer_id, course, distance, stroke,
               CASE WHEN birth_year IS NOT NULL
                    THEN season_end_year - birth_year END,
               best1, best2, best3, top3_avg, race_count
          FROM top3
        """,
        (list(VALID_STROKES),),
    )
    step(steps[0])

    # ---- 2. Overall rows: top 3 across ALL events of the season/course ----
    cur.execute(
        f"""
        WITH ranked AS MATERIALIZED (
            SELECT r.swimmer_id,
                   s.birth_year,
                   {SEASON_EXPR} AS season_end_year,
                   {COURSE_EXPR} AS course,
                   r.points_fina,
                   row_number() OVER (
                       PARTITION BY r.swimmer_id, {SEASON_EXPR}, {COURSE_EXPR}
                       ORDER BY r.points_fina DESC, r.time_seconds ASC
                   ) AS rn
              FROM results r
              JOIN meets m    ON m.id = r.meet_id
              JOIN events e   ON e.id = r.event_id
              JOIN swimmers s ON s.id = r.swimmer_id
             WHERE r.time_seconds > 0
               AND (r.status IS NULL OR btrim(r.status) = '')
               AND r.points_fina BETWEEN 1 AND 1500
               AND COALESCE(r.is_relay, false) = false
               AND r.result_date IS NOT NULL
               AND e.pool_length IN (25, 50)
               AND e.stroke = ANY(%s)
        ),
        top3 AS MATERIALIZED (
            SELECT swimmer_id, season_end_year, course,
                   max(birth_year) AS birth_year,
                   avg(points_fina) FILTER (WHERE rn <= 3) AS top3_avg,
                   max(points_fina) FILTER (WHERE rn = 1) AS best1,
                   max(points_fina) FILTER (WHERE rn = 2) AS best2,
                   max(points_fina) FILTER (WHERE rn = 3) AS best3,
                   count(*) AS race_count
              FROM ranked
             GROUP BY swimmer_id, season_end_year, course
        )
        INSERT INTO athlete_season_points
            (season_end_year, swimmer_id, course, distance, stroke, age_group,
             best1_points, best2_points, best3_points, top3_avg_points, race_count)
        SELECT season_end_year, swimmer_id, course, 0, 'ALL',
               CASE WHEN birth_year IS NOT NULL
                    THEN season_end_year - birth_year END,
               best1, best2, best3, top3_avg, race_count
          FROM top3
        """,
        (list(VALID_STROKES),),
    )
    step(steps[1])

    # ---- 3+4. Percentile bands + athlete ranks per comparison population ----
    for country, age_mode in POPULATIONS:
        country_filter = "AND s.country_code = %s" if country != "ALL" else ""
        country_params = (country,) if country != "ALL" else ()
        age_filter = "a.age_group BETWEEN 8 AND 19" if age_mode == "AGE" else "TRUE"
        band_age = "a.age_group" if age_mode == "AGE" else "0"
        rank_band_age = "age_group" if age_mode == "AGE" else "0"

        cur.execute(
            f"""
            WITH career AS MATERIALIZED (
                SELECT swimmer_id, max(best1_points) AS career_best
                  FROM athlete_season_points
                 GROUP BY swimmer_id
            ),
            eligible AS MATERIALIZED (
                SELECT a.season_end_year, a.course, {band_age} AS age_group,
                       a.distance, a.stroke, a.top3_avg_points
                  FROM athlete_season_points a
                  JOIN career c ON c.swimmer_id = a.swimmer_id
                  JOIN swimmers s ON s.id = a.swimmer_id
                 WHERE a.top3_avg_points IS NOT NULL
                   AND {age_filter}
                   AND c.career_best >= %s
                   {country_filter}
            )
            INSERT INTO season_percentile_bands
                (season_end_year, course, age_group, distance, stroke, country, age_mode,
                 population_count,
                 p10, p20, p25, p40, p50, p60, p75, p80, p90, p95)
            SELECT season_end_year, course, age_group, distance, stroke, %s, %s,
                   count(*)::int,
                   percentile_cont(0.10) WITHIN GROUP (ORDER BY top3_avg_points),
                   percentile_cont(0.20) WITHIN GROUP (ORDER BY top3_avg_points),
                   percentile_cont(0.25) WITHIN GROUP (ORDER BY top3_avg_points),
                   percentile_cont(0.40) WITHIN GROUP (ORDER BY top3_avg_points),
                   percentile_cont(0.50) WITHIN GROUP (ORDER BY top3_avg_points),
                   percentile_cont(0.60) WITHIN GROUP (ORDER BY top3_avg_points),
                   percentile_cont(0.75) WITHIN GROUP (ORDER BY top3_avg_points),
                   percentile_cont(0.80) WITHIN GROUP (ORDER BY top3_avg_points),
                   percentile_cont(0.90) WITHIN GROUP (ORDER BY top3_avg_points),
                   percentile_cont(0.95) WITHIN GROUP (ORDER BY top3_avg_points)
              FROM eligible
             GROUP BY season_end_year, course, age_group, distance, stroke
            """,
            (population_threshold,) + country_params + (country, age_mode),
        )

        cur.execute(
            f"""
            WITH career AS MATERIALIZED (
                SELECT swimmer_id, max(best1_points) AS career_best
                  FROM athlete_season_points
                 GROUP BY swimmer_id
            ),
            eligible AS MATERIALIZED (
                SELECT a.id,
                       a.season_end_year, a.course, a.age_group, a.distance, a.stroke,
                       a.top3_avg_points
                  FROM athlete_season_points a
                  JOIN career c ON c.swimmer_id = a.swimmer_id
                  JOIN swimmers s ON s.id = a.swimmer_id
                 WHERE a.top3_avg_points IS NOT NULL
                   AND {age_filter}
                   AND c.career_best >= %s
                   {country_filter}
            ),
            ranked AS MATERIALIZED (
                SELECT id,
                       {rank_band_age} AS age_group,
                       100.0 * percent_rank() OVER (
                           PARTITION BY season_end_year, course, {rank_band_age}, distance, stroke
                           ORDER BY top3_avg_points
                       ) AS pct
                  FROM eligible
            )
            INSERT INTO athlete_percentile_ranks
                (athlete_season_point_id, country, age_mode, percentile_rank)
            SELECT r.id, %s, %s, r.pct
              FROM ranked r
            """,
            (population_threshold,) + country_params + (country, age_mode),
        )
        step(f"percentile {country}/{age_mode}")

    # Convenience: default chart rank (SUI/AGE) on the athlete row itself.
    cur.execute("""
        UPDATE athlete_season_points a
           SET percentile_rank = r.percentile_rank
          FROM athlete_percentile_ranks r
         WHERE r.athlete_season_point_id = a.id
           AND r.country = 'SUI'
           AND r.age_mode = 'AGE'
        """)
    step(steps[3])

    # ---- 5. AQUA per meeting (season-progress charts) ----
    cur.execute(
        f"""
        WITH ranked AS MATERIALIZED (
            SELECT r.swimmer_id,
                   r.meet_id,
                   {SEASON_EXPR} AS season_end_year,
                   min(r.result_date) OVER (PARTITION BY r.swimmer_id,r.meet_id,{SEASON_EXPR},{COURSE_EXPR}) AS meet_date,
                   {COURSE_EXPR} AS course,
                   e.distance,
                   e.stroke,
                   r.points_fina,
                   row_number() OVER (
                       PARTITION BY r.swimmer_id, r.meet_id, {SEASON_EXPR}, {COURSE_EXPR},
                                    e.distance, e.stroke
                       ORDER BY r.points_fina DESC, r.time_seconds ASC
                   ) AS rn
              FROM results r
              JOIN meets m    ON m.id = r.meet_id
              JOIN events e   ON e.id = r.event_id
             WHERE r.time_seconds > 0
               AND (r.status IS NULL OR btrim(r.status) = '')
               AND r.points_fina BETWEEN 1 AND 1500
               AND COALESCE(r.is_relay, false) = false
               AND r.result_date IS NOT NULL AND e.pool_length IN (25,50)
               AND e.stroke = ANY(%s)
        ),
        top3 AS MATERIALIZED (
            SELECT swimmer_id, meet_id, season_end_year, meet_date, course, distance, stroke,
                   avg(points_fina) FILTER (WHERE rn <= 3) AS top3_avg,
                   max(points_fina) FILTER (WHERE rn = 1) AS best1,
                   max(points_fina) FILTER (WHERE rn = 2) AS best2,
                   max(points_fina) FILTER (WHERE rn = 3) AS best3,
                   count(*) AS race_count
              FROM ranked
             GROUP BY swimmer_id, meet_id, season_end_year, meet_date, course, distance, stroke
        )
        INSERT INTO athlete_meet_points
            (swimmer_id, meet_id, season_end_year, course, distance, stroke, meet_date,
             best1_points, best2_points, best3_points, top3_avg_points, race_count)
        SELECT swimmer_id, meet_id, season_end_year, course, distance, stroke, meet_date,
               best1, best2, best3, top3_avg, race_count
          FROM top3
        """,
        (list(VALID_STROKES),),
    )

    # Overall rows: top 3 across ALL events within each meet
    cur.execute(
        f"""
        WITH ranked AS MATERIALIZED (
            SELECT r.swimmer_id,
                   r.meet_id,
                   {SEASON_EXPR} AS season_end_year,
                   min(r.result_date) OVER (PARTITION BY r.swimmer_id,r.meet_id,{SEASON_EXPR},{COURSE_EXPR}) AS meet_date,
                   {COURSE_EXPR} AS course,
                   r.points_fina,
                   row_number() OVER (
                       PARTITION BY r.swimmer_id, r.meet_id, {SEASON_EXPR}, {COURSE_EXPR}
                       ORDER BY r.points_fina DESC, r.time_seconds ASC
                   ) AS rn
              FROM results r
              JOIN meets m    ON m.id = r.meet_id
              JOIN events e   ON e.id = r.event_id
             WHERE r.time_seconds > 0
               AND (r.status IS NULL OR btrim(r.status) = '')
               AND r.points_fina BETWEEN 1 AND 1500
               AND COALESCE(r.is_relay, false) = false
               AND r.result_date IS NOT NULL
               AND e.pool_length IN (25, 50)
               AND e.stroke = ANY(%s)
        ),
        top3 AS MATERIALIZED (
            SELECT swimmer_id, meet_id, season_end_year, meet_date, course,
                   avg(points_fina) FILTER (WHERE rn <= 3) AS top3_avg,
                   max(points_fina) FILTER (WHERE rn = 1) AS best1,
                   max(points_fina) FILTER (WHERE rn = 2) AS best2,
                   max(points_fina) FILTER (WHERE rn = 3) AS best3,
                   count(*) AS race_count
              FROM ranked
             GROUP BY swimmer_id, meet_id, season_end_year, meet_date, course
        )
        INSERT INTO athlete_meet_points
            (swimmer_id, meet_id, season_end_year, course, distance, stroke, meet_date,
             best1_points, best2_points, best3_points, top3_avg_points, race_count)
        SELECT swimmer_id, meet_id, season_end_year, course, 0, 'ALL', meet_date,
               best1, best2, best3, top3_avg, race_count
          FROM top3
        """,
        (list(VALID_STROKES),),
    )

    # ---- 6. Single-race points percentile bands per population ----
    for country, age_mode in POPULATIONS:
        country_filter = "AND s.country_code = %s" if country != "ALL" else ""
        country_params = (country,) if country != "ALL" else ()
        if age_mode == "AGE":
            age_expr = "LEAST(19, GREATEST(8, season_age))"
            age_filter = "season_age BETWEEN 8 AND 19"
        else:
            age_expr = "0"
            age_filter = "TRUE"
        cur.execute(
            f"""
            WITH base AS MATERIALIZED (
                SELECT e.distance,
                       e.stroke,
                       e.pool_length,
                       {SEASON_EXPR} - s.birth_year AS season_age,
                       r.points_fina,
                       r.points_rudolph
                  FROM results r
                  JOIN meets m    ON m.id = r.meet_id
                  JOIN events e   ON e.id = r.event_id
                  JOIN swimmers s ON s.id = r.swimmer_id
                 WHERE r.time_seconds > 0
               AND (r.status IS NULL OR btrim(r.status) = '')
                   AND COALESCE(r.is_relay, false) = false
                   AND r.result_date IS NOT NULL
                   AND e.pool_length IN (25, 50)
                   AND s.birth_year IS NOT NULL
                   AND e.stroke = ANY(%s)
                   {country_filter}
            ),
            grouped AS MATERIALIZED (
                SELECT distance, stroke, pool_length,
                       {age_expr} AS age_group,
                       points_fina,
                       points_rudolph
                  FROM base
                 WHERE {age_filter}
            ),
            fina AS MATERIALIZED (
                SELECT distance, stroke, pool_length, age_group,
                       count(*) AS population_count,
                       max(points_fina) AS max_fina,
                       percentile_cont(0.10) WITHIN GROUP (ORDER BY points_fina) AS p10,
                       percentile_cont(0.20) WITHIN GROUP (ORDER BY points_fina) AS p20,
                       percentile_cont(0.25) WITHIN GROUP (ORDER BY points_fina) AS p25,
                       percentile_cont(0.40) WITHIN GROUP (ORDER BY points_fina) AS p40,
                       percentile_cont(0.50) WITHIN GROUP (ORDER BY points_fina) AS p50,
                       percentile_cont(0.60) WITHIN GROUP (ORDER BY points_fina) AS p60,
                       percentile_cont(0.75) WITHIN GROUP (ORDER BY points_fina) AS p75,
                       percentile_cont(0.80) WITHIN GROUP (ORDER BY points_fina) AS p80,
                       percentile_cont(0.90) WITHIN GROUP (ORDER BY points_fina) AS p90,
                       percentile_cont(0.95) WITHIN GROUP (ORDER BY points_fina) AS p95
                  FROM grouped
                 WHERE points_fina BETWEEN 1 AND 1500
                 GROUP BY distance, stroke, pool_length, age_group
            ),
            rudolph AS MATERIALIZED (
                SELECT distance, stroke, pool_length, age_group,
                       count(*) AS population_count,
                       max(points_rudolph) AS max_rudolph,
                       percentile_cont(0.10) WITHIN GROUP (ORDER BY points_rudolph) AS r_p10,
                       percentile_cont(0.20) WITHIN GROUP (ORDER BY points_rudolph) AS r_p20,
                       percentile_cont(0.25) WITHIN GROUP (ORDER BY points_rudolph) AS r_p25,
                       percentile_cont(0.40) WITHIN GROUP (ORDER BY points_rudolph) AS r_p40,
                       percentile_cont(0.50) WITHIN GROUP (ORDER BY points_rudolph) AS r_p50,
                       percentile_cont(0.60) WITHIN GROUP (ORDER BY points_rudolph) AS r_p60,
                       percentile_cont(0.75) WITHIN GROUP (ORDER BY points_rudolph) AS r_p75,
                       percentile_cont(0.80) WITHIN GROUP (ORDER BY points_rudolph) AS r_p80,
                       percentile_cont(0.90) WITHIN GROUP (ORDER BY points_rudolph) AS r_p90,
                       percentile_cont(0.95) WITHIN GROUP (ORDER BY points_rudolph) AS r_p95
                  FROM grouped
                 WHERE points_rudolph BETWEEN 1 AND 20
                 GROUP BY distance, stroke, pool_length, age_group
            )
            INSERT INTO race_points_bands
                (distance, stroke, pool_length, age_group, country, age_mode,
                 population_count, max_fina,
                 p10, p20, p25, p40, p50, p60, p75, p80, p90, p95,
                 max_rudolph,
                 r_p10, r_p20, r_p25, r_p40, r_p50, r_p60, r_p75, r_p80, r_p90, r_p95)
            SELECT f.distance, f.stroke, f.pool_length, f.age_group, %s, %s,
                   f.population_count, f.max_fina,
                   f.p10, f.p20, f.p25, f.p40, f.p50, f.p60, f.p75, f.p80, f.p90, f.p95,
                   r.max_rudolph,
                   r.r_p10, r.r_p20, r.r_p25, r.r_p40, r.r_p50, r.r_p60, r.r_p75, r.r_p80, r.r_p90, r.r_p95
              FROM fina f
              LEFT JOIN rudolph r USING (distance, stroke, pool_length, age_group)
            """,
            (list(VALID_STROKES),) + country_params + (country, age_mode),
        )
        step(f"race bands {country}/{age_mode}")

    step(steps[4])

    cur.execute("SELECT count(*) FROM athlete_season_points")
    athlete_rows = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM season_percentile_bands")
    band_rows = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM athlete_meet_points")
    meet_rows = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM race_points_bands")
    race_band_rows = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO points_summary_rebuild (country, population_threshold, athlete_rows, band_rows) "
        "VALUES (%s, %s, %s, %s)",
        (country, population_threshold, athlete_rows, band_rows),
    )
    step(steps[4])
    print(
        f"Prepared athlete_rows={athlete_rows} band_rows={band_rows} "
        f"meet_rows={meet_rows} race_band_rows={race_band_rows} "
        f"country={country} threshold={population_threshold} in {time.time() - start:.0f}s"
    )

    return {
        "athlete_rows": athlete_rows,
        "band_rows": band_rows,
        "meet_rows": meet_rows,
        "race_band_rows": race_band_rows,
    }
