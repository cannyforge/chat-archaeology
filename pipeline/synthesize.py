#!/usr/bin/env python3
"""
Merges all topic extractions into a final design spec.
Timeline-aware: later decisions on the same topic override earlier ones.
Conflicts are surfaced, not silently resolved.

Output:
  design_spec.md   — human-readable, LLM-agent-ready
  design_spec.json — full machine-readable extractions sidecar
"""
import json
from pathlib import Path
from config import make_client, call_kwargs, first_text

EXTRACTIONS_DIR = Path("work/extractions")

SYSTEM = "You are a senior software architect writing a design specification document."

PROMPT = """Below are structured extractions from team chat history, organized by design topic.
Each extraction was pulled chronologically — later dates carry more weight when decisions conflict.

Write a comprehensive SOFTWARE DESIGN SPEC in Markdown with these sections:

# System Overview
# Core Features
# Architecture
# Data Models
# API Design
# Authentication & Authorization
# Tech Stack
# Open Questions & Unresolved Conflicts
# Appendix: Decision Log (timeline of key decisions, newest last)

Rules:
- Later decisions override earlier ones — note when something was changed
- Flag every unresolved conflict explicitly with ⚠️
- Use exact names the team used (class names, field names, route paths)
- Be concrete — if a schema was discussed, write it out
- Keep each section scannable: bullet points and tables preferred over prose
- The spec must be complete enough for an LLM agent to recreate the application from it alone

Extractions:
{extractions}"""


def main():
    extraction_files = sorted(EXTRACTIONS_DIR.glob("*.json"))
    if not extraction_files:
        print("No extractions found. Run extract.py first.")
        return

    all_extractions = {}
    for path in extraction_files:
        all_extractions[path.stem] = json.loads(path.read_text())

    print(f"Synthesizing {len(all_extractions)} topics → design_spec.md ...")

    client = make_client()
    resp = client.messages.create(
        **call_kwargs(),
        system=SYSTEM,
        messages=[{
            "role": "user",
            "content": PROMPT.format(extractions=json.dumps(all_extractions, indent=2)),
        }],
    )

    spec = first_text(resp.content)

    Path("design_spec.md").write_text(spec, encoding="utf-8")
    Path("design_spec.json").write_text(
        json.dumps(all_extractions, indent=2), encoding="utf-8"
    )

    print("Saved: design_spec.md  (human/LLM-readable)")
    print("Saved: design_spec.json (machine-readable extractions)")


if __name__ == "__main__":
    main()
