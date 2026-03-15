# MaaStellaSora 開發記錄

## 專案概述

基於 [MaaFramework](https://github.com/MaaXYZ/MaaFramework) 的《星塔旅人》自動化助手。
主要維護官服（簡體中文）與日服，台服適配不完整，目前由台服玩家接手補齊。

---

## 台服（繁體中文）適配工作

### 架構說明

- `assets/resource/base/` — 官服（簡體中文）基礎資源
- `assets/resource/tw/` — 台服覆蓋資源（只需寫與 base 不同的節點）
- `assets/resource/tw/pipeline/main.json` — 已有的台服覆蓋（部分功能）
- MaaFramework 會將 tw 的定義**合併覆蓋** base，只需寫有差異的欄位

### Pipeline 覆蓋進度

| 功能 | 檔案 | 狀態 | 備註 |
|---|---|---|---|
| 通用節點 | `tw/pipeline/base.json` | ✅ 已完成 | 月卡領取、通用空白處 |
| 登入 | `tw/pipeline/login.json` | ✅ 已完成 | 下載完成文字、點擊文字 |
| 基金（採購獎勵） | `tw/pipeline/grant.json` | ✅ 已完成 | 今日目標、全部領取等 |
| 邀約 | `tw/pipeline/invite.json` | ✅ 已完成 | 角色名繁化、所有界面文字 |
| 活動快速戰鬥 | `tw/pipeline/activity.json` | ⚠️ 部分完成 | 關卡名稱用繁化猜測，待確認 |
| 心鏈送禮 | `tw/pipeline/main.json`（已有）| ✅ 已完成 | — |
| 好友加油 | `tw/pipeline/main.json`（已有）| ✅ 已完成 | — |
| 每日任務 | `tw/pipeline/main.json`（已有）| ✅ 已完成 | — |
| 委託派遣 | `tw/pipeline/main.json`（已有）| ✅ 已完成 | — |
| 採購每日贈禮 | `tw/pipeline/main.json`（已有）| ✅ 已完成 | — |
| 郵件 | `tw/pipeline/`（未建） | ❌ 待確認 | 全用圖片比對，需確認截圖是否相同 |
| 爬塔 | `tw/pipeline/climb_tower/` | ⚠️ 部分完成 | OCR 已繁化；對話選項需進遊戲確認；圖片模板待確認 |

---

## 待使用者確認的項目

### 🔴 必須確認（影響功能運作）

- [ ] **活動關卡名稱**：台服的活動關卡叫什麼？（官服叫「深入溫室的調查I」）
      → 確認後更新 `tw/pipeline/activity.json` 的 `活动_选择活动关卡` 節點

- [x] **邀約角色名稱**：已確認正確（使用者確認）
  - 希娅 → 希婭 ✅
  - 雾语 → 霧語 ✅
  - 苍兰 → 蒼蘭 ✅
  - 冬香、夏花 → 相同，無需修改 ✅

- [ ] **基金 UI 文字**：確認台服是否有以下文字：
  - 今日目標、每週事務、全部領取、基礎補貼、基金補貼

### 🟡 可能需要截圖

- [ ] `quick_claim.png`（一鍵領取按鈕）：base 使用此圖，tw/image 只有 `onekey_claim.png`，需確認是否相同
- [ ] `grant/grant.png`（基金圖示）：tw/image 無此圖，確認是否跟官服相同

---

## 待開發項目

### Python InviteAuto 繁化
- [x] ✅ 確認 `agent/custom/action/invite.py`：角色名從 pipeline 節點動態讀取（`context.get_node_data(node)`），無硬編碼，**不需要修改 Python**

### 爬塔台服測試
- [ ] 進遊戲確認爬塔對話選項文字（`tw/pipeline/climb_tower/climb_tower.json` 中 `星塔_节点_对话选项` 的20個選項）
- [ ] 確認「星塔商店」、「星塔背包」台服是否相同字串
- [ ] 確認圖片模板（屬性塔截圖、Buff推薦圖示）是否與官服相同

---

## 圖片資源清單（tw/image/）

目前已有：
- `activity.png` — 活動圖示
- `claim.png` — 領取按鈕
- `login.png` — 登入按鈕
- `onekey_claim.png` — 一鍵領取
- `procurement.png` — 採購圖示

可能需要補充：
- `quick_claim.png` — 確認是否與 `onekey_claim.png` 相同
- `grant/grant.png` — 基金圖示

---

## 開發規範

- Pipeline 覆蓋只寫差異部分（參考 jp 的做法），不重複整個節點
- 所有新增的台服 pipeline 放在 `assets/resource/tw/pipeline/`
- 圖片放在 `assets/resource/tw/image/`
- Python 自定義邏輯放在 `agent/custom/`
- **Pipeline JSON 禁止使用 `//` 註解**：MaaFramework 使用標準 JSON 解析器，不支援註解語法，會導致「資源加載失敗」。需要留記錄請寫在 CLAUDE.md。
