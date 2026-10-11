\getenv taskflow_app_user TASKFLOW_APP_DB_USER
\getenv taskflow_app_password TASKFLOW_APP_DB_PASSWORD

SELECT format(
    'CREATE ROLE %I LOGIN PASSWORD %L',
    :'taskflow_app_user',
    :'taskflow_app_password'
)
WHERE NOT EXISTS (
    SELECT 1
    FROM pg_catalog.pg_roles
    WHERE rolname = :'taskflow_app_user'
) \gexec

SELECT format(
    'ALTER ROLE %I WITH LOGIN PASSWORD %L',
    :'taskflow_app_user',
    :'taskflow_app_password'
) \gexec

SELECT format(
    'GRANT CONNECT ON DATABASE %I TO %I',
    current_database(),
    :'taskflow_app_user'
) \gexec

SELECT format(
    'GRANT USAGE, CREATE ON SCHEMA public TO %I',
    :'taskflow_app_user'
) \gexec
