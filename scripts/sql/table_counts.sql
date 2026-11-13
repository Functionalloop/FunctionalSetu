-- Exact row count of every table in the app and public schemas, one "schema.table|count"
-- line each (partitions are counted in their parent). Used by backup.sh and restore.sh.
-- Run as the superuser, so row-level security does not hide rows.
SELECT n.nspname || '.' || c.relname,
       (xpath('/row/c/text()',
              query_to_xml(format('SELECT count(*) AS c FROM %I.%I', n.nspname, c.relname),
                           false, true, '')))[1]::text
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p') AND NOT c.relispartition AND n.nspname IN ('app', 'public')
ORDER BY 1;
