# chat-archaeology

Recover design decisions from months of Discord history — without a vector database.

A grep-first, LLM-second pipeline that transforms chat exports into structured design specifications. Timestamps are preserved as a first-class dimension. Decisions track a lifecycle (proposed → confirmed → reversed). Conflicts surface automatically.

---

## How It Works

```
Discord JSON  →  Temporal Clusters  →  Grep Scoring  →  Haiku Extraction  →  Sonnet Synthesis
```

**Six stages, two model tiers:**

| Stage | Cost | What happens |
|-------|------|--------------|
| Preprocessing | Free | Deduplicate messages, split by 30-min silence gaps into clusters |
| Term generation | 1 Haiku call | App description → domain-aware regex patterns |
| Grep scoring | Free | Score every cluster × topic pair — no tokens |
| Threshold filter | Free | Drop low-scoring clusters (~75% never reach an LLM) |
| Parallel extraction | N × Haiku | Per-cluster: decision state, topic tags, verbatim quote |
| Synthesis | 1 Sonnet call | Chronological notes + conflict summary → full design spec |

**Decision states** tracked per cluster: `proposed` → `debated` → `confirmed` → `reversed` → `deferred`

**Conflict detection**: topics where the state sequence contains both `confirmed` and `reversed` trigger a targeted Haiku call to summarize the shift. Topics that evolved cleanly: zero extra cost.

---

## Setup

```bash
# 1. Clone and install dependencies
git clone https://github.com/cannyforge/chat-archaeology
cd chat-archaeology
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env with your Discord bot token, channel ID, and LLM API key
```

### Discord Bot Setup

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications)
2. Create a new application → Bot → copy the token
3. Enable **Message Content Intent** under Privileged Gateway Intents
4. Invite the bot to your server with `Read Message History` permission
5. Copy the channel ID (right-click channel → Copy Channel ID)

---

## Usage

### Step 1: Export Discord history

```bash
python3 bot.py
# Saves: history_<channel-name>_<timestamp>.json
```

### Step 2: Run the full pipeline

```bash
python3 pipeline/recover_app.py <slug> "brief description of the app"

# Examples:
python3 pipeline/recover_app.py my_app "Task management app with Kanban boards and team collaboration"
python3 pipeline/recover_app.py finance_app "Portfolio tracking and rebalancing tool for stocks and options"
```

Output: `<slug>_spec_<timestamp>.md` — a complete design specification.

### Alternative: Run stages individually

```bash
# 1. Preprocess multiple JSON exports
python3 pipeline/preprocess.py history_channel1.json history_channel2.json

# 2. Generate search terms (1 LLM call)
python3 pipeline/gen_terms.py "your app description"

# 3. Score clusters with grep (free)
bash pipeline/search.sh

# 4. Extract decisions (parallel Haiku calls)
python3 pipeline/extract.py

# 5. Synthesize final spec (1 Sonnet call)
python3 pipeline/synthesize.py
```

---

## Configuration

All settings via `.env` (copy from `.env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `DISCORD_TOKEN` | — | Bot token from Discord Developer Portal |
| `DISCORD_CHANNEL_ID` | — | Channel to export (one at a time) |
| `LLM_API_KEY` | — | Anthropic API key (or compatible) |
| `LLM_FAST_MODEL` | `claude-haiku-4-5-20251001` | Model for extraction (parallel, cheap) |
| `LLM_SMART_MODEL` | `claude-sonnet-4-6` | Model for synthesis (one call, high quality) |
| `LLM_MAX_TOKENS` | `16000` | Max output tokens per call |
| `LLM_BASE_URL` | — | Optional: non-Anthropic endpoint (e.g., DeepSeek) |
| `LLM_EXTRA_BODY` | — | Extra API params, e.g. `{"enable_thinking": false}` |
| `CLUSTER_GAP_MINUTES` | `30` | Silence gap that splits a new cluster |
| `SCORE_THRESHOLD` | `1` | Min grep hits for a cluster to proceed |
| `EXTRACT_WORKERS` | `6` | Parallel workers for Haiku extraction |

### Using a non-Anthropic model

The pipeline uses the Anthropic SDK but supports any compatible endpoint:

```env
LLM_BASE_URL=https://api.deepseek.com/anthropic
LLM_FAST_MODEL=deepseek-v4-flash
LLM_SMART_MODEL=deepseek-v4-pro
LLM_EXTRA_BODY={"enable_thinking": false}
```

---

## Output Format

The recovered spec is structured Markdown with ten sections:

1. **Product Overview** — what the app is and does
2. **Core Features & User Experience** — feature list and UX flows
3. **Architecture & System Design** — tech choices and structure
4. **Data Models** — entities, fields, relationships
5. **API & Integrations** — endpoints and external services
6. **Engineering Decisions & Rationale** — why things are the way they are
7. **QA & Testing Considerations** — test strategy
8. **Deferred / Future Work** — what got pushed to later
9. **Design Decisions That Changed Over Time** — the intellectual history: original approach → trigger → final direction
10. **Open Questions & Unresolved Conflicts** — what's still unsettled

Section 9 is the most valuable: it captures the *why* behind each pivot, which no point-in-time snapshot can recover.

---

## Why Grep Instead of Embeddings

Semantic search via embeddings requires infrastructure: an embedding API, a vector store, and a retrieval query per run. Grep requires none of that.

When search terms are generated by a domain-aware LLM call (step 2), the vocabulary is already high-signal. "Delta-neutral rebalancing" in a finance chat is precise enough that grep finds it reliably. The recall gap between grep and semantic search is smaller than it sounds — and the cost gap is infinite.

**Token economics for a typical corpus:**
- ~75% of messages filtered by grep at zero cost
- Extraction: O(relevant_clusters) × Haiku price
- Synthesis: O(1) × Sonnet price
- Total: roughly equivalent to 2–3 standalone Sonnet calls for a months-long chat history

---

## Project Structure

```
.
├── bot.py                    # Discord history exporter
├── run.sh                    # Full pipeline runner (single command)
├── requirements.txt
├── .env.example              # Configuration template
└── pipeline/
    ├── config.py             # Shared LLM client config
    ├── preprocess.py         # Cluster messages by time gap
    ├── gen_terms.py          # Generate domain search terms (1 LLM call)
    ├── search.sh             # Grep scoring (free)
    ├── extract.py            # Per-topic decision extraction
    ├── synthesize.py         # Final spec synthesis
    └── recover_app.py        # All-in-one: grep + extract + synthesize for one app
```

---

## Requirements

- Python 3.11+
- `anthropic>=0.40.0`
- `discord.py>=2.3.0`
- `python-dotenv`
- `json-repair` (handles truncated LLM JSON output gracefully)

```bash
pip install -r requirements.txt
```

---

## License

MIT
