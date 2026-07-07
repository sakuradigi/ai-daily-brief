#!/usr/bin/env python3
"""抓取過去 24–26 小時各來源新項目 → data/sources_raw.json

來源皆為免費公開介面（RSS / API），無需任何 key。
單一來源失敗不影響整體（try/except + 記錄）。
"""
import json
import os
import re
import sys
import time
from pathlib import Path

import feedparser
import requests

UA = {"User-Agent": "ai-daily-brief/1.0 (+https://github.com/sakuradigi/ai-daily-brief)"}
NOW = time.time()
CUTOFF_HOURS = float(os.environ.get("CUTOFF_HOURS", "26"))
CUTOFF = NOW - CUTOFF_HOURS * 3600
OUT = Path(__file__).resolve().parent.parent / "data" / "sources_raw.json"

# (名稱, RSS/Atom URL, 權重 1–5)
FEEDS = [
    ("Anthropic", "https://www.anthropic.com/rss.xml", 5),
    ("OpenAI", "https://openai.com/news/rss.xml", 5),
    ("Google DeepMind", "https://deepmind.google/blog/rss.xml", 5),
    ("Hugging Face", "https://huggingface.co/blog/feed.xml", 4),
    ("Simon Willison", "https://simonwillison.net/atom/everything/", 4),
    ("The Verge AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", 3),
    ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/", 3),
    ("Ars Technica AI", "https://arstechnica.com/ai/feed/", 3),
]

AI_KEYWORDS = re.compile(
    r"\b(ai|llm|gpt|claude|gemini|llama|qwen|deepseek|mistral|grok|anthropic|openai|"
    r"deepmind|hugging\s?face|model|agent|agentic|transformer|neural|inference|mcp|"
    r"rag|fine-?tun|open[- ]?weight|benchmark|robotic|autonomous|copilot|chatbot)\b",
    re.I,
)

items = []
errors = []


def add(source, weight, title, url, published_ts, score=0, summary=""):
    if not title or not url or (published_ts and published_ts < CUTOFF):
        return
    items.append({
        "source": source,
        "weight": weight,
        "title": title.strip()[:300],
        "url": url,
        "published": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(published_ts or NOW)),
        "score": score,
        "summary": re.sub(r"<[^>]+>", "", summary or "").strip()[:500],
    })


def entry_ts(e):
    for k in ("published_parsed", "updated_parsed"):
        if e.get(k):
            return time.mktime(e[k])
    return None


def fetch_feeds():
    for name, url, weight in FEEDS:
        try:
            r = requests.get(url, headers=UA, timeout=20)
            r.raise_for_status()
            feed = feedparser.parse(r.content)
            for e in feed.entries[:30]:
                ts = entry_ts(e)
                if ts is None or ts < CUTOFF:
                    continue
                add(name, weight, e.get("title"), e.get("link"), ts,
                    summary=e.get("summary", ""))
        except Exception as ex:
            errors.append(f"{name}: {ex}")


def fetch_hackernews():
    """HN Algolia API：過去 26h、>=80 分、標題含 AI 關鍵字。"""
    try:
        r = requests.get(
            "https://hn.algolia.com/api/v1/search",
            params={
                "tags": "story",
                "numericFilters": f"created_at_i>{int(CUTOFF)},points>=80",
                "hitsPerPage": 100,
            },
            headers=UA, timeout=20,
        )
        r.raise_for_status()
        for h in r.json().get("hits", []):
            title = h.get("title") or ""
            if not AI_KEYWORDS.search(title):
                continue
            url = h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}"
            add("Hacker News", 4, title, url, h.get("created_at_i"),
                score=h.get("points", 0))
    except Exception as ex:
        errors.append(f"Hacker News: {ex}")


def fetch_arxiv():
    try:
        r = requests.get(
            "https://export.arxiv.org/api/query",
            params={
                "search_query": "cat:cs.CL OR cat:cs.AI OR cat:cs.LG",
                "sortBy": "submittedDate", "sortOrder": "descending",
                "max_results": 50,
            },
            headers=UA, timeout=30,
        )
        r.raise_for_status()
        feed = feedparser.parse(r.content)
        for e in feed.entries:
            ts = entry_ts(e)
            if ts is None or ts < CUTOFF:
                continue
            add("arXiv", 3, e.get("title", "").replace("\n", " "), e.get("link"), ts,
                summary=e.get("summary", ""))
    except Exception as ex:
        errors.append(f"arXiv: {ex}")


def fetch_reddit():
    for sub in ("LocalLLaMA", "MachineLearning"):
        try:
            r = requests.get(
                f"https://www.reddit.com/r/{sub}/top.json",
                params={"t": "day", "limit": 25},
                headers=UA, timeout=20,
            )
            r.raise_for_status()
            for c in r.json()["data"]["children"]:
                d = c["data"]
                if d.get("score", 0) < 100:
                    continue
                add(f"r/{sub}", 3, d.get("title"),
                    "https://www.reddit.com" + d.get("permalink", ""),
                    d.get("created_utc"), score=d.get("score", 0),
                    summary=d.get("selftext", "")[:500])
        except Exception as ex:
            errors.append(f"r/{sub}: {ex}")


def main():
    fetch_feeds()
    fetch_hackernews()
    fetch_arxiv()
    fetch_reddit()

    # 去重（同 URL）＋ 依 權重*log(score) 概念簡化排序 ＋ 總量上限
    seen, unique = set(), []
    for it in items:
        key = it["url"].split("?")[0].rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        unique.append(it)
    unique.sort(key=lambda x: (x["weight"], x["score"]), reverse=True)
    unique = unique[: int(os.environ.get("MAX_ITEMS", "120"))]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW)),
        "cutoff_hours": CUTOFF_HOURS,
        "errors": errors,
        "items": unique,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"OK: {len(unique)} items ({len(items)} raw), {len(errors)} source errors")
    for e in errors:
        print(f"  WARN {e}", file=sys.stderr)
    if not unique:
        print("FATAL: no items fetched", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
