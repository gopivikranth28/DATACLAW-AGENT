#!/usr/bin/env bash
# Test notebook kernel via API endpoints.
# Creates a project (new_env), a session, then calls notebook tools directly.
#
# Usage: ./test-notebook.sh [base_url]

set -euo pipefail

BASE="${1:-http://localhost:8000}"
API="$BASE/api"

echo "==> API: $API"
echo ""

# Helper: call a tool via POST /api/tools/{name}/call
call_tool() {
  local tool="$1"
  local params="$2"
  local session="$3"
  echo "--- $tool ---"
  RESULT=$(curl -s -w "\n%{http_code}" -X POST "$API/tools/$tool/invoke" \
    -H "Content-Type: application/json" \
    -d "{\"session_id\": \"$session\", \"params\": $params}")
  HTTP_CODE=$(echo "$RESULT" | tail -1)
  BODY=$(echo "$RESULT" | sed '$d')
  echo "   HTTP $HTTP_CODE"
  echo "$BODY" | python3 -m json.tool 2>/dev/null || echo "$BODY"
  echo ""
}

# ── 1. Create a project with kernel_mode=new_env ──────────────────────────
echo "==> 1. Creating project..."
PROJECT=$(curl -s -X POST "$API/projects/" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "kernel-test",
    "description": "Test notebook kernel creation",
    "kernel_mode": "new_env",
    "packages": ["ipykernel", "pandas", "numpy", "duckdb", "requests", "mlflow"]
  }')
PROJECT_ID=$(echo "$PROJECT" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "   Project ID: $PROJECT_ID"
echo ""

# ── 2. Create a chat session tied to the project ──────────────────────────
echo "==> 2. Creating chat session..."
SESSION=$(curl -s -X POST "$API/chat/sessions" \
  -H "Content-Type: application/json" \
  -d "{\"project_id\": \"$PROJECT_ID\", \"title\": \"Kernel Test\"}")
SESSION_ID=$(echo "$SESSION" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "   Session ID: $SESSION_ID"
echo ""

# ── 3. Open / create a notebook ───────────────────────────────────────────
echo "==> 3. Opening notebook..."
call_tool "open_notebook" '{"path": "kernel_test.ipynb", "create": true, "start_kernel": true}' "$SESSION_ID"

# ── 4. Insert a code cell ─────────────────────────────────────────────────
echo "==> 4. Inserting cell..."
call_tool "insert_cell" '{"source": "import sys, requests, mlflow, pandas, numpy, duckdb\nprint(f\"Python: {sys.executable}\")\nprint(f\"requests: {requests.__version__}\")\nprint(f\"mlflow: {mlflow.__version__}\")\nprint(f\"pandas: {pandas.__version__}\")\nprint(\"hello from kernel\")", "cell_type": "code"}' "$SESSION_ID"

# ── 5. Execute the cell ───────────────────────────────────────────────────
echo "==> 5. Executing cell..."
call_tool "execute_cell" '{"cell_index": 0, "timeout": 60}' "$SESSION_ID"

# ── 6. Cleanup ────────────────────────────────────────────────────────────
echo "==> 6. Cleaning up..."
call_tool "close_notebook" '{"name": "kernel_test"}' "$SESSION_ID"
curl -s -X DELETE "$API/projects/$PROJECT_ID" > /dev/null 2>&1 || true
echo "Done."
