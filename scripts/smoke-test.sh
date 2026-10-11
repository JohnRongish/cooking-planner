#!/usr/bin/env bash
# Start the image on a fresh, empty volume and check: it migrates, /healthz answers,
# the demo data loads, every output renders, and PDF export works.
# usage: scripts/smoke-test.sh IMAGE [PORT]
set -euo pipefail
IMAGE="${1:?usage: smoke-test.sh IMAGE [PORT]}"
PORT="${2:-18080}"
NAME="planner-smoke-$$"
VOL="planner-smoke-vol-$$"
cleanup() { docker logs "$NAME" 2>&1 | tail -n 30 || true; docker rm -f "$NAME" >/dev/null 2>&1 || true; docker volume rm "$VOL" >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker volume create "$VOL" >/dev/null
docker run -d --name "$NAME" -p "$PORT:8080" -v "$VOL:/data" "$IMAGE" >/dev/null

for i in $(seq 1 40); do
  if curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then break; fi
  sleep 1
  if [ "$i" = 40 ]; then echo "FAIL: /healthz never answered"; exit 1; fi
done
echo "ok: /healthz"

curl -fsS -X POST -o /dev/null "http://127.0.0.1:$PORT/seed"
echo "ok: seed data loaded"

base="http://127.0.0.1:$PORT/events/fall-camp-weekend/plan"
for gen in shopping timeline recipes; do
  curl -fsS -o /dev/null "$base/$gen"
  curl -fsS -o /dev/null "$base/$gen/print"
done
echo "ok: all outputs render"

curl -fsS -o /tmp/smoke.pdf "$base/shopping/pdf"
head -c 4 /tmp/smoke.pdf | grep -q '%PDF'
echo "ok: PDF export ($(wc -c </tmp/smoke.pdf) bytes)"

curl -fsS "$base/shopping/csv" | head -n 1 | grep -q '^section,ingredient'
echo "ok: CSV export"

# the container must only write under /data
changed=$(docker diff "$NAME" | grep -v ' /data' | grep -E '^[ACD] ' | grep -v -E ' /(tmp|run)(/|$)' || true)
if [ -n "$changed" ]; then echo "FAIL: wrote outside /data:"; echo "$changed"; exit 1; fi
echo "ok: no writes outside /data"

# state survives a restart (the volume is the only state)
docker restart "$NAME" >/dev/null
for i in $(seq 1 40); do curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1 && break; sleep 1; done
curl -fsS "http://127.0.0.1:$PORT/recipes" | grep -q 'Beef chili'
echo "ok: data survived a restart"
echo "SMOKE TEST PASSED"
