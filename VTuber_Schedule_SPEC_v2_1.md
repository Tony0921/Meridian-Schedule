# Meridian Schedule V2.1 Specification

## 1. Overview

Meridian Schedule 是一套用於整理 VTuber 週表資訊並發布至 GitHub Pages 的自動化系統。

V2.1 的主要目標：

- 不使用 X API
- 不使用 OpenAI API
- 不使用 Google Sheets API
- 不需要 Google Cloud Service Account
- 不需要 OAuth
- 儘量維持零額外費用
- 使用 ChatGPT 進行貼文搜尋、圖片理解與結構化
- 使用 Google Sheets 作為 AI 與 GitHub 之間的暫存資料層
- 使用 GitHub Actions 自動同步資料並重新部署網站

---

# 2. Architecture

```text
X / Discord / 其他公開來源
            │
            ▼
┌────────────────────────────┐
│ ChatGPT Scheduled Task     │
│                            │
│ - 搜尋 VTuber 最新貼文     │
│ - 判斷是否為週表           │
│ - 解析週表圖片             │
│ - 轉換為結構化資料         │
└─────────────┬──────────────┘
              │
              ▼
┌────────────────────────────┐
│ Google Sheets              │
│ schedule_ingestion         │
│                            │
│ AI 寫入資料                │
└─────────────┬──────────────┘
              │
              │ Publish to Web
              ▼
┌────────────────────────────┐
│ Public CSV Endpoint        │
│                            │
│ 不使用 Google Sheets API   │
│ 不需要任何 Google 認證     │
└─────────────┬──────────────┘
              │
              ▼
┌────────────────────────────┐
│ GitHub Actions             │
│                            │
│ - 下載 CSV                 │
│ - 驗證資料                 │
│ - 去除重複                 │
│ - 產生 schedule JSON       │
│ - commit 更新資料          │
└─────────────┬──────────────┘
              │
              ▼
┌────────────────────────────┐
│ GitHub Repository          │
│ data/*.json                │
└─────────────┬──────────────┘
              │
              ▼
       GitHub Pages
```

---

# 3. Design Principles

## 3.1 Source of Truth

正式資料來源仍為 GitHub Repository 內的資料檔案。

例如：

```text
data/
├── members.json
├── schedule.json
└── ...
```

Google Sheets 不作為正式資料庫。

其角色僅為：

> ChatGPT 與 GitHub 資料處理流程之間的 Ingestion Layer。

---

# 4. Google Sheets

## 4.1 Purpose

Google Sheets 用於：

- 接收 ChatGPT 解析後的週表資料
- 提供簡單的人工作業介面
- 作為 GitHub Actions 可讀取的暫存資料來源

不負責：

- 網站直接查詢
- 正式資料保存
- 使用者帳號系統
- 權限管理
- 複雜資料庫操作

---

# 5. Google Sheets API

## 5.1 V2.0 原方案

原本設計：

```text
GitHub Actions
      │
      ▼
Google Sheets API
      │
      ▼
Google Sheet
```

這需要：

- Google Cloud Project
- 啟用 Google Sheets API
- Service Account 或 OAuth
- credentials
- GitHub Secrets
- API 權限設定

對目前專案而言複雜度過高。

---

## 5.2 V2.1 修改

V2.1 不再使用 Google Sheets API。

改為：

```text
Google Sheet
     │
     │ Publish to Web
     ▼
CSV URL
     │
     ▼
GitHub Actions
```

GitHub Actions 僅需透過 HTTP GET 下載 CSV。

例如概念上：

```bash
curl -L "$SCHEDULE_CSV_URL" -o schedule.csv
```

因此不再需要：

```text
Google Cloud Project
Google Sheets API
Service Account
OAuth
credentials.json
```

---

# 6. Google Sheet Structure

第一階段只使用一個 worksheet：

```text
schedule_ingestion
```

建議欄位：

| 欄位 | Type | 說明 |
|---|---|---|
| `id` | string | 唯一識別碼 |
| `member_id` | string | VTuber ID |
| `date` | date | 行程日期 |
| `time` | time | 開始時間 |
| `title` | string | 行程名稱 |
| `source_url` | URL | 原始 X / Discord 來源 |
| `status` | enum | pending / imported / invalid |
| `created_at` | datetime | AI 寫入時間 |

例如：

```csv
id,member_id,date,time,title,source_url,status,created_at
miri_20261028_01,miri,2026-10-28,20:00,雜談直播,https://x.com/...,pending,2026-10-28T02:10:00+08:00
```

---

# 7. Public CSV

## 7.1 Publish to Web

Google Sheet 的 `schedule_ingestion` worksheet 需要使用：

```text
File
→ Share
→ Publish to web
```

並選擇：

```text
schedule_ingestion
CSV
```

系統產生公開 CSV URL。

---

## 7.2 Security Model

Publish to Web 產生的資料視為：

```text
Public Read
```

因此 Google Sheet 中只能存放公開資訊。

允許：

```text
VTuber 名稱
直播日期
直播時間
標題
X 貼文 URL
公開來源
處理狀態
```

禁止：

```text
API Key
GitHub Token
OAuth Token
Email
私人帳號資訊
內部密碼
其他 Secret
```

---

# 8. ChatGPT Ingestion

ChatGPT Scheduled Task 負責：

```text
搜尋來源
↓
判斷貼文是否為週表
↓
分析圖片
↓
解析行程
↓
轉換成結構化資料
↓
寫入 Google Sheet
```

每一個行程寫入一 row。

---

# 9. Duplicate Prevention

AI 在寫入資料時應產生 deterministic 或可追蹤的 `id`。

建議格式：

```text
{member_id}_{date}_{index}
```

例如：

```text
miri_20261028_01
miri_20261028_02
miri_20261029_01
```

後端亦必須執行去重。

不可僅依賴 AI 避免重複。

---

# 10. GitHub Actions

## 10.1 Schedule

GitHub Actions 定期執行。

初期建議：

```text
每 60 分鐘
```

例如：

```yaml
schedule:
  - cron: "0 * * * *"
```

亦保留：

```yaml
workflow_dispatch:
```

供手動觸發。

---

# 11. GitHub Action Workflow

流程：

```text
Start
 │
 ▼
下載 Google Sheet CSV
 │
 ▼
CSV schema validation
 │
 ▼
選取需要處理的資料
 │
 ▼
Normalize
 │
 ▼
Deduplicate
 │
 ▼
Merge existing schedule
 │
 ▼
產生 data/schedule.json
 │
 ▼
檢查是否真的有變更
 │
 ├── No → End
 │
 ▼ Yes
git commit
 │
 ▼
git push
 │
 ▼
GitHub Pages rebuild
```

---

# 12. CSV Download

GitHub Action 不需要 Google API。

只需要：

```bash
curl -L "$SCHEDULE_CSV_URL" \
  -o /tmp/schedule.csv
```

CSV URL 可放在：

```text
GitHub Repository Variable
```

例如：

```text
SCHEDULE_CSV_URL
```

因為該 URL 本身並不是 Secret。

---

# 13. Import Script

建議建立：

```text
scripts/
└── import_schedule.py
```

責任：

```text
downloaded CSV
      ↓
validate
      ↓
normalize
      ↓
deduplicate
      ↓
merge
      ↓
generate JSON
```

GitHub Actions 本身不處理複雜 business logic。

---

# 14. Validation

最低驗證項目：

```text
member_id != empty
date = YYYY-MM-DD
time = HH:MM 或明確的特殊值
title != empty
source_url != empty
```

Invalid row：

```text
skip
+
log warning
```

不應造成整個 workflow failure，除非 CSV schema 本身無法解析。

---

# 15. Normalization

Importer 應將 AI 可能產生的格式差異統一。

例如：

```text
20：00
20:00
8:00 PM
晚上八點
```

統一為：

```text
20:00
```

日期：

```text
10/28
2026/10/28
Oct 28
```

統一為：

```text
2026-10-28
```

---

# 16. Status Field

V2.1 可以保留：

```text
pending
imported
invalid
```

但需注意：

GitHub Actions 透過 Publish CSV 為唯讀。

因此 GitHub Actions **不能直接把 Google Sheet 的 status 從 pending 改成 imported**。

---

# 17. Status Handling Change

因此 V2.1 建議：

Google Sheet 的 `status` 不作為 GitHub Actions 的正式處理狀態。

真正是否已匯入，由 GitHub Repository 判斷。

例如：

```text
data/imported_ids.json
```

內容：

```json
[
  "miri_20261028_01",
  "miri_20261028_02"
]
```

流程：

```text
CSV row
   │
   ▼
id 是否存在 imported_ids.json？
   │
 ┌─┴─┐
Yes  No
 │    │
skip  import
```

這樣完全不需要從 GitHub 回寫 Google Sheet。

---

# 18. Recommended Simplification

甚至可以完全移除 `status` 欄位。

Sheet：

```text
id
member_id
date
time
title
source_url
created_at
```

GitHub 自己管理：

```text
是否已匯入
是否重複
是否已更新
```

這是 V2.1 推薦方案。

---

# 19. Updating Existing Schedule

不能假設所有貼文都是新增行程。

可能包含：

```text
新增
時間修改
取消
標題修改
整張週表重新發布
```

第一階段 V2.1 MVP 可先採：

```text
member_id + date + time
```

或其他穩定欄位作為比對依據。

後續再增加：

```text
operation
revision
schedule_version
```

不在 V2.1 MVP 強制實作。

---

# 20. Git Commit Strategy

只有產生實際資料差異才 commit。

例如：

```bash
git diff --quiet
```

若沒有變更：

```text
workflow success
no commit
```

有變更：

```text
git add data/
git commit -m "chore: update schedule data"
git push
```

---

# 21. Website Update

GitHub Pages 網站不直接讀 Google Sheet。

正式流程：

```text
Google Sheet
↓
CSV
↓
GitHub Actions
↓
data/schedule.json
↓
Git commit
↓
GitHub Pages
```

網站只讀：

```text
data/schedule.json
```

因此即使 Google Sheet 暫時無法存取，既有網站資料仍然可以正常運作。

---

# 22. Failure Handling

## CSV 無法下載

```text
保持現有 data/*.json
workflow failure
不 commit
```

## CSV 格式異常

```text
停止 import
保持既有資料
```

## 單筆資料錯誤

```text
skip row
log warning
繼續處理其他資料
```

## 沒有新資料

```text
正常結束
不產生 commit
```

---

# 23. Cost

V2.1 預期使用：

| Service | Cost |
|---|---:|
| ChatGPT Scheduled Task | 現有 ChatGPT 方案 |
| Google Sheets | Free |
| Google Sheets Publish CSV | Free |
| GitHub Repository | Free |
| GitHub Actions | Free Tier |
| GitHub Pages | Free |
| X API | 不使用 |
| OpenAI API | 不使用 |
| Google Sheets API | 不使用 |

額外基礎設施成本：

```text
NT$0
```

在現有服務免費額度與使用限制內。

---

# 24. V2.0 → V2.1 Changes

## Removed

```text
Google Sheets API
Google Cloud Project
Service Account
OAuth
credentials.json
GitHub Google credentials secret
GitHub → Google Sheet write-back
```

## Added

```text
Google Sheets Publish to Web
Public CSV endpoint
CSV HTTP download
Repo-side imported ID tracking
```

## Simplified

原本：

```text
ChatGPT
↓
Google Sheet
↕
Google Sheets API
↓
GitHub Actions
```

V2.1：

```text
ChatGPT
↓
Google Sheet
↓
Public CSV
↓
GitHub Actions
```

---

# 25. V2.1 MVP

第一階段只需要完成：

- [ ] 建立 `schedule_ingestion` worksheet
- [ ] 定義 CSV schema
- [ ] Publish worksheet as CSV
- [ ] GitHub Actions 下載 CSV
- [ ] 建立 `import_schedule.py`
- [ ] CSV validation
- [ ] Duplicate detection
- [ ] 產生 `data/schedule.json`
- [ ] 有資料變更才 commit
- [ ] GitHub Pages 使用 repo JSON
- [ ] ChatGPT 可以新增 schedule row

以下暫不實作：

- Google Sheets API
- Service Account
- OAuth
- Sheet write-back
- 自動修改 status
- Review UI
- Proposal system
- Complex revision system

---

# 26. Final V2.1 Data Flow

```text
┌──────────────┐
│ X / Discord  │
└──────┬───────┘
       ▼
┌───────────────────┐
│ ChatGPT            │
│ Search + Vision    │
└────────┬──────────┘
         ▼
┌───────────────────┐
│ Google Sheet      │
│ ingestion buffer  │
└────────┬──────────┘
         │
         │ Publish CSV
         ▼
┌───────────────────┐
│ Public CSV        │
└────────┬──────────┘
         ▼
┌───────────────────┐
│ GitHub Actions    │
└────────┬──────────┘
         ▼
┌───────────────────┐
│ import_schedule.py│
└────────┬──────────┘
         ▼
┌───────────────────┐
│ data/schedule.json│
└────────┬──────────┘
         ▼
┌───────────────────┐
│ GitHub Pages      │
└───────────────────┘
```

## Core Principle

V2.1 的核心是：

> Google Sheet 只負責讓 AI 寫入資料；GitHub 只透過公開 CSV 讀取資料。兩側不需要建立 Google API 認證關係。

這可保留原本 V2 的自動化架構，同時移除 Google Sheets API 帶來的大部分設定複雜度。