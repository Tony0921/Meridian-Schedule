# 自動化與 Collector 操作手冊

v2.1 主要流程請先閱讀 [公開 CSV 匯入操作手冊](ingestion.md)，只需 `SCHEDULE_CSV_URL`，不需要 Google API 認證、Pi 或人工提案。本頁保留既有採用、備份、復原與**選配 v1 API Pipeline** 的操作方式；`OPENAI_API_KEY`、`X_API_TOKEN` 只適用於下列 API 路徑。`Process X post` 與 `Reconcile X posts` workflows 預設停用，需明確設定 repository Variable `ENABLE_LEGACY_API_PIPELINE=true`；v2.1 不呼叫這些 API。

## 實作進度與驗收界線

| Phase | 已實作 | 仍需外部驗證 |
| --- | --- | --- |
| 1 | 靜態網站、今日／本週／成員篩選、資料驗證 | Pages 啟用與雲端部署、手機實機 |
| 2 | 手動文字／圖片、AI Provider、Schema、merge、Revision | 真實貼文與圖片的辨識品質 |
| 3 | 外部／手動 dispatch、提案採用、PR、可選自動提交、推送衝突重試 | Secrets、PR 權限、分支保護與 workflow 實跑 |
| 4 | 可替換來源、X API adapter、JSONL 重播、SQLite 去重、dispatch | X 權限／穩定性／費用、Pi 持續運行 |
| 5 | 台灣時間每日補漏、checkpoint、重試與人工重送 | 真實斷線／rate limit、GitHub 排程延遲 |
| 6 | 信心門檻、結構化日誌、健康檢查、備份、交易復原、多成員設定 | 告警通知設定、長時間運行、外部備援 |

本機可完成的程式已提供；未以 mock 通過推定真實 API 可用，也未將 Spec 的全部驗收核取方塊改為完成。已使用獨立 Chrome 測試環境驗證 375px／1280px 的今日、本週、成員篩選、來源連結、狀態與載入失敗畫面；仍未驗證手機實機。

## GitHub 設定

正式分支預設 `main`，workflow 必須位於 repository 的預設分支。若改分支，須同步更新兩份 workflow 的 checkout／branch 條件及發布腳本的 base。

在 Actions Secrets 設定 `OPENAI_API_KEY`、`X_API_TOKEN`；Variables 設定 `OPENAI_MODEL`，指定支援圖片與 JSON mode 且帳號可使用的模型。可選的 Variables：

| 名稱 | 預設 | 用途 |
| --- | --- | --- |
| `REVIEW_ALL` | `true` | 所有行程變更建立 PR |
| `AUTO_MERGE_CONFIDENCE` | `0.95` | 明確設為 `REVIEW_ALL=false` 後的自動採用門檻 |
| `PR_CONFIDENCE` | `0.70` | 低於此值只記錄 `manual_review`，不修改行程 |

自動採用只會在 validation 通過後提交，不會繞過分支保護；推送被拒絕時 workflow 失敗。低信心與無關貼文只提交來源紀錄，行程維持原樣。所有正式資料寫入仍經 deterministic merge。

在 **Settings → Actions → General** 確認允許 Actions 建立 Pull Request。預設使用 workflow 的 `GITHUB_TOKEN`；亦可設定 `SCHEDULE_BOT_TOKEN`，需有 Contents write 與 Pull requests write 權限。Pi 的 Token 只需目標 repository 的 Contents write 以送出 dispatch。權限依 [GitHub dispatch API](https://docs.github.com/en/rest/repos/repos#create-a-repository-dispatch-event) 與 [PR API](https://docs.github.com/en/rest/pulls/pulls#create-a-pull-request)。

內建 `GITHUB_TOKEN` 可觸發 `repository_dispatch`；由它建立的 PR，其檢查可能需要有寫入權限的人在 PR 上核准執行。若使用 App／PAT，則可依該 Token 的權限自動觸發。參見 [GitHub workflow 觸發規則](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow)。

在 **Settings → Pages** 啟用 Pages 並選 **GitHub Actions**。`configure-pages` 只確認設定，不自行建立 Pages 網站，也不改 repository 可見性。先前的 404 仍需由這個設定排除；private repository 是否可啟用，請以帳號實際設定畫面為準。

在 Actions 手動執行 **Process X post**，輸入 `source=x`、真實 `post_id` 及 `members.json` 的 `member_id`。外部 dispatch 的 `client_payload` 也僅接受這三個欄位；不接受 AI Provider、模型、程式路徑或其他命令設定。Processor 會重新取得完整貼文並驗證實際作者，下載 X 圖片後才呼叫 AI。

每次處理最多初次嘗試加 3 次重試，間隔 1、5、30 分鐘；超過上限保存 `manual_review` 狀態。貼文原文、提案及狀態保存在 `post-<run_id>` artifact（30 天），不發布至 Pages。讀取憑證等設定錯誤也會留下 status；workflow 被取消或 artifact 上傳失敗時，仍須查看 Actions 日誌。修正問題後可 rerun failed job；尚未提交的來源會重新處理，已提交的貼文則略過。

## Collector 與來源

需求：Python 3.11+。程式不自動讀 `.env`；可參考 `.env.example`，由 shell 或 systemd `EnvironmentFile` 載入，勿將實際憑證提交。

```sh
python -m collector.main setup-rules
python -m collector.main listen
```

`setup-rules` 會實際新增啟用成員的 `from:username -is:retweet` 規則，略過相同規則，不刪除既有規則。必須先確認 [X Filtered Stream](https://docs.x.com/x-api/posts/filtered-stream/introduction) 的權限與費用。變更成員後重新設定規則；停用的舊規則可由管理者移除，Collector 仍會過濾停用／未列出的作者。

預設來源為 `x-api`，`X_API_TOKEN` 用作 Bearer Token；帳號需同時可讀取 Stream、單篇貼文與 user timeline。串流中斷採退避重連，空白 keepalive 更新來源心跳。單篇資料錯誤不終止事件接收；補漏會再次發現其 id。原貼文的照片下載僅允許 HTTPS `pbs.twimg.com`、禁止重新導向，最多 8 張、單張 10 MiB、總計 20 MiB。

來源介面維持 `PostSource.listen/fetch_recent/fetch_post`。自訂來源以 `--source module:factory` 或 `POST_SOURCE` 指定，factory 接收 `members`、`timeout`；`fetch_post` 回傳手動 Parser 的 `{post, post_text, images}`。來源實作由本機管理者設定，不從 dispatch 或 AI 回應載入。YouTube／Twitch adapter 尚未提供。

離線 JSONL 每行是一個手動輸入 JSON 物件；設定 `POSTS_JSONL` 為路徑後，可用 `--source jsonl`。`listen --once` 可重播整份檔案；搭配真實 `GITHUB_TOKEN` 仍會送出 dispatch，純離線驗證請執行測試。壞行會略過；重複 id 由 SQLite 去重。

## 去重、補漏與重試

SQLite 預設 `.local/collector.db`，以 `(source, post_id)` 為唯一鍵。不同程序使用 transaction claim 與 120 秒 lease；API 成功回覆後標記 `dispatched`。這代表 GitHub 已接受通知，不代表 AI 或 PR 已成功。

網路上無法在「GitHub 已收到但本機尚未寫入狀態」的中斷點保證 exactly once。恢復後允許重送，Processor 會根據正式 posts 與既有 PR 做冪等檢查。正常已送出項目不重送；同一貼文不得改屬其他成員。

Pi daemon 預設台灣時間 06:00、18:00 補漏，可用 `--reconcile-hours 6,18` 或 `RECONCILE_HOURS` 設定。啟動時補執行最近時段，預設查看過去 48 小時，可用 `--lookback-hours` 調整；與上次成功 checkpoint 重疊 1 小時。完整分頁成功後才前進 checkpoint；失敗至少隔 5 分鐘再掃描。

dispatch 失敗會在 1、5、30 分鐘後重試；HTTP `Retry-After` 更長時等待該值。初次加 3 次失敗後標記 `manual_review`，不再自動送出。修正問題後：

```sh
python -m collector.main retry
python -m collector.main requeue --post-id POST_ID
python -m collector.main reconcile --lookback-hours 72
```

`retry` 只取已到重試時間的項目；`requeue` 只允許人工重送 failed／manual_review，不重送 dispatched。資料中的低信心 `manual_review` 需要人工確認來源並整理正確資料；直接 rerun 不會覆寫已記錄貼文。

**Reconcile X posts** workflow 以 UTC `22:00/10:00` 對應台灣 `06:00/18:00`，共用 Collector 與 dispatch，沒有第二套 Processor。GitHub 排程不是準時保證；SQLite cache 僅減少重複通知，cache 遺失時仍靠 Processor 去重。此一次性 job 的失敗 outbox 會保存至 cache／artifact，精確的分鐘級持續重試由 Pi daemon 負責，也可手動執行 retry。建議選擇 Pi 排程或 GitHub 排程作主要補漏，避免重複 API 費用。

## 提案採用、備份與復原

`process_post` 只輸出提案；採用端重新驗證原始變更描述，不信任候選 schedule、decision 或成員快照。人工採用須 `--approve`，且比對基準資料指紋；資料已變更就拒絕，應重新產生提案。

```sh
python -m scripts.apply_proposal .local/proposal.json --approve
python -m scripts.backup_data backup
python -m scripts.backup_data restore --snapshot .local/backups/SNAPSHOT.json
python -m scripts.backup_data recover
```

每次採用、CSV 匯入或 restore 前都會將四份正式資料、存在的 `imported_ids.json` 與校驗值寫入 `.local/backups/`，restore 也保留還原前的備份。檔案鎖防止並行讀寫；JSON 與匯入 ID 透過交易日誌連動寫入，失敗時回復原始位元組。還原不含匯入 ID 的舊版備份時會清空 receipt，避免漏掉需要重匯的行程。程序被強制中止時可能留下 `.transaction.json`；讀取／建置會拒絕不完整交易，先執行 `recover` 回復再重跑。這是程序中斷復原，不宣稱跨檔案瞬間原子性或電源故障下的磁碟耐久保證。

發布腳本以最新 main 建立隔離 checkout，重新 merge，再提交資料。預設以固定貼文分支建立 PR；已存在的 PR 直接回報。不 force-push；自動提交遇到推送衝突時最多取最新資料重算 3 次。若提案要修改的同一欄位已被更新，則停止，避免較舊公告覆蓋較新異動。比對歧義或權限錯誤也會停止並保留 artifact。隔離 checkout 的交易備份只保留至該次發布結束，持續保留的版本在 Git 歷史及每日備份 artifact。此腳本會實際 commit／push／建立 PR，僅在設定好 Token 且準備發布時執行。

**Backup schedule data** workflow 每日台灣 03:30 驗證資料並上傳備份 artifact（90 天）。本機備份不自動刪除；請依儲存空間保留需要的快照。Git 歷史與同帳號 artifact 不是外部備援；跨帳號／離線備份需另行安排。

## Pi 與健康檢查

`examples/collector.service`、`collector-health.service`、`collector-health.timer` 是 systemd 範本。部署時調整使用者、Python 路徑與 repository 路徑；先建立可寫入的 `.local`，並讓服務使用者能讀取 repository 與建立 `data/.update.lock`。憑證放 `/etc/meridian-schedule.env`，限制可讀取的使用者。

Collector 主服務只需要讀取成員 JSON 與寫 SQLite；`ProtectSystem=strict` 僅開放 `.local` 寫入。健康檢查服務另需資料鎖檔的寫入權限。主服務自動重啟，daemon 自行執行補漏與 dispatch 重試，不需要另外安裝補漏 timer。

```sh
python -m scripts.health_check --db .local/collector.db
```

健康檢查會檢查資料關聯、Collector／來源心跳、成員補漏時間與待人工處理項目；不健康回傳非零碼及 JSON 原因。預設心跳上限 300 秒，可用 `--max-heartbeat-age` 調整。health timer 每 5 分鐘執行，失敗可在 systemd journal 查看；通知設定依 GitHub／systemd 運行環境處理，沒有自動寄信或第三方告警。

新增成員只需編輯 `members.json`、驗證並重新部署 Collector／規則；目前不會自動重新載入 daemon 的成員名單。長時間離線超過 lookback 時，請加大補漏範圍；X 自身的 timeline 歷史限制仍適用。

## 本次變更檔案與驗證

| 檔案 | 用途 |
| --- | --- |
| `collector/events.py` | 驗證最小 dispatch payload 與識別碼 |
| `collector/http.py` | HTTP timeout、禁止重新導向、rate limit 與不含機密的錯誤 |
| `collector/github_dispatch.py` | GitHub dispatch、查找與建立 PR |
| `collector/sources.py` | X API 與 JSONL adapter，可替換 factory |
| `collector/dedupe.py` | SQLite outbox、去重、lease、重試與人工重送 |
| `collector/reconcile.py` | 可設定台灣時段、分頁 checkpoint 與重疊補漏 |
| `collector/main.py` | 持續接收、背景重連與共用 CLI |
| `processor/storage.py` | 檔案鎖、指紋、備份、連動寫入與復原 |
| `processor/media.py` | X 圖片下載與限制 |
| `scripts/process_post.py` | 提案基準、信心設定、完整失敗日誌與共用存取 |
| `scripts/apply_proposal.py` | 審核採用、過期與同欄位衝突保護 |
| `scripts/process_event.py` | 取得完整貼文、作者驗證、解析、重試與 artifact 狀態 |
| `scripts/publish_proposal.py` | 隔離 checkout、PR／自動提交與推送衝突重算 |
| `scripts/backup_data.py` | 備份、restore、recover CLI |
| `scripts/health_check.py` | 資料、心跳、補漏與佇列檢查 |
| `scripts/build_site.py`、`scripts/validate_data.py` | 共用鎖定資料讀取，拒絕中斷交易 |
| `.github/workflows/process-post.yml` | 外部／手動貼文事件與發布流程 |
| `.github/workflows/reconcile.yml` | 每日補漏與 SQLite 狀態保存 |
| `.github/workflows/backup-data.yml` | 每日資料健康檢查與備份 |
| `.github/workflows/deploy-pages.yml` | Pages 設定檢查及 Processor 完成後部署 |
| `examples/collector.service` | Pi 長期運行範本 |
| `examples/collector-health.service`、`collector-health.timer` | Pi 健康檢查範本 |
| `.env.example`、`.gitignore` | 憑證設定範本、忽略鎖與交易狀態檔 |
| `site/index.html` | 移除會隨自動更新失效的固定週表提示 |
| `tests/test_storage.py` | 採用、過期、鎖、回復與備份測試 |
| `tests/test_collector.py` | 來源、HTTP、去重、補漏與重試測試 |
| `tests/test_automation.py` | Processor、PR、衝突、圖片與健康檢查測試 |
| `README.md`、`docs/operations.md` | 現況、設定、操作、驗收界線與復原說明 |

2026/10/16 本機驗證：`python -m unittest discover -s tests -v` 共 92 項通過；`node --check site/app.js`、`node --test tests/test_site.cjs`（6 項）、`python -m scripts.validate_data`、`python -m scripts.build_site`、`python -m scripts.health_check` 均通過。Python 使用 Codex 內建執行檔，測試因 Windows 沙箱暫存目錄權限而在核准後於沙箱外執行。另以既有開發環境的 YAML parser 解析 5 份 workflow，並以既有 Playwright／獨立無介面 Chrome 完成上述 UI 檢查；沒有加入正式環境依賴。GitHub Actions expression、權限與雲端行為仍須上線實測。這些驗證沒有實際 commit、push、建立 PR 或呼叫真實 X／AI API。
