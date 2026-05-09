#!/usr/bin/env python3
"""
Converts Discord JSON exports → flat TSV + per-cluster text files.
Groups messages into clusters by time gap (default: 30 min silence = new cluster).

Output:
  work/messages.tsv          — one line per message, grep-friendly
  work/clusters/cluster_NNN.txt — human-readable cluster files
  work/cluster_index.tsv     — summary: cluster id, time range, message count
"""
import json, sys, os
from datetime import datetime, timedelta
from pathlib import Path

GAP_MINUTES = int(os.environ.get("CLUSTER_GAP_MINUTES", "30"))
WORK_DIR = Path("work")


def load_messages(paths):
    msgs = []
    for p in paths:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        for m in data:
            content = m.get("content", "").strip()
            if not content:
                continue
            msgs.append({
                "id": m["id"],
                "ts": datetime.fromisoformat(m["timestamp"].replace("Z", "+00:00")),
                "author": m["author"],
                "content": content,
                "attachments": m.get("attachments", []),
            })
    msgs.sort(key=lambda m: m["ts"])
    # deduplicate by message id
    seen, unique = set(), []
    for m in msgs:
        if m["id"] not in seen:
            seen.add(m["id"])
            unique.append(m)
    return unique


def assign_clusters(msgs, gap_minutes):
    clusters, current = [], []
    for m in msgs:
        if current and (m["ts"] - current[-1]["ts"]) > timedelta(minutes=gap_minutes):
            clusters.append(current)
            current = []
        current.append(m)
    if current:
        clusters.append(current)
    return clusters


def write_tsv(clusters):
    path = WORK_DIR / "messages.tsv"
    with open(path, "w", encoding="utf-8") as f:
        f.write("cluster_id\ttimestamp\tauthor\tcontent\n")
        for i, cluster in enumerate(clusters):
            cid = f"cluster_{i:04d}"
            for m in cluster:
                # flatten to single line for grep
                content = m["content"].replace("\n", "\\n").replace("\t", " ")
                f.write(f"{cid}\t{m['ts'].isoformat()}\t{m['author']}\t{content}\n")


def write_clusters(clusters):
    cdir = WORK_DIR / "clusters"
    cdir.mkdir(parents=True, exist_ok=True)
    for i, cluster in enumerate(clusters):
        cid = f"cluster_{i:04d}"
        start = cluster[0]["ts"].strftime("%Y-%m-%d %H:%M")
        end = cluster[-1]["ts"].strftime("%H:%M")
        with open(cdir / f"{cid}.txt", "w", encoding="utf-8") as f:
            f.write(f"=== {cid.upper()} [{start} – {end}] ({len(cluster)} messages) ===\n\n")
            for m in cluster:
                ts = m["ts"].strftime("%H:%M")
                f.write(f"[{ts}] {m['author']}:\n{m['content']}\n")
                if m["attachments"]:
                    f.write(f"[attachments: {', '.join(m['attachments'])}]\n")
                f.write("\n")


def write_index(clusters):
    path = WORK_DIR / "cluster_index.tsv"
    with open(path, "w", encoding="utf-8") as f:
        f.write("cluster_id\tstart\tend\tcount\n")
        for i, cluster in enumerate(clusters):
            cid = f"cluster_{i:04d}"
            f.write(f"{cid}\t{cluster[0]['ts'].isoformat()}\t{cluster[-1]['ts'].isoformat()}\t{len(cluster)}\n")


def main():
    if len(sys.argv) < 2:
        print("Usage: python preprocess.py history1.json [history2.json ...]")
        sys.exit(1)

    WORK_DIR.mkdir(exist_ok=True)
    msgs = load_messages(sys.argv[1:])
    print(f"Loaded {len(msgs)} messages")

    clusters = assign_clusters(msgs, GAP_MINUTES)
    print(f"Found {len(clusters)} clusters  (gap threshold = {GAP_MINUTES} min)")

    write_tsv(clusters)
    write_clusters(clusters)
    write_index(clusters)

    print(f"Output → work/messages.tsv, work/clusters/ ({len(clusters)} files), work/cluster_index.tsv")


if __name__ == "__main__":
    main()
