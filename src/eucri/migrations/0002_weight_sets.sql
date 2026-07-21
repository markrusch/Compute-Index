-- Scheduled weight reviews (METHODOLOGY.md §3): one row per (review, scope, key).
-- scope 'provider': key = provider name, model_class = the class the weight applies to,
--   weight = raw review weight (capacity units x tier multiplier x presence ratio).
-- scope 'model': key = model class, model_class = '', weight = basket share in percent
--   (shares sum to 100 per review revision).
-- Append-only like every published artefact: recomputation under a new methodology
-- version adds a revision, never edits.
CREATE TABLE weight_sets (
  effective_date TEXT NOT NULL,   -- first print date the set applies to (review date)
  scope TEXT NOT NULL CHECK (scope IN ('provider','model')),
  model_class TEXT NOT NULL DEFAULT '',
  key TEXT NOT NULL,
  weight REAL NOT NULL,
  window_start TEXT NOT NULL,
  window_end TEXT NOT NULL,
  n_days_observed INTEGER NOT NULL, -- provider scope: days the provider was observed;
                                    -- model scope: collection days in the window
  n_days_window INTEGER NOT NULL,   -- collection days in the window
  revision INTEGER NOT NULL,
  methodology_version TEXT NOT NULL,
  computed_at TEXT NOT NULL,
  PRIMARY KEY (effective_date, scope, model_class, key, revision)
);
CREATE TRIGGER ws_no_update BEFORE UPDATE ON weight_sets
  BEGIN SELECT RAISE(ABORT, 'weight_sets rows are immutable; add a revision'); END;
CREATE TRIGGER ws_no_delete BEFORE DELETE ON weight_sets
  BEGIN SELECT RAISE(ABORT, 'weight_sets rows are immutable; add a revision'); END;
