#!/bin/bash
# Helper script to run SQL queries against Dockerized PostgreSQL

# Find the postgres container name
CONTAINER=$(sudo docker ps --filter "ancestor=pgvector/pgvector:pg16" --format "{{.Names}}" | head -1)

if [ -z "$CONTAINER" ]; then
    echo "Error: PostgreSQL container not found!"
    echo "Make sure the database is running: sudo docker compose -f ops/docker-compose.yml up -d"
    exit 1
fi

echo "Using container: $CONTAINER"
echo ""

if [ "$#" -eq 0 ]; then
    # Interactive mode
    sudo docker exec -it "$CONTAINER" psql -U grundrisse -d grundrisse
else
    # Execute provided SQL
    sudo docker exec -it "$CONTAINER" psql -U grundrisse -d grundrisse -c "$1"
fi
