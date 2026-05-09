"""
Shared LLM client config. Loaded once and imported by all pipeline scripts.
Reads from .env (or environment). Supports any Anthropic-compatible API.
"""
import os, json as _json
from pathlib import Path
from dotenv import load_dotenv
import anthropic

load_dotenv(Path(__file__).parent.parent / ".env")

API_KEY     = os.environ.get("LLM_API_KEY", "")
BASE_URL    = os.environ.get("LLM_BASE_URL", "")
MODEL       = os.environ.get("LLM_MODEL",       "claude-sonnet-4-6")
FAST_MODEL  = os.environ.get("LLM_FAST_MODEL",  "claude-haiku-4-5-20251001")
SMART_MODEL = os.environ.get("LLM_SMART_MODEL", "claude-sonnet-4-6")
MAX_TOKENS  = int(os.environ.get("LLM_MAX_TOKENS", "16000"))

# Extra body params forwarded verbatim to every API call.
# Use this to disable thinking on reasoning models, e.g.:
#   LLM_EXTRA_BODY={"enable_thinking": false}
_extra_raw  = os.environ.get("LLM_EXTRA_BODY", "")
EXTRA_BODY  = _json.loads(_extra_raw) if _extra_raw.strip() else {}


def make_client() -> anthropic.Anthropic:
    kwargs = {"api_key": API_KEY}
    if BASE_URL:
        kwargs["base_url"] = BASE_URL
    return anthropic.Anthropic(**kwargs)


def call_kwargs(model: str = None, max_tokens: int = None) -> dict:
    """Base kwargs merged into every messages.create() call."""
    kw = {
        "model": model or MODEL,
        "max_tokens": max_tokens or MAX_TOKENS,
    }
    if EXTRA_BODY:
        kw["extra_body"] = EXTRA_BODY
    return kw


def extract_json(text: str) -> dict:
    """
    Parse JSON from LLM output using multiple strategies in order:
      1. Direct parse (clean output)
      2. Strip markdown fences, then parse
      3. raw_decode from first '{' (ignores trailing prose)
      4. json-repair (handles truncation, unbalanced braces, bad quotes)
    Returns a dict, never a string.
    """
    import re, json as _json

    def _try(s: str):
        return _json.loads(s)

    # 1. direct
    try:
        return _try(text.strip())
    except Exception:
        pass

    # 2. strip markdown fences
    fenced = re.search(r"```(?:json)?\s*(\{.*?)\s*```", text, re.DOTALL)
    if fenced:
        try:
            return _try(fenced.group(1))
        except Exception:
            pass

    # 3. raw_decode from first '{' — stops at first complete object, ignores trailing text
    start = text.find("{")
    if start != -1:
        try:
            obj, _ = _json.JSONDecoder().raw_decode(text, start)
            return obj
        except Exception:
            pass

    # 4. json-repair — handles truncated responses, unbalanced braces, missing quotes
    try:
        from json_repair import repair_json
        repaired = repair_json(text[start:] if start != -1 else text)
        return _json.loads(repaired)
    except Exception:
        pass

    raise ValueError(f"Could not parse JSON from response (len={len(text)})")


def ensure_dict(obj) -> dict:
    """Coerce parsed JSON to a dict. Unwraps lists by merging all dict items."""
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, list):
        merged = {}
        for item in obj:
            if isinstance(item, dict):
                merged.update(item)
        if merged:
            return merged
    raise ValueError(f"Expected a JSON object, got {type(obj).__name__}: {repr(obj)[:80]}")


def first_text(content) -> str:
    """
    Return text from the first TextBlock, skipping ThinkingBlocks.
    Falls back to ThinkingBlock.thinking if no TextBlock exists
    (happens when max_tokens is too low for reasoning models to finish both).
    """
    thinking_fallback = None
    for block in content:
        if hasattr(block, "text"):
            return block.text
        if hasattr(block, "thinking") and thinking_fallback is None:
            thinking_fallback = block.thinking

    if thinking_fallback:
        return thinking_fallback

    raise ValueError(
        f"No usable block found in response. Blocks: {[type(b).__name__ for b in content]}"
    )
