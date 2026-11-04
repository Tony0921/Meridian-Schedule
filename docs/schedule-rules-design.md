# ChatGPT Scheduled Task + GitHub 規則管理方案

## 1. 目的

將 ChatGPT 排程任務的複雜判定規則從 Task Prompt 中抽離，改由 GitHub repository 內的 Markdown 文件集中管理。

目標：

- 降低 Scheduled Task Prompt 長度
- 提升規則可讀性與可維護性
- 保留完整版本歷史
- 讓 ChatGPT、Codex 與人工維護共用同一份規則
- 避免排程規則與專案實作產生版本分歧
- 將 GitHub 作為規則的唯一真實來源（Single Source of Truth）

---

## 2. 整體架構

```text
GitHub Repository
Meridian-Schedule/
├── README.md
├── docs/
│   ├── schedule-rules.md
│   └── chatgpt-scheduled-task.md
└── src/
        │
        │ 每次執行前讀取最新版規則
        ▼
ChatGPT Scheduled Task
        │
        ├── 檢查 VTuber 週表來源
        ├── 解析貼文與圖片
        ├── 套用 schedule-rules.md
        └── 判斷新增 / 更新資料
        │
        ▼
Google Sheet
└── 儲存實際週表資料
```

責任分工：

| 元件 | 用途 |
|---|---|
| GitHub | 程式碼、Spec、AI 判定規則、版本控制 |
| `schedule-rules.md` | Scheduled Task 的主要業務規則 |
| ChatGPT Scheduled Task | 執行資料收集、判定與寫入 |
| Google Sheet | 儲存最終週表資料 |
| Codex | 開發與協助維護 repository |

---

## 3. Repository 結構

建議：

```text
Meridian-Schedule/
├── README.md
├── docs/
│   ├── schedule-rules.md
│   ├── chatgpt-scheduled-task.md
│   └── spec.md
├── src/
└── ...
```

### `docs/schedule-rules.md`

存放所有 AI 執行時必須遵守的規則，例如：

```markdown
# Schedule Rules

## Source Rules

## Date Rules

## Time Rules

## Platform Rules

## Collaboration Rules

## Deduplication Rules

## Update Rules

## Validation Rules
```

這份文件應作為週表資料判定的唯一規則來源。

---

## 4. Scheduled Task 設計原則

Scheduled Task 本身只保留「執行流程」，不要重複存放完整業務規則。

Task Prompt 應維持精簡，主要負責：

1. 指定 GitHub repository
2. 指定規則文件位置
3. 要求每次執行先讀取最新規則
4. 指定資料來源
5. 指定 Google Sheet
6. 定義錯誤處理方式

避免在 Task Prompt 內再次維護：

- `time` 判定規則
- `platform` 判定規則
- 合作藝人規則
- 去重規則
- 更新優先級
- 欄位細節

否則容易產生兩份不同版本的規則。

---

## 5. Scheduled Task Prompt 建議

```text
執行 Meridian Schedule VTuber 週表同步。

GitHub Repository：
Tony0921/Meridian-Schedule

規則文件：
docs/schedule-rules.md

執行要求：

1. 每次執行前先讀取 GitHub repository 中最新版的
   docs/schedule-rules.md。

2. 所有週表資料的解析、欄位判定、time、platform、
   collaboration、去重、更新與驗證邏輯，
   皆以該文件為唯一依據。

3. 依任務指定的 VTuber X 帳號檢查新的週表資訊，
   包含貼文文字與週表圖片。

4. 僅處理已確認符合規則的資料。

5. 將新增或需要更新的資料寫入指定 Google Sheet。

6. 不得因資訊不足自行創造資料；
   無法判定時依 schedule-rules.md 所定義的 fallback 規則處理。

7. 若無法取得最新版 schedule-rules.md，
   停止本次資料寫入並回報錯誤，
   不得自行使用記憶中的舊規則繼續執行。
```

帳號清單與 Google Sheet 位置可以：

- 直接保留在 Task Prompt
- 或另外放入 GitHub 文件

---

## 6. Source 清單管理

若 VTuber 帳號清單會持續增加，建議再拆出：

```text
docs/sources.md
```

例如：

```markdown
# Sources

## VTuber X Accounts

- https://x.com/998rrr_
- https://x.com/MizukiVtuberTW
- https://x.com/Reirei_Neon
- https://x.com/Yuzumi_Neon
```

Scheduled Task 改為：

```text
執行前讀取：

- docs/schedule-rules.md
- docs/sources.md
```

好處是新增 VTuber 時不用修改 Scheduled Task。

---

## 7. `schedule-rules.md` 建議結構

```markdown
# Meridian Schedule Rules

## 1. Schema

資料欄位與格式定義。

## 2. Source

哪些貼文可以視為有效週表來源。

## 3. Date

日期與跨日處理規則。

## 4. Time

例如：

- 明確時間 → `HH:mm`
- 明確休息 → `day_off`
- 明確突發 → `tbd`
- 有平台但沒有時間 → `tbd`
- 無法判定 → `unknown`

## 5. Platform

例如：

- 明確標示平台 → 使用標示值
- 一般藝人有時間但未標平台 → `youtube`
- 合作藝人有時間但未標平台 → `twitch`
- 明確標示 YouTube → `youtube`

## 6. Collaboration

合作直播的辨識與預設行為。

## 7. Deduplication

如何判斷同一場直播已存在。

## 8. Update Policy

新資訊與既有資料衝突時的更新優先級。

例如：

明確資訊 > 推測資訊 > unknown

## 9. Validation

寫入 Google Sheet 前必須完成的檢查。

## 10. Error Handling

資訊不足、來源衝突或解析失敗時的處理方式。
```

---

## 8. 規則修改流程

推薦：

```text
修改 schedule-rules.md
        ↓
Git commit
        ↓
Push / PR
        ↓
Review
        ↓
Merge
        ↓
下一次 Scheduled Task
自動讀取最新版規則
```

例如：

```diff
- 合作藝人 + 有時間 + 無平台 → youtube
+ 合作藝人 + 有時間 + 無平台 → twitch
```

Commit：

```text
fix(schedule-rules): default collaborator streams to Twitch
```

因此可明確追蹤：

- 哪條規則被修改
- 修改時間
- 修改原因
- 修改者
- 必要時回復舊版本

---

## 9. 規則版本

初期可直接使用 Git commit 作為版本管理，不需要額外維護版本號。

若之後規則開始與程式版本綁定，可在文件加入：

```yaml
---
rules_version: 2.1
updated: 2026-11-03
---
```

但不建議 Scheduled Task 依賴固定版本號。

正常情況應直接使用：

```text
main branch 最新版本
```

---

## 10. 防止規則漂移

禁止同一條業務規則同時存在於：

```text
Scheduled Task Prompt
schedule-rules.md
README.md
程式碼註解
```

其中多個位置。

應指定：

```text
docs/schedule-rules.md
```

為 authoritative source。

其他文件若需要說明，只引用：

```text
See docs/schedule-rules.md
```

不要複製完整規則。

---

## 11. 錯誤處理

Scheduled Task 必須遵守 fail-safe 原則。

若發生：

- GitHub repository 無法讀取
- `schedule-rules.md` 不存在
- 文件格式嚴重異常
- 無法確認目前規則
- Google Sheet 無法存取

則：

```text
停止資料寫入
```

不得：

```text
使用模型記憶中的舊規則
自行推測規則
寫入未確認資料
```

可繼續完成資料蒐集，但不得提交具有風險的變更。

---

## 12. Google Sheet 定位

Google Sheet 僅作為 Runtime Data Store。

不建議將主要 AI 規則存入 Sheet。

```text
GitHub
└── What should happen

ChatGPT Scheduled Task
└── Execute

Google Sheet
└── What actually happened
```

讓規則與資料維持分離。

---

## 13. 未來擴充

若專案規模增加，可進一步拆成：

```text
docs/rules/
├── README.md
├── schema.md
├── source.md
├── time.md
├── platform.md
├── collaboration.md
├── deduplication.md
└── validation.md
```

但目前規則量還不大時，建議先維持：

```text
docs/schedule-rules.md
```

單一文件。

避免過早拆分造成 Scheduled Task 每次必須讀取大量文件。

---

## 14. 最終建議架構

目前 Meridian Schedule 建議採用：

```text
Meridian-Schedule/
├── README.md
├── docs/
│   ├── spec.md
│   ├── schedule-rules.md
│   └── chatgpt-scheduled-task.md
└── src/
```

其中：

```text
spec.md
→ 專案系統設計

schedule-rules.md
→ AI / Scheduled Task 業務判定規則

chatgpt-scheduled-task.md
→ ChatGPT 排程架構與維護方式
```

資料則維持：

```text
Google Sheet
→ VTuber schedule runtime data
```

最終資料流：

```text
GitHub Rules
     ↓
Scheduled Task
     ↓
X / 週表圖片
     ↓
解析與規則判定
     ↓
驗證 / 去重 / 更新
     ↓
Google Sheet
     ↓
Meridian Schedule Website
```

此架構讓 GitHub 成為規則與專案設計的中心，Google Sheet 專注於資料儲存，ChatGPT Scheduled Task 僅負責執行，避免三者職責混在一起。