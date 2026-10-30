# Meridian Schedule V2.3 — 明確事件狀態

本版延續 [v2.2](VTuber_Schedule_SPEC_v2_2.md) 的穩定事件 ID、更新、來源、Revision、receipt、備份與交易復原規則，將 CSV 的時間與事件狀態拆開。本文取代 v2.2 第 14、15 節的過渡設計，並開放以明確狀態更新取消與延期。

## 1. 範圍

- 新增唯一一個 CSV 欄位 `event_status`；不新增其他選填欄位或正式環境相依套件。
- CSV `time` 只承載時間；`event_status` 承載事件狀態。
- 既有事件、Sheet 列、receipt 與 Revision 的 ID 全部保留，不重新編號。
- 正式 Event 已有獨立的 `time` 與 `status`，因此 CSV `event_status` 對應既有 Event `status`，不另新增重複的 JSON 欄位。
- `operation`、刪除、整張週表替換、`schedule_version` 與 fuzzy auto-merge 仍不提供。

## 2. CSV 欄位

event_status 緊接 time，放在 F 欄；原 F:I 移為 G:J，ID、時間與 C 欄公式位置保持不變：

```csv
id,member_id,group,date,time,event_status,title,platform,source_url,created_at
```

| 欄位 | 規則 |
| --- | --- |
| `id` | 穩定事件 ID；同一事件任何資訊修正仍沿用原 ID |
| `member_id` | 已啟用成員；同 ID 不得更換 ownership |
| `group` | 僅供顯示，由既有公式計算，匯入時忽略 |
| `date` | 建議完整 `YYYY-MM-DD`，沿用既有日期正規化 |
| `time` | `HH:MM` 或空白；沿用既有實際時間格式正規化，禁止在新格式填入狀態 token |
| `event_status` | 新格式每列必填；允許值見下表 |
| `title` | 必填 |
| `platform` | 保留 youtube/twitch/none/unknown；缺欄或空白保留既有平台 |
| `source_url` | 公開公告來源，不作事件 identity 或更新權限判斷 |
| `created_at` | 該列首次建立時間；既有事件已記錄時保持不變 |

舊有選填 `status=pending/imported/invalid` 屬於 ingestion 控制，不是事件狀態。pending/imported 忽略；invalid 仍作人工停用標記。不要把事件狀態寫入該欄。

## 3. 狀態與時間配對

| event_status | time | 意義 |
| --- | --- | --- |
| `scheduled` | 必須有時間 | 已排定，時間確定 |
| `tbd` | 必須空白 | 官方明確表示時間未定 |
| `day_off` | 必須空白 | 官方明確休息 |
| `unknown` | 必須空白 | 資訊不足，無法判定時間或行程狀態 |
| `cancelled` | 實際時間或空白 | 官方明確取消；可保留已知原時間供追溯 |
| `postponed` | 實際時間或空白 | 官方明確延期；只有官方已確認時才填時間 |

CSV 空白時間正規化為 JSON `null`，不是字串 `null`。`event_status` 去除前後空白並轉小寫。

有 `event_status` 欄時，即使特殊值與狀態相符，也不得在 `time` 填 `tbd`、`day_off`、`unknown` 或其中文別名。未知/空白狀態、scheduled 缺時間、待定/休息/未知同時填時間，皆為單列錯誤並略過；其他有效列繼續匯入。

`changed` 代表舊版變更標記，不是新 CSV 的事件狀態。`live`、`finished` 本版不接受 CSV 輸入，避免依時間經過自行推論直播狀態。正式 schema 保留這些值供舊流程與歷史快照相容。

## 4. 更新規則

- 相同 ID 的 `event_status` 可直接更新，包含取消、延期、恢復 scheduled，以及 tbd/day_off/unknown 轉為確定時間。
- 有明確 event_status 時，以該狀態更新正式 Event.status；內容、平台或來源修正不會再將 scheduled 自動改成 changed。
- 既有 changed 事件收到明確 scheduled 時，轉為 scheduled 並保留正常 Revision。
- 所有實際變更保存前後快照；內容相同保持完全 no-op，不改 updated_at、不新增 Revision、備份或 commit。
- 新 ID 不得隱性修改舊事件。重複內容包含正規化後的事件狀態；同時段標題相似但狀態不同仍警告略過，不自行合併。
- 同 ID 更新後與另一事件的成員、日期、時間、標題、平台相同時停止更新，避免碰撞，即使兩者狀態不同也不建立第二個邏輯事件。
- source_url 仍只是來源，group 仍不參與合併；CSV 列消失不刪除事件。

## 5. 舊格式相容

只有完全沒有 `event_status` 標題時，才啟用舊格式：

| 舊 time | 正規化 time | 正規化 event_status |
| --- | --- | --- |
| 實際時間 | `HH:MM` | `scheduled` |
| `tbd`／待定別名 | `null` | `tbd` |
| `day_off`／休息別名 | `null` | `day_off` |
| `unknown`／未知 | `null` | `unknown` |

舊格式空白 time 仍無效。舊格式修改既有事件時保留原本 terminal state 與 changed 行為，避免部署前後舊 CSV 自行恢復取消事件；只有新格式的明確 event_status 能控制此轉換。

只要 event_status 標題存在，就不得將空白狀態當成舊格式處理。不能在同一份新 CSV 混用尚未遷移的狀態 token。

## 6. Sheet 與提示範本

- A:E 保持原位置，C 欄保留 group 的 ARRAYFORMULA；以原生欄位移動保留原 F:I 的內容、格式與驗證，移為 G:J。
- F1 為 event_status，F2:F1000 使用六種狀態的嚴格下拉選單。
- 新增列寫入 A:B 與 D:J；修正列只更新 D:I 的異動欄位，保留 A:B 的 ID/member_id 與 J 欄 created_at。
- 取消/延期必須有明確官方證據，不能因來源消失、搜尋不到或排程時間已過而推定。
- 任何狀態變更都沿用原 ID；不新增另一列取代同一事件。

## 7. 部署與遷移順序

1. 先部署同時支援舊格式與新格式的程式、schema、測試、範例與提示。
2. 確認雲端已使用新版程式，舊 CSV 匯入無效列為 0，Pages 部署成功。
3. 重新讀取並備份 Sheet 的值、公式、格式與驗證；新增的 event_status 放在 F，使用原生欄位移動保留原欄位結構。
4. 按既有 time 建立 event_status；實際時間維持原值，特殊狀態的 time 改為空白。先以副本匯入預演，確認 ID 與語意不變。
5. 時間與狀態在同一原子 batch 更新，最終 E 欄為 time、F 欄為 event_status；其他欄位僅依上述順序移動，不更動內容或 ID。正式資料已是 time/status 分離時，無須為格式遷移製造 Revision。
6. 驗證 Sheet 回讀、公開 CSV 與正式重新匯入；比對全部事件 ID、時間、狀態與來源，最後檢查網站。

部署與遷移期間保留舊格式相容，不停用既有排程，不需要新增 Google API 認證到 GitHub Actions。

## 8. 網站與驗收

- 正式 JSON 沿用 time/status，既有網站資料與歷史 schema 相容。
- time 為 null 時：day_off 顯示「全天」、unknown 顯示「未知」、tbd 顯示「時間待定」、cancelled 顯示「已取消」、postponed 顯示「延期」。有實際時間時顯示時間及對應狀態徽章。
- 測試涵蓋六種狀態、欄位配對錯誤、同 ID 更新、ownership、碰撞、防重複、Revision、no-op、交易回復及新舊格式。
- 正式資料與 Sheet 的 ID 集合保持原樣；相同內容由舊格式轉新格式重跑不得產生資料變更。
