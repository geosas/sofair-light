#!/usr/bin/env bash
#
# restart_frost.sh restarts the FROST containers (archive + partage).
#
# Deletes NO data: the PostgreSQL databases live on the host, not inside the
# containers. Chains `docker compose down` then `up -d`, so the containers are
# RECREATED: any change to docker-compose.yaml is picked up.

set -euo pipefail

DC="${DOCKER_COMPOSE:-sudo docker compose}"
cd "$(dirname "$0")"   # directory holding docker-compose.yaml

SOFT=0
[ "${1:-}" = "--soft" ] && SOFT=1

# Hard stop: this script brings FROST back up, and without those values the
# containers would restart with an empty connection URL
# (persistence_db_url=jdbc:postgresql://:/...).
[ -f .env ] || {
    echo "❌ frost/.env is missing: run ./create_db.sh first (it generates the file)."
    exit 1
}

if [ "$SOFT" -eq 1 ]; then
    echo "→ Quick restart of the FROST containers (--soft)..."
    $DC restart
else
    echo "→ Stopping the FROST containers..."
    $DC down
    echo "→ Bringing the FROST containers back up..."
    $DC up -d
fi

echo "✅ FROST restarted (the PostgreSQL data on the host is untouched)."
echo "   Check (the JSON listing of STA resources should show up):"
echo "     curl -s http://localhost:8080/FROST-Server/v1.1 | head   # partage"
echo "     curl -s http://localhost:8081/FROST-Server/v1.1 | head   # archive"
