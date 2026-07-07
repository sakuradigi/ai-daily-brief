# ⚡ AI 時事快報 / AI Daily Brief

每日自動更新的雙語 AI 時事摘要。週一為週報。收合式設計，3–5 分鐘掌握重點。

Bilingual (繁中/EN) daily AI news digest. Weekly edition on Mondays. Collapsible design — scan everything in 3–5 minutes.

## 結構

```
├── index.html                  # 單頁應用（無 build step）
├── archive.json                # 日報索引（latest + 清單）
├── reports/YYYY/MM/YYYY-MM-DD.json   # 每日一檔，雙語同檔
└── 構思提案.md                  # 架構提案
```

## 本地預覽

```bash
python3 -m http.server 8000
# 開 http://localhost:8000
```

（直接雙擊 index.html 會因 file:// 無法 fetch JSON）

## 部署到 GitHub Pages

1. 在 GitHub 建立公開 repo（例如 `ai-daily-brief`）
2. ```bash
   git remote add origin https://github.com/<你的帳號>/ai-daily-brief.git
   git push -u origin main
   ```
3. Repo → Settings → Pages → Source 選 `main` branch / root → Save
4. 網站上線於 `https://<你的帳號>.github.io/ai-daily-brief/`

## 每日更新流程

每日產出一個 `reports/YYYY/MM/YYYY-MM-DD.json` 並更新 `archive.json`（`latest` 與 `reports` 清單），commit + push 即完成發布。週一的檔案 `type` 設為 `weekly` 並加上 `weekly` 欄位（雙語一週綜觀）。

日報 JSON 欄位見 `reports/2026/07/2026-07-07.json` 範例。
