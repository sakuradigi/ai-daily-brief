#!/usr/bin/env python3
"""出報成功後推播到 Telegram：一句話快訊 + 當日快報連結。

需環境變數：
- TELEGRAM_BOT_TOKEN、TELEGRAM_CHAT_ID（見 docs/SETUP.md 設定教學）
- SITE_URL（GitHub Pages 網址，例 https://sakuradigi.github.io/ai-daily-brief）
- REPORT_DATE（可選，預設台北今日）

設計為「盡力送達」：缺 secret 或送出失敗只印警告、exit 0，不讓通知問題把已成功的出報標成紅叉。
失敗情境的通知由 workflow 用 curl 另外處理（見 daily.yml）。
"""
import datetime
import html
import json
import os
import sys
import zoneinfo
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
TAIPEI = zoneinfo.ZoneInfo("Asia/Taipei")
DATE = os.environ.get("REPORT_DATE", datetime.datetime.now(TAIPEI).date().isoformat())


def send(token: str, chat_id: str, text: str):
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    r.raise_for_status()


def build_message() -> str:
    report_path = ROOT / "reports" / DATE[:4] / DATE[5:7] / f"{DATE}.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))

    is_weekly = report.get("type") == "weekly"
    kind = "週報" if is_weekly else "日報"

    # 一句話梗概（存在 archive.json，不在報告檔內）
    subtitle = ""
    try:
        archive = json.loads((ROOT / "archive.json").read_text(encoding="utf-8"))
        entry = next((e for e in archive["reports"] if e["date"] == DATE), None)
        if entry and entry.get("summary", {}).get("zh"):
            subtitle = f"\n<i>{html.escape(entry['summary']['zh'])}</i>"
    except Exception:
        pass

    # 一句話快訊（quickbits section）
    bullets = []
    for sec in report.get("sections", []):
        if sec.get("id") == "quickbits" or sec.get("style") == "flash":
            for it in sec.get("items", []):
                h = it.get("headline", {}).get("zh")
                if h:
                    bullets.append(f"• {html.escape(h)}")
    flash = ("\n\n📌 <b>一句話快訊</b>\n" + "\n".join(bullets)) if bullets else ""

    site = os.environ.get("SITE_URL", "https://sakuradigi.github.io/ai-daily-brief").rstrip("/")
    link = f"{site}/#{DATE}"
    model = report.get("model", "")
    footer = f"\n\n📖 <a href=\"{link}\">看完整快報</a>"
    if model:
        footer += f"\n<i>由 {html.escape(model)} 撰寫</i>"

    return f"⚡ <b>AI 時事快報 · {DATE} {kind}</b>{subtitle}{flash}{footer}"


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("SKIP notify: 未設定 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID", file=sys.stderr)
        return
    try:
        send(token, chat_id, build_message())
        print(f"OK: Telegram 已推播 {DATE}")
    except Exception as ex:
        print(f"WARN notify 失敗（不影響出報）: {ex}", file=sys.stderr)


if __name__ == "__main__":
    main()
