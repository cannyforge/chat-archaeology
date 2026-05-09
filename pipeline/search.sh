#!/usr/bin/env bash
# search.sh — zero LLM cost
#
# 1. Expands work/terms.json → per-topic pattern files
# 2. Greps every cluster file against every topic's patterns → scores
# 3. Assembles per-topic text files from clusters above threshold
#
# Env vars:
#   SCORE_THRESHOLD  minimum hits to include a cluster (default: 2)

set -euo pipefail

WORK="work"
CLUSTERS="$WORK/clusters"
PATTERNS="$WORK/patterns"
TOPICS_DIR="$WORK/topics"
SCORED="$WORK/scored.tsv"
THRESHOLD="${SCORE_THRESHOLD:-2}"

mkdir -p "$PATTERNS" "$TOPICS_DIR"

echo "Expanding terms.json → pattern files..."
python3 - <<'PYEOF'
import json
from pathlib import Path

terms = json.loads(Path("work/terms.json").read_text())
Path("work/patterns").mkdir(exist_ok=True)

for topic, data in terms.items():
    # combine keywords + patterns; grep -E handles alternation
    all_pats = data.get("patterns", []) + data.get("keywords", [])
    Path(f"work/patterns/{topic}.grep").write_text("\n".join(all_pats))
    print(f"  {topic}: {len(all_pats)} patterns")
PYEOF

echo ""
echo "Scoring clusters (grep, no LLM)..."
printf "cluster_id\ttopic\tscore\n" > "$SCORED"

for cluster_file in "$CLUSTERS"/cluster_*.txt; do
    cluster_id=$(basename "$cluster_file" .txt)

    for pattern_file in "$PATTERNS"/*.grep; do
        topic=$(basename "$pattern_file" .grep)
        score=0

        while IFS= read -r pattern; do
            [[ -z "$pattern" ]] && continue
            hits=$(grep -ciE "$pattern" "$cluster_file" 2>/dev/null) || hits=0
            score=$((score + hits))
        done < "$pattern_file"

        printf "%s\t%s\t%s\n" "$cluster_id" "$topic" "$score" >> "$SCORED"
    done
done

total=$(wc -l < "$SCORED")
echo "Scored $((total - 1)) cluster-topic pairs"

echo ""
echo "Building topic files (threshold = $THRESHOLD hits)..."
python3 - <<PYEOF
import csv, os
from pathlib import Path

threshold = int(os.environ.get("SCORE_THRESHOLD", "2"))
hits_by_topic = {}

with open("work/scored.tsv") as f:
    for row in csv.DictReader(f, delimiter="\t"):
        score = int(row["score"])
        if score >= threshold:
            hits_by_topic.setdefault(row["topic"], []).append((score, row["cluster_id"]))

topics_dir = Path("work/topics")
for topic, entries in hits_by_topic.items():
    entries.sort(reverse=True)
    out = topics_dir / f"{topic}.txt"
    with open(out, "w") as f:
        f.write(f"=== TOPIC: {topic.upper()} — {len(entries)} clusters ===\n\n")
        for score, cid in entries:
            cluster_path = Path(f"work/clusters/{cid}.txt")
            f.write(f"--- [{score} hits] {cid} ---\n")
            f.write(cluster_path.read_text())
            f.write("\n")
    size_kb = out.stat().st_size // 1024
    print(f"  {topic}: {len(entries)} clusters, {size_kb}KB → {out}")

skipped = [t for t in Path("work/patterns").glob("*.grep")
           if t.stem not in hits_by_topic]
if skipped:
    print(f"  (no clusters above threshold for: {', '.join(t.stem for t in skipped)})")
PYEOF

echo ""
echo "Done → work/topics/"
