"""
TowerLoopAction — 台服星塔爬塔主迴圈

以 Python 狀態機驅動整個爬塔流程，取代原本以 JSON 為主的
星塔_爬塔流程 節點。設計目標：
- 台服（繁體中文）為標準
- 修正 星塔_保存紀錄 不當退出的 bug
- buff 選擇 + 拿走 在同一個 atomic 操作中完成
- 商店購物、強化、上樓等狀態全部在 Python 中處理
"""

import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction


# ──────────────────────────────────────────────────────────────────
# 工具函數
# ──────────────────────────────────────────────────────────────────

def _load_preset(param_raw: Any) -> Dict[int, List[str]]:
    """從 preset 檔名或 JSON 字串載入 buff 優先級字典。"""
    if param_raw is None:
        return {}

    if isinstance(param_raw, (bytes, bytearray)):
        param_raw = param_raw.decode("utf-8", errors="replace")

    if isinstance(param_raw, str):
        param_raw = param_raw.strip()
        if not param_raw or param_raw in ("{}", ""):
            return {}
        if param_raw.startswith("{"):
            parsed = json.loads(param_raw)
        else:
            filename = param_raw
            if param_raw.startswith('"'):
                try:
                    filename = json.loads(param_raw)
                except Exception:
                    pass
            # agent/custom/action/ → agent/
            agent_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            preset_path = os.path.join(agent_dir, "presets", filename)
            print(f"[tower_loop] loading preset: {preset_path!r}")
            with open(preset_path, "r", encoding="utf-8-sig") as f:
                parsed = json.load(f)
    else:
        parsed = param_raw

    if not isinstance(parsed, dict):
        return {}

    result: Dict[int, List[str]] = {}
    for key, value in parsed.items():
        try:
            priority = int(key)
        except (TypeError, ValueError):
            continue
        if isinstance(value, (list, tuple)):
            targets = list(value)
        else:
            targets = [value]
        result[priority] = [str(t) for t in targets if str(t).strip()]
    return result


def _box_center(box: Tuple[int, int, int, int]) -> Tuple[int, int]:
    x, y, w, h = box
    return x + w // 2, y + h // 2


# 商店 8 格 ROI（格子左上角 x, y, 寬, 高）
_GRID_ROIS: Dict[int, List[int]] = {
    1: [638, 159, 114, 133],
    2: [791, 157, 114, 133],
    3: [941, 157, 114, 133],
    4: [1094, 162, 114, 133],
    5: [641, 359, 114, 133],
    6: [791, 361, 114, 133],
    7: [943, 360, 114, 133],
    8: [1093, 361, 114, 133],
}


# ──────────────────────────────────────────────────────────────────
# TowerLoopAction
# ──────────────────────────────────────────────────────────────────

@AgentServer.custom_action("tower_loop")
class TowerLoopAction(CustomAction):
    TIMEOUT = 1800          # 最長執行 30 分鐘
    MAX_UNKNOWN = 10        # 連續未知狀態上限

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        priority_dict = _load_preset(argv.custom_action_param)
        print(f"[tower_loop] started, priority levels: {sorted(priority_dict.keys(), reverse=True)}")

        start = time.time()
        consecutive_unknown = 0
        self._shop_done_this_room = False      # 每次 run() 重置
        self._strengthen_done_this_room = False

        while not context.tasker.stopping:
            if time.time() - start > self.TIMEOUT:
                print("[tower_loop] timeout, exiting")
                return True

            img = context.tasker.controller.post_screencap().wait().get()
            state = self._detect_state(context, img)
            print(f"[tower_loop] state={state}")

            if state in ("tower_complete", "leave_confirm"):
                if state == "leave_confirm":
                    print("[tower_loop] leave confirm dialog, clicking 確認")
                    confirm = context.run_recognition("塔_偵測_確認按鈕", img)
                    if confirm and confirm.hit and confirm.best_result:
                        cx, cy = _box_center(confirm.best_result.box)
                        context.tasker.controller.post_click(cx, cy).wait()
                        print(f"[tower_loop] 確認 clicked at ({cx}, {cy})")
                    else:
                        # OCR 失敗（簡繁不同或字體問題）→ 固定座標點右側按鈕
                        print("[tower_loop] 確認 OCR failed, fallback click (875, 601)")
                        context.tasker.controller.post_click(875, 601).wait()
                    time.sleep(2.0)
                else:
                    print("[tower_loop] tower complete, done")
                return True

            if state == "unknown":
                consecutive_unknown += 1
                if consecutive_unknown >= self.MAX_UNKNOWN:
                    print(f"[tower_loop] {self.MAX_UNKNOWN}x unknown, assuming done")
                    return True
                time.sleep(1.0)  # 等待畫面過渡
                continue

            consecutive_unknown = 0
            self._dispatch(state, context, img, priority_dict)

        print("[tower_loop] stop signal received")
        return True

    # ──────────────────────────────────────────────────────────────
    # 狀態偵測
    # ──────────────────────────────────────────────────────────────

    def _detect_state(self, context: Context, img) -> str:
        """依優先順序偵測當前遊戲狀態。"""

        # 1. 塔探索完成（最高優先，避免誤跑）
        if self._hit(context, img, "塔_偵測_完成"):
            return "tower_complete"

        # 2. Buff 選擇畫面（推薦圖示 template match）
        if self._hit(context, img, "塔_偵測_buff選擇"):
            return "buff_select"

        # 3. 等級提升（進入 buff 選擇前的過渡）
        if self._hit(context, img, "塔_偵測_等級提升"):
            return "level_up"

        # 4. 點選空白關閉（優先於對話選項：取 buff 後的提示可能誤觸對話選項偵測）
        if self._hit(context, img, "塔_偵測_點選空白"):
            return "blank_close"

        # 5. 默契提升（同上，優先排除）
        if self._hit(context, img, "塔_偵測_默契提升"):
            return "harmony_up"

        # 6. 對話選項（有多個可選項）
        if self._hit(context, img, "塔_偵測_對話選項"):
            return "dialogue_option"

        # 7. 保存紀錄（點擊但不退出迴圈）
        if self._hit(context, img, "塔_偵測_保存紀錄"):
            return "save_record"

        # 8. 商店節點選擇畫面（優先於上樓/強化，避免在商店選擇畫面直接點上樓）
        #    已購物後由旗標保護，不會重複進入
        if not self._shop_done_this_room and self._hit(context, img, "塔_偵測_商店節點"):
            return "shop_node"

        # 9. 商店主界面（格子購物視圖）
        if self._hit(context, img, "塔_偵測_商店主界面"):
            return "shop_main"

        # 10. 強化可用（免費或 ≤180 幣）—— 購物完成後才處理，已強化則跳過
        if not self._strengthen_done_this_room and self._hit(context, img, "塔_偵測_強化可用"):
            return "strengthen_available"

        # 11. 上樓（商店/強化完成後前往下一層）
        if self._hit(context, img, "塔_偵測_上樓"):
            return "go_up"

        # 12. 離開確認彈窗（點「離開星塔」後彈出的確認對話框）
        if self._hit(context, img, "塔_偵測_離開確認"):
            return "leave_confirm"

        # 13. 最終商店離開星塔
        if self._hit(context, img, "塔_偵測_最終離開"):
            return "final_leave"

        # 13. 強化選卡畫面（潛能卡片選擇）
        if self._hit(context, img, "塔_偵測_強化選卡"):
            return "strengthen_card"

        # 14. 對話泡泡（點擊繼續）
        if self._hit(context, img, "星塔_节点_对话"):
            return "dialogue"

        # 15. 突發事件選項（藍色圓圈按鈕圖示，非預設對話選項的隨機事件）
        if self._hit(context, img, "塔_偵測_突發事件"):
            return "dialogue_ignore"

        return "unknown"

    def _hit(self, context: Context, img, node: str) -> bool:
        result = context.run_recognition(node, img)
        return bool(result and result.hit)

    # ──────────────────────────────────────────────────────────────
    # 狀態分派
    # ──────────────────────────────────────────────────────────────

    def _dispatch(self, state: str, context: Context, img, priority_dict: Dict):
        if state == "buff_select":
            self._handle_buff_select(context, img, priority_dict)

        elif state == "level_up":
            self._click_hit(context, img, "塔_偵測_等級提升")
            time.sleep(1.0)  # 等級提升動畫

        elif state == "dialogue_option":
            self._handle_dialogue_option(context, img)

        elif state == "save_record":
            # 點存檔但繼續跑（修正原 bug）
            self._click_hit(context, img, "塔_偵測_保存紀錄")
            time.sleep(0.8)

        elif state == "strengthen_available":
            self._strengthen_done_this_room = True  # 點了就標記，避免無限迴圈
            self._click_hit(context, img, "塔_偵測_強化可用")
            time.sleep(1.5)  # 等強化選卡 UI 打開或錯誤彈窗
            # 若幣不夠（付費強化但幣為0），彈窗會出現，關掉即可
            img2 = context.tasker.controller.post_screencap().wait().get()
            if self._hit(context, img2, "塔_商店_錢不夠"):
                print("[tower_loop] strengthen too expensive, dismissing")
                context.tasker.controller.post_click(640, 400).wait()
                time.sleep(0.5)

        elif state == "strengthen_card":
            self._handle_strengthen_card(context, img, priority_dict)

        elif state == "go_up":
            self._shop_done_this_room = False      # 進入下一層，重置旗標
            self._strengthen_done_this_room = False
            self._click_hit(context, img, "塔_偵測_上樓")
            time.sleep(2.0)  # 換層動畫較長

        elif state == "final_leave":
            self._click_hit(context, img, "塔_偵測_最終離開")
            time.sleep(2.0)

        elif state == "shop_node":
            self._handle_shop_node(context, img)

        elif state == "shop_main":
            self._handle_shop_main(context, img)
            self._shop_done_this_room = True  # 購物完成，本房間不再重複進入

        elif state == "dialogue":
            self._click_hit(context, img, "星塔_节点_对话")
            time.sleep(1.0)  # 等對話動畫

        elif state == "blank_close":
            self._click_hit(context, img, "塔_偵測_點選空白")
            time.sleep(1.0)  # 等提示消失

        elif state == "dialogue_ignore":
            # 突發事件：點擊偵測到的選項按鈕
            self._click_hit(context, img, "塔_偵測_突發事件")
            time.sleep(1.0)

        elif state == "harmony_up":
            self._click_hit(context, img, "塔_偵測_默契提升")
            time.sleep(1.0)

    def _click_hit(self, context: Context, img, node: str):
        """偵測節點並點擊命中位置的中心。"""
        result = context.run_recognition(node, img)
        if result and result.hit and result.best_result:
            cx, cy = _box_center(result.best_result.box)
            context.tasker.controller.post_click(cx, cy).wait()

    # ──────────────────────────────────────────────────────────────
    # Buff / 強化選卡
    # ──────────────────────────────────────────────────────────────

    def _handle_buff_select(self, context: Context, img, priority_dict: Dict):
        """戰鬥後的 buff 選擇畫面。"""
        fallback_result = context.run_recognition("塔_偵測_buff選擇", img)
        fallback_box = (
            fallback_result.best_result.box
            if (fallback_result and fallback_result.hit and fallback_result.best_result)
            else None
        )
        self._select_card_and_take(context, img, priority_dict, fallback_box)

    def _handle_strengthen_card(self, context: Context, img, priority_dict: Dict):
        """商店強化的潛能卡片選擇畫面。"""
        # 無推薦圖示；同樣走 priority_dict，無命中就點最左卡
        self._select_card_and_take(context, img, priority_dict, fallback_box=None)

    def _select_card_and_take(
        self,
        context: Context,
        img,
        priority_dict: Dict,
        fallback_box: Optional[Tuple],
    ):
        """掃描 priority_dict，點最高優先卡，再點拿走。"""
        target_box = None

        for priority in sorted(priority_dict.keys(), reverse=True):
            for target in priority_dict[priority]:
                if context.tasker.stopping:
                    return
                print(f"[tower_loop] scanning priority {priority}: {target!r}")
                reco = context.run_recognition(
                    "塔_OCR_卡牌區域",
                    img,
                    pipeline_override={
                        "塔_OCR_卡牌區域": {
                            "recognition": "OCR",
                            "expected": target,
                            "action": "DoNothing",
                        }
                    },
                )
                if reco and reco.hit and reco.best_result:
                    target_box = reco.best_result.box
                    print(f"[tower_loop] found {target!r} at {target_box}")
                    break
            if target_box is not None:
                break

        if target_box is None:
            if fallback_box is not None:
                target_box = fallback_box
                print(f"[tower_loop] no priority match, using fallback at {fallback_box}")
            else:
                # 無推薦圖示（強化選卡）→ 點畫面中央偏左第一張卡的大致位置
                target_box = (350, 430, 90, 30)
                print("[tower_loop] no match, clicking first card area")

        cx, cy = _box_center(target_box)
        context.tasker.controller.post_click(cx, cy).wait()
        time.sleep(1.0)  # 等選卡高亮動畫完成

        # 點拿走
        img2 = context.tasker.controller.post_screencap().wait().get()
        take = context.run_recognition("塔_OCR_拿走", img2)
        if take and take.hit and take.best_result:
            cx2, cy2 = _box_center(take.best_result.box)
            context.tasker.controller.post_click(cx2, cy2).wait()
            print("[tower_loop] 拿走 clicked")
        else:
            # 退一步：直接點「拿走」按鈕的固定座標
            print("[tower_loop] 拿走 not found, fallback click at fixed position")
            context.tasker.controller.post_click(335, 710).wait()
        time.sleep(1.5)  # 等取得 buff 動畫完成

    # ──────────────────────────────────────────────────────────────
    # 商店
    # ──────────────────────────────────────────────────────────────

    def _handle_shop_node(self, context: Context, img):
        """商店節點選擇畫面：點「商店購物」進入購物。"""
        self._click_hit(context, img, "塔_偵測_商店節點")
        time.sleep(2.0)  # 等商店主界面打開

    def _handle_shop_main(self, context: Context, img):
        """商店主界面：掃描 8 格，買有折扣的 buff / 音符；幣多則重置繼續買。"""
        for reroll_round in range(3):  # 最多原始 + 2 次重置
            items_bought = 0
            shop_closed_early = False
            for grid_idx, roi in _GRID_ROIS.items():
                # 每格前重新截圖，確認仍在商店主界面
                current_img = context.tasker.controller.post_screencap().wait().get()
                if not self._hit(context, current_img, "塔_偵測_商店主界面"):
                    print(f"[tower_loop] shop main gone at grid {grid_idx}")
                    shop_closed_early = True
                    break
                if self._process_grid(context, grid_idx, roi):
                    items_bought += 1

            if shop_closed_early:
                return  # 商店已自動關閉，交由主迴圈處理

            # 本輪掃完：嘗試重置（幣帶不走，積極花）
            if reroll_round < 2 and self._try_reroll_shop(context):
                print(f"[tower_loop] shop rerolled (round {reroll_round + 1}, bought {items_bought})")
                time.sleep(1.5)  # 等重置動畫
            else:
                print(f"[tower_loop] shop done (round {reroll_round}, bought {items_bought})")
                break  # 沒東西買或無法重置，結束

        time.sleep(0.5)
        self._exit_shop_main(context)

    def _try_reroll_shop(self, context: Context) -> bool:
        """嘗試點擊商店重置按鈕。若成功回傳 True，無法重置回傳 False。"""
        img = context.tasker.controller.post_screencap().wait().get()

        result = context.run_recognition("塔_商店_重置按鈕", img)
        if not (result and result.hit and result.best_result):
            print("[tower_loop] reroll button not found, skip")
            return False

        cx, cy = _box_center(result.best_result.box)
        context.tasker.controller.post_click(cx, cy).wait()
        time.sleep(1.0)

        # 檢查是否出現「無法重置」或「錢不夠」彈窗
        img2 = context.tasker.controller.post_screencap().wait().get()
        if self._hit(context, img2, "塔_商店_無法重置") or self._hit(context, img2, "塔_商店_錢不夠"):
            print("[tower_loop] reroll failed (no coins or no rerolls left)")
            context.tasker.controller.post_click(640, 400).wait()
            time.sleep(0.5)
            return False

        return True

    def _process_grid(self, context: Context, grid_idx: int, roi: List[int]) -> bool:
        """點擊一個商店格子，判斷是否購買。回傳 True 表示成功購買。"""
        cx, cy = roi[0] + roi[2] // 2, roi[1] + roi[3] // 2
        context.tasker.controller.post_click(cx, cy).wait()
        time.sleep(0.8)  # 等詳情面板滑入

        img = context.tasker.controller.post_screencap().wait().get()

        # 售罄 → 跳過
        if self._hit(context, img, "塔_商店_售罄"):
            print(f"[tower_loop] grid {grid_idx}: sold out")
            return False

        # 錢不夠 → 跳過
        if self._hit(context, img, "塔_商店_錢不夠"):
            print(f"[tower_loop] grid {grid_idx}: insufficient funds")
            return False

        # 沒有打開詳情面板 → 跳過
        if not self._hit(context, img, "塔_商店_購買按鈕"):
            print(f"[tower_loop] grid {grid_idx}: no detail panel")
            return False

        is_buff = self._hit(context, img, "塔_商店_buff類型")
        is_note = (not is_buff) and self._hit(context, img, "塔_商店_音符類型")

        if is_buff:
            # buff 類（潛能特飲等）：永遠值得買
            print(f"[tower_loop] grid {grid_idx}: buff, buying")
            self._do_buy(context)
            return True

        if is_note:
            # 音符類：只買已激活（與隊伍相關）的音符；未激活的沒有效益，跳過
            is_activated = self._hit(context, img, "塔_商店_音符激活")
            if is_activated:
                print(f"[tower_loop] grid {grid_idx}: activated note, buying")
                self._do_buy(context)
                return True
            else:
                print(f"[tower_loop] grid {grid_idx}: unactivated note, skip")

        else:
            print(f"[tower_loop] grid {grid_idx}: skip (not buff or note)")

        self._close_detail(context, img)
        return False

    def _do_buy(self, context: Context):
        """點擊購買確認按鈕。"""
        img = context.tasker.controller.post_screencap().wait().get()
        result = context.run_recognition("塔_商店_購買確認", img)
        if result and result.hit and result.best_result:
            cx, cy = _box_center(result.best_result.box)
            context.tasker.controller.post_click(cx, cy).wait()
            time.sleep(1.5)  # 等購買動畫完成
            # 確認後可能出現的彈窗
            img2 = context.tasker.controller.post_screencap().wait().get()
            if self._hit(context, img2, "塔_商店_錢不夠"):
                context.tasker.controller.post_click(640, 400).wait()
                time.sleep(0.5)
            elif self._hit(context, img2, "塔_偵測_點選空白"):
                # 購買後出現「點選空白處繼續」提示（如拿到新 buff 時）
                self._click_hit(context, img2, "塔_偵測_點選空白")
                time.sleep(1.0)

    def _close_detail(self, context: Context, img):
        """關閉格子詳情面板。"""
        result = context.run_recognition("塔_商店_關閉按鈕", img)
        if result and result.hit and result.best_result:
            cx, cy = _box_center(result.best_result.box)
            context.tasker.controller.post_click(cx, cy).wait()
        else:
            # 備用：點空白區域
            context.tasker.controller.post_click(471 + 335 // 2, 486 + 216 // 2).wait()
        time.sleep(0.6)  # 等詳情面板收起

    def _exit_shop_main(self, context: Context):
        """從商店主界面返回選擇畫面。"""
        img = context.tasker.controller.post_screencap().wait().get()
        result = context.run_recognition("星塔_节点_商店_返回_agent", img)
        if result and result.hit and result.best_result:
            cx, cy = _box_center(result.best_result.box)
            context.tasker.controller.post_click(cx, cy).wait()
            time.sleep(2.0)  # 等返回動畫
            return
        # 備用：點左上角返回箭頭的固定座標
        context.tasker.controller.post_click(50, 35).wait()
        time.sleep(2.0)

    # ──────────────────────────────────────────────────────────────
    # 對話選項
    # ──────────────────────────────────────────────────────────────

    def _handle_dialogue_option(self, context: Context, img):
        """點擊識別到的對話選項文字。"""
        result = context.run_recognition("塔_偵測_對話選項", img)
        if result and result.hit and result.best_result:
            cx, cy = _box_center(result.best_result.box)
            context.tasker.controller.post_click(cx, cy).wait()
            time.sleep(0.5)  # 對話選項通常快速響應，多頁劇情也能快速點完
