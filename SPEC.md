# Meridian Schedule — VTuber 行程聚合器現行完整規格

本文件說明現行主流程、資料契約、相容規則、失敗復原及驗收項目。外部排程、Sheet 寫入與 Pages 部署須在實際環境驗證。

## 1. 專案目標

建立以 VTuber 官方公開公告為依據的行程聚合器，讓使用者查看今日、本週、自選日期與多位成員行程，並能追溯更新來源。

系統需能：

1. 由外部 ChatGPT 依排程規則辨識官方週表，新增或更新可確認的行程，將疑義交人工確認。
2. 理解文字與週表圖片，將可確認資訊寫成固定欄位。
3. 由程式驗證、正規化、去重及合併，維護正式 JSON 與修改歷史。
4. 在 GitHub Actions 有實際資料差異時提交資料，再由 GitHub Pages 發布靜態網站。
5. 保留來源、事件 ID 與 Revision；單筆資訊不確定或外部來源失效時保留既有正式資料。
6. 核心流程不以 X API、OpenAI API、Google Sheets API 或 Raspberry Pi 為必要條件。

目前接受小時級同步，不要求秒級通知。整體新鮮度取決於來源發現、Sheet 發布與 Actions 執行，不保證每篇公告都能被搜尋到。

## 2. 範圍與非目標

現行主流程涵蓋官方公開資訊擷取、單表 CSV 匯入、儲存庫資料保存及靜態網站。人工可直接整理相同 CSV 作為替代輸入。

目前不提供：

- 公開後端服務、使用者登入、社群／聊天室、複雜權限、完整資料庫或獨立手機 App。
- Discord 私人伺服器蒐集、YouTube／Twitch 自動蒐集 adapter、秒級 X 通知或不漏貼文保證。
- 本機大型模型、自行訓練 Vision 模型或強制 OCR；YouTube 待機室不是唯一排程依據。
- CSV `operation`、`schedule_version`、明確刪除、整張週表替換或模糊比對後自動覆寫。
- Google 認證、Sheet 狀態回寫、程式內文字／圖片 Parser、AI API Provider、提案採用／PR 發佈或 confidence 核准門檻。

`cancelled`、`postponed` 是正式事件狀態，可透過 CSV 更新；取消保留事件，不等同刪除。其他平台可作為已由外部確認的公開來源 URL，不表示儲存庫已實作其自動蒐集功能。

## 3. 核心設計原則

| 原則 | 現行要求 |
| --- | --- |
| 正式資料來源 | Git repository 的 `data/*.json` 為準；Sheet、ChatGPT 對話與本機 CSV 都是輸入或暫存資料 |
| AI 理解、程式決定修改 | AI 寫入暫存欄位；程式執行固定驗證及合併，不授予來源文字／圖片修改程式或執行命令的權限 |
| 發現可能不完整、處理必須可重現 | 搜尋不到不代表取消、休息或事件不存在；日期推算不依本次執行日漂移 |
| 穩定 identity | 同一邏輯事件永遠沿用原 ID，日期、時間、狀態、標題、平台或來源修正均不重編 |
| 失敗保留資料 | 下載／結構／交易失敗保留既有資料；單列錯誤略過，不妨礙其他有效列 |
| 冪等 | 相同有效輸入重跑不改時間戳、不新增歷史、備份或無意義 commit |
| 可追溯 | 每個正式事件與 Revision 均有同成員的來源紀錄；來源變更保留舊紀錄 |
| 低相依性 | Python 標準函式庫與原生 HTML／CSS／JavaScript；正式環境目前無額外套件 |

「不新增 API 使用費」是核心架構的限制；ChatGPT 訂閱、網路、既有硬體及託管服務額度仍各自受實際帳號條件限制。

## 4. 現行架構與責任

```mermaid
flowchart TD
    Source[官方公開貼文與週表圖片] --> Discovery[外部 ChatGPT 或人工擷取]
    Discovery --> Sheet[Google Sheet schedule_ingestion]
    Sheet --> CSV[Publish to Web 公開 CSV]
    CSV --> Actions[GitHub Actions 每小時匯入]
    Local[本機 CSV] --> Importer[CSV 驗證與正規化]
    Actions --> Importer
    Importer --> Merge[依 ID 合併與防重複]
    Merge --> Transaction[關聯驗證、鎖、備份、交易寫入]
    Transaction --> Data[正式 data JSON 與 receipts]
    Data --> Git[Actions 有差異才提交]
    Git --> Build[驗證及靜態建置]
    Build --> Pages[GitHub Pages]
```

| 元件 | 責任 |
| --- | --- |
| 外部 ChatGPT／人工 | ChatGPT 讀取 GitHub 最新排程規則、理解官方週表並同步 Sheet，人工處理疑義；能力與排程須在實際環境驗證 |
| Google Sheet | 公開 ingestion buffer 與人工作業介面；不當作網站資料庫 |
| CSV importer | 下載／讀檔、欄位驗證、正規化、依 ID 合併、防重複、來源／Revision／receipt 維護 |
| 共用 storage／validation | 資料關聯、檔案鎖、備份、交易失敗回復及中斷復原 |
| GitHub Actions | 測試、匯入、驗證、建置、有差異才提交、協調 Pages 部署 |
| 靜態前端 | 只讀取建置後的成員與行程；負責顯示與篩選 |

CSV 的確定性合併位於 `ingestion/schedule_csv.py`，使用共用正式資料模型、關聯驗證與 storage。匯入入口接收 CSV 事件列。

## 5. 儲存庫結構

| 位置 | 用途 |
| --- | --- |
| `ingestion/schedule_csv.py`、`scripts/import_schedule.py` | 現行 CSV 主流程與 CLI |
| `processor/models.py`、`schemas.py`、`validate.py`、`storage.py` | 資料模型、Schema、跨檔驗證、鎖與交易 |
| `data/` | `members.json`、`schedule.json`、`posts.json`、`revisions.json`、`imported_ids.json` |
| `schemas/` | 正式資料與 CSV 正規化列 Schema |
| `site/` | `index.html`、`app.js`、`theme.js`、`style.css` |
| `scripts/` | CSV 匯入、驗證、建置、備份與健康檢查命令 |
| `.github/workflows/` | CI、CSV 匯入、Pages 與備份 workflows |
| `tests/fixtures/data/` | 獨立虛構測試基準，不隨正式週表更新 |
| `examples/` | 十欄 CSV 輸入範例 |
| `docs/schedule-rules.md`、`docs/chatgpt-task.md` | 週表擷取業務規則與外部排程提示 |
| `docs/ingestion.md`、`docs/operations.md` | 匯入設定與資料維運 |
| `.local/`、`dist/` | 忽略追蹤的執行狀態／備份與建置輸出 |

## 6. 正式資料模型

JSON Schema 使用 Draft 2020-12 格式。實際驗證器只支援專案現用的關鍵字，並非通用 JSON Schema 引擎；新增 Schema 關鍵字時必須同步擴充 `processor/schemas.py` 與測試。

以下 JSON 為相互對應的虛構格式範例，不能直接當作正式成員或公告資料。

### 6.1 `members.json`

```json
[
  {
    "id": "demo-miri",
    "name": "示範成員",
    "group": "none",
    "group_name": "示範成員",
    "x_username": null,
    "youtube": null,
    "twitch": null,
    "enabled": true
  }
]
```

- 必填欄位如上；`id` 唯一，格式為小寫英數、底線或連字號，開頭為英數。
- `group` 是團體識別碼，`group_name` 是顯示名稱。現行設定包含 `neon`／霓 NEO(n)、`ianvs`／扉暮 IANVS、`teraz`／序境 TeRaź、`aetris`／沉珀 Aetris；無團體用 `none` 並以成員名稱作 `group_name`，合作藝人用 `collaborators`／合作藝人。
- `x_username` 是帳號名稱或 `null`；`youtube`、`twitch` 是完整頻道 HTTP(S) URL 或 `null`，不填帳號短名稱。
- CSV 僅接受 `enabled=true` 的成員；網站也隱藏停用成員。停用不刪除其既有資料或歷史。
- 前端選單沿用陣列順序；目前維護慣例為合作藝人置後。KSP 保留成員及頻道資料，目前因不發布週表而停用；實際啟用名單以檔案為準。

### 6.2 `schedule.json`

```json
{
  "updated_at": "2026-10-28T03:00:00+08:00",
  "events": [
    {
      "id": "demo-miri_20261028_01",
      "member_id": "demo-miri",
      "date": "2026-10-28",
      "time": "20:00",
      "timezone": "Asia/Taipei",
      "title": "示範雜談",
      "platform": "unknown",
      "url": null,
      "status": "scheduled",
      "origin": "weekly_schedule",
      "source_post_id": "demo-source-001",
      "confidence": 0.70,
      "updated_at": "2026-10-28T03:00:00+08:00",
      "source_url": "https://example.com/public-source",
      "created_at": "2026-10-28T02:10:00+08:00"
    }
  ]
}
```

| 欄位 | 契約 |
| --- | --- |
| 頂層 `updated_at` | 最近實際行程變更時間，含時區；空行程可為 `null` |
| `id`、`member_id` | 唯一事件 ID 與存在的成員；CSV 更新不得更換 ownership |
| `date`、`time`、`timezone` | `YYYY-MM-DD`、`HH:MM` 或 `null`、固定 `Asia/Taipei` |
| `title`、`platform`、`url` | 非空標題、平台代碼或 `null`、直播 URL 或 `null` |
| `status` | `scheduled/changed/cancelled/postponed/live/finished/day_off/unknown/tbd` |
| `origin` | `weekly_schedule/schedule_change/sudden_stream/cancellation/postponement/day_off` |
| `source_post_id` | 唯一回溯至同成員的 `posts.json` 紀錄 |
| `confidence` | 0～1；CSV 新事件固定 `0.70` 作相容值，不表示 AI 評估結果 |
| 事件 `updated_at` | 最近實際修改時間，含時區 |
| `source_url`、`created_at` | Schema 選填以相容舊資料；CSV 新事件記錄來源與初次建立時間 |

`scheduled/changed/live/finished` 必須有時間。CSV 的狀態／時間配對比正式 JSON 的舊資料相容驗證更嚴格，見第 8 節。正式平台 Schema 仍保留 `other`，新 CSV 不接受此值。

### 6.3 `posts.json`

```json
[
  {
    "source": "other",
    "post_id": "demo-source-001",
    "member_id": "demo-miri",
    "published_at": "2026-10-28T02:10:00+08:00",
    "processed_at": "2026-10-28T03:00:00+08:00",
    "type": "weekly_schedule",
    "status": "processed",
    "source_url": "https://example.com/public-source",
    "media": []
  }
]
```

- `source` 接受 `x/discord/other`。貼文分類 `type` 接受 `weekly_schedule/schedule_change/sudden_stream/cancellation/postponement/day_off/irrelevant/unknown`。
- 貼文處理 `status` 接受 `processed/pending_review/ignored/failed/manual_review`，與事件狀態、Sheet 選填的 ingestion status 各自獨立。
- `(source, post_id)` 不得重複；被事件或 Revision 引用的 `post_id` 必須跨來源唯一並屬於相同成員。
- CSV 未提供原公告發文時間，新增來源的 `published_at` 使用該列 `created_at`，不得解讀為已核實的原始發文時間；`processed_at` 使用匯入時間，`media` 為空陣列。

### 6.4 `revisions.json`

每筆包含 `event_id`、含時區 `timestamp`、`source_post_id`、`before`、`after`。新增事件的 `before=null`；其餘為修改前完整 Event，`after` 為修改後完整 Event，不使用僅含異動欄位的局部快照。

快照 ID 必須等於 `event_id`，事件與來源必須存在，`after` 的來源及成員必須與該 Revision 一致。來源更換時保存完整前後來源，舊來源紀錄不刪除。

### 6.5 `imported_ids.json`

```json
["demo-miri_20261028_01"]
```

此檔為已見過的 CSV row／event ID receipt。是否新增或更新以 `schedule.json` 是否存在該 ID 判斷；receipt 不是唯讀鎖，也不是可靠的舊 ID 對照表。

只有實際接受新增／更新時才新增 receipt；純重複、無變更或無效列不為補記 receipt 而寫檔。receipt 已存在但事件不存在時，仍按新事件規則檢查。

## 7. 外部發現與 Sheet 寫入

外部 ChatGPT 作業依 [提示範本](docs/chatgpt-task.md) 設定，建議每小時執行。每次以 GitHub `main` 最新的 [排程規則](docs/schedule-rules.md) 判定來源、欄位、去重、更新、寫入驗證與錯誤處理。匯入器收到 CSV 後依第 8 至 13 節驗證及合併。

Google Sheet 主表名稱為 `schedule_ingestion`。建議 ID、日期、時間、URL 與時間戳欄設純文字。

- 隱藏 `members_lookup` 的 A:D 保存 `id/group/group_name/enabled`，由維護者在名單異動時同步。E 欄篩選啟用 ID，供主表 B 欄下拉使用。
- 主表 C 欄 `group` 由公式依 B 欄查表，使用識別碼。保留 C2 的 ARRAYFORMULA 及展開範圍，設定限制編輯的保護範圍。公式與詳細設定見 [匯入手冊](docs/ingestion.md)。
- F2:F1000 使用六種 `event_status` 的嚴格下拉選單。
- ChatGPT 的寫入範圍及核對方式見 [排程規則](docs/schedule-rules.md#9-寫入驗證)。人工修正同樣保留事件 ID、成員、公式及首次建立時間。
- Sheet 對外發布為 CSV，僅放可公開行程資料。保護範圍是防誤改措施，擁有者仍可修改。

## 8. CSV 欄位與狀態契約

新格式建議依序使用十欄；Importer 按標題對應，接受欄位換序：

```csv
id,member_id,group,date,time,event_status,title,platform,source_url,created_at
demo-miri_20261028_01,demo-miri,none,2026-10-28,20:00,scheduled,示範雜談,unknown,https://example.com/public-source,2026-10-28T02:10:00+08:00
```

| 欄／欄位 | 新格式規則 |
| --- | --- |
| A `id` | 必填；直接作為 Event ID，建議 `{member_id}_{YYYYMMDD}_{index}`，建立後固定 |
| B `member_id` | 必填；必須存在且已啟用，同 ID 不得換成員 |
| C `group` | 選填、僅供 Sheet 顯示，匯入忽略，不覆寫正式分組 |
| D `date` | 必填；建議完整 `YYYY-MM-DD` |
| E `time` | `HH:MM` 或空白；不填狀態 token，也不填字串 `null` |
| F `event_status` | 有此標題即每列必填，去除前後空白並轉小寫；只接受下表六值 |
| G `title` | 必填；去除前後空白後不可為空 |
| H `platform` | 選填；`youtube/twitch/none/unknown`，不區分大小寫；缺欄／空白對既有事件表示保留原值 |
| I `source_url` | 必填、無帳密及空白控制字元的 HTTP(S) 公開來源 URL；不參與事件 identity |
| J `created_at` | 必填、含時區與秒數的 ISO 8601；代表首次建立，不因修正重產 |
| 選填 `status` | 空白／`pending/imported/invalid`；與 `event_status` 無關，`invalid` 作人工停用，其餘不參與合併 |

| `event_status` | `time` 配對 | 語意 |
| --- | --- | --- |
| `scheduled` | 必須有實際時間 | 已排定且時間確定 |
| `tbd` | 必須空白 | 官方明確表示時間未定 |
| `day_off` | 必須空白 | 官方明確休息 |
| `unknown` | 必須空白 | 資訊不足，無法判定時間或行程狀態 |
| `cancelled` | 實際時間或空白 | 官方明確取消，可保留已知原時間 |
| `postponed` | 實際時間或空白 | 官方明確延期，只有已確認時才填時間 |

空白時間轉 JSON `null`；CSV `event_status` 對應 Event `status`，正式 JSON 不增加另一個 `event_status` 欄位。

新格式不接受 `changed/live/finished`。明確狀態為 `scheduled` 時，修正其他內容不自動變成 `changed`；既有 `changed` 收到明確 `scheduled` 可正常更新並留下 Revision。

平台 `none` 表示已確認無開台平台，`unknown` 表示無法確認，兩者保留不同值。新事件平台缺欄或空白儲存為 `null`；既有事件則保留原值。明確填 `none/unknown` 可覆寫既有平台。CSV 不接受 `other`。

## 9. 正規化與舊 CSV 相容

### 9.1 結構與輸入限制

- 公開下載只接受無帳密的 HTTPS URL，重新導向也須維持 HTTPS；不傳送 Google 認證。預設逾時 30 秒，最多讀取 10 MiB。
- 本機 CSV 同樣上限 10 MiB，使用 UTF-8，接受 BOM、CRLF、引號、欄內逗號與換行；空白列忽略。
- 必要標題為 `id,member_id,date,time,title,source_url,created_at`；額外只接受 `group,platform,event_status,status`。缺少必要標題、重複／未知標題、空檔或 CSV 語法錯誤中止整批。
- 單列欄數不符、欄值不合法、未知／停用成員或狀態／時間配對錯誤，略過並警告行號；其餘有效列繼續。
- `schemas/schedule_ingestion.schema.json` 描述正規化後的列；跨欄時間／狀態規則由 Importer 額外驗證。

### 9.2 日期、時間與來源

- 接受完整日期 `YYYY-MM-DD`、`YYYY/M/D`，以及 `M/D`、`Oct 28`、`October 28, 2026`。
- 短日期以初次 `created_at` 換算的台灣日期，在前一年、當年、後一年選最近有效日期；同距離取較早日期。既有事件已記錄建立時間時沿用該值，不受後續 CSV 時間戳或執行日影響。
- 實際時間接受 `20:00`、全形冒號、`8:00 PM`、`晚上八點` 等既有格式，正規化為 `HH:MM`；不是任意自然語言時間解析器。
- `created_at` 正規化為台灣時區及秒數。既有事件的建立時間不因 CSV 更新而改變。
- X／Twitter 支援的分享網址統一至 `https://x.com`，去除追蹤參數；其他來源移除 fragment，保留其餘網址內容。

### 9.3 舊格式啟用條件

僅當 CSV 完全沒有 `event_status` 標題時，才啟用舊格式：

| 舊 `time` | 正規化 `time` | 推導事件狀態 |
| --- | --- | --- |
| 實際時間 | `HH:MM` | `scheduled` |
| `tbd`／待定／未定／時間未定 | `null` | `tbd` |
| `day_off`／休息／休息日 | `null` | `day_off` |
| `unknown`／未知 | `null` | `unknown` |

舊格式空白時間無效。只要有 `event_status` 標題，空白狀態就屬單列錯誤；即使兩欄語意相同，也不能在新 `time` 填狀態 token。

舊格式以實際時間修改既有事件時，沿用既有 `cancelled/postponed/live/finished` 等狀態；一般內容更新保留舊 `changed` 邏輯。只有新格式的明確狀態能明確控制取消、延期及恢復。

`working_day`／工作日／作業日已不接受，應由人工依資訊改填 `unknown` 等有效狀態。既有資料已將該舊代碼轉為 `unknown`；這種格式轉換不代表官方發布異動。

## 10. 事件識別、更新與防重複

CSV 以 `schedule.events[].id` 唯一判斷新增或更新。ID 建議包含的日期只在初次產生時使用；事件改期後 ID 不重編。`member_id + date + normalized time` 只供新 ID 防重複，不作自動更新依據。

| CSV 情況 | 行為 |
| --- | --- |
| 新 ID，無相似事件 | 新增 Event、來源、Revision 與 receipt |
| 新 ID，正規化內容完全相同 | 視為重複，不新增事件或 receipt，即使來源不同也一樣 |
| 新 ID，同時段且標題相似 | 警告並略過，交由人工確認原 ID |
| 相同 ID，內容及來源相同 | 完全 no-op |
| 相同 ID，日期／時間／狀態／標題／明確平台／來源改變 | 更新原事件並保存 Revision |
| 相同 ID，`member_id` 改變 | 拒絕該列並警告 |
| 相同 ID，更新後與另一事件內容重複 | 拒絕該列並警告 |
| 同批同 ID，正規化內容相同 | 只處理一次，其餘計重複 |
| 同批同 ID，存在不同有效內容 | 整組略過並警告，不依列順序挑選 |
| CSV 列消失 | 保留正式事件 |

完全重複比較成員、日期、時間、標題、平台與狀態，並把舊 `changed` 視同 `scheduled`。新 ID 疑似重複條件為同成員、日期、時間，且忽略大小寫的 `SequenceMatcher` 標題相似度至少 0.6；平台或狀態不同也不自行認定為更新。同時段但標題未達相似門檻可新增不同事件。

同 ID 更新碰撞檢查比較另一事件的成員、日期、時間、標題、平台，即使狀態不同也拒絕碰撞。

既有事件更新保留 `id`、`member_id`、已記錄的 `created_at`、`confidence`、`origin`、直播 `url`。`group` 不參與內容比較，`pending/imported` 不影響合併；只修改這些欄位或已記錄的建立時間不產生變更。

相同內容重跑不得修改任何正式 JSON 位元組或 `updated_at`，不得新增 Revision、備份、receipt 或 commit。

## 11. 來源與 Revision 維護

CSV 同一篇週表可產生多個事件，不能因來源 URL 已存在而略過整張週表。

- 同成員、正規化來源 URL 相同時共用來源紀錄；既有事件仍引用相同來源時沿用原 `post_id`。
- 新來源 ID 由成員及來源 URL 的 SHA-256 產生 `csv-...`；來源平台依 URL 主機標為 `x/discord/other`，不等於直播平台。
- CSV 新事件的 `origin` 依狀態產生：休息為 `day_off`、取消為 `cancellation`、延期為 `postponement`，其餘為 `weekly_schedule`。後續更新保留原 `origin`；CSV 沒有獨立的分類／origin 欄位。
- 新事件的直播 `url=null`、`confidence=0.70`。CSV 不提供這兩欄，既有值也不因修正覆寫。
- `source_url` 可以由原週表換為修正版或其他官方公告，不能把來源不同當作拒絕同 ID 更新的理由。
- 實際變更才新增 Revision；來源更換時保存 `before.source_url` 與 `after.source_url`，並保留原 `posts`。
- 舊 Event 尚未記錄 `source_url` 時，在首次實際 CSV 更新的 `before` 從來源紀錄補入；缺少 `created_at` 欄位時，也於實際更新記錄首次值。

跨檔資料驗證涵蓋成員、事件 ID、來源唯一性與 ownership、Revision 引用及完整快照。來源 URL 格式驗證不等於官方身分或公告內容驗證，後者由擷取及人工查核負責。

## 12. 匯入交易與冪等性

1. 完整下載／讀取並解析 CSV，結構錯誤在正式資料修改前中止。
2. 取得資料目錄檔案鎖，讀取並驗證既有正式資料及 receipt；發現未完成交易時拒絕繼續。
3. 正規化每列，檢查成員，將同 ID 有效列分組以偵測內容衝突。
4. 在記憶體副本逐列合併並驗證跨檔關聯；單列失敗不保留其部分變更。
5. 無實際變更時直接成功結束；只有標題或全部列無效也不得清空原資料。
6. 有變更時先備份原資料，再建立交易日誌，連動寫入行程、來源、Revision 及 receipt。
7. 正常寫入失敗回復原始位元組；全部完成後移除交易日誌。

`members.json` 由管理者維護，CSV 不變更其內容；共用 storage 備份／交易仍包含成員檔。鎖衝突時失敗，等待重試，不能繞過鎖直接寫檔。

程序被強制中止可能留下 `data/.transaction.json`；讀取、驗證與建置會拒絕不完整交易，須先執行 `python -m scripts.backup_data recover`。這是程序中斷復原機制，不保證跨檔案瞬間原子性或斷電時的磁碟耐久。

## 13. CSV 變更採用與資料保護

現行只接受公開或本機 CSV。每筆有效列依事件 ID 新增／更新，經正規化、Schema、ownership、防碰撞及完整資料關聯驗證後直接寫入；不產生審核提案，也沒有 confidence 採用門檻。

人工修正同樣沿用 CSV 的穩定 ID。原始文字／圖片須由外部 ChatGPT 或人工先整理成欄位。

每次實際變更保留來源與完整 Revision；寫入前備份，失敗回復整批資料與 receipt。相同內容重跑完全 no-op。Git 提交只由 CSV workflow 的既有有差異提交步驟負責，CLI 不進行 Git 操作或發送 PR。

## 14. 資料相容範圍

- CSV 相容格式與轉換規則見第 9 節，舊 CSV 遷移步驟見第 22.2 節。
- 正式 JSON 欄位與歷史快照的相容規則見第 6、11 節。
- 不含 receipt 的備份還原方式見第 19 節。

## 15. GitHub 整合與部署

正式分支預設 `main`。CSV CLI 只匯入指定資料目錄，不自行執行 Git 操作；提交由已配置的 workflow 負責。

| Workflow | 觸發及作用 |
| --- | --- |
| `ci.yml`／Validate and test | push、PR：Python 測試、前端語法／測試、資料驗證、靜態建置 |
| `process-ingestion.yml`／Process ingestion | main push、手動、`new_ingestion` dispatch、每小時第 17 分鐘；只有 CSV URL 已設定且位於 main 才執行 |
| `deploy-pages.yml`／Deploy GitHub Pages | main 的相關程式／資料變更、手動，或 CSV 匯入 workflow 成功完成後驗證及部署 |
| `backup-data.yml`／Backup schedule data | 每日台灣 03:30 或手動健康檢查及備份 |

現行匯入排程設定為 `cron: '17 * * * *'`、`timezone: 'Asia/Taipei'`。GitHub 排程可能延遲或漏跑，不視為準時保證。

匯入 workflow 順序為測試 → 匯入 CSV → 驗證資料 → 建置 → 檢查暫存差異。只提交以下實際變更：

```text
data/schedule.json
data/posts.json
data/revisions.json
data/imported_ids.json
```

沒有差異即成功結束，不 commit。匯入 workflow 使用固定 concurrency group 且不取消進行中的 run；分支保護或 push 被拒絕會失敗，下次從遠端 main 重新匯入，不繞過保護或 force-push。

Pages 使用 `workflow_run` 銜接成功匯入，處理內建 `GITHUB_TOKEN` 資料提交後的部署；這條銜接以匯入前後 `data/members.json`、`data/schedule.json` 是否改變決定部署，只有 receipt／歷史差異時略過。手動部署與其他觸發依 workflow 設定執行。

建置輸出至 `dist/`，包含靜態資產、`.nojekyll` 及公開 `data/members.json`、`data/schedule.json`。公開 schedule 額外含 `sources` URL 對照；這是建置衍生資料，不寫回正式 schedule Schema。前端不讀 Sheet、posts、revisions 或 receipt。

## 16. 網站行為

### 16.1 日期、範圍與成員

- 初次載入選台灣當日，使用 HTTP 讀取 JSON；不支援以 `file://` 直接開 HTML 載入資料。
- 「今日」回到台灣當日；「本週」顯示所選日期所在週一至週日，支援跨月／跨年；手動更換有效日期切至「選擇日期」，只顯示該日。三種模式互斥高亮並同步 `aria-pressed`，日期與模式不保存偏好。
- 成員篩選提供「全選」及「團體」「VTuber」兩區，僅顯示啟用成員，依資料順序排列；團體由啟用成員產生，沒有啟用成員的團體不顯示。`none` 不列為團體，其成員仍可單獨選取；合作藝人依相同團體規則處理。
- 團體可複選，勾選團體時，以所有已勾團體的成員聯集取代選取，取消其他成員；取消團體只移除該團體成員，保留其他手動選取。成員可自由勾選，團體全員選滿時自動勾選團體，缺少任一人即取消。
- 勾選全選會選取全部啟用成員，取消全選會清空；逐人選滿時自動勾選全選，未選滿則取消。成員清單為唯一選取依據，團體與全選由此推算，不影響事件狀態勾選。全部取消時不顯示事件，提示「請至少勾選一位 VTuber。」
- 第一次開啟預設全選，之後以獨立 `localStorage` 項目 `meridian-members` 保存成員 ID 陣列，包含全部取消。恢復時忽略已移除或停用的 ID，新成員預設不勾選；儲存格式損壞時回到全選，儲存遭封鎖仍可於本次瀏覽使用。
- 行程依日期、時間、ID 排序，無時間者排該日最後；取消與延期保留在行程中，由狀態篩選控制顯示。
- 空日、無符合資料、載入失敗須有明確訊息；顯示的最後更新來自 schedule 時間戳，不代表最近成功搜尋時間。

### 16.2 狀態及時間顯示

| Event `status` | 徽章 | `time=null` 時時間欄 |
| --- | --- | --- |
| `scheduled` | 正常 | 正式驗證不允許 |
| `changed` | 已異動 | 正式驗證不允許 |
| `cancelled` | 已取消 | 已取消 |
| `postponed` | 延期 | 延期 |
| `live` | 直播中 | 正式驗證不允許 |
| `finished` | 已結束 | 正式驗證不允許 |
| `day_off` | 休息 | 全天 |
| `unknown` | 未知 | 未知 |
| `tbd` | 待定 | 時間待定 |

有實際時間時顯示時間與對應徽章。`origin=sudden_stream` 額外顯示「突發」；突發不是另一種 Event status。未知、時間待定與休息有不同語意，不互相替代。

### 16.3 事件狀態複選

固定提供目前 CSV `event_status` 的六種狀態：`scheduled/tbd/day_off/unknown/cancelled/postponed`，顯示正常、待定、休息、未知、已取消、延期，預設全選。直接依 Event `status` 與日期、模式及成員條件共同篩選，更新行程與筆數。`changed/live/finished` 保留舊 JSON 與徽章相容，但不列為選項，也不包含於六種狀態的篩選結果；不改寫正式資料。

全不勾選時不顯示事件，提示至少勾選一種狀態；重新勾選可恢復。切換其他條件保留目前勾選，重新載入恢復全選，不保存事件狀態偏好。核取方塊須可用 Tab／空白鍵操作。

### 16.4 平台、來源與色系

- 頁首及頁尾顯示：「本站由非官方維護，行程資訊僅供參考，最新異動請以官方公告為準。」
- YouTube 使用紅色白字徽章、Twitch 使用紫色，`unknown` 顯示灰色「平台未確認」；`none`、`null` 或休息日不顯示平台徽章。
- YouTube／Twitch 徽章連至成員相應頻道，不等同該場直播 URL；缺少有效頻道時顯示純文字。事件 `url` 有值時另提供「前往直播」。
- 成員名稱依 `x_username` 連至 X 個人頁；未設定維持文字。來源連結優先用建置 `sources`；只有舊數字 X post ID 可組合 X URL，不能把 `csv-...`／Discord ID 當成 X 貼文。
- 文字以 DOM `textContent` 呈現；連結僅允許 HTTP(S)，新分頁使用 `noopener noreferrer`。
- 深淺色初次跟隨系統；手動切換後以 `meridian-theme` 保存偏好，重載沿用。未手動選擇時跟隨系統變動；儲存遭封鎖仍可於本次瀏覽切換。
- 色系在內容顯示前套用，行程載入失敗時開關仍可使用。手機 375px 應無橫向捲動，控制項可用鍵盤操作。

## 17. 執行環境、設定與安全

需求 Python 3.11+；前端測試需 Node.js 22+。無需 `pip install`、`npm install` 或正式環境 framework。程式不自動載入 `.env`，由 shell 提供環境變數。

| 設定 | 用途與範圍 |
| --- | --- |
| `SCHEDULE_CSV_URL` | 主流程公開 CSV URL，GitHub Repository Variable；CLI 也可 `--url` 或 `--input` |
| 內建 `GITHUB_TOKEN` | workflow 的資料寫入及 Pages 權限；按 job 配置最小需要權限 |

公開 CSV 只能包含可公開資料；API Key、Token、密碼、憑證、Email 或私人帳號不可寫入或提交。`.env`、本機資料庫、鎖、交易狀態與備份不納入 Git。

CSV URL 是公開讀取設定，不能靠不公開連結當成存取控制。欄位驗證只保證資料格式及合併限制，不能證明公告真實性；Sheet 編輯權限與擷取端查核仍是資料信任邊界。

## 18. 日誌、錯誤與重試

CSV CLI 成功回傳 JSON：`result`、`rows`、`imported`、`duplicates`、`invalid`、`changed`、`schedule_changed`。

- `imported` 包含新增及同 ID 更新；no-op 與新 ID 完全重複列計 `duplicates`。
- 無效／需人工確認列計 `invalid` 並輸出行號警告。單列錯誤不代表整批失敗，需查看報告修正。
- 下載、解析或寫入失敗回傳非零結束碼及不含敏感內容的錯誤訊息；不輸出回應本文、憑證或圖片資料。

| 失敗 | 行為與重試 |
| --- | --- |
| CSV 網路／下載錯誤 | 保留正式資料、不提交；修復後重跑或等待下次小時排程。下載函式沒有內建多次重試 |
| CSV 結構錯誤 | 整批停止，保留資料；修正標題／語法再重跑 |
| 單列無效、ownership／重複疑慮／碰撞 | 略過該列並警告，其餘有效列繼續；人工修正後可重試 |
| 鎖衝突／未完成交易 | 停止；等待其他程序或先 recover，不繞過保護 |
| 寫入失敗 | 回復整批原始資料與 receipt；強制中止後先 recover |
| CSV push 失敗 | workflow 失敗，下次從最新 main 重新匯入 |
| 外部 ChatGPT／Sheet 不可用 | 保留正式網站資料，不推定任何事件狀態；外部端回報缺少工具／權限 |

CSV CLI 沒有內建多次下載重試；由人工重跑或等待下一次排程。

## 19. 備份、復原與健康檢查

每次實際 CSV 寫入或還原前，先將正式資料與存在的 receipt、校驗值及原始位元組備份到資料目錄外，預設 `.local/backups/`。no-op 不建立備份。

```sh
python -m scripts.backup_data backup
python -m scripts.backup_data restore --snapshot .local/backups/SNAPSHOT.json
python -m scripts.backup_data recover
python -m scripts.health_check
```

`restore` 會實際修改正式資料，並先備份目前版本；`SNAPSHOT.json` 須替換為已確認的快照。還原不含 receipt 的舊版備份時清空匯入 IDs，讓後續可重新匯入。

CSV workflow 備份 artifact 保存 30 天，每日備份 workflow 保存 90 天；本機備份不自動清除。Git 歷史與同帳號 artifact 不是獨立外部備援，離線／跨帳號備份須另行安排。

`health_check` 驗證正式資料關聯及 `manual_review/failed` 來源，只有 `--data-dir` 選項；資料無效或有待人工處理來源時回傳非零碼與 JSON 原因。備份、還原、復原及健康檢查可在只含資料核心與維運指令的隔離副本執行。尚無自動寄信／第三方告警或完整 discovery 心跳。

## 20. 測試與驗證

沿用專案驗證命令，在根目錄執行：

```sh
python -m unittest discover -s tests -v
node --check site/app.js
node --check site/theme.js
node --test tests/test_site.cjs
python -m scripts.validate_data
python -m scripts.build_site
```

| 範圍 | 必要案例與預期 |
| --- | --- |
| CSV 批次與修正 | 同來源多列新增、同 ID 改時間、明確取消／延期／恢復、無效列略過及舊資料保留 |
| CSV 結構與正規化 | 必要／未知／重複標題、BOM／引號／換行、大小上限、錯誤單列略過、日期時間及跨年可重現 |
| 事件識別與更新 | 同 ID 修改允許欄位、保留建立時間、拒絕換成員、來源更新、receipt 不鎖定、防重複及碰撞 |
| CSV 事件狀態 | 六種狀態、時間配對、取消／延期／恢復、新舊格式相容、明確狀態不變 changed、遷移內容相同完全 no-op |
| storage | 無變更不寫檔／備份、完整 Revision、來源關聯、鎖、寫入／receipt 失敗回復、中斷復原 |
| 前端 | 台灣日期、跨年週界、排序、停用成員、日期／成員／狀態複選、全不選與恢復、空資料及載入失敗、來源連結安全 |
| 色系 | 系統預設、切換保存及重載、系統變動、儲存遭封鎖 |
| 獨立資料維運 | 只含 CSV／資料核心模組的副本執行匯入、歷史／receipt、驗證、健康檢查、no-op、備份、還原與復原 |

外部服務測試使用 mock；不以單元測試證明真實搜尋、Vision、Google 寫入、X 權限或雲端部署成功。正式資料與測試 fixtures 分離，不將虛構基準複製回 `data/`。

人工 UI 驗證使用 375px 及桌面寬度檢查無溢出、日期／本週／成員／狀態篩選、狀態語意、來源與平台連結；用 Tab／空白鍵操作；切換色系並重載；中斷資料載入確認錯誤與色系開關。手機實機及外部端到端驗證需另外記錄。

## 21. 階段進度與驗收標準

下表列出儲存庫已有的功能與仍須在實際環境驗收的項目。

| 階段 | 儲存庫已有 | 驗收仍需確認 |
| --- | --- | --- |
| 靜態資料與網站 | Schema、跨檔驗證、今日／本週／成員／狀態、色系與連結 | 實際 Pages、手機實機及無障礙操作 |
| 外部擷取 | ChatGPT 提示與固定 CSV 格式 | 真實貼文／圖片理解、外部工具與 Sheet 寫入能力 |
| 自動匯入與部署 | CSV CLI、Actions、條件提交、Pages 銜接 | 公開 CSV、變數、Token／分支權限與 workflow 實跑 |
| identity 與事件修正 | 穩定 ID、可更新欄位、六狀態、來源及完整歷史 | Sheet 與正式 ID／來源的一致性 |
| 維運 | 鎖、備份、交易復原、健康檢查 | 外部備援、告警管道與長期運作 |

現行主流程驗收應逐項留下證據：

- 有效 CSV 能新增事件；同 ID 可改日期、時間、狀態、標題、平台及來源，ID 不變。
- 取消／延期／恢復與待定／休息／未知有獨立語意；錯誤配對或跨成員修改被拒絕。
- 每次實際變更均可從 Revision 回溯來源及完整前後值；刪除 CSV 列不刪除正式事件。
- 重跑相同內容不改 JSON、時間戳、備份或 Git；新 ID 不會隱性修改舊事件。
- 結構、下載、寫入及中斷復原失敗不破壞正式資料與 receipt。
- 真實公開 CSV 可由 Actions 匯入；有差異才提交，成功後 Pages 顯示對應資料。
- 核心部署無需 X／OpenAI／Google API credentials，儲存庫不包含 AI Provider、提案或 PR 發佈入口。

實際線上狀態可能晚於或早於本次文件整理，應依帳號、workflow 紀錄及現場驗收判斷；本文件不自行勾選外部驗收完成。

## 22. 部署、遷移與本機操作

### 22.1 初次部署

1. 驗證正式成員、來源與行程，執行第 20 節命令。
2. 建立 Sheet、成員對照／保護範圍／下拉選單並發布指定工作表為公開 CSV。
3. 在有來源讀取、圖片理解與 Sheet 寫入權限的環境手動驗證外部提示，再配置小時排程；工具不可用時採人工 CSV。
4. 設定 Repository Variable `SCHEDULE_CSV_URL`，確認內建 Token 可寫入及分支保護允許預期流程。
5. Pages Source 選 GitHub Actions，手動執行 Process ingestion；檢查警告、資料差異與部署結果。
6. 驗證網站實際來源、狀態、篩選與手機畫面，並建立持續備份／故障通知方式。

### 22.2 舊 CSV 遷移至明確狀態

1. 先部署同時支援新舊格式的 importer、Schema、測試、範例與提示，確認舊 CSV 雲端匯入正常及 Pages 成功。
2. 重新讀取並備份 Sheet 值、公式、格式、驗證與全部 ID；用副本預演。
3. A:E 與 C 欄公式保持位置；新增 F `event_status`，原 F:I 使用原生欄位移動為 G:J，保留其內容／格式／驗證，不整張重寫。
4. 實際時間對應 `scheduled` 並保留時間；舊特殊值轉成相應狀態並清空 time。E:F 在同一原子 batch 更新，不混用新標題與舊 token。
5. 保留全部 ID、`created_at`、來源及公式；不得因格式遷移重編事件或歷史引用。
6. 回讀 Sheet／公開 CSV、重新匯入並比對 ID、時間、狀態與來源。若正式事件語意相同，應無新增 Revision、備份或資料差異；本來是 `changed` 且改為明確 `scheduled` 則屬實際狀態變更。

### 22.3 隔離的離線匯入

以下 PowerShell 範例使用全新的目的目錄名稱，避免更動正式資料及原始 fixture；若目錄已存在，先改用另一名稱。

```powershell
New-Item -ItemType Directory -Force .local
Copy-Item -Recurse tests/fixtures/data .local/spec-csv-demo-data
python -m scripts.import_schedule --input examples/schedule-ingestion.csv --data-dir .local/spec-csv-demo-data --backup-dir .local/spec-csv-demo-backups
python -m scripts.validate_data --data-dir .local/spec-csv-demo-data
```

再次執行相同 importer 命令應回傳 `changed: false`。正式匯入省略 `--data-dir` 會直接更新 `data/`，應先核對輸入；程式不自行 commit／push。

```sh
python -m scripts.build_site
python -m http.server 8000 --bind 127.0.0.1 --directory dist
```

本機預覽開啟 `http://localhost:8000`。Windows 若 `python` 是未安裝的 Store 別名，改用實際 Python 執行檔；PowerShell 使用 `& '完整路徑/python.exe' -m ...`。

## 23. 已知限制與待實測項目

- 儲存庫提供外部 ChatGPT 提示，不會自動建立 ChatGPT 排程，也不能保證背景任務可搜尋、理解圖片或寫 Sheet。須在實際環境驗證並保留人工替代路徑。
- 搜尋結果與公開 X 介面可能不完整或失效；無法保證發現所有公告。外部 ChatGPT 搜尋／圖片理解與帳號能力不得在未實測前視為穩定。
- CSV 沒有原始公告時間、獨立 confidence、直播 URL、operation 或 schedule_version；不進行公告新舊排序。人工修正時須避免將舊公告內容寫回相同事件；`created_at` 僅供建立時間及日期推算，不是版本號。
- CSV 無 `sudden_stream` 分類欄；正式 schema 與既有歷史保留突發 origin，但 CSV 沒有新增此分類的輸入欄位。
- Sheet 列／正式事件 ID 不一致時需人工核對。receipt 不能可靠反推對應，Importer 不自動重編或以 natural key 重新命名。
- 主流程沒有 Google write-back、完整 discovery 心跳、stuck ingestion 管理或自動告警。
- 目前沒有刪除、整張週表取代、行程版本仲裁、跨時區、多來源身分查核或公開審核 UI。
- 真實服務費用／額度、雲端權限與排程準時性、長期運作、手機實機及外部備援須另行驗證；不能以 mock 或文件存在代替。

## 24. 後續實作與交付規則

- 修改前讀取適用的 `AGENTS.md`、相關 README、建置設定、程式與測試；先確認工作目錄與 Git 狀態，保留使用者既有變更。
- 採最小根因修正，遵循既有架構、格式、錯誤處理與測試方式，不做無關重構或全檔格式化。
- 正式相依套件如確有必要，先說明原因、替代方案與影響並取得確認；外部服務透過既有介面，不寫死未經驗證的可用性。
- 新資料／AI 輸出先驗證再合併；任何正式寫入保持 identity、來源、Revision、鎖、備份與復原契約。
- 執行與範圍相符的既有驗證並檢查最終 `git diff`；純文件修改不要求完整測試。沒有執行的驗證不得宣稱通過。
- 交付列明修改檔案、實際命令與結果、重要假設、未驗證與待處理事項。不得輸出或提交機密。
- 除非使用者明確要求，不自行 commit、push、rebase、force-push 或建立 PR。此限制適用於維護工作，不取代已由部署者配置的自動資料 workflow。
- 行為變更時同步更新本規格與相關操作文件。
