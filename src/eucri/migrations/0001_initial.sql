CREATE TABLE runs (
  run_id      TEXT PRIMARY KEY,
  utc_date    TEXT NOT NULL,
  source      TEXT NOT NULL,
  started_utc TEXT NOT NULL,
  finished_utc TEXT,
  status      TEXT NOT NULL CHECK (status IN ('running','ok','failed','skipped')),
  git_sha     TEXT,
  notes       TEXT
);
CREATE INDEX idx_runs_day_source ON runs(utc_date, source);

CREATE TABLE observations (
  id INTEGER PRIMARY KEY,
  run_id  TEXT NOT NULL REFERENCES runs(run_id),
  ts_utc  TEXT NOT NULL,
  source  TEXT NOT NULL,
  provider TEXT NOT NULL,
  gpu_model TEXT NOT NULL,
  gpu_count INTEGER,
  price_usd_per_gpu_hr REAL NOT NULL,
  region TEXT,
  country TEXT,
  interconnect TEXT,
  tier TEXT NOT NULL CHECK (tier IN ('executable','list')),
  term TEXT NOT NULL DEFAULT 'on_demand',
  raw_json TEXT NOT NULL
);
CREATE TRIGGER obs_no_update BEFORE UPDATE ON observations
  BEGIN SELECT RAISE(ABORT, 'observations are immutable'); END;
CREATE TRIGGER obs_no_delete BEFORE DELETE ON observations
  BEGIN SELECT RAISE(ABORT, 'observations are immutable'); END;

CREATE TABLE fx (
  date TEXT PRIMARY KEY,
  eur_usd REAL NOT NULL,
  source TEXT NOT NULL
);

CREATE TABLE daily_index (
  date TEXT NOT NULL,
  series TEXT NOT NULL,
  revision INTEGER NOT NULL,
  value_usd REAL,
  value_eur REAL,
  fx_rate REAL,
  fx_date TEXT,
  n_sources INTEGER NOT NULL,
  n_executable INTEGER NOT NULL,
  flags TEXT NOT NULL DEFAULT '',
  methodology_version TEXT NOT NULL,
  computed_at TEXT NOT NULL,
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  PRIMARY KEY (date, series, revision)
);
CREATE TRIGGER dix_no_update BEFORE UPDATE ON daily_index
  BEGIN SELECT RAISE(ABORT, 'daily_index rows are immutable; add a revision'); END;
CREATE TRIGGER dix_no_delete BEFORE DELETE ON daily_index
  BEGIN SELECT RAISE(ABORT, 'daily_index rows are immutable; add a revision'); END;

CREATE TABLE constituents (
  date TEXT NOT NULL,
  series TEXT NOT NULL,
  revision INTEGER NOT NULL,
  provider TEXT NOT NULL,
  source TEXT NOT NULL,
  tier TEXT NOT NULL,
  price_usd REAL NOT NULL,
  weight REAL NOT NULL,
  included INTEGER NOT NULL,
  exclusion_reason TEXT,
  flags TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (date, series, revision, provider)
);

CREATE TABLE overlay_power (
  date TEXT NOT NULL,
  zone TEXT NOT NULL,
  avg_price_eur_mwh REAL NOT NULL,
  raw_json TEXT NOT NULL,
  PRIMARY KEY (date, zone)
);
