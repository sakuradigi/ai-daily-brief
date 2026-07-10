#!/usr/bin/env python3
"""讀取 data/sources_raw.json → 呼叫 LLM 生成雙語日報 → reports/ + archive.json

Model-agnostic：PROVIDER=gemini（預設）| claude | mock
- gemini: 需 GEMINI_API_KEY（免費層即可），GEMINI_MODEL 未設時自動用現行 flash（見 GEMINI_FALLBACKS）
- claude: 需 ANTHROPIC_API_KEY，CLAUDE_MODEL 預設 claude-sonnet-5
- mock:   不呼叫 API，產生測試用日報（驗證管線）
週一（台北時間）自動生成週報：type=weekly + weekly 綜觀欄位。
"""
import datetime
import json
import os
import re
import sys
import time
import zoneinfo
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
TAIPEI = zoneinfo.ZoneInfo("Asia/Taipei")
TODAY = datetime.datetime.now(TAIPEI).date()
DATE = os.environ.get("REPORT_DATE", TODAY.isoformat())
IS_WEEKLY = datetime.date.fromisoformat(DATE).weekday() == 0  # 週一
PROVIDER = os.environ.get("PROVIDER", "gemini").lower()

REPORT_PATH = ROOT / "reports" / DATE[:4] / DATE[5:7] / f"{DATE}.json"
ARCHIVE_PATH = ROOT / "archive.json"

SECTIONS_SPEC = """[
 {"id":"headlines","title":{"zh":"今日頭條","en":"Top Stories"}},          ← 最多 3 則
 {"id":"opensource","title":{"zh":"開源與工具","en":"Open Source & Tools"}},
 {"id":"products","title":{"zh":"產品與應用","en":"Products & Applications"}},
 {"id":"research","title":{"zh":"模型與研究","en":"Models & Research"}},
 {"id":"industry","title":{"zh":"產業與政策","en":"Industry & Policy"}},
 {"id":"quickbits","title":{"zh":"一句話快訊","en":"Quick Bits"},"style":"flash"}
]"""

PROMPT_TEMPLATE = """你是「AI 時事快報」的主編，為技術宅讀者製作每日 AI/LLM/前沿科技摘要。

## 讀者輪廓與口味
- 工程師/geek，想用 3–5 分鐘掌握世界 AI 發展
- 口味排序：開源與工具 > 產品與應用 > 模型與研究；產業/政策僅收重大者，小事放快訊
- 重視：可動手的東西（工具、開源權重、API、benchmark）、對開發者的實際影響（價格、額度、棄用）
- 不要行銷語言、不要湊數；寧缺勿濫

## 任務
從下方原始素材中挑選並撰寫今日日報。輸出「單一 JSON 物件」，不要 markdown code fence，不要任何 JSON 以外的文字。

## 輸出格式
{{
  "date": "{date}",
  "type": "{rtype}",{weekly_field}
  "summary": {{"zh": "20 字內今日梗概", "en": "one-line digest"}},
  "sections": {sections_spec}
}}
- 每個 section 含 "items" 陣列。一般 item：{{"headline":{{"zh":"...","en":"..."}},"detail":{{"zh":"...","en":"..."}},"source":"原始URL","tags":["..."]}}
- headline：一句話、資訊密度高（收合時唯一可見）；detail：2–3 句，說清楚「是什麼＋為什麼重要/對開發者的影響」
- quickbits 的 item 只要 headline 與 source（不要 detail）
- 各 section 2–4 則、quickbits 3–6 則、全報合計 12–18 則；某分類無料時 items 給空陣列
- source 一律用素材中的原始 URL，禁止捏造 URL 或內容；素材不足的主題寧可不寫
- 雙語皆為完整撰寫（正體中文、English），不是互譯腔；中文用台灣用語

{weekly_instructions}
## 原始素材（過去 24 小時，含來源權重與社群分數）
{sources}
"""

WEEKLY_INSTRUCTIONS = """## 週報加項（今天是週一）
"weekly" 欄位：{"zh":"...","en":"..."}，150–250 字綜觀本週——主要趨勢 2–3 條 + 本週最重要的 3 件事。以下是過去 7 天日報的標題供回顧：
{week_headlines}
"""


# 候選模型：GEMINI_MODEL（若設）優先，其後依序 fallback。
# 單一型號名失效（改名/下架 → 404）不再整包失敗，會自動退到下一個。
# 現行名稱見 https://ai.google.dev/gemini-api/docs/models（2026-06 為準）
GEMINI_FALLBACKS = ["gemini-3.5-flash", "gemini-flash-latest", "gemini-3.1-flash-lite"]


# 過載/限流/暫時性錯誤：退避重試，退避後仍失敗就換下一個候選模型
TRANSIENT = {429, 500, 502, 503, 504}


def call_gemini(prompt: str) -> str:
    key = os.environ["GEMINI_API_KEY"]
    candidates = []
    if os.environ.get("GEMINI_MODEL"):
        candidates.append(os.environ["GEMINI_MODEL"])
    candidates += [m for m in GEMINI_FALLBACKS if m not in candidates]

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 16384,
            "responseMimeType": "application/json",
        },
    }

    last_err = None
    for model in candidates:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        # 每個模型最多 4 次，指數退避（5→10→20→40s），吸收 503/429 這類暫時性過載
        for attempt in range(4):
            try:
                r = requests.post(url, params={"key": key}, json=payload, timeout=300)
            except requests.RequestException as ex:  # 連線/逾時
                last_err = f"{model}: {ex}"
                wait = 5 * 2 ** attempt
                print(f"WARN {model} network error, backoff {wait}s: {ex}", file=sys.stderr)
                time.sleep(wait)
                continue
            if r.status_code in (403, 404):  # 型號不存在/無權限 → 直接換下一個候選
                last_err = f"{model}: HTTP {r.status_code} {r.text[:200]}"
                print(f"WARN model '{model}' unavailable ({r.status_code}), trying next model", file=sys.stderr)
                break
            if r.status_code in TRANSIENT:  # 過載/限流 → 退避後重試同模型
                last_err = f"{model}: HTTP {r.status_code} {r.text[:200]}"
                wait = 5 * 2 ** attempt
                print(f"WARN {model} HTTP {r.status_code} (transient), backoff {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()["candidates"][0]["content"]["parts"][0]["text"], model
    raise RuntimeError(f"all Gemini attempts exhausted: {last_err}")


def call_claude(prompt: str):
    """備援：Anthropic Claude（付費、穩定）。預設 Haiku，性價比高。"""
    model = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5")
    last_err = None
    for attempt in range(4):
        try:
            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": model,
                    "max_tokens": 16384,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=300,
            )
        except requests.RequestException as ex:
            last_err = ex
            wait = 5 * 2 ** attempt
            print(f"WARN claude network error, backoff {wait}s: {ex}", file=sys.stderr)
            time.sleep(wait)
            continue
        if r.status_code in TRANSIENT or r.status_code == 529:  # 過載/限流 → 退避重試
            last_err = f"HTTP {r.status_code} {r.text[:200]}"
            wait = 5 * 2 ** attempt
            print(f"WARN claude HTTP {r.status_code} (transient), backoff {wait}s", file=sys.stderr)
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r.json()["content"][0]["text"], model
    raise RuntimeError(f"claude attempts exhausted: {last_err}")


def call_mock(prompt: str):
    report = {
        "date": DATE, "type": "weekly" if IS_WEEKLY else "daily",
        "summary": {"zh": "管線測試", "en": "pipeline test"},
        "sections": [{
            "id": "headlines", "title": {"zh": "今日頭條", "en": "Top Stories"},
            "items": [{"headline": {"zh": "測試項目", "en": "Test item"},
                       "detail": {"zh": "這是 mock provider 產生的測試內容。", "en": "Generated by the mock provider."},
                       "source": "https://example.com", "tags": ["test"]}],
        }, {
            "id": "quickbits", "title": {"zh": "一句話快訊", "en": "Quick Bits"},
            "style": "flash",
            "items": [{"headline": {"zh": "快訊測試", "en": "Flash test"}, "source": "https://example.com"}],
        }],
    }
    if IS_WEEKLY:
        report["weekly"] = {"zh": "本週綜觀測試。", "en": "Weekly test."}
    return json.dumps(report, ensure_ascii=False), "mock"


PROVIDERS = {"gemini": call_gemini, "claude": call_claude, "mock": call_mock}


def parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


def validate(r: dict):
    assert r["date"] == DATE, "date mismatch"
    assert r["type"] in ("daily", "weekly")
    assert r["summary"]["zh"] and r["summary"]["en"]
    if IS_WEEKLY:
        assert r.get("weekly", {}).get("zh") and r["weekly"].get("en"), "missing weekly"
    total = 0
    for s in r["sections"]:
        assert s["id"] and s["title"]["zh"] and s["title"]["en"]
        for it in s["items"]:
            total += 1
            assert it["headline"]["zh"] and it["headline"]["en"]
            assert it.get("source", "").startswith("http"), f"bad source in {s['id']}"
            if s.get("style") != "flash":
                assert it["detail"]["zh"] and it["detail"]["en"]
    min_items = 1 if PROVIDER == "mock" else 5
    assert total >= min_items, f"only {total} items"


def week_headlines() -> str:
    lines = []
    d = datetime.date.fromisoformat(DATE)
    for i in range(1, 8):
        day = d - datetime.timedelta(days=i)
        p = ROOT / "reports" / day.strftime("%Y") / day.strftime("%m") / f"{day}.json"
        if not p.exists():
            continue
        rep = json.loads(p.read_text(encoding="utf-8"))
        for s in rep.get("sections", []):
            for it in s.get("items", []):
                lines.append(f"- [{day}] {it['headline']['zh']}")
    return "\n".join(lines) or "（過去 7 天尚無日報）"


def main():
    if REPORT_PATH.exists() and os.environ.get("FORCE") != "1":
        print(f"SKIP: {REPORT_PATH} already exists (set FORCE=1 to regenerate)")
        return

    sources = json.loads((ROOT / "data" / "sources_raw.json").read_text(encoding="utf-8"))
    prompt = PROMPT_TEMPLATE.format(
        date=DATE,
        rtype="weekly" if IS_WEEKLY else "daily",
        weekly_field='\n  "weekly": {"zh": "...", "en": "..."},' if IS_WEEKLY else "",
        sections_spec=SECTIONS_SPEC,
        weekly_instructions=WEEKLY_INSTRUCTIONS.replace("{week_headlines}", week_headlines()) if IS_WEEKLY else "",
        sources=json.dumps(sources["items"], ensure_ascii=False),
    )

    # 供應商鏈：PROVIDER 可為逗號清單（如 "gemini,claude"）。依序嘗試，前者失敗才退到後者。
    # 每個供應商內層各自已對 503/429 做退避重試；外層這 2 次主要救「解析/驗證」失敗（重下 prompt）。
    chain = [p.strip() for p in PROVIDER.split(",") if p.strip()]
    report, used_model, last_err = None, None, None
    for prov in chain:
        call = PROVIDERS.get(prov)
        if call is None:
            print(f"WARN unknown provider '{prov}', skipping", file=sys.stderr)
            continue
        for attempt in range(2):
            try:
                text, used_model = call(prompt)
                rep = parse_json(text)
                rep["date"] = DATE  # 強制對齊
                validate(rep)
                report = rep
                break
            except Exception as ex:
                last_err = ex
                print(f"WARN provider={prov} attempt {attempt + 1} failed: {ex}", file=sys.stderr)
        if report is not None:
            break
        print(f"WARN provider={prov} 全數失敗，改試下一個供應商", file=sys.stderr)
    if report is None:
        raise SystemExit(f"FATAL: 所有供應商皆失敗: {last_err}")

    summary = report.pop("summary")
    report["model"] = used_model  # 實際生成本報的模型，供網頁顯示
    report["generated_at"] = datetime.datetime.now(TAIPEI).isoformat(timespec="minutes")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    archive = json.loads(ARCHIVE_PATH.read_text(encoding="utf-8"))
    archive["reports"] = [e for e in archive["reports"] if e["date"] != DATE]
    archive["reports"].append({"date": DATE, "type": report["type"], "summary": summary})
    archive["reports"].sort(key=lambda e: e["date"], reverse=True)
    archive["latest"] = archive["reports"][0]["date"]
    ARCHIVE_PATH.write_text(json.dumps(archive, ensure_ascii=False, indent=1), encoding="utf-8")

    n = sum(len(s["items"]) for s in report["sections"])
    print(f"OK: {REPORT_PATH.relative_to(ROOT)} ({report['type']}, {n} items, model={used_model})")


if __name__ == "__main__":
    main()
