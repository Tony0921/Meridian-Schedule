# 舊自動流程退役實作計畫

> **For agentic workers:** 使用 `superpowers:executing-plans` 依序執行；使用者已明確要求實作，不另設計畫核准關卡。

**Goal:** 解除維運命令的舊模組依賴，退役 OAuth Queue、X／AI API 自動處理及 Pi／RSS 補漏，維持 CSV 與手動提案功能。

**Architecture:** CSV、共用資料模型及 storage 保持原樣。備份與健康檢查獨立於 Parser／Queue；手動 Parser、採用及 PR 發佈保留，共用 GitHub／HTTP 工具暫留原路徑以避免額外搬動。

**Tech Stack:** Python 3.11+ 標準函式庫、原生 JavaScript、GitHub Actions。

**Spec:** [現行完整規格](../../../VTuber_Schedule_SPEC_current.md)，加上使用者本輪確認的退役範圍；完成後同步修正規格中的現況。

## Global Constraints

- 使用繁體中文；保留既有未提交文件變更，不修改正式資料與前端行為。
- 不新增正式環境相依套件，不自行 commit、push、rebase 或建立 PR。
- 保留手動文字／圖片 Parser、提案採用、信心策略與手動 PR 發佈。
- 不連線呼叫真實 X／AI／Google／GitHub 寫入 API，不修改 `.env` 或遠端設定。
- 保留來源、Revision、receipt、鎖、備份、還原及中斷交易復原。

## Review Focus

- 沒有舊 Parser／Collector／Queue 時，備份、還原及健康檢查仍能執行。
- 舊 Observation 提案必須明確拒絕，避免移除來源政策後被當成一般手動提案採用。
- 健康檢查仍能回報資料損壞與待人工處理來源，不因刪除外部監控而失去基本檢查。
- CSV 新舊格式、重跑 no-op、完整歷史與交易復原不能退化。
- 保留手動提案發佈所需的 GitHub／HTTP 工具與測試，移除自動 dispatch 入口。

### Task 1: 解除維運與手動提案的舊依賴

**Files:** `scripts/backup_data.py`、`scripts/health_check.py`、`scripts/apply_proposal.py`；新增 `tests/test_maintenance.py`，修改 `tests/test_storage.py`。

**Interfaces:** 維持 backup/restore/recover CLI 與健康檢查的 JSON 結果；健康檢查只接受資料目錄。手動提案採用拒絕含 `observation` 的舊 Queue bundle。

- [x] 在缺少舊模組的隔離副本執行備份／還原／復原與健康檢查，先確認失敗。
- [x] 增加有效舊 Observation 被拒絕且資料不變的案例，先確認失敗。
- [x] 備份、健康檢查自行取得根目錄；移除舊狀態檢查及 Queue 正規化依賴。
- [x] 執行相關測試，確認上述案例及既有 storage 行為通過。

### Task 2: 退役自動流程並保留手動能力

**Files:** 移除舊 workflows、Collector 蒐集／補漏模組、Queue 模組／Schema、相關 CLI、範本與專用測試；整理 `tests/test_automation.py`、`collector/github_dispatch.py`、套件註釋、`scripts/process_post.py`、`.env.example`。

**Interfaces:** `scripts.import_schedule`、手動 Parser／提案及 PR 發佈介面保留；Pages 僅銜接 CSV 匯入 workflow。`collector` 暫留純 GitHub／HTTP／識別驗證工具。

- [x] 移除 API 自動處理、OAuth Queue、Pi／RSS 補漏及其專用範本／測試。
- [x] 保留共用 HTTP 安全／PR 發佈測試，移除手動 Parser 中已退役的圖片下載分支。
- [x] 移除 Pages 的舊 workflow 銜接及 `.env.example` 的 X／RSS 設定。
- [x] 執行完整 Python 測試及前端測試；靜態檢查無殘留匯入或可執行入口。

### Task 3: 同步文件與完成驗證

**Files:** `README.md`、`docs/operations.md`、`docs/ingestion.md`、`docs/project-structure.md`、`VTuber_Schedule_SPEC_current.md`。

- [x] 更新現行能力、退役界線、維運命令及檔案樹；歷史版本規格保留原樣。
- [x] 執行 Python 全套、Node 語法／測試、正式資料驗證、靜態建置。
- [x] 檢查 Markdown 連結、目錄樹覆蓋、正式資料未變及最終 diff。
- [x] 使用新上下文 reviewer 審查未提交差異，修正重要問題並完成相關驗證。
