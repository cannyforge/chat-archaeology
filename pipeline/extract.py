#!/usr/bin/env python3
"""
Sends each topic file to Claude for structured extraction.
System prompt is cached (shared across all topic calls) to minimize token cost.

Output: work/extractions/<topic>.json per topic
"""
import json, sys, os
from pathlib import Path
from config import make_client, call_kwargs, first_text, extract_json

WORK_DIR = Path("work")
TOPICS_DIR = WORK_DIR / "topics"
EXTRACTIONS_DIR = WORK_DIR / "extractions"

# Cached once across all topic calls — only charged on first call
SYSTEM_PROMPT = """You are a software architect extracting design decisions from raw chat logs.

Rules:
- Extract ONLY explicitly stated or confirmed decisions — never infer
- A decision is "confirmed" when the team agreed (look for: agreed, confirmed, done, let's go with, decided)
- A decision is "likely" when proposed without objection
- A decision is "uncertain" when still being discussed
- Surface conflicts even if resolved — they show why a choice was made
- Preserve exact terminology the team used (class names, field names, endpoint paths)

Output valid JSON only, no markdown:
{
  "topic": "string",
  "decisions": [
    {
      "statement": "what was decided",
      "confidence": "confirmed|likely|uncertain",
      "evidence": "short verbatim quote or close paraphrase",
      "approximate_date": "YYYY-MM-DD or date range"
    }
  ],
  "conflicts": [
    {
      "description": "what was debated",
      "options": ["option A", "option B"],
      "resolution": "how resolved, or null if open"
    }
  ],
  "open_questions": ["unanswered question"],
  "key_terms": ["domain terms defined or coined in this discussion"]
}"""


def extract_topic(client, topic_name, content):
    # For very large topic files: keep the first 2/3 (context) + last 1/3 (latest decisions win)
    max_chars = 80_000
    if len(content) > max_chars:
        keep_start = (max_chars * 2) // 3
        keep_end = max_chars // 3
        content = (
            content[:keep_start]
            + f"\n\n[... {len(content) - max_chars} chars truncated — middle section ...]\n\n"
            + content[-keep_end:]
        )

    resp = client.messages.create(
        **call_kwargs(),
        system=[{
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},  # reused across all topic calls
        }],
        messages=[{
            "role": "user",
            "content": f"Extract design decisions for topic: {topic_name}\n\n{content}",
        }],
    )

    text = first_text(resp.content)
    return extract_json(text)


def main():
    client = make_client()
    EXTRACTIONS_DIR.mkdir(parents=True, exist_ok=True)

    topic_files = sorted(TOPICS_DIR.glob("*.txt"))
    if not topic_files:
        print("No topic files found in work/topics/. Run search.sh first.")
        sys.exit(1)

    print(f"Extracting {len(topic_files)} topics...")
    for path in topic_files:
        topic = path.stem
        out_path = EXTRACTIONS_DIR / f"{topic}.json"

        if out_path.exists() and "--redo" not in sys.argv:
            print(f"  {topic}: skipped (already extracted — pass --redo to force)")
            continue

        print(f"  {topic}: calling LLM ({path.stat().st_size // 1024}KB)...")
        content = path.read_text(encoding="utf-8")
        result = extract_topic(client, topic, content)

        out_path.write_text(json.dumps(result, indent=2))

        d = len(result.get("decisions", []))
        c = len(result.get("conflicts", []))
        q = len(result.get("open_questions", []))
        print(f"    → {d} decisions, {c} conflicts, {q} open questions")

    print(f"\nExtractions saved → {EXTRACTIONS_DIR}/")


if __name__ == "__main__":
    main()
