-- Migration 0003: optional analysis-server project bindings.

ALTER TABLE plan
    ADD COLUMN project_ids text[] NOT NULL DEFAULT '{}',
    ADD COLUMN primary_project_id text NULL;

ALTER TABLE step
    ADD COLUMN project_id text NULL;
