# Meridian Schedule V2.2 Spec 修改項目

## 1. V2.2 目標

V2.2 聚焦於簡化 CSV 行程更新邏輯，建立一致且可預期的事件識別與更新規則。

核心原則：

- `id` 為行程唯一識別碼。
- 相同 `id` 代表同一個邏輯事件。
- CSV 可直接修正既有事件內容。
- `member_id + date + time` 不再作為主要更新識別。
- `source_url` 僅作來源追蹤，不參與事件 identity 判定。
- 所有實際修改保留 Revision。
- CSV 刪除資料不代表刪除正式行程。

---

# 2. Event Identity

## 2.1 `id` 定義

`id` 為事件的穩定唯一識別碼。

建議格式維持：

```text
{member_id}_{YYYYMMDD}_{index}
```

例如：

```text
miri_aetris_20261101_01
```

同一個邏輯事件即使後續發生以下修改，也必須保留相同 `id`：

- 時間修改
- 標題修改
- 平台修改
- 日期修改
- 來源貼文修改
- `tbd` 變為確定時間
- `day_off` 改為直播
- `unknown` 補齊為正式資訊

不得因內容修改而建立新的 `id`。

---

# 3. CSV 更新模型

Importer 只使用 `id` 判斷事件是新增或更新。

```text
CSV row
   │
   ▼
id 是否已存在？
   │
 ┌─┴─────────────┐
 No              Yes
 │                │
Insert          Update
```

---

# 4. 新增事件

當 CSV `id` 尚未存在於正式資料時：

```text
INSERT
```

新增事件包含：

```text
member_id
date
time
title
platform
source_url
```

並建立：

- `schedule.json` event
- `posts.json` source record
- `imported_ids.json` receipt
- 必要的 Revision / audit record

---

# 5. 更新既有事件

當 CSV `id` 已存在時：

```text
UPDATE existing event
```

允許更新：

| 欄位 | 可更新 |
|---|---|
| `id` | 否 |
| `member_id` | 原則上否 |
| `group` | 不參與事件更新 |
| `date` | 是 |
| `time` | 是 |
| `title` | 是 |
| `platform` | 是 |
| `source_url` | 是 |
| `created_at` | 否 |

`created_at` 代表該 ingestion row 首次建立時間，不應因後續同步重新產生。

---

# 6. `member_id` 修改

既有事件不得透過一般 CSV 更新修改 `member_id`。

若同一 `id` 出現不同 `member_id`：

```text
reject + warning
```

原因：

`member_id` 屬於事件 ownership，修改可能代表：

- ID 使用錯誤
- 行程誤配
- 成員資料錯置

此情況應人工確認。

---

# 7. Revision 規則

相同 `id` 的資料若與正式事件不同：

```text
before != after
```

則：

```text
更新 event
+
建立 Revision
```

Revision 應保存：

```text
event_id
timestamp
source
before
after
```

若所有欄位相同：

```text
no-op
```

不得：

- 更新 `updated_at`
- 建立 Revision
- 建立備份
- 產生無意義 commit

---

# 8. Natural Key 降級為重複防護

以下組合：

```text
member_id + date + normalized time
```

不再作為主要事件更新依據。

用途改為：

> duplicate safeguard

僅在「新 ID」出現時檢查是否可能重複。

---

# 9. 新 ID 重複檢查

新 ID 匯入時：

```text
id 不存在
↓
搜尋內容相同或高度相似的既有事件
```

分為三種結果。

### A. 無匹配事件

```text
insert
```

### B. 完全相同事件

例如：

```text
member_id 相同
date 相同
time 相同
title 相同
platform 相同
```

視為：

```text
duplicate
```

不建立第二筆 event。

可選擇只記錄該 CSV row 已處理。

### C. 疑似同一事件但 ID 不同

例如：

```text
同 member
同 date
同 time
title 很接近
```

此時：

```text
warning
+
skip automatic merge
```

Importer 不應自行決定哪一個 ID 正確。

---

# 10. 禁止以新 ID 隱性修改舊事件

V2.1 以下行為移除：

```text
新 ID
+
member/date/time 找到既有事件
→ 直接更新舊事件
```

V2.2 改為：

```text
新 ID ≠ 舊 ID
→ 不自動當成 update
```

原因是避免兩套 identity system 同時存在。

---

# 11. Source URL

`source_url` 定義為：

> Event provenance / latest referenced source

不得作為：

- event identity
- update permission
- duplicate primary key

---

# 12. Source URL 更新

相同事件可能從不同官方貼文取得修正版：

```text
週表貼文 A
↓
修正版貼文 B
```

因此相同 `id`：

```text
source_url: A → B
```

應允許更新。

Revision 保存：

```text
before.source_url = A
after.source_url  = B
```

不得因來源不同拒絕更新。

---

# 13. CSV Row 刪除

CSV 為 ingestion layer，不是正式資料庫。

因此：

```text
CSV 中某 row 消失
```

不得推導為：

```text
delete event
```

正式事件保持不變。

需要刪除或取消事件時，必須使用明確狀態或未來新增的 operation 機制。

---

# 14. Time / State 模型

V2.2 可先維持目前格式：

```text
HH:MM
tbd
day_off
unknown
```

但 spec 應明確記錄：

目前 `time` 同時承載：

- 時間
- 行程狀態

屬於過渡設計。

---

# 15. 未來 Event Status

後續版本建議拆分：

```text
time
event_status
```

例如：

```text
time = 20:00
event_status = scheduled
```

或：

```text
time = null
event_status = tbd
```

候選狀態：

```text
scheduled
tbd
day_off
unknown
cancelled
postponed
```

V2.2 不強制修改 schema，但避免新增更多特殊值到 `time`。

---

# 16. Platform 更新

移除 V2.1：

> 已匯入 ID 只能更新 platform

V2.2 改為：

相同 `id` 可以更新所有允許變更的事件欄位。

例如：

```text
platform:
unknown → youtube
youtube → twitch
youtube → unknown
youtube → none
```

均為正常 update。

---

# 17. Title 更新

V2.1：

```text
修改 title → 建立新 row ID
```

V2.2 改為：

```text
相同 id
title old → title new
```

直接更新原事件並建立 Revision。

不得僅因標題修正建立新事件。

---

# 18. Time 更新

以下皆視為正常事件更新：

```text
tbd → 20:00
unknown → 21:00
19:00 → 20:00
day_off → 22:00
```

保持原 `id`。

不應建立另一筆事件。

---

# 19. Date 更新

若官方修正日期：

```text
2026-11-01 → 2026-11-02
```

相同 `id` 可直接更新。

但若修改後與另一個既有事件產生明確重複，應：

```text
warning
+
停止該 row 更新
```

避免產生資料 collision。

---

# 20. Import Receipt

`imported_ids.json` 的角色重新定義為：

> 已見過的 ingestion row / event ID receipt

它不得代表：

```text
這個 ID 永遠不可再修改
```

因此：

```text
id in imported_ids
```

只代表：

```text
existing event / previously ingested
```

Importer 仍須比較內容並處理 update。

---

# 21. `status` 欄位

Google Sheet 的：

```text
pending
imported
invalid
```

仍不作為正式匯入狀態來源。

建議 V2.2：

```text
移除 status 欄位
```

若為相容既有 Sheet 保留：

```text
ignore for merge logic
```

唯一例外：

```text
invalid
```

可繼續作為人工停用該 row 的標記。

---

# 22. `group` 欄位

`group`：

- 僅供 Sheet 顯示。
- 不參與 event identity。
- 不參與 update。
- 正式 group 仍由 `members.json` 決定。

---

# 23. Update 決策表

| CSV 狀況 | V2.2 行為 |
|---|---|
| 新 ID，無相似事件 | Insert |
| 新 ID，內容完全相同 | Duplicate / skip |
| 新 ID，疑似同事件 | Warning / skip |
| 相同 ID，內容相同 | No-op |
| 相同 ID，title 改變 | Update |
| 相同 ID，time 改變 | Update |
| 相同 ID，date 改變 | Update |
| 相同 ID，platform 改變 | Update |
| 相同 ID，source 改變 | Update |
| 相同 ID，member_id 改變 | Reject |
| CSV row 消失 | Ignore |
| CSV 新增不同 ID 企圖取代舊事件 | 不自動取代 |

---

# 24. ChatGPT Scheduled Task 規則修改

V2.1：

```text
已匯入 ID 只能修改 platform
標題修改使用新 ID
時間修改交人工
```

全部移除。

V2.2 改為：

```text
若確認為同一個邏輯事件，必須沿用原 ID。
資訊修正時直接修改該 row。
不得為同一事件產生新的 ID。
```

新增前：

```text
優先以既有 Sheet / schedule / imported_ids
確認是否已有事件 ID。
```

---

# 25. ID 穩定性規則

ChatGPT 產生 ID 時必須遵守：

```text
同一事件永遠沿用相同 ID
```

以下都不是建立新 ID 的理由：

```text
時間不同
標題不同
平台不同
來源貼文不同
週表重發
```

只有真正新增另一場不同事件時才產生新 ID。

---

# 26. V2.1 → V2.2 行為差異

```text
V2.1
id = ingestion receipt
natural key = event matching
source = update guard
```

改為：

```text
V2.2
id = event identity
natural key = duplicate safeguard
source = provenance
```

這是 V2.2 最主要的架構變更。

---

# 27. V2.2 暫不處理項目

本版本先不加入：

```text
operation
schedule_version
explicit delete
explicit cancel command
full snapshot replacement
AI fuzzy auto-merge
```

取消、延期等狀態若未納入目前 CSV schema，可留待後續版本設計。

---

# 28. 預期效果

更新邏輯由：

```text
ID
+
member/date/time
+
source_url
+
platform 特例
+
人工處理例外
```

簡化為：

```text
Same ID
→ Update

New ID
→ Insert or duplicate check
```

最終目標是讓：

> Google Sheet 中同一 row 的修正，等價於正式事件的修正。

Importer 不再猜測哪個事件需要被覆寫。