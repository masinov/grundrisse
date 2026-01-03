# Crawl Monitoring Guide

## Real-Time Progress Monitoring

The crawler now outputs progress information as it runs. You'll see:

### Phase 1: Link Graph Building

```
🌐 Starting link graph build from https://www.marxists.org/
   Max depth: 8, Max URLs: 10000

✓ Fetched 10 URLs | Discovered 15 | Failed 0 | Queue 12 | Depth 1/1
✓ Fetched 20 URLs | Discovered 45 | Failed 0 | Queue 38 | Depth 2/2
💾 Checkpoint: Committed 100 URLs to database
✓ Fetched 110 URLs | Discovered 234 | Failed 2 | Queue 156 | Depth 3/3

✅ Link graph build complete!
   URLs discovered: 1,234
   URLs fetched: 1,200
   URLs failed: 34
   Max depth: 6
```

### Phase 2: Classification

```
🧠 Starting progressive classification (leaf-to-root)
   Strategy: leaf_to_root
   Token budget: 100,000
   Starting depth: 6

   Depth 6: Found 45 URLs in 8 parent groups
   ✓ Classified 12 URLs | Total: 12 | LLM calls: 1 | Tokens: 3,245/100,000 (3.2%)
   ✓ Classified 15 URLs | Total: 27 | LLM calls: 2 | Tokens: 6,891/100,000 (6.9%)

   Depth 6: No unclassified URLs, moving up
   Switching to depth 5

✅ Classification budget exceeded!
   URLs classified: 456
   LLM calls: 38
   Errors: 2
   Tokens used: 98,234 / 100,000 (98.2%)
   ⚠️  Budget exceeded - run again with more tokens to continue
```

## Monitor in a Separate Terminal

### Option 1: Quick Inspection Script (Easiest)

```bash
./scripts/inspect-crawl.sh
```

Shows a snapshot of:
- Recent crawl runs
- URL breakdown by status
- Classification progress
- Recent URLs fetched

### Option 2: Real-Time Monitor Script

Open a new terminal and run:

```bash
cd /mnt/c/Users/Datision/Documents/grundrisse
source .venv/bin/activate
python3 scripts/monitor_crawl.py
```

This will show a live-updating dashboard with:
- Crawl run status and duration
- URL counts by status (new, fetched, error)
- Max depth reached
- Classification progress
- Token usage

Updates every 5 seconds. Press Ctrl+C to stop.

### Option 3: Direct Database Queries

Since Postgres runs in Docker, you have two ways to query:

#### Method A: Via Docker (Most Reliable)

```bash
# Get container name (usually ops-postgres-1 or ops_postgres_1)
sudo docker ps | grep postgres

# Run queries inside the container
sudo docker exec -it ops-postgres-1 psql -U grundrisse -d grundrisse -c "
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
LIMIT 1;
"

# URL breakdown by status
sudo docker exec -it ops-postgres-1 psql -U grundrisse -d grundrisse -c "
SELECT
    status,
    COUNT(*) as count,
    MAX(depth) as max_depth
FROM url_catalog_entry
WHERE crawl_run_id = (SELECT crawl_run_id FROM crawl_run ORDER BY started_at DESC LIMIT 1)
GROUP BY status;
"
```

#### Method B: Direct Connection (If port 5432 is exposed)

```bash
# This works if Docker exposes port 5432 and you have psql installed
psql -h localhost -U grundrisse -d grundrisse -c "
SELECT status, COUNT(*) FROM url_catalog_entry
WHERE crawl_run_id = (SELECT crawl_run_id FROM crawl_run ORDER BY started_at DESC LIMIT 1)
GROUP BY status;
"
```

Note: You may need to set `PGPASSWORD=grundrisse` or use `-W` and enter the password.

### Option 4: Helper Scripts for Custom Queries

```bash
# Interactive SQL shell (run any queries)
./scripts/db-query.sh

# Or run a single query
./scripts/db-query.sh "SELECT COUNT(*) FROM url_catalog_entry;"

# Run a SQL file
./scripts/db-query.sh < your-query.sql
```

## Understanding the Output

### Link Graph Builder

- **Fetched**: Successfully downloaded and stored HTML
- **Discovered**: Total URLs found (including duplicates/out-of-scope)
- **Failed**: HTTP errors or fetch failures
- **Queue**: URLs waiting to be processed
- **Depth**: Current/maximum depth in the link tree

The crawler commits to the database every 100 URLs, so you can inspect mid-run.

### Progressive Classifier

- **Depth**: Current depth being classified (starts at deepest, moves up)
- **Parent groups**: Sibling URLs grouped by common parent
- **Total**: Cumulative URLs classified
- **LLM calls**: Number of API requests made
- **Tokens**: Token usage vs budget (with percentage)

## Performance Expectations

### Phase 1 (Link Graph)
- **Speed**: ~2 URLs/second with 0.5s delay
- **Cost**: $0 (no LLM calls)
- **Time for 1,000 URLs**: ~8-10 minutes

### Phase 2 (Classification)
- **Speed**: Depends on LLM API latency
- **Cost**: ~$0.50 per 1M tokens (varies by model)
- **Typical batch**: 15 URLs per LLM call
- **Time for 1,000 URLs**: ~5-10 minutes (depends on API)

## Troubleshooting

### Crawl seems stuck
1. Check the queue size - if it's 0, the crawl is complete
2. Check for errors in the terminal output
3. Run the monitor script to see real-time status
4. Query the database to see latest fetched URLs

### Too many failed URLs
- Check network connectivity
- Verify the website is accessible
- Look at error messages in the database:
  ```sql
  SELECT url_canonical, error_message
  FROM url_catalog_entry
  WHERE status = 'error'
  LIMIT 10;
  ```

### Classification running out of tokens quickly
- Reduce `--max-nodes-per-call` (default 15)
- Use `--no-content-samples` to skip page content in prompts
- Start with a smaller depth/URL count for testing
