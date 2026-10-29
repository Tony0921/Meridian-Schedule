# V2.2 公開 CSV 匯入操作手冊

依據 [spec v2.2](../VTuber_Schedule_SPEC_v2_2.md)，主要流程為：ChatGPT 搜尋／解析 → Google Sheet `schedule_ingestion` → Publish to Web CSV → GitHub Actions → repository JSON → GitHub Pages。GitHub 端只執行公開 HTTP GET，不使用 Google Sheets API、Service Account、OAuth、X API 或 OpenAI API，也不回寫 Sheet。正式資料仍在 `data/`，網站不直接查詢 Sheet。

## 建立工作表與公開 CSV

1. 建立 Google Sheet，新增單一工作表 `schedule_ingestion`。
2. 複製 `examples/schedule-ingestion.csv` 的標題列；範例成員是虛構測試資料，上線請使用正式 `data/members.json` 中已啟用的 ID。
3. 將 ID、日期、時間、網址與時間戳欄位設為純文字，避免試算表自行轉換格式。每個行程一列；同篇週表可有多列。
4. 在「檔案 → 共用 → 發布到網路」選擇該工作表與 CSV，複製產生的公開網址。一般的編輯／共用網址或登入頁不是 CSV endpoint。
5. 如需自動帶入 `group`，建立隱藏工作表 `members_lookup`：A:D 分別放入 `members.json` 的 `id`、`group`、`group_name`、`enabled`，D 欄使用布林值。E1 填 `enabled_member_id`，E2 填 `=IFNA(FILTER(A2:A,A2:A<>"",D2:D=TRUE),"")`。將主表 B2:B1000 的資料驗證設為來自 `members_lookup!E2:E100` 的下拉選單；成員資料異動時同步更新對照表 A:D。
6. 主表依序為 `id,member_id,group,date,time,title,platform,source_url,created_at`。清空 C2:C1000 的既有值，在 C2 填入 `=ARRAYFORMULA(IF(TRIM(B2:B)="","",IFNA(VLOOKUP(TRIM(B2:B),members_lookup!A2:B,2,FALSE),"")))`。C 欄由公式自動計算，不提供手動下拉；新增行程分別寫入 A:B 與 D:I，保留 C2 公式及其展開範圍。
7. 將整個 C 欄設為「保護工作表和範圍」，選擇「限制可編輯這個範圍的使用者」並只保留維護帳號，避免其他編輯者覆寫公式或結果；不要只設定編輯警告。保護範圍不會阻止公式依 B 欄更新，但 Google Sheets 的擁有者仍可修改受保護範圍。

建議欄位（順序可調整）：

```csv
id,member_id,group,date,time,title,platform,source_url,created_at
miri_aetris_20261028_01,miri_aetris,aetris,2026-10-28,20:00,雜談直播,youtube,https://example.com/public-source,2026-10-28T02:10:00+08:00
```

| 欄位 | 規則 |
| --- | --- |
| `id` | 必填，直接作為正式事件 ID；建議 `{member_id}_{YYYYMMDD}_{index}`，同一事件改日期、時間、標題、平台或來源仍沿用原 ID |
| `member_id` | 必須是 `members.json` 中已啟用的成員 |
| `group` | 選填團體識別碼，由公式依 `member_id` 自動帶入；僅供 Sheet 查閱，匯入時忽略欄值 |
| `date` | 正式值為 `YYYY-MM-DD`；也接受 `YYYY/M/D`、`M/D`、`Oct 28`／`October 28, 2026` |
| `time` | 正式值為 `HH:MM` 或 `tbd`／`day_off`／`unknown`；接受全形冒號、`8:00 PM`、`晚上八點`等格式 |
| `title` | 必填，去除前後空白後不可空白 |
| `platform` | 選填開台平台，可省略整欄；接受 `youtube`、`twitch`、`none`、`unknown`，不區分大小寫；新資料請明確填寫 |
| `source_url` | 必填、無帳密的 HTTP(S) 公開來源，可為 X、Discord 或其他公開來源 |
| `created_at` | 必填，該列初次建立的含時區與秒數 ISO 8601，例如 `2026-10-28T02:10:00+08:00`；後續修正不得重產，匯入時保留事件首次記錄的值 |
| `status` | 選填，可省略整欄；接受空白、`pending`、`imported`、`invalid` |

成員 ID 以 `data/members.json` 為準，Miri 使用 `miri_aetris`。既有行程 ID 與已匯入列 ID 保留原值，不因成員 ID 調整而重編。

`group` 使用 `neon`、`ianvs`、`teraz`、`aetris`、`none`、`collaborators` 等識別碼，不使用 `group_name` 顯示名稱。選取或更換 `member_id` 後會由隱藏的 `members_lookup` 對照表自動帶入；空白或查無 ID 時留空。對照表是 `members.json` 的匯入副本，來源異動後需同步更新。成員分組仍以 `members.json` 為準，Sheet 欄位不會覆寫成員、事件或 Revision。既有七欄／八欄 CSV 仍可使用，僅改動 `group` 不會觸發行程更新。

行程卡片中的成員名稱會依 `x_username` 連到對應的 X 個人頁，並於新分頁開啟；未設定帳號時維持純文字。

`platform` 代表該場直播的平台，須由官方行程文字、圖片或直播連結確認；不要把 X 貼文來源當成開台平台，也不要僅因成員有 YouTube／Twitch 頻道就推定每場的平台。休息或已確認不開台填 `none`；平台無法確認填 `unknown`。CSV 不再接受 `other`。`none` 與 `unknown` 會以不同值保存於正式行程與 Revision；網站以紅色 YouTube、紫色 Twitch、灰色「平台未確認」徽章顯示平台，`none` 或休息日不顯示平台徽章。YouTube／Twitch 徽章分別連到該成員 `youtube`／`twitch` 欄位的頻道並於新分頁開啟；缺少有效網址或平台未確認時維持純文字徽章。舊七欄 CSV 仍可匯入；更新既有行程時，缺欄或空白會保留原本平台。

既有線上工作表新增 `platform` 或 `group` 欄之前，須先部署支援該欄的匯入程式；舊程式會將額外標題視為結構錯誤而中止整批。

官方明確表示時間未定時填 `tbd`／`待定`／`未定`／`時間未定`；休息填 `day_off`／`休息`／`休息日`；已知日期與公開來源，但 AI 無法判定時間或行程狀態時填 `unknown`／`未知`。匯入後三者均使用對應狀態與 `time: null`；網站時間欄分別顯示「時間待定」、「全天」、「未知」，狀態徽章分別為「待定」、「休息」、「未知」。未知狀態不代表休息，也不影響 `platform` 欄位的「平台未確認」。空白時間不會自行推論。所有行程均為台灣時間。CSV `time` 同時承載時間與行程狀態，是過渡設計；v2.2 不新增特殊值，也不加入新的 event_status 欄位。

已移除 `working_day`／`工作日`／`作業日` 輸入；舊 CSV 請改用 `unknown`，否則該列會被略過。既有正式行程與歷史快照的 `working_day` 狀態代碼統一轉為 `unknown`，原始標題、時間戳與來源保留；這是資料格式轉換，不代表來源公告發生異動。

缺少年份時，以首次 `created_at` 換算的台灣日期，在前一年、當年、後一年中選最近的有效日期；不使用執行當天日期。既有事件已記錄建立時間時，優先沿用該值，CSV 後續時間戳變動不會改變短日期的年份。跨年結果因此可以重現。建議生產者一律填完整日期。

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

也可使用 `--url URL`，或以 `--input 檔案.csv` 代替下載。程式不自動讀取 `.env`。CLI 只匯入資料，不執行 Git 操作。輸出包含列數、匯入、重複、無效列、資料變更及行程變更統計；`imported` 包含新增與同 ID 更新，內容相同的既有列與新 ID 完全重複列計為 `duplicates`，需人工確認的列計為 `invalid` 並警告。

## 去重與更新界線

- 正式 receipt 是 `data/imported_ids.json`，代表已見過的 ingestion row／event ID，不是永久鎖定更新。是否新增或更新只看 `schedule.json` 是否存在該 ID；receipt 已存在但事件不存在時，仍走新事件檢查。Sheet 的 `pending`／`imported` 不決定合併，也不由 Actions 修改。標為 `invalid` 的列會略過且不寫 receipt，修正後可重試。
- 相同 ID 可更新 `date`、`time`、`title`、明確填寫的 `platform` 與 `source_url`，包含來源換成另一篇貼文；不同 `member_id` 則拒絕並警告。`id` 與已記錄的 `created_at` 保持不變，`group` 忽略。同批同 ID 但正規化後內容不同時，整組略過並警告，不依列順序選擇版本。
- 所有實際更新保存 Revision 的事件 ID、時間、來源與完整前後快照（含 `source_url`），並保留舊來源紀錄。正常排程異動標為 `changed`，`tbd`／`unknown`／`day_off` 可直接改成確定時間；取消、延期、直播中、已結束事件的一般欄位修正保留其狀態。平台缺欄或空白保留既有值；`none`、`unknown` 是可覆寫的明確值。
- 內容相同時完全 no-op：不更新時間戳、不新增 Revision、不寫檔、不建立備份，也不為了補 receipt 產生變更。僅改 `group`、`pending`／`imported` 或 `created_at` 不會更新事件。
- 新 ID 的「成員＋日期＋正規化時間＋標題＋平台」及特殊時間狀態完全相同時略過，不新增第二筆事件，也不額外記 receipt；來源網址不同不影響此判定。同成員、日期、時間且標題接近（沿用專案 `SequenceMatcher`、忽略大小寫，相似度至少 0.6）時警告並略過，不自行合併。相同時段但標題不同且未達門檻可新增另一場事件；此防護不等於判斷兩個邏輯事件必然相同。
- 同 ID 修改後若與另一筆事件內容明確重複，該列停止更新並警告，其他有效列繼續處理。
- 同一來源的多列行程共用貼文紀錄，不會因來源 URL 已出現而略過整張週表。X／Twitter 分享網址會統一並移除追蹤參數。
- CSV 不提供 operation、revision 或 schedule_version 欄位，也不支援 explicit delete／cancel、整張週表替換或 AI fuzzy auto-merge。修正同一事件必須沿用原 ID，不要另建 ID 企圖取代它。
- 不會因 CSV 列被刪除或暫時缺少就刪除既有行程。

為相容現有網站資料，Importer 同步維護 `posts.json` 與 `revisions.json`。CSV 未提供來源發文時間，新增來源紀錄的 `published_at` 使用該列 `created_at`，不代表已驗證的原始發文時間。CSV 未提供 confidence，新事件使用 `0.70` 作格式相容值，並非 AI 信心評估；既有事件修正保留原本的 confidence、origin 與直播網址。v2.2 直接匯入不套用舊版 REVIEW_ALL／提案策略。新行程的平台未提供或留空時為 `null`；直播網址為 `null`。

事件 schema 新增選填 `source_url` 與 `created_at`，既有 JSON 與歷史仍可驗證，不會批次改寫正式資料或 ID。舊事件首次實際 CSV 更新時，`created_at` 取該列的首次建立時間，Revision 的 `before.source_url` 從原 `posts.json` 補入。保留的手動提案流程更新 CSV 事件時，也會同步目前來源 URL 與 Revision 快照。**v2.1 曾依內容產生正式 ID，可能與 Sheet ID 不同；更新這些事件前，先確認並使用 `schedule.json` 的正式 ID。** receipt 是字串清單，無法可靠反推舊 ID 的對應，因此不自動重新命名或依 natural key 遷移。若新 Sheet ID 與既有事件完全重複則略過，疑似重複則警告。

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

一般備份／還原使用既有 `scripts.backup_data`，會一併處理 imported IDs；還原沒有 receipt 的舊版備份時，會清空 IDs 以便重新匯入。舊 v2 OAuth／posts+changes adapters 與提案程式保留供相容使用，不屬於 v2.2 主流程，Actions 不再呼叫或設定它們；舊版付費 API workflows 仍預設停用。

## 尚待外部設定與驗證

本機測試使用合成 CSV 與網路 mock；實際工作表建立、Publish to Web、ChatGPT 搜尋／圖片理解／寫入、Repository Variable、雲端 Actions 權限與 Pages 部署仍需在實際帳號驗證。本次程式修改不會代為建立外部工作表或排程，也不會自行 commit／push。提示範本見 [chatgpt-task.md](chatgpt-task.md)。
