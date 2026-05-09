#!/usr/bin/env python3
"""
Recovers a full design spec for one app from conversation clusters.

Two-model strategy:
  FAST  (Haiku)  — parallel per-cluster extraction + conflict detection
  SMART (Sonnet) — final spec synthesis

Handles:
  - Temporal idea shifts  (tracked via cluster timestamps)
  - Decision state changes (proposed → debated → confirmed → reversed)
  - Conflict detection     (same topic, different conclusions over time)

Usage:
  python3 pipeline/recover_app.py coaching "Voice-based AI personal coaching app"
  python3 pipeline/recover_app.py h_alpha  "Hedging portfolio framework for stocks and options"
"""
import json, sys, re, os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))
from config import make_client, call_kwargs, first_text, extract_json, ensure_dict, FAST_MODEL, SMART_MODEL

WORK_DIR    = Path("work")
MAX_WORKERS = int(os.environ.get("EXTRACT_WORKERS", "6"))
MIN_HITS    = int(os.environ.get("SCORE_THRESHOLD", "1"))

# ── Haiku extraction prompt ───────────────────────────────────────────────────
EXTRACT_SYSTEM = """\
You extract design information for a specific app from a chat log segment.
Output JSON only — no explanation or markdown.

Relevance: 0=unrelated, 1=mentioned in passing, 2=substantive design discussion

Decision state signals:
  proposed  — someone suggested this idea
  debated   — team is discussing pros/cons
  confirmed — team explicitly agreed (look for: agreed, confirmed, let's go with, decided, yes)
  reversed  — earlier decision overturned (look for: actually, changed, instead, dropped, no longer)
  deferred  — pushed to later (look for: later, next phase, not now, backlog)

Output schema:
{
  "relevant":    0|1|2,
  "state":       "proposed|debated|confirmed|reversed|deferred",
  "topic_tags":  ["2-4 short keywords for this discussion topic"],
  "product":     "product/UX insights or empty string",
  "engineering": "architecture/tech/data model insights or empty string",
  "ux_qa":       "UX flow or QA/testing notes or empty string",
  "deferred":    "features explicitly pushed to later or empty string",
  "reverses":    "description of what earlier decision this overturns, or empty string",
  "verbatim":    "one short direct quote capturing the key design intent"
}"""

# ── Haiku conflict summarizer ─────────────────────────────────────────────────
CONFLICT_SYSTEM = """\
You analyze a sequence of design notes about the same topic to identify idea shifts.
Output JSON only — no explanation.

{
  "topic":            "topic label",
  "original_approach":"what was proposed or decided first",
  "shift_description":"what changed and why",
  "final_approach":   "the most recent confirmed direction",
  "when_shifted":     "cluster ID where the shift occurred",
  "resolved":         true|false
}"""

# ── Sonnet synthesis prompt ───────────────────────────────────────────────────
SPEC_SYSTEM = """\
You are a senior software architect writing a complete design specification.
Be concrete — use exact names, data models, endpoints, flows from the source material.
This spec must be complete enough for an LLM agent to recreate the app from it alone."""

SPEC_PROMPT = """\
App: {name}
Description: {desc}

DESIGN NOTES ({n} clusters, chronological — later entries take precedence):
{notes}

DETECTED CONFLICTS & IDEA SHIFTS:
{conflicts}

Write a COMPLETE design spec in Markdown:

# {name} — Design Specification

## 1. Product Overview
## 2. Core Features & User Experience
## 3. Architecture & System Design
## 4. Data Models
## 5. API & Integrations
## 6. Engineering Decisions & Rationale
## 7. QA & Testing Considerations
## 8. Deferred / Future Work
## 9. Design Decisions That Changed Over Time
   (for each: original approach → trigger for change → final direction)
## 10. Open Questions & Unresolved Conflicts"""


def parse_cluster_timestamp(content: str) -> str:
    """Extract date from cluster header: === CLUSTER_NNNN [2026-03-20 06:32 ...] ==="""
    m = re.search(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})', content)
    return m.group(1) if m else "unknown"


def grep_clusters(app_name: str, app_desc: str) -> list[tuple[str, int, str, str]]:
    """Returns (cluster_id, score, content, timestamp) sorted by score desc."""
    words = re.findall(r'\w{4,}', (app_name + " " + app_desc).lower())
    patterns = [re.compile(w, re.IGNORECASE) for w in set(words)]

    results = []
    for f in sorted((WORK_DIR / "clusters").glob("cluster_*.txt")):
        content = f.read_text(encoding="utf-8")
        score = sum(len(p.findall(content)) for p in patterns)
        if score >= MIN_HITS:
            ts = parse_cluster_timestamp(content)
            results.append((f.stem, score, content, ts))

    results.sort(key=lambda x: x[1], reverse=True)
    return results


def haiku_extract(client, cluster_id: str, content: str,
                  timestamp: str, app_name: str, app_desc: str) -> dict:
    """Haiku call: extract design signals + decision state from one cluster."""
    truncated = content[:4000]
    try:
        resp = client.messages.create(
            **call_kwargs(model=FAST_MODEL, max_tokens=1000),
            system=EXTRACT_SYSTEM,
            messages=[{"role": "user", "content":
                f"App: {app_name} — {app_desc}\n"
                f"Cluster: {cluster_id}  Date: {timestamp}\n\n{truncated}"
            }],
        )
        data = ensure_dict(extract_json(first_text(resp.content)))
    except Exception as e:
        data = {"relevant": 0, "state": "proposed", "topic_tags": [],
                "product": "", "engineering": "", "ux_qa": "",
                "deferred": "", "reverses": "", "verbatim": ""}
        print(f"    [warn] {cluster_id}: {e}")

    data["cluster_id"] = cluster_id
    data["timestamp"]  = timestamp
    return data


def conflict_pass(client, relevant: list[dict]) -> list[dict]:
    """
    Detect temporal idea shifts across clusters.

    Strategy (no LLM until a real conflict signal is found):
      1. Group extractions by shared topic_tags
      2. Flag groups where state changed (confirmed → reversed) or reverses != ""
      3. For each flagged group: one small Haiku call to summarize the shift
    """
    # build tag → [extractions] map (chronological)
    tag_groups: dict[str, list[dict]] = defaultdict(list)
    for ex in sorted(relevant, key=lambda e: e["cluster_id"]):
        for tag in ex.get("topic_tags", []):
            tag_groups[tag.lower()].append(ex)

    conflicts = []

    for tag, entries in tag_groups.items():
        if len(entries) < 2:
            continue

        has_reversal = any(e.get("reverses") for e in entries)
        states = [e.get("state", "") for e in entries]
        has_state_flip = (
            "confirmed" in states and "reversed" in states
        ) or (
            states.count("confirmed") > 1  # same topic confirmed differently twice
        )

        if not (has_reversal or has_state_flip):
            continue

        # build compact timeline for Haiku
        timeline = "\n".join(
            f"[{e['cluster_id']} | {e['timestamp']} | state={e['state']}] "
            f"{e.get('product','')} {e.get('engineering','')} "
            f"{'REVERSES: ' + e['reverses'] if e.get('reverses') else ''}"
            for e in entries
        )

        try:
            resp = client.messages.create(
                **call_kwargs(model=FAST_MODEL, max_tokens=800),
                system=CONFLICT_SYSTEM,
                messages=[{"role": "user", "content":
                    f"Topic: {tag}\n\nChronological design notes:\n{timeline}"
                }],
            )
            summary = ensure_dict(extract_json(first_text(resp.content)))
            summary["tag"] = tag
            conflicts.append(summary)
            print(f"      conflict detected: [{tag}] — {summary.get('resolved') and 'resolved' or 'OPEN'}")
        except Exception as e:
            print(f"      [warn] conflict pass [{tag}]: {e}")

    return conflicts


def format_notes(extractions: list[dict]) -> str:
    lines = []
    for ex in sorted(extractions, key=lambda e: e["cluster_id"]):
        cid  = ex["cluster_id"]
        ts   = ex.get("timestamp", "")
        state = ex.get("state", "")
        parts = [ex.get("product",""), ex.get("engineering",""),
                 ex.get("ux_qa",""), ex.get("deferred","")]
        body = " | ".join(p for p in parts if p.strip())
        verbatim = ex.get("verbatim", "")
        reverses = ex.get("reverses", "")

        if body or verbatim:
            lines.append(f"[{cid} | {ts} | {state}] {body}")
            if reverses:
                lines.append(f"  ↩ REVERSES: {reverses}")
            if verbatim:
                lines.append(f'  > "{verbatim}"')
    return "\n".join(lines)


def format_conflicts(conflicts: list[dict]) -> str:
    if not conflicts:
        return "No explicit conflicts or idea reversals detected."
    lines = []
    for c in conflicts:
        resolved = "✓ resolved" if c.get("resolved") else "⚠ OPEN"
        lines.append(
            f"[{c.get('tag','?')}] {resolved}\n"
            f"  Original : {c.get('original_approach','')}\n"
            f"  Shift    : {c.get('shift_description','')}\n"
            f"  Final    : {c.get('final_approach','')}\n"
            f"  Shifted at: {c.get('when_shifted','')}"
        )
    return "\n\n".join(lines)


def recover(app_slug: str, app_desc: str):
    client   = make_client()
    app_name = app_slug.replace("_", " ").title()

    print(f"\n=== Recovering: {app_name} ===")
    print(f"    Fast  : {FAST_MODEL}")
    print(f"    Smart : {SMART_MODEL}")

    # Phase 1: grep
    print("\n[1/4] Grepping clusters...")
    matched = grep_clusters(app_slug + " " + app_name, app_desc)
    print(f"      {len(matched)} clusters matched")
    if not matched:
        print("      No clusters matched. Try a broader description or lower SCORE_THRESHOLD.")
        return

    # Phase 2: parallel Haiku extraction
    print(f"\n[2/4] Extracting with {FAST_MODEL} ({MAX_WORKERS} parallel)...")
    extractions = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(haiku_extract, client, cid, content, ts, app_name, app_desc): cid
            for cid, score, content, ts in matched
        }
        done = 0
        for future in as_completed(futures):
            extractions.append(future.result())
            done += 1
            if done % 10 == 0 or done == len(futures):
                n_rel = sum(1 for e in extractions if e.get("relevant", 0) >= 1)
                print(f"      {done}/{len(futures)} processed — {n_rel} relevant so far")

    relevant = [e for e in extractions if e.get("relevant", 0) >= 1]
    relevant.sort(key=lambda e: e["cluster_id"])
    print(f"      {len(relevant)} clusters with design content")

    (WORK_DIR / f"recovery_{app_slug}.json").write_text(json.dumps(relevant, indent=2))

    if not relevant:
        print("      No relevant content found.")
        return

    # Phase 3: conflict detection
    print(f"\n[3/4] Detecting conflicts & idea shifts...")
    conflicts = conflict_pass(client, relevant)
    print(f"      {len(conflicts)} conflict(s) found")

    # Phase 4: Sonnet synthesis
    print(f"\n[4/4] Synthesizing spec with {SMART_MODEL}...")
    prompt = SPEC_PROMPT.format(
        name=app_name,
        desc=app_desc,
        n=len(relevant),
        notes=format_notes(relevant),
        conflicts=format_conflicts(conflicts),
    )

    resp = client.messages.create(
        **call_kwargs(model=SMART_MODEL, max_tokens=12000),
        system=SPEC_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    spec = first_text(resp.content)

    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = Path(f"{app_slug}_spec_{ts}.md")
    out_path.write_text(spec, encoding="utf-8")
    print(f"\n✓  {out_path}  ({len(spec):,} chars | {len(relevant)} clusters | {len(conflicts)} conflicts)")


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 pipeline/recover_app.py <slug> 'description'")
        sys.exit(1)
    recover(app_slug=sys.argv[1], app_desc=" ".join(sys.argv[2:]))


if __name__ == "__main__":
    main()
