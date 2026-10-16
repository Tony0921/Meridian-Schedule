# VTuber 行程聚合器 — Technical Spec

> 狀態：Draft / MVP Spec  
> 目標：交付 Codex 進行初版實作  
> 核心使用情境：每週查看本週行程、每天查看今日直播，並在 VTuber 發布週表、異動或突發公告後盡快更新。

---

## 1. 專案目標

建立一個以 VTuber 官方社群貼文為主要資訊來源的「行程聚合器」。

系統需：

1. 持續接收或偵測指定 VTuber 帳號的新貼文。
2. 以 X 為主要來源，未來可擴充 YouTube、Twitch、其他社群。
3. 辨識貼文是否屬於：
   - 週表
   - 行程異動
   - 突發直播
   - 取消 / 延期 / 休息
   - 無關貼文
4. 對文字與週表圖片進行 AI / Vision 解析。
5. 將結果轉成統一 JSON 格式。
6. 合併至目前行程資料。
7. 將資料提交至 GitHub repository。
8. 由 GitHub Pages 顯示：
   - 今日行程
   - 本週行程
   - 各 VTuber 行程
9. 保留原始來源與修改歷史，方便追溯。
10. 即時事件作為主要更新機制，低頻掃描作為補漏機制。

---

# 2. 非目標

MVP 階段不處理：

- Discord 官方伺服器資料蒐集。
- 自行架設公開後端 Web Server。
- 使用者登入。
- 留言 / 社群功能。
- 複雜權限系統。
- 即時聊天室資料。
- 本地執行大型 Vision 模型。
- 完整資料庫服務，例如 PostgreSQL。
- 直接依賴 YouTube 待機室作為主要行程來源。

YouTube / Twitch 在 MVP 中定位為輔助資訊與直播連結來源，不作為建立週排程的唯一依據。

---

# 3. 核心設計原則

## 3.1 Event-driven First

主要流程採事件驅動：

```text
新貼文
  ↓
Collector
  ↓
觸發處理流程
```

避免高頻率輪詢所有帳號。

另設低頻 reconciliation job：

```text
每天 1～2 次
  ↓
重新確認指定帳號近期貼文
  ↓
找出漏接 post
  ↓
補入正常處理流程
```

---

## 3.2 Collector 與 Processor 分離

Raspberry Pi 主要負責：

```text
長期運行
事件接收
post_id 去重
低頻補漏
觸發 GitHub Actions
```

GitHub Actions 主要負責：

```text
取得完整貼文
下載媒體
AI 判斷
Vision 解析
資料合併
資料驗證
建立 commit / PR
部署 GitHub Pages
```

不要把所有邏輯放在 Raspberry Pi。

---

## 3.3 AI 負責理解，不負責監控

AI / Agent 用於：

- 判斷貼文類型。
- 理解自然語言。
- 理解週表圖片。
- 判斷「新增事件」或「修改既有事件」。
- 輸出結構化 JSON。
- 產生資料變更建議。

AI 不負責：

- 自己定期巡覽 X。
- 自己維持長時間監控。
- 自己判斷是否有新貼文。

---

# 4. 高階架構

```text
                     X
                     │
          ┌──────────┴──────────┐
          │                     │
      即時事件來源          Reconciliation
          │                 1~2 次 / 日
          │                     │
          └──────────┬──────────┘
                     ▼
              Raspberry Pi
                 Collector
                     │
             Deduplication
                     │
                     ▼
           repository_dispatch
                     │
                     ▼
              GitHub Actions
                     │
       ┌─────────────┴─────────────┐
       │                           │
   取得貼文文字                下載圖片
       │                           │
       └─────────────┬─────────────┘
                     ▼
                AI Processor
                     │
        classify + extract + merge
                     │
                     ▼
               validation
                     │
          ┌──────────┴──────────┐
          │                     │
     高信心變更              不確定
          │                     │
          ▼                     ▼
       commit                 Pull Request
          │
          ▼
     schedule.json
          │
          ▼
      GitHub Pages
```

---

# 5. Repository 建議結構

```text
vtuber-schedule/
├── README.md
├── SPEC.md
├── AGENTS.md
│
├── collector/
│   ├── main.py
│   ├── config.py
│   ├── x_source.py
│   ├── reconcile.py
│   ├── dedupe.py
│   └── github_dispatch.py
│
├── processor/
│   ├── classify.py
│   ├── extract.py
│   ├── merge.py
│   ├── validate.py
│   └── schemas.py
│
├── scripts/
│   ├── process_post.py
│   ├── validate_data.py
│   └── build_site.py
│
├── data/
│   ├── members.json
│   ├── schedule.json
│   ├── posts.json
│   └── revisions.json
│
├── site/
│   ├── index.html
│   ├── app.js
│   └── style.css
│
├── tests/
│   ├── test_merge.py
│   ├── test_validate.py
│   └── fixtures/
│
└── .github/
    └── workflows/
        ├── process-post.yml
        ├── reconcile.yml
        └── deploy-pages.yml
```

MVP 可再簡化。

---

# 6. 資料模型

## 6.1 members.json

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

---

## 6.2 posts.json

保留已處理貼文，用於去重與追蹤。

```json
[
  {
    "source": "x",
    "post_id": "123456789",
    "member_id": "miri",
    "published_at": "2026-10-11T22:33:00+08:00",
    "processed_at": "2026-10-11T22:35:10+08:00",
    "type": "weekly_schedule",
    "status": "processed",
    "source_url": "https://x.com/...",
    "media": [
      {
        "type": "image",
        "url": "https://..."
      }
    ]
  }
]
```

---

## 6.3 schedule.json

```json
{
  "updated_at": "2026-10-15T18:00:00+08:00",
  "events": [
    {
      "id": "miri-20261016-2100-001",
      "member_id": "miri",
      "date": "2026-10-16",
      "time": "21:00",
      "timezone": "Asia/Taipei",
      "title": "Minecraft",
      "platform": "youtube",
      "url": null,
      "status": "scheduled",
      "origin": "weekly_schedule",
      "source_post_id": "123456789",
      "confidence": 0.98,
      "updated_at": "2026-10-15T18:00:00+08:00"
    }
  ]
}
```

---

## 6.4 Event status

允許值：

```text
scheduled
changed
cancelled
postponed
live
finished
day_off
working_day
tbd
```

MVP 至少支援：

```text
scheduled
cancelled
postponed
day_off
tbd
```

---

## 6.5 Post classification

允許值：

```text
weekly_schedule
schedule_change
sudden_stream
cancellation
postponement
irrelevant
unknown
```

---

# 7. AI Processor

## 7.1 輸入

AI 應接收：

```json
{
  "member": {},
  "post_text": "...",
  "published_at": "...",
  "images": [],
  "current_schedule": []
}
```

---

## 7.2 輸出

必須輸出符合固定 Schema 的 JSON。

範例：

```json
{
  "classification": "schedule_change",
  "confidence": 0.96,
  "changes": [
    {
      "operation": "update",
      "match": {
        "date": "2026-10-16",
        "member_id": "miri"
      },
      "set": {
        "time": "21:00"
      }
    }
  ],
  "reason": "貼文明確表示今日直播改為 21:00"
}
```

---

## 7.3 Operation

允許：

```text
insert
update
cancel
ignore
```

不要讓 AI 任意修改 repository。

AI 只輸出「變更描述」，由 deterministic merge layer 實際套用。

---

# 8. Merge Layer

所有資料變更必須經過 `merge.py`。

AI 不直接改 `schedule.json`。

流程：

```text
AI JSON
  ↓
Schema validation
  ↓
Merge rules
  ↓
schedule.json
```

---

## 8.1 基本規則

### insert

如果找不到合理相符事件：

```text
新增 event
```

### update

優先依：

```text
member_id
date
title similarity
platform
time proximity
```

比對既有事件。

### cancel

不刪除 event。

改為：

```json
{
  "status": "cancelled"
}
```

### 修改

保留 revision。

---

# 9. Revision History

建議保留：

```json
{
  "event_id": "miri-20261016-2100-001",
  "timestamp": "2026-10-16T18:30:00+08:00",
  "source_post_id": "987654321",
  "before": {
    "time": "20:00"
  },
  "after": {
    "time": "21:00"
  }
}
```

用途：

- Debug。
- 追溯。
- 顯示「已異動」。
- 防止 AI 覆蓋錯誤後完全無法復原。

---

# 10. Raspberry Pi Collector

## 10.1 職責

Collector 只負責：

```text
接收新貼文事件
取得基本 metadata
post_id 去重
保存最低限度狀態
觸發 GitHub Actions
執行 reconciliation
```

---

## 10.2 Local storage

可使用 SQLite：

```text
collector.db
```

Schema 例：

```sql
CREATE TABLE posts (
    source TEXT NOT NULL,
    post_id TEXT NOT NULL,
    member_id TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    dispatched_at TEXT,
    status TEXT NOT NULL,
    PRIMARY KEY (source, post_id)
);
```

---

## 10.3 去重

同一個：

```text
source + post_id
```

最多 dispatch 一次。

但允許：

```text
failed
```

狀態重新送出。

---

# 11. Reconciliation

目的：

> 補上即時事件來源漏接的貼文。

MVP 預設：

```text
每日 06:00
每日 18:00
```

實際時間可設定。

流程：

```text
取得每位成員近期貼文
↓
比較 collector.db
↓
發現不存在 post_id
↓
加入正常 pipeline
```

不要另寫第二套 processor。

---

# 12. GitHub Integration

## 12.1 Raspberry Pi → GitHub

優先使用：

```text
repository_dispatch
```

Payload 只傳必要資料：

```json
{
  "event_type": "new_x_post",
  "client_payload": {
    "source": "x",
    "post_id": "123456789",
    "member_id": "miri"
  }
}
```

---

## 12.2 GitHub Actions

`process-post.yml`：

```text
repository_dispatch
↓
checkout
↓
取得貼文
↓
AI processor
↓
validate
↓
merge
↓
test
↓
commit / PR
```

---

# 13. 安全更新策略

AI 不應無條件直接更新 production。

建議：

```text
confidence >= 0.95
且 schema / validation 全部通過
→ 允許自動 commit

0.70 <= confidence < 0.95
→ 建立 Pull Request

confidence < 0.70
→ 記錄結果，不修改 schedule
```

confidence threshold 必須可設定。

例如：

```yaml
AUTO_MERGE_CONFIDENCE: 0.95
PR_CONFIDENCE: 0.70
```

MVP 初期可選擇：

```text
所有 AI 變更一律 PR
```

等資料穩定後再啟用 auto merge。

---

# 14. GitHub Pages

GitHub Pages 僅負責讀取：

```text
data/schedule.json
data/members.json
```

不負責資料蒐集與 AI。

---

## 14.1 Today View

首頁預設：

```text
今天 10/15

18:00
雪 Koyuki
LOL
Twitch

21:00
璃 Miri
Minecraft
YouTube
```

排序：

```text
time ASC
```

---

## 14.2 Week View

顯示：

```text
星期一～星期日
```

可採：

- 日曆。
- Card。
- Timeline。

MVP 優先使用手機友善 Card / Timeline。

---

## 14.3 Member View

顯示單一 VTuber：

```text
名稱
本週所有 event
平台
狀態
來源
```

---

# 15. UI 狀態標示

建議：

```text
scheduled  → 正常
changed    → 已異動
cancelled  → 已取消
postponed  → 延期
sudden     → 突發
tbd        → 待定
```

MVP 不要求特定顏色。

---

# 16. Secrets

不可提交至 Git。

至少包含：

```text
X_API_TOKEN
OPENAI_API_KEY
GITHUB_TOKEN
```

Pi 使用：

```text
.env
```

GitHub 使用：

```text
GitHub Actions Secrets
```

---

# 17. Logging

所有 processor 至少輸出：

```text
timestamp
post_id
member_id
classification
confidence
operation
result
```

例如：

```text
2026-10-15T18:33:00+08:00
post=123456789
member=miri
classification=schedule_change
confidence=0.97
operation=update
result=success
```

---

# 18. Error Handling

至少處理：

```text
API timeout
X rate limit
圖片下載失敗
AI timeout
AI schema invalid
找不到 event
GitHub dispatch failure
GitHub push conflict
```

原則：

```text
不要因單篇貼文失敗停止 Collector。
```

失敗 post 標記：

```text
failed
```

供 reconciliation 或 retry 重試。

---

# 19. Retry

建議：

```text
1 min
5 min
30 min
```

最多 3 次。

之後標記：

```text
manual_review
```

---

# 20. 測試

至少包含以下 fixtures。

## Case 1：正常週表

```text
圖片包含 Mon~Sun 行程
```

預期：

```text
insert 多筆 events
```

## Case 2：改時間

```text
原本 20:00
貼文：「今天改九點」
```

預期：

```text
20:00 → 21:00
```

## Case 3：取消

```text
「今天身體不舒服，直播取消」
```

預期：

```text
status = cancelled
```

## Case 4：突發

```text
「等等 22:00 突發 Apex」
```

預期：

```text
insert new event
origin = sudden_stream
```

## Case 5：一般貼文

```text
「今天午餐吃拉麵」
```

預期：

```text
ignore
```

## Case 6：圖片解析不確定

預期：

```text
不 auto merge
```

---

# 21. MVP Milestones

## Phase 1 — Static Data

先不接 X。

完成：

```text
members.json
schedule.json
GitHub Pages
Today View
Week View
```

驗證前端與資料格式。

---

## Phase 2 — AI Parser

使用手動提供的：

```text
貼文文字
週表圖片
```

測試：

```text
classify
extract
merge
revision
```

---

## Phase 3 — GitHub Automation

完成：

```text
repository_dispatch
GitHub Actions
自動處理
PR
```

此階段仍可手動 dispatch。

---

## Phase 4 — X Collector

Raspberry Pi：

```text
取得新貼文事件
dedupe
dispatch
```

---

## Phase 5 — Reconciliation

加入：

```text
每日 1～2 次補漏掃描
retry
failure recovery
```

---

## Phase 6 — Production Hardening

加入：

```text
auto merge threshold
完整 logging
monitoring
backup
更多 VTuber
其他資料來源
```

---

# 22. MVP Acceptance Criteria

完成以下條件即視為 MVP：

- [ ] GitHub Pages 可正常開啟。
- [ ] 手機可清楚瀏覽。
- [ ] 可顯示 Today View。
- [ ] 可顯示 Week View。
- [ ] `members.json` 可增加成員。
- [ ] `schedule.json` 可新增、修改、取消 event。
- [ ] 一篇週表貼文可經 AI 轉為合法 JSON。
- [ ] 一篇異動貼文可以修改既有 event。
- [ ] 一篇突發貼文可以新增 event。
- [ ] 一般貼文不會修改 schedule。
- [ ] 所有修改保留 source_post_id。
- [ ] 所有修改保留 revision。
- [ ] GitHub Action 可由外部 dispatch 觸發。
- [ ] AI 不直接任意修改 repository。
- [ ] 低 confidence 內容不自動 merge。
- [ ] Collector 可避免重複 post。
- [ ] reconciliation 可補回漏接 post。

---

# 23. 尚未決定 / 需先 PoC

以下不要在沒有驗證前寫死：

## 23.1 X 即時來源

需實測：

```text
官方 X API
Filtered Stream
Webhook
第三方 service
RSS bridge
其他 event source
```

要求：

```text
穩定
合法
成本可接受
可取得指定帳號貼文
可取得圖片 URL
```

Collector 必須抽象成 interface，避免綁死單一來源。

建議：

```python
class PostSource:
    def listen(self):
        ...

    def fetch_recent(self, account, since):
        ...

    def fetch_post(self, post_id):
        ...
```

---

## 23.2 AI Provider

不要綁死模型。

interface 例：

```python
class ScheduleInterpreter:
    def classify(self, post):
        ...

    def extract(self, post, current_schedule):
        ...
```

未來可切換不同 AI API。

---

# 24. Codex 實作規則

## Working rules

- 先讀完整專案再修改。
- 優先最小改動。
- 不重構無關程式碼。
- 不新增依賴，除非有明確理由。
- 資訊不足時先提出問題。
- 不自行假設 X API 一定可用。
- 外部服務一律透過 abstraction/interface。
- AI 輸出必須經 JSON Schema 驗證。
- AI 不直接編輯 production data。
- 所有更新必須可追溯到 source post。
- 任何失敗不得破壞現有 `schedule.json`。

## Delivery requirements

每次完成任務後：

1. 列出修改檔案。
2. 說明修改內容。
3. 提供驗證步驟。
4. 執行可執行的測試。
5. 列出未完成或需人工確認項目。
6. 關鍵邏輯需有註解。

---

# 25. 建議 Codex 第一個任務

```text
請先依 SPEC.md 建立 MVP 骨架。

目標：
1. 建立 repository 目錄結構。
2. 建立 members.json 與 schedule.json schema。
3. 建立 Python data model / validation。
4. 建立最基本 merge layer。
5. 建立 GitHub Pages 靜態 Today / Week View。
6. 加入 fixture data，暫時不要串接 X API 與 AI API。
7. 建立基本 tests。
8. README 說明本地執行與 GitHub Pages 部署方法。

限制：
- 不實作 X Collector。
- 不串 AI。
- 不新增不必要 framework。
- 前端優先使用原生 HTML/CSS/JavaScript。
- Python 優先使用標準函式庫；若需要額外 dependency，先說明理由。
```

---

# 26. 後續建議順序

```text
Step 1
Static site + JSON

Step 2
Merge engine

Step 3
AI parser with manual input

Step 4
GitHub Actions

Step 5
X event source PoC

Step 6
Raspberry Pi collector

Step 7
Reconciliation

Step 8
Auto merge
```

不要一開始同時做：

```text
X + AI + Pi + GitHub + UI
```

否則問題來源會難以定位。

---

# 27. 最終目標流程

```text
VTuber 發 X 貼文
        │
        ▼
事件來源偵測
        │
        ▼
Raspberry Pi Collector
        │
        ▼
GitHub repository_dispatch
        │
        ▼
GitHub Actions
        │
        ▼
AI 判讀文字 / 圖片
        │
        ▼
Structured Change
        │
        ▼
Validation
        │
        ▼
Merge Engine
        │
        ▼
schedule.json
        │
        ▼
GitHub Pages
        │
        ▼
使用者看到最新 Today / Week 行程
```

另以：

```text
每日 1～2 次 reconciliation
```

補足即時事件漏接。

