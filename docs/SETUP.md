# 自動化設定（一次性，約 10 分鐘）

完成後：每天台北 07:00 自動出報，$0/月。

## 1. Gemini API key（生成用）

1. 到 [Google AI Studio](https://aistudio.google.com/apikey) 建立 API key（免費，不用信用卡）
2. **注意：該 Google Cloud 專案不要啟用 billing**，否則失去免費層
3. Repo → Settings → Secrets and variables → Actions → New repository secret
   - Name: `GEMINI_API_KEY`，Value: 貼上 key

（可選）若要固定模型：Settings → Secrets and variables → Actions → Variables 分頁 → 新增 `GEMINI_MODEL`（例如 `gemini-3.5-flash`）。留空時腳本自動用現行 flash 候選，並在型號改名/下架時自動退到下一個，不會整包失敗。

## 2. 觸發用 PAT（cron-job.org 呼叫 GitHub 用）

1. GitHub → Settings（個人）→ Developer settings → [Fine-grained tokens](https://github.com/settings/personal-access-tokens/new)
2. 設定：
   - Repository access: Only select repositories → `ai-daily-brief`
   - Permissions → Repository permissions → **Actions: Read and write**（其餘不用）
   - Expiration 建議一年，到期記得換
3. 產生後複製 token（只顯示一次）

## 3. cron-job.org 準點觸發

1. 到 [cron-job.org](https://cron-job.org) 註冊（免費）→ Create cronjob
2. 設定：
   - URL: `https://api.github.com/repos/sakuradigi/ai-daily-brief/actions/workflows/daily.yml/dispatches`
   - Schedule: 每天 **23:00 UTC**（= 台北 07:00）
   - Advanced → Request method: **POST**
   - Headers:
     ```
     Authorization: Bearer <你的PAT>
     Accept: application/vnd.github+json
     User-Agent: cron-job-org
     ```
   - Request body: `{"ref":"main"}`
3. 存檔後按 Test run，回 HTTP 204 即成功

repo 內建的 `schedule`（台北 07:30）作為備援：cron-job.org 沒打到時，最晚當天早上仍會出報（GitHub cron 可能延遲）。腳本有防重複機制，兩者都觸發也只會出一份。

## 4. 手動測試

Repo → Actions → Daily Brief → Run workflow。約 1–2 分鐘後：

- 綠勾 → `reports/` 出現今日 JSON、網站已更新
- 紅叉 → 點進去看 log；常見問題：
  - `GEMINI_API_KEY` secret 沒設或打錯名
  - 模型名失效 → 到 [模型清單](https://ai.google.dev/gemini-api/docs/models) 查現行名稱，設 `GEMINI_MODEL` variable
  - 某 RSS 來源失效 → 只是 WARN 不影響出報；要調整清單改 `scripts/fetch_sources.py` 的 `FEEDS`

## 維運備忘

- 週一自動出週報（台北時區判斷），無需設定
- 想重生成當日報告：Run workflow 前先刪掉當日 JSON，或本地跑 `FORCE=1 python scripts/generate_report.py`
- 換回 Claude 生成：workflow env 改 `PROVIDER: claude` + 新增 secret `ANTHROPIC_API_KEY`
- Actions 60 天無 push 會自動停用 schedule——本 repo 每日 commit，不會發生
