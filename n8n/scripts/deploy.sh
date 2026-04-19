#!/usr/bin/env bash
set -euo pipefail

# Deploy n8n workflows via n8n public API.
# Required env:
#   N8N_BASE_URL   (e.g. https://giovannimavilla.app.n8n.cloud)
#   N8N_API_KEY    (JWT)

: "${N8N_BASE_URL:?N8N_BASE_URL required}"
: "${N8N_API_KEY:?N8N_API_KEY required}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WFDIR="$ROOT/workflows"
OUT="$ROOT/.deployed.json"

api() {
  local method="$1" path="$2" body="${3:-}"
  if [[ -n "$body" ]]; then
    curl -sS -X "$method" "$N8N_BASE_URL$path" \
      -H "X-N8N-API-KEY: $N8N_API_KEY" \
      -H "Content-Type: application/json" \
      -d "$body"
  else
    curl -sS -X "$method" "$N8N_BASE_URL$path" \
      -H "X-N8N-API-KEY: $N8N_API_KEY" \
      -H "accept: application/json"
  fi
}

# n8n public API rejects unknown top-level keys; keep only: name, nodes, connections, settings
clean_wf() {
  python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps({k:d[k] for k in ('name','nodes','connections','settings') if k in d}))" < "$1"
}

create_wf() {
  local file="$1"
  local body
  body=$(clean_wf "$file")
  api POST "/api/v1/workflows" "$body"
}

echo "=== Creating workflows ==="
declare -A IDS

for f in 00_setup_sheet 03_delivery 02_content_factory 01_intelligence; do
  echo "→ $f.json"
  resp=$(create_wf "$WFDIR/$f.json")
  id=$(echo "$resp" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" )
  if [[ -z "$id" ]]; then
    echo "  FAILED: $resp" >&2
    exit 1
  fi
  IDS[$f]=$id
  echo "  id=$id"
done

# Patch WF1 config to wire content factory + delivery ids
WF1_ID=${IDS[01_intelligence]}
WF2_ID=${IDS[02_content_factory]}
WF3_ID=${IDS[03_delivery]}

echo "=== Wiring cross-workflow references ==="
python3 - <<PY
import json, os, sys, urllib.request
base = os.environ["N8N_BASE_URL"]
key  = os.environ["N8N_API_KEY"]
wf1  = "${WF1_ID}"
wf2  = "${WF2_ID}"
wf3  = "${WF3_ID}"

def req(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(base+path, data=data, method=method,
        headers={"X-N8N-API-KEY": key, "Content-Type":"application/json", "accept":"application/json"})
    return json.loads(urllib.request.urlopen(r).read())

wf = req("GET", f"/api/v1/workflows/{wf1}")
for n in wf["nodes"]:
    if n["name"] == "Config":
        for a in n["parameters"]["assignments"]["assignments"]:
            if a["name"] == "contentFactoryId":  a["value"] = wf2
            if a["name"] == "deliveryWorkflowId": a["value"] = wf3
# n8n public API PUT body must include name, nodes, connections, settings only
body = {k: wf[k] for k in ("name","nodes","connections","settings") if k in wf}
req("PUT", f"/api/v1/workflows/{wf1}", body)
print("WF1 config updated → WF2=", wf2, " WF3=", wf3)
PY

cat > "$OUT" <<EOF
{
  "setup":        "${IDS[00_setup_sheet]}",
  "delivery":     "${IDS[03_delivery]}",
  "content":      "${IDS[02_content_factory]}",
  "intelligence": "${IDS[01_intelligence]}"
}
EOF
echo "=== Done ==="
cat "$OUT"
