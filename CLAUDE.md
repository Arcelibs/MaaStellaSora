# MaaStellaSora 開發記錄

## 專案概述

基於 [MaaFramework](https://github.com/MaaXYZ/MaaFramework) 的《星塔旅人》自動化助手。
Fork 自 [MaaStellaSora/MaaStellaSora](https://github.com/MaaStellaSora/MaaStellaSora)，由台服玩家（Arcelibs）獨立維護台服適配版本。

**Fork repo**：`https://github.com/Arcelibs/MaaStellaSora`
**主開發分支**：`pr/tw-adaptation`
**最新 release**：`v0.8.1-tw.1`（標籤推上去後 GitHub Actions 自動 build）

---

## 台服（繁體中文）適配工作

### 架構說明

- `assets/resource/base/` — 官服（簡體中文）基礎資源，不要直接修改
- `assets/resource/tw/` — 台服覆蓋資源（只需寫與 base 不同的節點）
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
| 爬塔 | `tw/pipeline/climb_tower/` | ✅ 主體完成 | Python 狀態機 + OCR 繁化完成；對話選項待補齊 |

---

## 爬塔功能（核心）

### 架構

爬塔完全由 Python 狀態機驅動，取代原本的 JSON pipeline 流程：

- **入口**：`assets/resource/tw/pipeline/climb_tower/climb_tower_tw.json` 的 `星塔_爬塔流程`（DirectHit → 呼叫 tower_loop）
- **主邏輯**：`agent/custom/action/tower_loop.py`（`TowerLoopAction` 狀態機）
- **OCR 節點**：`climb_tower_tw.json` 定義所有台服繁體文字的偵測節點
- **作業檔**：`agent/presets/*.json`（各隊伍 Buff 優先級清單）
- **適配指南**：`docs/climb_tower_adaptation.md`（其他語系適配參考）

### 狀態機流程（tower_loop.py）

`_detect_state` 優先順序（重要，順序不能亂）：

1. `tower_complete` — 探索完成
2. `backpack_screen` — **星塔背包（必須在 buff_select 之前！** 否則背包的綠框會誤觸 buff 偵測）
3. `buff_select` — Buff 選擇畫面
4. `level_up` — 等級提升
5. `blank_close` — 點選空白關閉
6. `harmony_up` — 默契提升
7. `dialogue_option` — 對話選項
8. `save_record` — 保存紀錄
9. `shop_node` — 商店節點選擇
10. `shop_main` — 商店主界面
11. `strengthen_available` — 強化可用
12. `go_up` — 上樓
13. `leave_confirm` — 離開確認
14. `final_leave` — 最終離開
15. `strengthen_card` — 強化選卡
16. `dialogue` — 對話泡泡
17. `dialogue_ignore` — 突發事件

### 商店購買策略

| 商品類型 | 購買條件 |
|---|---|
| Buff（潛能特飲等） | 有折扣才買（無折扣 200 幣不划算） |
| 已激活音符 | 直接買 |
| 未激活音符 | 跳過 |
| 其他 | 跳過 |

商店重置：掃完一輪後最多重置 2 次。`skip_shop_rerolls` 設定跳過前 N 次商店的重置。

### Buff 選卡策略

- 按 priority 3 → 2 → 1 掃描，找到就選
- 全部不在清單內且有設定優先級 → 最多重置 2 次（花幣）再掃
- 沒有設定 preset 或重置後仍無命中 → 選推薦圖示（fallback）

### Preset 格式

```json
{
    "config": {
        "skip_shop_rerolls": 1
    },
    "3": ["最高優先Buff1", "最高優先Buff2"],
    "2": ["次要Buff1"],
    "1": ["備選Buff1"]
}
```

### 現有 Preset 作業

| 檔名 | 隊伍 |
|---|---|
| `qiandushi-water.json` | 千都世+蒼蘭+特麗莎（水） |
| `xiya_miniewa_tiliya_yetuliu.json` | 希婭+密捏瓦+緹莉婭（夜兔流） |
| `xiya_miniewa_tiliya_xuetu.json` | 希婭+密捏瓦+緹莉婭（雪兔流） |
| `fengying_xiahua_xingzi_pugong.json` | 風影+夏花+杏子（風隊普攻流） |
| `feilengcui_piaoliji_kesaite_jishang.json` | 翡冷翠+縹莉姬+珂賽特（技傷流） |

### interface.json 任務

- **抄作業爬塔**：`entry: 星塔_入口`，從地圖進塔，正常流程
- **接續爬塔作業**：`entry: 星塔_爬塔流程`，直接從當前畫面接管，不消耗票，適合中途暫停後繼續

---

## 待使用者確認的項目

### 🔴 必須確認（影響功能運作）

- [ ] **活動關卡名稱**：台服的活動關卡叫什麼？（官服叫「深入溫室的調查I」）
      → 確認後更新 `tw/pipeline/activity.json` 的 `活动_选择活动关卡` 節點

- [x] **邀約角色名稱**：已確認正確
  - 希娅 → 希婭 ✅  /  雾语 → 霧語 ✅  /  苍兰 → 蒼蘭 ✅  /  冬香、夏花 → 相同 ✅

- [ ] **基金 UI 文字**：確認台服是否有：今日目標、每週事務、全部領取、基礎補貼、基金補貼

### 🟡 可能需要截圖

- [ ] `quick_claim.png`：base 使用此圖，tw/image 只有 `onekey_claim.png`，需確認是否相同
- [ ] `grant/grant.png`：tw/image 無此圖，確認是否跟官服相同

### 🟢 爬塔待補齊

- [ ] 爬塔對話選項文字（`climb_tower_tw.json` 的 `塔_偵測_對話選項`，目前 20 個猜測文字）
- [ ] 確認圖片模板（Buff推薦圖示、商店界面、突發事件按鈕）是否與官服相同

---

## 發布流程

在 `pr/tw-adaptation` 打 tag 後 GitHub Actions 自動 build：

```bash
git tag v0.8.1-tw.2
git push origin v0.8.1-tw.2
```

版本號規則：`v{上游版本}-tw.{台服序號}`，例如 `v0.8.1-tw.1`

GitHub Pages workflow（`static.yml`）在無 Pages 設定時會失敗，不影響 release 主體。

---

## 開發規範

- Pipeline 覆蓋只寫差異部分，不重複整個節點
- **Pipeline JSON 禁止 `//` 註解**（MaaFramework 不支援 JSONC，會導致資源加載失敗）
- 所有新增的台服 pipeline 放在 `assets/resource/tw/pipeline/`
- 圖片放在 `assets/resource/tw/image/`
- Python 自定義邏輯放在 `agent/custom/`

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
