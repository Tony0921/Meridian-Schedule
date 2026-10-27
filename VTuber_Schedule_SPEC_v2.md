# Meridian Schedule — VTuber 行程聚合器 Technical Spec v2

> 狀態：Draft  
> 版本：v2  
> 日期：2026-10-28  
> 專案：Meridian Schedule  
> Repository：`Tony0921/Meridian-Schedule`

---

# 1. 專案目標

建立一套以 VTuber 官方公開貼文為主要資訊來源的行程聚合系統。

系統需能：

1. 持續取得指定 VTuber 的公開貼文資訊。
2. 辨識：
   - 每週行程表
   - 行程異動
   - 突發直播
   - 延期
   - 取消
   - 休息日
   - 與行程無關的貼文
3. 理解貼文文字與週表圖片。
4. 將非結構化資訊轉換為固定 JSON 資料格式。
5. 對資料執行 deterministic validation / merge。
6. 保留來源貼文與 Revision History。
7. 部署為 GitHub Pages 靜態網站。
8. 不要求 X API 或 OpenAI API 等付費 API 才能正常運作。
9. 系統即使某個外部來源暫時失效，也不應破壞正式資料。
10. 支援人工審核與人工補入資料。

---

# 2. v2 核心設計目標

## 2.1 Zero Additional API Cost

v2 核心系統不得要求付費 API。

```text
Core system MUST NOT require a paid API.

Paid providers MAY be supported as optional enhancements.
```

預期基本營運成本：

| 元件 | 方案 | 額外成本 |
|---|---|---:|
| AI 資料蒐集 | ChatGPT Scheduled Task | 既有訂閱 |
| AI Vision | ChatGPT | 不使用 API 計費 |
| 暫存資料 | Google Sheets | $0 |
| Collector 補漏 | Raspberry Pi | 既有硬體 |
| Git Repository | GitHub | $0 |
| CI/CD | GitHub Actions | $0 |
| 網站 | GitHub Pages | $0 |
| X Developer API | 不使用 | $0 |
| OpenAI API | 非必要 | $0 |

「免費」在本文件中定義為：

> Meridian Schedule 不額外產生按 API 使用量計價的固定營運成本。

不代表 ChatGPT、網路、電力與既有硬體本身沒有成本。

---

# 3. v1 → v2 核心變更

## v1

```text
X API / Event Source
        ↓
Raspberry Pi Collector
        ↓
repository_dispatch
        ↓
GitHub Actions
        ↓
OpenAI Vision API
        ↓
Processor
        ↓
GitHub
```

問題：

- X API 需要付費。
- OpenAI API 需要額外付費。
- 即時事件來源依賴 X 官方 API。
- 難以達成零額外營運成本。

---

## v2

```text
ChatGPT Scheduled Task
        ↓
搜尋 / 讀取公開 X 貼文
        ↓
AI Vision / Text Understanding
        ↓
Google Sheets
   Ingestion Queue
        ↓
Meridian Importer
        ↓
Processor
        ↓
Validation
        ↓
Merge
        ↓
Review / Apply
        ↓
GitHub Repository
        ↓
GitHub Pages
```

另設獨立補漏來源：

```text
X Public Source
        ↓
Raspberry Pi Collector
        ↓
Post Deduplication
        ↓
補漏 Queue
```

---

# 4. 核心設計原則

## 4.1 AI 負責理解，不直接修改 Production

AI 可以：

- 搜尋可能相關的公開貼文。
- 判斷貼文類型。
- 讀取貼文文字。
- 理解週表圖片。
- 推導日期與時間。
- 產生結構化資料。
- 提供 confidence。
- 產生變更建議。

AI 不可以：

- 直接覆寫 `schedule.json`。
- 任意刪除既有事件。
- 直接執行 production merge。
- 自行修改 Revision History。
- 將「沒搜尋到」判定為「不存在」。

流程必須為：

```text
AI Observation
      ↓
Schema Validation
      ↓
Deterministic Merge
      ↓
Review Policy
      ↓
Production Data
```

---

# 5. 系統架構

```text
                           Internet
                              │
                              ▼
                    ┌──────────────────┐
                    │ ChatGPT Scheduled│
                    │       Task       │
                    └────────┬─────────┘
                             │
                  搜尋 / 瀏覽公開貼文
                             │
                  Text + Image Understanding
                             │
                             ▼
                    ┌────────────────┐
                    │ Google Sheets  │
                    │ Ingestion Queue│
                    └────────┬───────┘
                             │
                             │ read
                             ▼
                    ┌────────────────┐
                    │ Meridian       │
                    │ Importer       │
                    └────────┬───────┘
                             │
                             ▼
                    ┌────────────────┐
                    │ Processor      │
                    │ Schema         │
                    │ Merge          │
                    │ Policy         │
                    └────────┬───────┘
                             │
                    ┌────────┴────────┐
                    │                 │
               Auto Apply          Review
                    │                 │
                    ▼                 ▼
              schedule.json      Proposal / PR
                    │
                    ▼
                 GitHub
                    │
                    ▼
              GitHub Pages


      Optional / Independent Fallback Path

         X Public Timeline / Other Source
                      │
                      ▼
              Raspberry Pi
                 Collector
                      │
                  SQLite
                      │
                      ▼
                Missing Posts
                      │
                      └─────────────→ Processor
```

---

# 6. Component Responsibilities

## 6.1 ChatGPT Scheduled Task

定位：

> Primary AI discovery and extraction layer.

負責：

```text
定期檢查指定 VTuber
↓
尋找近期公開貼文
↓
判斷是否可能與行程相關
↓
理解文字 / 圖片
↓
輸出標準 Observation
↓
寫入 Google Sheets
```

不負責：

```text
Production merge
Git commit
Revision mutation
正式資料刪除
```

---

# 7. Scheduled Task Strategy

## 7.1 預設頻率

建議：

```text
每 1 小時
```

目的：

- 一般週表發布。
- 當日異動。
- 突發直播。
- 延期 / 取消。

不要求秒級即時。

---

## 7.2 Search Window

每次執行需檢查指定帳號近期貼文。

建議搜尋範圍：

```text
過去 24 小時
```

週表高峰期可以擴大：

```text
過去 72 小時
```

但必須依 `post_id` 或 `source_url` 去重。

---

## 7.3 Search Semantics

搜尋不到貼文不能被解讀成：

```text
不存在貼文
```

只能表示：

```text
本次 discovery 未找到
```

因此：

```text
absence of evidence != evidence of absence
```

---

# 8. VTuber Member Configuration

正式成員設定仍放在：

```text
data/members.json
```

例如：

```json
[
  {
    "id": "miri",
    "name": "璃 Miri",
    "x_username": "Miri_Aetris",
    "youtube": null,
    "twitch": "miri_aetris",
    "enabled": true
  }
]
```

Scheduled Task 使用相同名單。

---

# 9. Google Sheets 定位

Google Sheets 不作為 Production Database。

定位為：

```text
AI Ingestion Queue
```

目的：

- 保存 ChatGPT 發現的 Observation。
- 避免直接修改 GitHub。
- 支援人工檢查。
- 支援去重。
- 支援 Processor 再驗證。
- 解耦 AI 與 production data。

---

# 10. Google Sheet Structure

建議建立一個：

```text
Meridian Schedule Ingestion
```

Spreadsheet。

至少包含：

```text
posts
changes
```

兩個 Sheet。

---

# 11. posts Sheet

每一列代表一篇被發現的來源貼文。

建議欄位：

| 欄位 | 說明 |
|---|---|
| ingestion_id | Meridian ingestion UUID |
| source | `x` |
| post_id | 原始平台貼文 ID |
| member_id | VTuber ID |
| published_at | 原貼文時間 |
| discovered_at | AI 發現時間 |
| source_url | 原始貼文網址 |
| post_text | 原文 |
| media_urls | 圖片網址 |
| classification | AI 分類 |
| confidence | AI 信心 |
| status | queue 狀態 |
| processed_at | Processor 處理時間 |
| processor_result | 處理結果 |

---

## 11.1 status

允許：

```text
new
processing
processed
ignored
review
failed
duplicate
```

---

# 12. changes Sheet

每列代表 AI 從貼文推導出的單一 operation。

例如一篇週表可能產生：

```text
7~10 rows
```

建議欄位：

| 欄位 | 說明 |
|---|---|
| ingestion_id | 關聯 posts |
| change_index | operation index |
| operation | insert / update / cancel / ignore |
| member_id | VTuber |
| date | 日期 |
| time | 時間 |
| title | 標題 |
| platform | YouTube / Twitch / etc |
| url | 直播網址 |
| status | event status |
| confidence | 單筆 confidence |
| match_event_id | 修改既有事件時使用 |
| reason | AI 判斷理由 |

---

# 13. AI Classification

允許：

```text
weekly_schedule
schedule_change
sudden_stream
cancellation
postponement
day_off
irrelevant
unknown
```

---

# 14. Event Operations

AI 只能提出：

```text
insert
update
cancel
ignore
```

AI 不可以直接執行資料操作。

---

# 15. AI Output

ChatGPT 實際輸出的邏輯資料模型應接近：

```json
{
  "source": "x",
  "post_id": "123456789",
  "member_id": "miri",
  "published_at": "2026-10-27T20:30:00+08:00",
  "source_url": "https://x.com/...",
  "classification": "weekly_schedule",
  "confidence": 0.97,
  "changes": [
    {
      "operation": "insert",
      "member_id": "miri",
      "date": "2026-10-28",
      "time": "21:00",
      "title": "Minecraft",
      "platform": "youtube",
      "url": null,
      "status": "scheduled",
      "confidence": 0.96,
      "reason": "週表圖片標示 10/28 21:00 Minecraft"
    }
  ]
}
```

---

# 16. Google Sheets → Meridian Importer

新增：

```text
collector/google_sheets_source.py
```

或：

```text
ingestion/google_sheets.py
```

建議後者。

Repository：

```text
ingestion/
├── __init__.py
├── models.py
├── google_sheets.py
├── importer.py
└── dedupe.py
```

---

# 17. Importer Responsibility

Importer：

1. 讀取 `status=new` 的 posts。
2. 讀取其關聯 changes。
3. 轉換為 Meridian Proposal。
4. 執行 Schema Validation。
5. 執行 Processor。
6. 更新 Sheet 狀態。

流程：

```text
Google Sheets
    ↓
read new ingestion
    ↓
normalize
    ↓
schema validation
    ↓
processor
    ↓
proposal
    ↓
review / apply
```

---

# 18. Existing Processor

v2 原則上保留目前：

```text
processor/
```

包括：

```text
models.py
schemas.py
validate.py
merge.py
classify.py
storage.py
```

現有 deterministic merge architecture 不應移除。

---

# 19. Proposal First

所有外部來源必須先轉為：

```text
Proposal
```

不能直接修改：

```text
data/schedule.json
```

流程：

```text
Observation
↓
Normalize
↓
Proposal
↓
Validation
↓
Merge Candidate
↓
Policy
↓
Apply
```

---

# 20. Review Policy

v2 預設：

```text
REVIEW_ALL=true
```

在系統穩定前：

```text
所有 AI 變更
→ review
```

未來可以：

```text
confidence >= 0.95
AND
schema valid
AND
deterministic merge unambiguous
AND
existing event conflict == false

→ auto apply
```

其餘：

```text
review
```

---

# 21. Confidence Policy

建議：

```text
confidence < 0.70
→ record_only

0.70 <= confidence < 0.95
→ review

confidence >= 0.95
→ eligible_for_auto
```

但：

```text
eligible_for_auto
!=
automatically applied
```

仍受：

```text
REVIEW_ALL
merge ambiguity
schema validation
source quality
```

控制。

---

# 22. Deduplication

至少三層。

## Layer 1 — Google Sheets

依：

```text
source + post_id
```

去重。

若 post_id 不可靠：

```text
source_url
```

作為 fallback。

---

## Layer 2 — Importer

Importer 再確認：

```text
data/posts.json
```

是否已存在。

---

## Layer 3 — Merge

Event merge 仍依：

```text
member_id
date
title
platform
time
```

判斷事件是否重複。

---

# 23. Source Reliability

所有 Observation 建議新增：

```json
{
  "discovery_source": "chatgpt",
  "source_quality": "primary"
}
```

允許：

```text
primary
secondary
unknown
```

例如：

```text
官方 X 貼文
→ primary

第三方轉貼
→ secondary
```

正式行程原則上只使用：

```text
primary
```

來源。

---

# 24. Raspberry Pi Collector v2

Raspberry Pi 從：

```text
primary collector
```

改為：

```text
optional reconciliation / fallback collector
```

主要用途：

- 補漏。
- 監控 ChatGPT discovery 是否漏資料。
- 檢查 X public timeline。
- 未來串接其他來源。
- 觸發 processor。

---

# 25. X Public Source

禁止將非官方 X Web Interface 視為穩定 API。

設計原則：

```text
XSource is disposable.
```

而不是：

```text
XSource is business logic.
```

因此：

```text
collector/x_source.py
```

必須透過 Protocol 抽象。

---

# 26. PostSource Protocol

```python
class PostSource(Protocol):
    def recent_posts(
        self,
        member: Member,
    ) -> list[Post]:
        ...
```

可實作：

```text
ChatGPTSheetSource
XSyndicationSource
XGuestWebSource
XSessionSource
JsonlSource
ManualSource
```

---

# 27. X Source Priority

建議：

```text
ChatGPT discovery
        +
optional X public scraper
```

彼此不是嚴格 primary / secondary。

應採：

```text
union
```

概念：

```text
ChatGPT found post
OR
Pi collector found post
        ↓
same dedupe
        ↓
same processor
```

---

# 28. Reconciliation

建議每日：

```text
06:00
18:00
```

執行較深檢查。

目的：

- 發現 ChatGPT 未找到的貼文。
- 發現 Pi Collector 漏掉的貼文。
- 檢查 Google Sheets ingestion 狀態。
- 發現 stuck / failed ingestion。

---

# 29. AI Request Optimization

不要所有貼文都做完整 Vision 分析。

可以先做低成本 heuristic。

例如：

```text
週表
行程
schedule
直播
開台
突發
延期
取消
休息
改時間
```

但 heuristic 只負責：

```text
candidate selection
```

不可作為最終分類。

---

# 30. Candidate Scoring

例如：

```text
contains schedule keyword    +2
contains image               +2
published Fri–Mon            +1
contains date/time           +2
reply                        -1
repost                       -2
```

分數高：

```text
full AI extraction
```

分數低：

```text
ignore / lightweight classification
```

---

# 31. Image Handling

VTuber 週表圖片特性：

```text
複雜背景
藝術字
多欄排版
角色插圖
圖示
彩色資訊
```

因此 MVP v2 不強制加入傳統 OCR。

預設：

```text
Vision model directly reads image
```

未來可選：

```text
OCR
+
Vision
```

作為輔助。

---

# 32. Production Data Model

保留：

```text
data/
├── members.json
├── schedule.json
├── posts.json
└── revisions.json
```

Google Sheets 不取代這些檔案。

---

# 33. schedule.json

範例：

```json
{
  "updated_at": "2026-10-28T00:00:00+08:00",
  "events": [
    {
      "id": "miri-20261028-2100-001",
      "member_id": "miri",
      "date": "2026-10-28",
      "time": "21:00",
      "timezone": "Asia/Taipei",
      "title": "Minecraft",
      "platform": "youtube",
      "url": null,
      "status": "scheduled",
      "origin": "weekly_schedule",
      "source_post_id": "123456789",
      "confidence": 0.97,
      "updated_at": "2026-10-27T20:30:00+08:00"
    }
  ]
}
```

---

# 34. posts.json

正式 posts 只記錄已經 Processor 接受的來源。

Google Sheets 中尚未處理的資料不能直接視為正式 post。

---

# 35. Revision History

所有正式變更仍需要：

```text
before
after
source
timestamp
```

例如：

```json
{
  "event_id": "miri-20261028-2100-001",
  "timestamp": "2026-10-28T18:00:00+08:00",
  "source_post_id": "987654321",
  "before": {
    "time": "21:00"
  },
  "after": {
    "time": "22:00"
  }
}
```

---

# 36. Source-of-Truth

正式 Source of Truth：

```text
Git Repository / data/*.json
```

不是：

```text
Google Sheets
```

不是：

```text
ChatGPT conversation
```

不是：

```text
Raspberry Pi SQLite
```

---

# 37. Google Sheets Failure Handling

如果 Google Sheets 無法讀取：

```text
Production site continues serving existing data.
```

不得：

```text
clear schedule
overwrite schedule
mark events cancelled
```

---

# 38. ChatGPT Failure Handling

如果 Scheduled Task：

```text
本次失敗
搜尋不到
沒有執行
```

系統應：

```text
保持 production data
```

不要推導：

```text
VTuber 沒有活動
```

---

# 39. Import Idempotency

同一筆 ingestion：

```text
execute N times
```

結果必須與：

```text
execute once
```

相同。

依：

```text
ingestion_id
source + post_id
```

實作。

---

# 40. Import Transaction

流程：

```text
fetch
↓
lock
↓
normalize
↓
schema validation
↓
merge candidate
↓
validate candidate dataset
↓
write proposal
↓
commit transaction
↓
mark Sheet processed
```

任何一步失敗：

```text
production data unchanged
```

---

# 41. Google Sheet State Update

只有 Processor 成功處理後才：

```text
status=processed
```

如果 merge ambiguous：

```text
status=review
```

如果 Schema invalid：

```text
status=failed
```

---

# 42. Manual Review

Review 介面 MVP 可維持：

```text
.local/proposal.json
```

或 GitHub Pull Request。

未來可建立：

```text
review.html
```

但不屬於 v2 MVP 必要功能。

---

# 43. Manual Input

仍保留：

```text
python -m scripts.process_post --manual ...
```

理由：

- AI / Google 故障。
- X 搜尋失效。
- 特殊格式貼文。
- Debug。
- 測試。

Manual path 必須與自動 path 使用同一 Processor。

---

# 44. GitHub Integration

Production update：

```text
Processor
↓
Validation
↓
Apply
↓
Git Commit / PR
↓
GitHub Actions
↓
Pages Deploy
```

---

# 45. GitHub Actions

建議：

```text
.github/workflows/
├── ci.yml
├── deploy-pages.yml
├── process-ingestion.yml
├── reconcile.yml
└── backup.yml
```

---

# 46. process-ingestion.yml

用途：

```text
manual dispatch
schedule
repository dispatch
```

流程：

```text
checkout
↓
Google Sheets importer
↓
proposal generation
↓
validate
↓
auto apply / PR
↓
tests
↓
commit
```

是否直接從 GitHub Actions 連 Google API，可依 credential complexity 決定。

MVP 可由 Raspberry Pi 執行 importer。

---

# 47. Deployment Architecture — MVP Preferred

v2 MVP 建議：

```text
ChatGPT
↓
Google Sheets
↓
Raspberry Pi
↓
Meridian Processor
↓
GitHub
↓
GitHub Pages
```

理由：

- Pi 已存在。
- Google credentials 不必放 GitHub。
- 容易 Debug。
- 可以持久化本機狀態。
- 未來可以加入 X reconciliation。

---

# 48. Raspberry Pi Local State

仍使用：

```text
SQLite
```

例如：

```sql
CREATE TABLE ingestion (
    ingestion_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    external_post_id TEXT,
    status TEXT NOT NULL,
    discovered_at TEXT,
    processed_at TEXT,
    last_error TEXT
);
```

---

# 49. Health Check

新增檢查：

```text
最後一次 ChatGPT ingestion 時間
最後一次 Google Sheets read 時間
Sheet 中 new 數量
Sheet 中 failed 數量
Sheet 中 review 數量
最後一次成功 Git push
Collector reconciliation status
```

---

# 50. Alert Conditions

例如：

```text
> 24h 沒有成功讀 Google Sheets
→ warning

failed ingestion > 0
→ warning

processing 超過 1h
→ stuck

repository data validation fail
→ critical
```

---

# 51. Data Retention

Google Sheets 可以保留完整 ingestion log。

Production repository：

```text
posts.json
revisions.json
```

保留已採用的正式歷史。

不必將所有 irrelevant 貼文存入 Git repository。

---

# 52. Security

Google credentials：

```text
不得 commit 到 repository
```

使用：

```text
.env
systemd EnvironmentFile
GitHub Secrets
```

依部署位置選擇。

---

# 53. Secrets

可能包含：

```text
GOOGLE_SERVICE_ACCOUNT_JSON
GOOGLE_SHEET_ID
GITHUB_TOKEN
```

Optional：

```text
OPENAI_API_KEY
GEMINI_API_KEY
X_SESSION_COOKIE
```

Optional provider secret 不得成為核心系統必要條件。

---

# 54. Optional AI Providers

保留 Provider Protocol。

```text
AIProvider
├── ChatGPTExternalIngestion
├── GeminiProvider
├── OpenAIProvider
└── FixtureProvider
```

其中：

```text
ChatGPTExternalIngestion
```

實際上不是 Processor 內 API Provider，而是：

```text
external structured observation source
```

建議將概念與 API AIProvider 分離。

---

# 55. 建議重新命名部分抽象

v1：

```text
AIProvider
```

v2 建議拆成：

```text
ObservationSource
Extractor
```

例如：

```text
ObservationSource
├── GoogleSheetsObservationSource
├── ManualObservationSource
└── JsonlObservationSource
```

以及：

```text
Extractor
├── OpenAIExtractor
├── GeminiExtractor
└── FixtureExtractor
```

原因：

ChatGPT Scheduled Task 已在系統外完成 extraction。

---

# 56. Unified Observation Model

不論：

```text
ChatGPT
OpenAI
Gemini
Manual
Fixture
```

都應轉換為同一結構：

```json
{
  "post": {},
  "classification": "...",
  "confidence": 0.95,
  "changes": []
}
```

Processor 不需要知道資料是由哪個 AI 產生。

---

# 57. Repository 建議結構

```text
Meridian-Schedule/
├── README.md
├── VTuber_Schedule_SPEC_v2.md
├── AGENTS.md
│
├── collector/
│   ├── protocol.py
│   ├── x_public.py
│   ├── reconcile.py
│   ├── sqlite.py
│   └── github_dispatch.py
│
├── ingestion/
│   ├── models.py
│   ├── google_sheets.py
│   ├── importer.py
│   ├── normalize.py
│   └── dedupe.py
│
├── processor/
│   ├── models.py
│   ├── schemas.py
│   ├── validate.py
│   ├── merge.py
│   ├── classify.py
│   ├── storage.py
│   ├── extract.py
│   ├── openai_provider.py
│   └── gemini_provider.py
│
├── scripts/
│   ├── import_sheet.py
│   ├── process_post.py
│   ├── apply_proposal.py
│   ├── validate_data.py
│   ├── build_site.py
│   ├── backup_data.py
│   └── health_check.py
│
├── data/
│   ├── members.json
│   ├── schedule.json
│   ├── posts.json
│   └── revisions.json
│
├── schemas/
│
├── site/
│
├── tests/
│
└── .github/
    └── workflows/
```

---

# 58. MVP Phase Plan

## Phase A — Google Sheets Ingestion

完成：

```text
Google Sheet schema
Observation model
Google Sheets reader
dedupe
import command
```

驗收：

```text
Sheet 一筆 Observation
↓
CLI
↓
proposal.json
```

---

## Phase B — Existing Processor Integration

完成：

```text
Observation
↓
existing merge
↓
candidate schedule
```

確認：

- insert
- update
- cancel
- ignore

都可正常運作。

---

## Phase C — ChatGPT Scheduled Task

建立排程：

```text
每小時
```

負責：

1. 讀取 VTuber 名單。
2. 搜尋近期官方貼文。
3. 判斷貼文是否已存在。
4. 解析相關貼文。
5. 寫入 Google Sheet。

---

## Phase D — Pi Automation

systemd：

```text
meridian-import.timer
```

例如：

```text
每 5~15 分鐘
```

流程：

```text
read Sheet
↓
process
↓
proposal
↓
GitHub
```

---

## Phase E — Reconciliation

Pi 增加：

```text
X public-source collector
```

每日：

```text
2 次
```

補漏。

---

## Phase F — Controlled Auto Apply

初期：

```text
REVIEW_ALL=true
```

觀察一段時間後再考慮：

```text
>= 0.95
```

自動採用。

---

# 59. Non-Goals — v2

v2 不處理：

- 完整公開後端 Server。
- PostgreSQL。
- 使用者登入。
- 社群功能。
- Mobile App。
- 秒級 X 即時通知。
- 商業級 X firehose。
- 自行訓練 Vision model。
- 本地大型 LLM。
- 自動相信第三方轉貼。
- 完全依賴 YouTube 待機室。
- 100% 保證不漏 X 貼文。

---

# 60. Reliability Model

系統應接受：

```text
Discovery is probabilistic.
Processing is deterministic.
```

也就是：

```text
「有沒有找到貼文」
可能不完全可靠

「找到後怎麼處理」
必須 deterministic
```

這是 v2 最重要的架構原則。

---

# 61. Failure Philosophy

外部來源可能失效：

```text
ChatGPT
Google Sheets
X Web
GitHub
Internet
```

但失效時系統必須：

```text
fail closed
```

即：

```text
保留舊資料
停止自動更新
留下 error
等待補漏
```

不得：

```text
猜測
清空
取消事件
覆寫正式資料
```

---

# 62. Acceptance Criteria

v2 MVP 完成條件：

### Discovery

- ChatGPT Scheduled Task 可以產生結構化 Observation。
- Observation 可寫入 Google Sheets。

### Ingestion

- Meridian 可讀取 Sheet。
- 支援 post dedupe。
- 支援 ingestion status。

### Processing

- Observation 能轉成現有 Proposal。
- Schema 驗證正常。
- Merge 正常。
- Revision 正常。
- duplicate 不會重複套用。

### Safety

- AI 不直接修改 production。
- ambiguous update 進 review。
- failure 不修改正式資料。

### Deployment

- 修改後可自動 build。
- GitHub Pages 正常更新。

### Cost

核心流程不需要：

```text
X paid API
OpenAI paid API
```

---

# 63. Long-Term Extension

未來可以新增：

```text
Discord Source
YouTube Source
Twitch Source
Threads Source
Bluesky Source
Manual Web UI
```

全部輸出：

```text
Unified Observation
```

再走相同：

```text
Processor
```

---

# 64. Final Architecture Principle

Meridian Schedule v2 的核心不是：

```text
「如何完美爬 X」
```

而是：

```text
「如何讓多種不可靠 discovery source
安全地餵給可靠且 deterministic 的 processing pipeline」
```

最終資料流：

```text
       ChatGPT
          │
          ▼
    Google Sheets
          │
          │
X Fallback├────────────┐
          │            │
          ▼            │
   Unified Observation │
          │            │
          ▼            │
      Validation       │
          │            │
          ▼            │
       Processor       │
          │            │
          ▼            │
    Deterministic Merge
          │
          ▼
      Review Policy
          │
          ▼
    Production JSON
          │
          ▼
        GitHub
          │
          ▼
     GitHub Pages
```

---

# 65. v2 Implementation Priority

建議 Codex 依序執行：

```text
1. Unified Observation Model
2. Google Sheets schema
3. Google Sheets importer
4. Existing Processor adapter
5. Deduplication
6. Import CLI
7. Tests
8. Pi automation
9. ChatGPT Scheduled Task
10. X fallback reconciliation
11. Controlled auto apply
```

不要先重寫現有 merge / validation。

現有 deterministic processing layer 應視為 v2 基礎，而不是重新實作對象。

---

# 66. 核心決策摘要

```text
X paid API
→ 移除必要依賴

OpenAI paid API
→ 移除必要依賴

ChatGPT Scheduled Task
→ Primary discovery + extraction

Google Sheets
→ Ingestion queue

Raspberry Pi
→ Importer + reconciliation

GitHub JSON
→ Source of Truth

Existing Processor
→ 保留

AI
→ 理解資料

Code
→ 決定資料怎麼被修改
```