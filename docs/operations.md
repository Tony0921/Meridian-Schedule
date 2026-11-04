# CSV 維運、備份與復原操作手冊

現行自動流程為公開 CSV → repository JSON → GitHub Pages，設定見 [匯入手冊](ingestion.md)。

## CSV 與 GitHub 設定

1. 設定 Repository Variable `SCHEDULE_CSV_URL` 為工作表 Publish to Web 的公開 CSV URL。
2. 確認內建 `GITHUB_TOKEN` 可以依分支保護規則寫入資料；Pages Source 選 GitHub Actions。
3. 執行 Process ingestion，檢查單列警告、資料差異與 Deploy GitHub Pages 的結果。

CSV CLI 不自行 commit／push；workflow 有實際差異才提交。外部搜尋或 Sheet 失效時保留既有網站資料。GitHub 排程可能延遲，不代表每小時準時更新。

## 資料健康檢查

```sh
python -m scripts.validate_data
python -m scripts.health_check
```

兩者都會讀取並驗證正式資料；健康檢查另檢查來源中 `manual_review` 或 `failed` 的筆數。正常回傳 `result=healthy` 及結束碼 0；資料損壞或待人工來源回傳 `result=unhealthy`、原因及非零碼。

可用 `--data-dir` 指定資料目錄。ChatGPT 搜尋與外部工具權限須在排程環境驗證。

## 備份、還原與中斷復原

```sh
python -m scripts.backup_data backup
python -m scripts.backup_data restore --snapshot .local/backups/SNAPSHOT.json
python -m scripts.backup_data recover
```

- `backup` 保存四份正式資料、存在的 `imported_ids.json`、校驗值與原始位元組，預設寫至 `.local/backups/`。
- `restore` 會實際修改正式資料；先確認並替換 `SNAPSHOT.json`，還原前會備份目前版本。沒有 receipt 的舊快照會還原為空 ID 清單，讓資料可重新匯入；JSON 會重新序列化。
- `recover` 處理程序中斷留下的 `.transaction.json`，回復交易前的原始位元組；不存在交易時安全結束。出現未完成交易時先復原，再重新匯入或建置。
- 檔案鎖防止並行寫入。寫入與 receipt 失敗連動回復；此機制不保證跨檔瞬間原子性或斷電耐久。

備份、健康檢查與 CSV 匯入只依賴共用資料核心。CSV no-op 不寫檔或建立備份；請勿同時部署不同程序覆寫同一正式資料。

CSV workflow 備份 artifact 保存 30 天；Backup schedule data 每日台灣 03:30 驗證並備份，artifact 保存 90 天。本機備份不自動刪除。Git 歷史及同帳號 artifact 不等於外部備援，離線／跨帳號備份與通知管道需另行安排。

## CSV 修正與人工處理

需要補入或修正資料時，使用相同 CSV 欄位，沿用既有事件 ID，再執行匯入／驗證／建置。工作表故障時可使用本機 `--input`；完整隔離範例見 [匯入手冊](ingestion.md)。

人工補入時先核對官方來源，再將貼文或圖片中的行程整理成 CSV。

既有 JSON 的 `confidence`、`origin`、歷史狀態與來源仍保留，確保驗證、瀏覽及舊備份可用。健康檢查若回報 `manual_review` 或 `failed` 來源，請人工查核來源紀錄。

## 舊部署清理

若曾在其他機器部署舊流程，請在該機器停用對應的 systemd service／timer。遠端 Secrets、Variables 與授權憑證由管理者依實際使用情況清理。
