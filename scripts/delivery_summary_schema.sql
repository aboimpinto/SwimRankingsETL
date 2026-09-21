-- Season AQUA summary tables for the athlete-progress charts
-- (SophiaWalkerSwim + LimmatSharks). Recalculated by scripts/delivery_summaries.py
-- after every import batch.
--
-- AQUA = World Aquatics (FINA) points. Per season (Sep 1 - Aug 31) and course
-- (LCM/SCM), the swimmer's top 3 AQUA results are averaged.
-- Age group = season end year - birth year (birthday normalized to Jan 1).
--
-- Populations: country SUI | ALL combined with age mode AGE (age-grouped)
-- | OPEN (open class, all ages combined, age_group = 0).

CREATE TABLE IF NOT EXISTS athlete_season_points (
    id serial PRIMARY KEY,
    season_end_year integer NOT NULL,
    swimmer_id integer NOT NULL REFERENCES swimmers(id) ON DELETE CASCADE,
    course text NOT NULL CHECK (course IN ('LCM', 'SCM')),
    distance integer NOT NULL DEFAULT 0 CHECK (distance >= 0),
    stroke text NOT NULL DEFAULT 'ALL',
    age_group integer,
    best1_points integer,
    best2_points integer,
    best3_points integer,
    top3_avg_points numeric(6, 1),
    race_count integer NOT NULL DEFAULT 0,
    percentile_rank numeric(5, 2),
    UNIQUE (season_end_year, swimmer_id, course, distance, stroke)
);

CREATE INDEX IF NOT EXISTS athlete_season_points_swimmer_idx
    ON athlete_season_points (swimmer_id, season_end_year, course);
CREATE INDEX IF NOT EXISTS athlete_season_points_chart_idx
    ON athlete_season_points (season_end_year, course, age_group, distance, stroke);

-- Percentile rank of each athlete per comparison population.
CREATE TABLE IF NOT EXISTS athlete_percentile_ranks (
    id serial PRIMARY KEY,
    athlete_season_point_id integer NOT NULL REFERENCES athlete_season_points(id) ON DELETE CASCADE,
    country text NOT NULL CHECK (country IN ('SUI', 'ALL')),
    age_mode text NOT NULL CHECK (age_mode IN ('AGE', 'OPEN')),
    percentile_rank numeric(5, 2),
    UNIQUE (athlete_season_point_id, country, age_mode)
);
CREATE INDEX IF NOT EXISTS athlete_percentile_ranks_lookup_idx
    ON athlete_percentile_ranks (country, age_mode, percentile_rank);

-- Percentile bands per (season, course, age group, event, population).
CREATE TABLE IF NOT EXISTS season_percentile_bands (
    id serial PRIMARY KEY,
    season_end_year integer NOT NULL,
    course text NOT NULL CHECK (course IN ('LCM', 'SCM')),
    age_group integer NOT NULL DEFAULT 0,  -- 0 = open class (all ages)
    distance integer NOT NULL DEFAULT 0 CHECK (distance >= 0),
    stroke text NOT NULL DEFAULT 'ALL',
    country text NOT NULL CHECK (country IN ('SUI', 'ALL')),
    age_mode text NOT NULL CHECK (age_mode IN ('AGE', 'OPEN')),
    population_count integer NOT NULL DEFAULT 0,
    p10 numeric(6, 1),
    p20 numeric(6, 1),
    p25 numeric(6, 1),
    p40 numeric(6, 1),
    p50 numeric(6, 1),
    p60 numeric(6, 1),
    p75 numeric(6, 1),
    p80 numeric(6, 1),
    p90 numeric(6, 1),
    p95 numeric(6, 1),
    UNIQUE (season_end_year, course, age_group, distance, stroke, country, age_mode)
);

CREATE TABLE IF NOT EXISTS points_summary_rebuild (
    id serial PRIMARY KEY,
    rebuilt_at timestamptz NOT NULL DEFAULT now(),
    country text,
    population_threshold integer NOT NULL DEFAULT 0,
    athlete_rows integer NOT NULL,
    band_rows integer NOT NULL
);

-- AQUA per meeting: average of the swimmer's top 3 FINA results within a
-- single meet (per course, per event). Powers the season-progress charts.
CREATE TABLE IF NOT EXISTS athlete_meet_points (
    id serial PRIMARY KEY,
    swimmer_id integer NOT NULL REFERENCES swimmers(id) ON DELETE CASCADE,
    meet_id integer NOT NULL REFERENCES meets(id) ON DELETE CASCADE,
    course text NOT NULL CHECK (course IN ('LCM', 'SCM')),
    distance integer NOT NULL DEFAULT 0 CHECK (distance >= 0),
    stroke text NOT NULL DEFAULT 'ALL',
    meet_date date,
    best1_points integer,
    best2_points integer,
    best3_points integer,
    top3_avg_points numeric(6, 1),
    race_count integer NOT NULL DEFAULT 0,
    UNIQUE (swimmer_id, meet_id, course, distance, stroke)
);
CREATE INDEX IF NOT EXISTS athlete_meet_points_chart_idx
    ON athlete_meet_points (swimmer_id, course, distance, stroke, meet_date);

-- Single-race points percentile bands per (event, course, age group,
-- population). age_group = 0 means open class. Percentiles of the
-- distribution of individual race points (FINA and Rudolph) across the
-- population; powers the per-race percentile view on the records page.
CREATE TABLE IF NOT EXISTS race_points_bands (
    id serial PRIMARY KEY,
    distance integer NOT NULL,
    stroke text NOT NULL,
    pool_length integer NOT NULL CHECK (pool_length IN (25, 50)),
    age_group integer NOT NULL DEFAULT 0,  -- 0 = open class (all ages)
    country text NOT NULL CHECK (country IN ('SUI', 'ALL')),
    age_mode text NOT NULL CHECK (age_mode IN ('AGE', 'OPEN')),
    population_count integer NOT NULL DEFAULT 0,
    max_fina integer,
    p10 numeric(6, 1), p20 numeric(6, 1), p25 numeric(6, 1), p40 numeric(6, 1),
    p50 numeric(6, 1), p60 numeric(6, 1), p75 numeric(6, 1), p80 numeric(6, 1),
    p90 numeric(6, 1), p95 numeric(6, 1),
    max_rudolph integer,
    r_p10 numeric(6, 1), r_p20 numeric(6, 1), r_p25 numeric(6, 1), r_p40 numeric(6, 1),
    r_p50 numeric(6, 1), r_p60 numeric(6, 1), r_p75 numeric(6, 1), r_p80 numeric(6, 1),
    r_p90 numeric(6, 1), r_p95 numeric(6, 1),
    UNIQUE (distance, stroke, pool_length, age_group, country, age_mode)
);

-- Split competition aggregates at the September boundary without touching races.
ALTER TABLE athlete_meet_points ADD COLUMN IF NOT EXISTS season_end_year integer;
ALTER TABLE athlete_meet_points DROP CONSTRAINT IF EXISTS athlete_meet_points_swimmer_id_meet_id_course_distance_stro_key;
CREATE UNIQUE INDEX IF NOT EXISTS athlete_meet_points_season_identity
 ON athlete_meet_points(season_end_year,swimmer_id,meet_id,course,distance,stroke);

-- Club history loads each result's ordered splits; avoid one full scan per race.
CREATE INDEX IF NOT EXISTS splits_result_order_idx ON splits (result_id, split_order);
