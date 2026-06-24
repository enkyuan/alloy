-- ryo bootstrap
-- Runs once on first container start against the `ryo` database.

-- Extensions
CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- gen_random_uuid(), encrypt/decrypt
CREATE EXTENSION IF NOT EXISTS "citext";     -- case-insensitive text (email columns)
CREATE EXTENSION IF NOT EXISTS "pg_trgm";    -- trigram indexes for search

-- Restricted app user (the Go API connects as this, not as postgres superuser)
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ryo') THEN
    CREATE ROLE ryo LOGIN PASSWORD 'ryo-dev';
  END IF;
END
$$;

GRANT CONNECT ON DATABASE ryo TO ryo;
GRANT USAGE  ON SCHEMA public TO ryo;

-- New tables/sequences created by migrations are auto-granted to the app role.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ryo;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO ryo;
