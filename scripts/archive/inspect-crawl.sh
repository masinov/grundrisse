#!/bin/bash
# Quick crawl inspection script

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

echo "=========================================="
echo "CRAWL RUN INSPECTION"
echo "=========================================="
echo ""

echo "Recent Crawl Runs:"
echo "------------------"
"$SCRIPT_DIR/db-query.sh" "
SELECT
    crawl_run_id,
    status,
    urls_discovered,
    urls_fetched,
    urls_failed,
    started_at,
    (NOW() - started_at) as running_for
FROM crawl_run
ORDER BY started_at DESC
LIMIT 3;
"

echo ""
echo "Latest Crawl Run - URL Breakdown:"
echo "----------------------------------"
"$SCRIPT_DIR/db-query.sh" "
SELECT
    status,
    COUNT(*) as count,
    MAX(depth) as max_depth
FROM url_catalog_entry
WHERE crawl_run_id = (SELECT crawl_run_id FROM crawl_run ORDER BY started_at DESC LIMIT 1)
GROUP BY status;
"

echo ""
echo "Classification Runs:"
echo "--------------------"
"$SCRIPT_DIR/db-query.sh" "
SELECT
    run_id,
    status,
    urls_classified,
    tokens_used,
    budget_tokens,
    current_depth,
    started_at
FROM classification_run
ORDER BY started_at DESC
LIMIT 3;
"

echo ""
echo "Recent URLs Fetched:"
echo "--------------------"
"$SCRIPT_DIR/db-query.sh" "
SELECT
    url_canonical,
    depth,
    status,
    http_status,
    fetched_at
FROM url_catalog_entry
WHERE crawl_run_id = (SELECT crawl_run_id FROM crawl_run ORDER BY started_at DESC LIMIT 1)
  AND fetched_at IS NOT NULL
ORDER BY fetched_at DESC
LIMIT 10;
"
