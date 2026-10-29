# V2.1 公開 CSV 匯入操作手冊

依據 [spec v2.1](../VTuber_Schedule_SPEC_v2_1.md)，主要流程為：ChatGPT 搜尋／解析 → Google Sheet `schedule_ingestion` → Publish to Web CSV → GitHub Actions → repository JSON → GitHub Pages。GitHub 端只執行公開 HTTP GET，不使用 Google Sheets API、Service Account、OAuth、X API 或 OpenAI API，也不回寫 Sheet。正式資料仍在 `data/`，網站不直接查詢 Sheet。

## 建立工作表與公開 CSV

1. 建立 Google Sheet，新增單一工作表 `schedule_ingestion`。
2. 複製 `examples/schedule-ingestion.csv` 的標題列；範例成員是虛構測試資料，上線請使用正式 `data/members.json` 中已啟用的 ID。
3. 將 ID、日期、時間、網址與時間戳欄位設為純文字，避免試算表自行轉換格式。每個行程一列；同篇週表可有多列。
4. 在「檔案 → 共用 → 發布到網路」選擇該工作表與 CSV，複製產生的公開網址。一般的編輯／共用網址或登入頁不是 CSV endpoint。

建議欄位（順序可調整）：

```csv
id,member_id,date,time,title,source_url,created_at,platform
miri_aetris_20261028_01,miri_aetris,2026-10-28,20:00,雜談直播,https://example.com/public-source,2026-10-28T02:10:00+08:00,youtube
```

| 欄位 | 規則 |
| --- | --- |
| `id` | 必填、穩定且唯一；建議 `{member_id}_{YYYYMMDD}_{index}`，重跑不得隨機重編 |
| `member_id` | 必須是 `members.json` 中已啟用的成員 |
| `date` | 正式值為 `YYYY-MM-DD`；也接受 `YYYY/M/D`、`M/D`、`Oct 28`／`October 28, 2026` |
| `time` | 正式值為 `HH:MM`；接受全形冒號、`8:00 PM`、`晚上八點`等格式 |
| `title` | 必填，去除前後空白後不可空白 |
| `source_url` | 必填、無帳密的 HTTP(S) 公開來源，可為 X、Discord 或其他公開來源 |
| `created_at` | 必填，含時區與秒數的 ISO 8601，例如 `2026-10-28T02:10:00+08:00` |
| `platform` | 選填開台平台，可省略整欄；接受 `youtube`、`twitch`、`none`、`unknown`，不區分大小寫；新資料請明確填寫 |
| `status` | 選填，可省略整欄；接受空白、`pending`、`imported`、`invalid` |

成員 ID 以 `data/members.json` 為準，Miri 使用 `miri_aetris`。既有行程 ID 與已匯入列 ID 保留原值，不因成員 ID 調整而重編。

行程卡片中的成員名稱會依 `x_username` 連到對應的 X 個人頁，並於新分頁開啟；未設定帳號時維持純文字。

`platform` 代表該場直播的平台，須由官方行程文字、圖片或直播連結確認；不要把 X 貼文來源當成開台平台，也不要僅因成員有 YouTube／Twitch 頻道就推定每場的平台。休息或已確認不開台填 `none`；平台無法確認填 `unknown`，工作日若仍可能突發開台也填 `unknown`。CSV 不再接受 `other`。`none` 與 `unknown` 會以不同值保存於正式行程與 Revision；網站以紅色 YouTube、紫色 Twitch、灰色「平台未確認」徽章顯示平台，`none` 或休息日不顯示平台徽章。YouTube／Twitch 徽章分別連到該成員 `youtube`／`twitch` 欄位的頻道並於新分頁開啟；缺少有效網址或平台未確認時維持純文字徽章。舊七欄 CSV 仍可匯入；更新既有行程時，缺欄或空白會保留原本平台。

既有線上工作表新增 `platform` 欄之前，須先部署支援該欄的匯入程式；舊程式會將額外標題視為結構錯誤而中止整批。

時間不明請明確填 `tbd`／`待定`／`未定`／`時間未定`；休息填 `day_off`／`休息`／`休息日`；工作日填 `working_day`／`工作日`／`作業日`。匯入後使用現有狀態與 `time: null`，空白時間不會自行推論。所有行程均為台灣時間。

缺少年份時，以 `created_at` 換算的台灣日期，在前一年、當年、後一年中選最近的有效日期；不使用執行當天日期。跨年結果因此可以重現。建議生產者一律填完整日期。

[CSV schema](../schemas/schedule_ingestion.schema.json) 描述正規化後的一列；Importer 先轉換日期與時間，再驗證。缺欄、重複或未知標題、空檔及無法解析的 CSV 語法會中止整批。UTF-8 BOM、CRLF、引號、標題中的逗號與換行均可處理。單列欄數不符、未知／停用成員、日期／時間／網址不合法則略過並記錄行號警告，其他有效列仍會匯入。下載與本機輸入上限為 10 MiB。

公開 CSV 的內容任何人皆可讀取；只放公開行程資訊，不放 API Key、Token、Email、私人帳號或密碼。CSV URL 是公開讀取網址，使用 Repository Variable 即可。

## 本機驗證

需求 Python 3.11+，不需安裝套件。以下 PowerShell 範例先複製測試基準，避免修改正式資料或原始 fixture：

```powershell
New-Item -ItemType Directory -Force .local
Copy-Item -Recurse tests/fixtures/data .local/csv-demo-data
python -m scripts.import_schedule --input examples/schedule-ingestion.csv --data-dir .local/csv-demo-data --backup-dir .local/csv-demo-backups
python -m scripts.validate_data --data-dir .local/csv-demo-data
```

第一次會匯入範例，第二次執行相同 importer 命令應回傳 `changed: false`，資料與時間戳不變，也不新增備份。重新準備範例時請使用新的目的目錄，避免 `Copy-Item` 將既有目錄多包一層。

正式匯入會直接更新指定資料目錄，無提案或人工核准步驟：

```powershell
$env:SCHEDULE_CSV_URL = '貼上 Publish to Web 的公開 CSV URL'
python -m scripts.import_schedule
python -m scripts.validate_data
python -m scripts.build_site
```

也可使用 `--url URL`，或以 `--input 檔案.csv` 代替下載。程式不自動讀取 `.env`。CLI 只匯入資料，不執行 Git 操作。輸出包含列數、匯入、重複、無效列、資料變更及行程變更統計。

## 去重與更新界線

- 正式 receipt 是 `data/imported_ids.json`；Sheet 的 `pending`／`imported` 不決定是否已處理，也不由 Actions 修改。標為 `invalid` 的列會略過且不寫 receipt，修正後可重試。
- 相同 ID 再次出現一律略過，包含已匯入後在 Sheet 編輯內容的情況。同批同 ID 但內容不同時，整組略過並警告，不依列順序選擇版本。
- 新 ID 以「成員＋日期＋正規化時間」比對正式行程。完全相同的內容只補 receipt；唯一匹配的標題／明確平台／特殊時間狀態變更會更新原事件並保留 Revision。已有多筆同時段事件時略過，不能任選對象。
- 同一來源的多列行程共用貼文紀錄，不會因來源 URL 已出現而略過整張週表。X／Twitter 分享網址會統一並移除追蹤參數。
- MVP 不提供 operation、revision 或 schedule_version 欄位。改時間、取消或整張週表替換須人工確認正式資料；不要靠改已匯入 ID 的內容更新，也不要把新時間以另一個 ID 直接加入後就視為已取代舊行程。
- 不會因 CSV 列被刪除或暫時缺少就刪除既有行程；不會將已取消、延期、直播中、已結束事件改回正常排程。

為相容現有網站資料，Importer 同步維護 `posts.json` 與 `revisions.json`。CSV 未提供來源發文時間，新增來源紀錄的 `published_at` 使用該列 `created_at`，不代表已驗證的原始發文時間。CSV 未提供 confidence，現有必要欄位固定使用 `0.70` 作格式相容值，並非 AI 信心評估；v2.1 直接匯入不套用舊版 REVIEW_ALL／提案策略。新行程的平台未提供或留空時為 `null`；直播網址維持 `null`。

## GitHub Actions 與 Pages

1. 在 Settings → Secrets and variables → Actions → Variables 新增 `SCHEDULE_CSV_URL`，填公開 CSV 網址。不需要 Google Secrets、PAT 或額外 API Key。
2. 確認內建 `GITHUB_TOKEN` 可寫入 repository；分支保護若禁止 bot 直接推送，需由管理者調整允許的自動化寫入方式，流程不繞過保護。
3. Settings → Pages 的 Source 選 GitHub Actions。
4. 推送至 `main` 會自動觸發 **Process ingestion**，也可透過 `workflow_dispatch` 手動執行或 `new_ingestion` dispatch 觸發。定時排程維持台灣時間每小時第 17 分鐘（`cron: '17 * * * *'`、`timezone: 'Asia/Taipei'`），避開整點高峰。只有設定 CSV URL 且位於 main 才執行；定時觸發仍可能因 GitHub 排程負載而延遲或漏跑。

流程依序測試、下載／匯入、資料驗證、網站建置，再檢查暫存差異。只提交 `schedule.json`、`posts.json`、`revisions.json`、`imported_ids.json` 的實際差異；沒有變化則成功結束，不 commit。推送失敗會明確失敗，下次從遠端 main 重新匯入。不要同時部署其他會寫相同正式資料的 importer。

Pages workflow 監聽匯入 workflow 成功完成，支援內建 GITHUB_TOKEN 更新資料的情況；比較匯入前後公開 JSON，沒有公開資料差異就略過部署。網站仍只載入 repository 建置出的 members／schedule；公開 schedule 會附上目前行程的 `sources` 網址對照，避免把 CSV／Discord 來源 ID 誤組成 X 貼文連結。CSV 斷線不影響既有網站。

## 失敗、備份與復原

CSV 下載或語法／標題驗證失敗，不更動正式資料。單筆錯誤不使整個匯入失敗，但需查看警告並修正；無有效新資料時不產生變更。Importer 在記憶體完成合併及關聯驗證後，使用現有檔案鎖、備份與交易日誌，將行程、來源、歷史及 receipt 一起寫入；寫入失敗會回復原始位元組，避免 ID 已記錄但行程未寫入。

備份位於 `.local/backups`，Actions 會上傳為 30 天 artifact。若程序被強制中止留下 `.transaction.json`，先執行：

```sh
python -m scripts.backup_data recover
```

一般備份／還原使用既有 `scripts.backup_data`，會一併處理 imported IDs；還原沒有 receipt 的舊版備份時，會清空 IDs 以便重新匯入。舊 v2 OAuth／posts+changes adapters 與提案程式保留供相容使用，不屬於 v2.1 主流程，Actions 不再呼叫或設定它們；舊版付費 API workflows 仍預設停用。

## 尚待外部設定與驗證

本機測試使用合成 CSV 與網路 mock；實際工作表建立、Publish to Web、ChatGPT 搜尋／圖片理解／寫入、Repository Variable、雲端 Actions 權限與 Pages 部署仍需在實際帳號驗證。本次程式修改不會代為建立外部工作表或排程，也不會自行 commit／push。提示範本見 [chatgpt-task.md](chatgpt-task.md)。
