# 自動化設定（一次性，約 10 分鐘）

完成後：每天台北 07:00 自動出報，$0/月。

## 1. Gemini API key（生成用）

1. 到 [Google AI Studio](https://aistudio.google.com/apikey) 建立 API key（免費，不用信用卡）
2. **注意：該 Google Cloud 專案不要啟用 billing**，否則失去免費層
3. Repo → Settings → Secrets and variables → Actions → New repository secret
   - Name: `GEMINI_API_KEY`，Value: 貼上 key

（可選）若要固定模型：Settings → Secrets and variables → Actions → Variables 分頁 → 新增 `GEMINI_MODEL`（例如 `gemini-3.5-flash`）。留空時腳本自動用現行 flash 候選，並在型號改名/下架時自動退到下一個，不會整包失敗。

### 1b. 備援：Claude（付費、穩定，強烈建議）

Gemini 免費層在尖峰易吃 503。workflow 已設 `PROVIDER: gemini,claude`：Gemini 失敗會自動退到 Claude。啟用只需加一個 secret：

1. 到 [Anthropic Console](https://console.anthropic.com/) 建立 API key（需綁定 billing 的帳戶才穩定）
2. Repo → Settings → Secrets and variables → Actions → New repository secret
   - Name: `ANTHROPIC_API_KEY`，Value: 貼上 key
3. （可選）固定模型：新增 Variable `CLAUDE_MODEL`（預設 `claude-haiku-4-5`）

一天一次、每月成本約 US$1–3。沒設 `ANTHROPIC_API_KEY` 也能跑，只是 Gemini 掛掉時沒有備援。網頁頁尾會顯示「本報由 X 撰寫」，一眼看出當天走的是主力還備援。

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

觸發只靠 cron-job.org（已移除 GitHub 內建 schedule）。腳本有防重複機制：當日已有報就綠燈跳過，重複觸發也只會出一份。

## 3b. Telegram 通知（可選，建議開）

每天出報成功會推播「一句話快訊 + 當日快報連結」；失敗也會用同一個 bot 通知並附 Actions log 連結，方便手機追蹤。

1. **建立 bot**：Telegram 內找 [@BotFather](https://t.me/BotFather) → 傳 `/newbot` → 依指示取名（username 需以 `bot` 結尾）→ 拿到 token（形如 `123456789:ABCdef...`）
2. **拿 chat id**：
   - 先對你剛建立的 bot 傳一句話（例如 `/start`）—— **這步必做**，否則 bot 無法主動傳訊給你
   - 再找 [@userinfobot](https://t.me/userinfobot) 傳任意訊息，它會回你的數字 id（就是 chat id）
   - （或：瀏覽 `https://api.telegram.org/bot<TOKEN>/getUpdates`，找 `"chat":{"id":...}`）
3. **加 secrets**：Repo → Settings → Secrets and variables → Actions → New repository secret
   - `TELEGRAM_BOT_TOKEN`：步驟 1 的 token
   - `TELEGRAM_CHAT_ID`：步驟 2 的數字 id
4. **（可選）** 若 Pages 網址不是 `https://sakuradigi.github.io/ai-daily-brief`，新增 Variable `SITE_URL` 覆蓋（通知連結用）

沒設這兩個 secret 也能正常出報，只是不推播。要推到群組：把 bot 拉進群、在群裡發一句話，chat id 改用群組的（負數）。

## 4. 手動測試

Repo → Actions → Daily Brief → Run workflow。約 1–2 分鐘後：

- 綠勾 → `reports/` 出現今日 JSON、網站已更新
- 紅叉 → 點進去看 log；常見問題：
  - `GEMINI_API_KEY` secret 沒設或打錯名
  - 模型名失效 → 到 [模型清單](https://ai.google.dev/gemini-api/docs/models) 查現行名稱，設 `GEMINI_MODEL` variable
  - Gemini 回 503/429（過載/限流）→ 腳本已內建指數退避重試＋換備援模型；若仍失敗多半是 Google 端當下大範圍不穩，稍後重跑即可
  - 某 RSS 來源失效 → 只是 WARN 不影響出報；要調整清單改 `scripts/fetch_sources.py` 的 `FEEDS`
  - 沒收到 Telegram → 確認已先對 bot 傳過訊息、secret 名稱無誤；通知失敗不會擋出報（腳本 exit 0）

## 維運備忘

- 週一自動出週報（台北時區判斷），無需設定
- 想重生成當日報告：Run workflow 前先刪掉當日 JSON，或本地跑 `FORCE=1 python scripts/generate_report.py`
- 換回 Claude 生成：workflow env 改 `PROVIDER: claude` + 新增 secret `ANTHROPIC_API_KEY`
- 觸發只靠 cron-job.org（workflow_dispatch）；已移除 GitHub 內建 schedule（會延遲又製造重複紅叉）。若哪天想加回保底 cron，於 `daily.yml` 的 `on:` 補 `schedule:` 即可
- 當日報告若已存在，workflow 會直接綠燈跳過（重複觸發不會再紅叉）
