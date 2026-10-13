-- Patchwork register, schema v1 (PostgreSQL 16 + PostGIS). Mirrors schema/models.py; tests/test_schema.py
-- checks that every pydantic field has a column. Changes after the schema-v1 tag: additive only.

CREATE EXTENSION IF NOT EXISTS postgis;

DO $$ BEGIN
  CREATE TYPE defect_type AS ENUM ('pothole', 'edge_break', 'depression');
  CREATE TYPE measurement_status AS ENUM ('measured', 'detected_not_measured', 'obscured');
  CREATE TYPE severity AS ENUM ('low', 'medium', 'high');
  CREATE TYPE defect_status AS ENUM ('new', 'unchanged', 'repaired', 'degraded', 'obscured');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS road_segment (
  road_segment_id text PRIMARY KEY,
  name            text NOT NULL,
  hierarchy       text NOT NULL,              -- OSM highway class
  is_control      boolean NOT NULL DEFAULT false,
  is_tunnel       boolean NOT NULL DEFAULT false,
  chainage_start_m real NOT NULL,
  chainage_end_m   real NOT NULL,
  geom            geometry(LineString, 4326) NOT NULL
);

CREATE TABLE IF NOT EXISTS poi (
  poi_id text PRIMARY KEY,
  kind   text NOT NULL,                       -- school | hospital | bus_stop | ...
  name   text,
  geom   geometry(Point, 4326) NOT NULL
);

CREATE TABLE IF NOT EXISTS defect (
  defect_id            text PRIMARY KEY,
  first_seen_pass      text NOT NULL,
  last_seen_pass       text NOT NULL,
  status               defect_status NOT NULL DEFAULT 'new',
  status_confidence    real NOT NULL DEFAULT 1.0,
  latest_obs_id        text NOT NULL,
  lat                  double precision NOT NULL,
  lon                  double precision NOT NULL,
  geom                 geometry(Point, 4326) GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(lon, lat), 4326)) STORED,
  road_segment_id      text NOT NULL REFERENCES road_segment,
  road_name            text NOT NULL,
  chainage_m           real NOT NULL,
  latest_area_m2       real,
  latest_severity      severity NOT NULL,
  open_work_package_id text
);

CREATE TABLE IF NOT EXISTS observation (
  obs_id               text PRIMARY KEY,
  defect_id            text REFERENCES defect,
  pass_id              text NOT NULL,
  clip_id              text NOT NULL,
  frame_idx            integer NOT NULL,
  frame_ts             timestamptz NOT NULL,
  lat                  double precision NOT NULL,
  lon                  double precision NOT NULL,
  geom                 geometry(Point, 4326) GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(lon, lat), 4326)) STORED,
  gnss_hdop_proxy      real NOT NULL,
  road_segment_id      text NOT NULL REFERENCES road_segment,
  road_name            text NOT NULL,
  chainage_m           real NOT NULL,
  lateral_offset_m     real NOT NULL,
  defect_type          defect_type NOT NULL,
  area_m2              real,
  area_uncertainty_m2  real,
  length_m             real,
  width_m              real,
  measurement_status   measurement_status NOT NULL,
  severity             severity NOT NULL,
  severity_confidence  real NOT NULL CHECK (severity_confidence BETWEEN 0 AND 1),
  detection_confidence real NOT NULL CHECK (detection_confidence BETWEEN 0 AND 1),
  material             jsonb,
  attributes           jsonb NOT NULL DEFAULT '{}'::jsonb,
  crop_key             text,
  overlay_key          text,
  rectified_key        text,
  calibration_id       text NOT NULL,
  model_version        text NOT NULL,
  pipeline_version     text NOT NULL,
  privacy_blurred      boolean NOT NULL CHECK (privacy_blurred),
  created_at           timestamptz NOT NULL DEFAULT now(),
  CHECK ((measurement_status = 'measured') = (area_m2 IS NOT NULL))
);

-- idempotent reloads: re-processing a clip (Spot retry, re-upload) cannot duplicate observations
CREATE UNIQUE INDEX IF NOT EXISTS observation_idem
  ON observation (clip_id, frame_idx, round(chainage_m::numeric, 1), defect_type);
CREATE INDEX IF NOT EXISTS observation_geom ON observation USING gist (geom);
CREATE INDEX IF NOT EXISTS defect_geom ON defect USING gist (geom);
CREATE INDEX IF NOT EXISTS defect_segment ON defect (road_segment_id, chainage_m);

CREATE TABLE IF NOT EXISTS status_event (
  event_id    bigserial PRIMARY KEY,
  defect_id   text NOT NULL REFERENCES defect,
  pass_id     text NOT NULL,
  from_status defect_status,
  to_status   defect_status NOT NULL,
  evidence    jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at  timestamptz NOT NULL DEFAULT now()
);

-- agent side (Phase 5); created now so schema-v1 is complete
CREATE TABLE IF NOT EXISTS work_package (
  package_id      text PRIMARY KEY,
  road_segment_id text REFERENCES road_segment,
  defect_ids      text[] NOT NULL,
  total_area_m2   real,
  material        jsonb,
  priority        smallint CHECK (priority BETWEEN 1 AND 3),
  exposure_score  real,
  rationale       text,
  confidence      real,
  state           text NOT NULL DEFAULT 'draft'
                  CHECK (state IN ('draft','awaiting_approval','approved','rejected','filed','verified','escalated')),
  pdf_key         text,
  agent_run_id    text,
  created_at      timestamptz NOT NULL DEFAULT now()
);

-- grounding, second line of defence: a package may only cite defects that exist
CREATE OR REPLACE FUNCTION work_package_defects_exist() RETURNS trigger AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM unnest(NEW.defect_ids) d WHERE NOT EXISTS (SELECT 1 FROM defect WHERE defect_id = d)) THEN
    RAISE EXCEPTION 'work_package cites unknown defect_id';
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS work_package_grounding ON work_package;
CREATE TRIGGER work_package_grounding BEFORE INSERT OR UPDATE ON work_package
  FOR EACH ROW EXECUTE FUNCTION work_package_defects_exist();

CREATE TABLE IF NOT EXISTS approval (
  approval_id       text PRIMARY KEY,
  package_id        text NOT NULL REFERENCES work_package,
  sfn_execution_arn text,
  decision          text NOT NULL CHECK (decision IN ('approve', 'reject')),
  decided_by        text NOT NULL,
  note              text,
  is_override       boolean NOT NULL DEFAULT false,
  decided_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ticket (
  ticket_id    text PRIMARY KEY,
  package_id   text NOT NULL REFERENCES work_package,
  external_ref text,                          -- mock endpoint only: nothing is filed with a real authority
  payload      jsonb NOT NULL,
  filed_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS reinspection (
  reinspection_id text PRIMARY KEY,
  road_segment_id text NOT NULL REFERENCES road_segment,
  chainage_from   real NOT NULL,
  chainage_to     real NOT NULL,
  due_pass        text NOT NULL,
  reason          text,
  package_id      text REFERENCES work_package
);
