#!/usr/bin/env bash
# run.sh — full pipeline: Discord JSON → design_spec.md
#
# Usage:
#   ./run.sh 'app description' history1.json [history2.json ...]
#
# Steps:
#   1  preprocess  — cluster messages by time gap (no LLM)
#   2  gen_terms   — generate domain search terms (1 LLM call)
#   3  search      — grep/awk scoring (no LLM)
#   4  extract     — extract decisions per topic (N LLM calls, cached system prompt)
#   5  synthesize  — merge into final spec (1 LLM call)
#
# Env vars:
#   CLUSTER_GAP_MINUTES  silence gap to split clusters (default: 30)
#   SCORE_THRESHOLD      min grep hits to include a cluster (default: 2)
#   ANTHROPIC_API_KEY    required for steps 2, 4, 5

set -euo pipefail

if [[ $# -lt 2 ]]; then
    echo "Usage: ./run.sh 'app description' history1.json [history2.json ...]"
    echo ""
    echo "Example:"
    echo "  ./run.sh 'Task management app with Kanban boards and team collaboration' history_general.json"
    exit 1
fi

APP_DESC="$1"; shift
JSON_FILES="$*"

echo "=== Discord → Design Spec Pipeline ==="
echo ""

echo "▶ Step 1/5  Clustering messages..."
python3 pipeline/preprocess.py $JSON_FILES

echo ""
echo "▶ Step 2/5  Generating search terms (1 LLM call)..."
python3 pipeline/gen_terms.py "$APP_DESC"

echo ""
echo "▶ Step 3/5  Scoring clusters with grep (no LLM)..."
bash pipeline/search.sh

echo ""
echo "▶ Step 4/5  Extracting decisions per topic (LLM, cached system prompt)..."
python3 pipeline/extract.py

echo ""
echo "▶ Step 5/5  Synthesizing final design spec (1 LLM call)..."
python3 pipeline/synthesize.py

echo ""
echo "=== Done ==="
echo ""
echo "  design_spec.md        ← start here"
echo "  design_spec.json      ← machine-readable sidecar"
echo "  work/topics/          ← per-topic filtered conversations (inspect if spec looks thin)"
echo "  work/clusters/        ← all raw clusters (grep these directly for deep dives)"
echo "  work/scored.tsv       ← cluster × topic score matrix"
