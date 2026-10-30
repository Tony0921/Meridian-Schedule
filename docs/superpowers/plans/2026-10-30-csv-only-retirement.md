# CSV 單一路徑退役計畫

> **For agentic workers:** 使用 `superpowers:executing-plans` 執行；使用者已要求實作，無需另設核准關卡。

**Goal:** 退役手動 Parser、OpenAI Provider、提案採用及 PR 發佈，保留 CSV、驗證、來源／Revision、備份還原與交易復原。

**Architecture:** `ingestion/schedule_csv.py` 與共用資料模型、Schema、validation、storage 保留。移除剩餘 Parser／提案／GitHub 工具及其專用測試，將共用 storage 測試改為直接操作有效資料副本。

**Tech Stack:** Python 3.11+ 標準函式庫、原生 JavaScript、GitHub Actions。

**Spec:** [現行完整規格](../../../VTuber_Schedule_SPEC_current.md)，加上使用者本輪確認的四項退役範圍；完成後同步更新現況。

## Global Constraints

- 保留前輪未提交修改；不修改正式 `data/`、前端行為及歷史 spec。
- 不新增正式相依套件，不 commit／push／建立 PR，不操作遠端設定或本機 `.env`。
- 保留舊 JSON／CSV 格式相容，包括既有來源、Revision、confidence／origin 等歷史欄位。
- CSV 的驗證、更新、冪等、防碰撞及寫入復原規則保持原樣。

## Review Focus

- 原 storage 測試不能隨提案測試一起刪除，須維持完整快照、鎖、備份完整性及原始位元組回復覆蓋。
- 只安裝 CSV 與共用資料模組的副本仍可匯入、驗證、健康檢查、備份、還原及復原。
- 移除對 Parser fixture 的最後引用後，保留前端／資料驗證需要的 `tests/fixtures/data/`。
- 文件不得留下仍可使用 Provider、提案採用、PR 發佈或 API Key 的現行操作指示。
- 不因退役程式而刪除歷史資料欄位或改動正式行程。

### Task 1: 改寫共用回歸測試

**Files:** `tests/test_storage.py`、`tests/test_schedule_csv.py`、`tests/test_maintenance.py`。

- [x] 先確認現有 Python 全套 143 項通過。
- [x] storage 改直接測試 `write_data_unlocked`，保留備份／Revision、拒絕無效資料、鎖、回復及還原完整性。
- [x] 移除 CSV 測試中專屬舊提案互通的案例；新增 CSV-only 隔離副本完整 CLI 與重跑 no-op 案例。
- [x] 在移除產品檔案前先跑測試，確認共用行為已有獨立覆蓋。

### Task 2: 刪除剩餘選配功能

**Files:** 剩餘 `collector/*.py`；`processor/classify.py`、`extract.py`、`manual.py`、`merge.py`、`openai_provider.py`；`scripts/process_post.py`、`apply_proposal.py`、`publish_proposal.py`；`schemas/changes.schema.json`；`examples/manual-post.json`；專用 Parser／merge／發佈測試與六份 proposal fixtures；`.env.example`。

- [x] 移除 23 份專用檔案，環境範本只留 CSV URL。
- [x] 確認所有現行 import、workflow CLI 及 Schema 引用可解析。
- [x] 執行完整 Python、前端語法／測試、正式資料驗證、健康檢查及建置。

### Task 3: 文件與審查

**Files:** `README.md`、`docs/ingestion.md`、`docs/operations.md`、`docs/project-structure.md`、`VTuber_Schedule_SPEC_current.md`。

- [x] 更新現行能力與退役界線，保留舊 spec／前輪計畫作歷史紀錄。
- [x] 核對全部現存檔案的 tree 註釋、連結、範例及最終 diff。
- [x] 執行獨立審查並處理重要問題，記錄實際驗證與未驗證的雲端範圍。
