-- Runs once when the container's data volume is first created.
-- Creates a separate database for the pytest suite and enables TimescaleDB in both.
CREATE DATABASE medcheck_test;
\c medcheck
CREATE EXTENSION IF NOT EXISTS timescaledb;
\c medcheck_test
CREATE EXTENSION IF NOT EXISTS timescaledb;
