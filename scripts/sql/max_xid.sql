-- Highest transaction number stored in any xid8 column of the app schema
-- (every sync_xid, and devices.last_pull_watermark). Used by restore.sh --live.
SELECT coalesce(max(x), 0)
FROM (
  SELECT (xpath('/row/m/text()',
                query_to_xml(format('SELECT coalesce(max(%I::text::numeric), 0) AS m FROM %I.%I',
                                    a.attname, n.nspname, c.relname),
                             false, true, '')))[1]::text::numeric AS x
  FROM pg_attribute a
  JOIN pg_class c ON c.oid = a.attrelid
  JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname = 'app' AND c.relkind IN ('r', 'p') AND NOT c.relispartition
    AND a.attnum > 0 AND NOT a.attisdropped AND a.atttypid = 'xid8'::regtype
) s;
