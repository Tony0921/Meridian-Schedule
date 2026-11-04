# ChatGPT 排程任務設定

1. 確認 [排程規則](schedule-rules.md) 已合併至 GitHub `main`。官方 X 帳號由 [成員設定](../data/members.json) 維護。
2. 複製下方提示，填入測試用 Google Sheet 的編輯連結。手動驗證 GitHub 規則讀取、X 貼文與圖片讀取、新增、同 ID 修正、寫後回讀及重跑去重。另用無法讀取的規則路徑確認任務會停止寫入。
3. 測試完成後，換成正式 Sheet 的編輯連結，將提示設到每小時執行的任務，並在實際執行環境驗證權限。需要調整判定時，更新規則文件並合併至 `main`，下一次任務即讀取新版。Sheet 與公開 CSV 設定見 [匯入操作手冊](ingestion.md)。

## 任務提示

```text
執行 Meridian Schedule VTuber 週表同步。

GitHub 儲存庫：Tony0921/Meridian-Schedule
分支：main
規則文件：docs/schedule-rules.md
Google Sheet：<試算表編輯連結>
工作表：schedule_ingestion

1. 每次執行先從 GitHub 讀取 main 最新版的規則文件，只採用本次讀取的內容。無法取得或確認規則完整且為最新版時，停止本次寫入並回報。
2. 依規則讀取最新正式資料及現有 Sheet，從官方 X 貼文與週表圖片確認行程。
3. 依規則判定、去重並驗證，只將確認可新增或可更新的資料寫入指定工作表。寫入後依規則回讀確認。
4. 依規則處理資料不足、存取失敗及寫入結果不明的情況，並回報需要處理的事項。
```
