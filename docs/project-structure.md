# 專案檔案結構

整理日期：2026-10-30。主樹列出版本控制中的檔案及目前的文件草稿，每份檔案後方以 `#` 簡述用途；本機設定、Git 內部資料、暫存及建置產物另列於下方。

現行只保留：外部 ChatGPT／人工 → Google Sheet 或本機 CSV → 匯入與驗證 → 正式 JSON／來源／Revision → GitHub Pages，以及資料健康檢查、備份、還原與交易復原。Parser／Provider、提案採用／PR、OAuth Queue、API 自動管線及 Pi／RSS 都已退役；舊 spec／計畫僅作歷史紀錄。

## 原始碼、正式資料與文件

```text
Meridian-Schedule/
├── .env.example                                 # 環境變數範本，不含實際憑證
├── .gitignore                                   # 排除機密、本機狀態與建置產物
├── LICENSE                                      # MIT 授權條款
├── pyproject.toml                               # Python 版本、專案版本與相依設定
├── README.md                                    # 專案入口、執行方式與部署說明
├── VTuber_Schedule_SPEC.md                      # 第一版完整規格與初始架構
├── VTuber_Schedule_SPEC_current.md              # 整合歷次修訂的現行完整規格
├── VTuber_Schedule_SPEC_v2.md                   # v2 外部 AI 與 Sheet Queue 設計
├── VTuber_Schedule_SPEC_v2_1.md                 # v2.1 公開 CSV 匯入規格
├── VTuber_Schedule_SPEC_v2_2.md                 # v2.2 穩定事件 ID 與更新規則
├── VTuber_Schedule_SPEC_v2_3.md                 # v2.3 時間與事件狀態分欄規格
├── .github/                                     # GitHub 自動化設定
│   └── workflows/                               # Actions 工作流程
│       ├── backup-data.yml                      # 定期驗證資料並上傳備份
│       ├── ci.yml                               # 測試、資料驗證與建置檢查
│       ├── deploy-pages.yml                     # 建置並部署 GitHub Pages
│       └── process-ingestion.yml                # 主流程：CSV 匯入及有差異才提交
├── data/                                        # 正式資料，以這裡的 JSON 為準
│   ├── imported_ids.json                        # 已匯入事件 ID 紀錄，仍允許更新
│   ├── members.json                             # 成員、團體、頻道與啟用設定
│   ├── posts.json                               # 來源公告、網址與處理紀錄
│   ├── revisions.json                           # 事件修改前後的完整歷史快照
│   └── schedule.json                            # 正式行程、狀態與更新時間
├── docs/                                        # 規格以外的操作與導覽文件
│   ├── superpowers/                             # 實作計畫紀錄
│   │   └── plans/                               # 已確認工作的實作步驟與驗證範圍
│   │       ├── 2026-10-30-csv-only-retirement.md # 本輪 Parser／Provider／提案／PR 退役計畫
│   │       └── 2026-10-30-retire-legacy-pipelines.md # 第一階段自動流程退役紀錄，手動功能後續也已退役
│   ├── chatgpt-task.md                          # 外部 ChatGPT 搜尋與 Sheet 寫入提示
│   ├── ingestion.md                             # 公開 CSV 設定、匯入及遷移手冊
│   ├── operations.md                            # CSV 維運、備份、還原與交易復原
│   └── project-structure.md                     # 本文件：檔案目錄樹與用途
├── examples/                                    # CSV 輸入範例
│   └── schedule-ingestion.csv                   # 主流程：十欄 CSV 離線範例
├── ingestion/                                   # 公開 CSV 行程匯入
│   ├── __init__.py                              # Python 套件入口
│   └── schedule_csv.py                          # 主流程：CSV 驗證、正規化與 ID 合併
├── processor/                                   # 共用資料模型、驗證與 storage 核心
│   ├── __init__.py                              # Python 套件入口
│   ├── models.py                                # Member／Event 資料模型
│   ├── schemas.py                               # Schema 載入、JSON 讀取與格式驗證
│   ├── storage.py                               # 共用檔案鎖、備份、交易與中斷復原
│   └── validate.py                              # 成員、行程、來源與歷史關聯驗證
├── schemas/                                     # 正式資料及 CSV 正規化列契約
│   ├── imported_ids.schema.json                 # CSV 匯入 ID 紀錄格式
│   ├── members.schema.json                      # 成員與團體設定格式
│   ├── posts.schema.json                        # 來源公告與處理紀錄格式
│   ├── revisions.schema.json                    # 事件歷史紀錄格式
│   ├── schedule.schema.json                     # 正式行程與事件格式
│   └── schedule_ingestion.schema.json           # CSV 正規化後的單列格式
├── scripts/                                     # 可用 python -m 執行的命令
│   ├── __init__.py                              # Python 套件入口
│   ├── backup_data.py                           # 備份、還原與交易中斷復原 CLI
│   ├── build_site.py                            # 驗證資料並產生 dist 靜態網站
│   ├── health_check.py                          # 獨立的正式資料與待人工來源健康檢查
│   ├── import_schedule.py                       # 主流程：公開／本機 CSV 匯入 CLI
│   └── validate_data.py                         # 正式 JSON Schema 與關聯驗證 CLI
├── site/                                        # 網站原始碼，使用原生前端技術
│   ├── app.js                                   # 行程載入、顯示、排序與條件篩選
│   ├── index.html                               # 頁面骨架、控制項與載入入口
│   ├── style.css                                # 版面、色系、徽章與手機樣式
│   └── theme.js                                 # 深淺色切換及瀏覽器偏好保存
└── tests/                                       # Python／JavaScript 測試
    ├── fixtures/                                # 測試專用虛構資料
    │   └── data/                                # 測試專用資料基準，與正式 data 分離
    │       ├── members.json                     # 虛構成員設定
    │       ├── posts.json                       # 虛構來源公告紀錄
    │       ├── revisions.json                   # 初始空歷史紀錄
    │       └── schedule.json                    # 虛構行程與狀態資料
    ├── test_maintenance.py                      # 只含 CSV／資料核心模組的 CLI 與 no-op 測試
    ├── test_schedule_csv.py                     # CSV、穩定 ID、狀態與冪等匯入測試
    ├── test_site.cjs                            # 前端日期、篩選、連結與色系測試
    ├── test_storage.py                          # 直接驗證寫入、Revision、鎖、備份與復原
    └── test_validate.py                         # Schema 與跨檔關聯驗證測試
```

## 本機檔案與建置產物

以下項目不納入版本控制；內容依本機設定及執行結果而異，因此不展開 `.git/`、`.local/` 的動態檔案。

```text
Meridian-Schedule/
├── .env                                 # 本機環境設定，可能含機密，不提交
├── .git/                                # Git 版本資料與儲存庫設定
├── .local/                              # 備份與本機執行紀錄
└── dist/                                # build_site 產生的可部署靜態網站
    ├── .nojekyll                        # GitHub Pages 略過 Jekyll 處理
    ├── app.js                           # 從 site 複製的前端程式
    ├── index.html                       # 從 site 複製的網頁入口
    ├── style.css                        # 從 site 複製的樣式
    ├── theme.js                         # 從 site 複製的色系程式
    └── data/                            # 網站實際讀取的公開資料
        ├── members.json                 # 建置時複製的成員資料
        └── schedule.json                # 行程及建置產生的來源 URL 對照
```

Python 執行後也可能在各套件目錄產生 `__pycache__/`；資料讀寫時可能出現 `.update.lock`，中斷交易時可能留下 `.transaction.json`，這些都由 `.gitignore` 排除。網站修改應從 `site/` 進行，再重新建置 `dist/`。

完整行為與資料契約見 [現行完整規格](../VTuber_Schedule_SPEC_current.md)，本機執行與驗證命令見 [README](../README.md)。新增、搬動或移除專案檔案時，請同步更新本文件。
