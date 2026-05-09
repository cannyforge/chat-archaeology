#!/usr/bin/env python3
"""
Single LLM call: given your app description, generate domain-aware grep patterns
for each design topic. These patterns drive all subsequent grep-based filtering —
no more LLM calls until extract.py.

Output: work/terms.json
"""
import json, sys
from pathlib import Path
from config import make_client, call_kwargs, first_text, extract_json

WORK_DIR = Path("work")

SYSTEM = (
    "You are a software architect. Given an application description, output ONLY "
    "valid JSON — no markdown, no explanation."
)

PROMPT_TEMPLATE = """Application:
{desc}

Generate grep-compatible search terms for each design topic below.
Each topic needs:
  - keywords: plain words likely to appear verbatim in chat (lowercase)
  - patterns: extended-regex patterns for grep -E -i (combine related terms with |)

Topics:
  architecture, api_design, data_model, auth, features,
  decisions, conflicts, tech_stack

Output schema:
{{
  "topic_name": {{
    "keywords": ["word1", "word2"],
    "patterns": ["pat1|pat2", "pat3"]
  }}
}}"""


def main():
    if len(sys.argv) < 2:
        print("Usage: python gen_terms.py 'brief app description'")
        print("   or: python gen_terms.py --file description.txt")
        sys.exit(1)

    if sys.argv[1] == "--file":
        desc = open(sys.argv[2], encoding="utf-8").read()
    else:
        desc = " ".join(sys.argv[1:])

    client = make_client()
    from config import MODEL
    print(f"Calling LLM to generate search terms (once) [{MODEL}]...")

    resp = client.messages.create(
        **call_kwargs(),
        system=SYSTEM,
        messages=[{"role": "user", "content": PROMPT_TEMPLATE.format(desc=desc)}],
    )

    text = first_text(resp.content)
    terms = extract_json(text)

    WORK_DIR.mkdir(exist_ok=True)
    out = WORK_DIR / "terms.json"
    out.write_text(json.dumps(terms, indent=2))

    print(f"Saved {len(terms)} topics → {out}")
    for topic, data in terms.items():
        kw = len(data.get("keywords", []))
        pat = len(data.get("patterns", []))
        print(f"  {topic}: {kw} keywords, {pat} patterns")


if __name__ == "__main__":
    main()
