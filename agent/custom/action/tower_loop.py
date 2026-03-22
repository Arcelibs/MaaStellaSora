"""
TowerLoopAction — 台服星塔爬塔主迴圈

以 Python 狀態機驅動整個爬塔流程，取代原本以 JSON 為主的
星塔_爬塔流程 節點。設計目標：
- 台服（繁體中文）為標準
- 修正 星塔_保存紀錄 不當退出的 bug
- buff 選擇 + 拿走 在同一個 atomic 操作中完成
- 商店購物、強化、上樓等狀態全部在 Python 中處理
- 融合上游精華：OCR 重試、幣數直讀、模糊匹配、最終商店策略
"""

import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction


# ──────────────────────────────────────────────────────────────────
# 工具函數
# ──────────────────────────────────────────────────────────────────

def _load_preset(param_raw: Any) -> Tuple[Dict[int, List[str]], Dict]:
    """從 preset 檔名或 JSON 字串載入 buff 優先級字典與設定。

    Returns:
        (priority_dict, config)
        config 支援的欄位：
          skip_shop_rerolls (int): 跳過前 N 次商店的重置
          strengthen_max_cost (int): 強化費用超過此值跳過（預設 180）
          strengthen_reserve (int): 購物前預留的幣數（預設 = strengthen_max_cost）
          verbose_log (bool): 啟用詳細 log
    """
    if param_raw is None:
        return {}, {}

    if isinstance(param_raw, (bytes, bytearray)):
        param_raw = param_raw.decode("utf-8", errors="replace")

    if isinstance(param_raw, str):
        param_raw = param_raw.strip()
        if not param_raw or param_raw in ("{}", ""):
            return {}, {}
        if param_raw.startswith("{"):
            parsed = json.loads(param_raw)
        else:
            # 先去掉外層引號（MaaFramework 有時會多包一層）
            filename = param_raw
            if filename.startswith('"'):
                try:
                    filename = json.loads(filename)
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
        return {}, {}

    # 提取 config（非整數 key 的特殊欄位）
    config: Dict = {}
    raw_config = parsed.get("config")
    if isinstance(raw_config, dict):
        config = raw_config

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
    return result, config


def _box_center(box: Tuple[int, int, int, int]) -> Tuple[int, int]:
    x, y, w, h = box
    return x + w // 2, y + h // 2


_RE_NON_ALNUM = re.compile(r'[\s·・\-—–_!！、，。：:；;（）()\[\]【】「」『』""\'\'\"]+')


def _normalize_name(name: str) -> str:
    """移除空格、標點、特殊符號，保留文字與數字，用於模糊比對。"""
    return _RE_NON_ALNUM.sub('', name)


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
        priority_dict, config = _load_preset(argv.custom_action_param)
        print(f"[tower_loop] started, priority levels: {sorted(priority_dict.keys(), reverse=True)}, config: {config}")

        start = time.time()
        consecutive_unknown = 0
        self._shop_done_this_room = False
        self._strengthen_done_this_room = False
        self._shop_visit_count = 0
        self._config = config
        self._verbose = config.get("verbose_log", False)
        self._current_floor = 0
        self._is_final_room = False

        # 強化相關設定
        self._strengthen_max_cost = config.get("strengthen_max_cost", 180)
        self._strengthen_reserve = config.get("strengthen_reserve", self._strengthen_max_cost)

        if self._verbose:
            print(f"[tower_loop] verbose log enabled, strengthen_max_cost={self._strengthen_max_cost}, reserve={self._strengthen_reserve}")

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
                time.sleep(1.0)
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

        # 2. 星塔背包（需在 buff 選擇之前偵測，
        #    因背包畫面的技能卡綠框可能誤觸 buff 選擇 TemplateMatch）
        if self._hit(context, img, "塔_偵測_星塔背包"):
            return "backpack_screen"

        # 3. Buff 選擇畫面（推薦圖示 template match）
        if self._hit(context, img, "塔_偵測_buff選擇"):
            return "buff_select"

        # 4. 等級提升（進入 buff 選擇前的過渡）
        if self._hit(context, img, "塔_偵測_等級提升"):
            return "level_up"

        # 5. 點選空白關閉（優先於對話選項：取 buff 後的提示可能誤觸對話選項偵測）
        if self._hit(context, img, "塔_偵測_點選空白"):
            return "blank_close"

        # 6. 默契提升（同上，優先排除）
        if self._hit(context, img, "塔_偵測_默契提升"):
            return "harmony_up"

        # 7. 對話選項（有多個可選項）
        if self._hit(context, img, "塔_偵測_對話選項"):
            return "dialogue_option"

        # 8. 保存紀錄（點擊但不退出迴圈）
        if self._hit(context, img, "塔_偵測_保存紀錄"):
            return "save_record"

        # 9. 商店節點選擇畫面（優先於上樓/強化）
        if not self._shop_done_this_room and self._hit(context, img, "塔_偵測_商店節點"):
            return "shop_node"

        # 10. 商店主界面（格子購物視圖）
        if not self._shop_done_this_room and self._hit(context, img, "塔_偵測_商店主界面"):
            return "shop_main"

        # 11. 強化可用——購物完成後才處理，已強化則跳過
        if not self._strengthen_done_this_room and self._hit(context, img, "塔_偵測_強化可用"):
            return "strengthen_available"

        # 12. 上樓（商店/強化完成後前往下一層）
        if self._hit(context, img, "塔_偵測_上樓"):
            return "go_up"

        # 13. 離開確認彈窗
        if self._hit(context, img, "塔_偵測_離開確認"):
            return "leave_confirm"

        # 14. 最終商店離開星塔
        if self._hit(context, img, "塔_偵測_最終離開"):
            return "final_leave"

        # 15. 強化選卡畫面（潛能卡片選擇）
        if self._hit(context, img, "塔_偵測_強化選卡"):
            return "strengthen_card"

        # 16. 對話泡泡（點擊繼續）
        if self._hit(context, img, "星塔_节点_对话"):
            return "dialogue"

        # 17. 突發事件選項（藍色圓圈按鈕圖示）
        if self._hit(context, img, "塔_偵測_突發事件"):
            return "dialogue_ignore"

        return "unknown"

    # ──────────────────────────────────────────────────────────────
    # 基礎工具
    # ──────────────────────────────────────────────────────────────

    def _hit(self, context: Context, img, node: str) -> bool:
        result = context.run_recognition(node, img)
        return bool(result and result.hit)

    def _click_hit(self, context: Context, img, node: str):
        """偵測節點並點擊命中位置的中心。"""
        result = context.run_recognition(node, img)
        if result and result.hit and result.best_result:
            cx, cy = _box_center(result.best_result.box)
            context.tasker.controller.post_click(cx, cy).wait()

    def _ocr_with_retry(self, context: Context, node: str, img=None,
                        max_tries: int = 3, sleep_sec: float = 0.5):
        """帶重試的 OCR 辨識。回傳 recognition result 或 None。"""
        for attempt in range(max_tries):
            if context.tasker.stopping:
                return None
            if img is None or attempt > 0:
                img = context.tasker.controller.post_screencap().wait().get()
            result = context.run_recognition(node, img)
            if result and result.hit and result.best_result:
                return result
            if attempt < max_tries - 1:
                time.sleep(sleep_sec)
        return None

    def _log(self, msg: str):
        """verbose log：僅在 verbose_log=true 時輸出詳細資訊。"""
        if self._verbose:
            print(f"[tower] F{self._current_floor} {msg}")

    # ──────────────────────────────────────────────────────────────
    # 幣數與費用讀取
    # ──────────────────────────────────────────────────────────────

    def _read_coin_amount(self, context: Context, img=None) -> int:
        """OCR 讀取當前幣數。失敗時回退到區間偵測，最差回傳 0。"""
        result = self._ocr_with_retry(context, "塔_OCR_幣數", img, max_tries=2)
        if result:
            try:
                text = getattr(result.best_result, "text", "").replace(",", "").strip()
                return int(text)
            except (ValueError, AttributeError):
                pass
        # fallback: 用既有的區間偵測
        if img is None:
            img = context.tasker.controller.post_screencap().wait().get()
        if self._hit(context, img, "塔_商店_幣數千五以上"):
            return 1500
        if self._hit(context, img, "塔_商店_幣數千以上"):
            return 1000
        if self._hit(context, img, "塔_商店_幣數六五零以上"):
            return 650
        return 0

    def _read_strengthen_cost(self, context: Context, img) -> int:
        """讀取強化費用，回傳整數。免費=0，識別失敗=65535（安全預設：不強化）。"""
        result = self._ocr_with_retry(context, "塔_強化_費用", img, max_tries=3)
        if result:
            text = getattr(result.best_result, "text", "").strip()
            if "免費" in text or "免费" in text:
                return 0
            try:
                return int(text)
            except ValueError:
                pass
        return 65535

    # ──────────────────────────────────────────────────────────────
    # 狀態分派
    # ──────────────────────────────────────────────────────────────

    def _dispatch(self, state: str, context: Context, img, priority_dict: Dict):
        if state == "buff_select":
            self._handle_buff_select(context, img, priority_dict)

        elif state == "level_up":
            self._click_hit(context, img, "塔_偵測_等級提升")
            time.sleep(1.0)

        elif state == "dialogue_option":
            self._handle_dialogue_option(context, img)

        elif state == "save_record":
            self._click_hit(context, img, "塔_偵測_保存紀錄")
            time.sleep(0.8)

        elif state == "strengthen_available":
            cost = self._read_strengthen_cost(context, img)
            self._strengthen_done_this_room = True

            # 最終商店強化不限費用（幣帶不走）
            max_cost = 65535 if self._is_final_room else self._strengthen_max_cost

            if cost > max_cost:
                print(f"[tower_loop] strengthen cost={cost} > max={max_cost}, skipping")
                self._log(f"強化 費用={cost} → 跳過(超過上限{max_cost})")
            elif cost == 65535:
                print("[tower_loop] strengthen cost unreadable, skipping for safety")
            else:
                print(f"[tower_loop] strengthen cost={cost}, proceeding")
                self._log(f"強化 費用={cost} → 執行")
                self._click_hit(context, img, "塔_偵測_強化可用")
                time.sleep(1.5)
                img2 = context.tasker.controller.post_screencap().wait().get()
                if self._hit(context, img2, "塔_商店_錢不夠"):
                    print(f"[tower_loop] strengthen cost={cost}, insufficient coins")
                    context.tasker.controller.post_click(640, 400).wait()
                    time.sleep(0.5)

        elif state == "strengthen_card":
            self._handle_strengthen_card(context, img, priority_dict)

        elif state == "go_up":
            self._shop_done_this_room = False
            self._strengthen_done_this_room = False
            self._is_final_room = False
            self._current_floor += 1
            print(f"[tower_loop] going up, now floor {self._current_floor}")
            self._click_hit(context, img, "塔_偵測_上樓")
            time.sleep(2.0)

        elif state == "final_leave":
            self._click_hit(context, img, "塔_偵測_最終離開")
            time.sleep(2.0)

        elif state == "shop_node":
            self._handle_shop_node(context, img)

        elif state == "shop_main":
            self._shop_visit_count += 1
            print(f"[tower_loop] shop visit #{self._shop_visit_count}")
            completed = self._handle_shop_main(context, img)
            if completed:
                self._shop_done_this_room = True

        elif state == "dialogue":
            self._click_hit(context, img, "星塔_节点_对话")
            time.sleep(1.0)

        elif state == "blank_close":
            self._click_hit(context, img, "塔_偵測_點選空白")
            time.sleep(1.0)

        elif state == "dialogue_ignore":
            self._click_hit(context, img, "塔_偵測_突發事件")
            time.sleep(1.0)

        elif state == "harmony_up":
            self._click_hit(context, img, "塔_偵測_默契提升")
            time.sleep(1.0)

        elif state == "backpack_screen":
            print("[tower_loop] backpack screen detected, pressing Android back key")
            context.tasker.controller.post_press_key(4).wait()
            time.sleep(1.5)

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
        self._select_card_and_take(context, img, priority_dict, fallback_box=None)

    def _find_priority_card(self, context: Context, img) -> Optional[Tuple]:
        """掃描畫面上的卡牌，回傳最高優先命中的 box；無命中回傳 None。

        兩段式匹配：
        - Pass 1: 精確 OCR expected 匹配（快速路徑）
        - Pass 2: 讀取所有卡牌文字，正規化後雙向 substring 比對
        """
        # Pass 1: 精確匹配
        for priority in sorted(self._priority_dict.keys(), reverse=True):
            for target in self._priority_dict[priority]:
                if context.tasker.stopping:
                    return None
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
                    box = reco.best_result.box
                    print(f"[tower_loop] found {target!r} (exact) at {box}")
                    return box

        # Pass 2: 模糊匹配 — 讀取所有卡牌文字，用 substring 比對
        all_text_reco = context.run_recognition(
            "塔_OCR_卡牌區域",
            img,
            pipeline_override={
                "塔_OCR_卡牌區域": {
                    "recognition": "OCR",
                    "expected": ".+",
                    "action": "DoNothing",
                }
            },
        )
        if not (all_text_reco and all_text_reco.hit):
            return None

        results = getattr(all_text_reco, "filtered_results", None) or []
        if all_text_reco.best_result:
            results = [all_text_reco.best_result] + [r for r in results if r != all_text_reco.best_result]

        for result in results:
            ocr_text = getattr(result, "text", "")
            ocr_norm = _normalize_name(ocr_text)
            if len(ocr_norm) < 2:
                continue
            for priority in sorted(self._priority_dict.keys(), reverse=True):
                for target in self._priority_dict[priority]:
                    target_norm = _normalize_name(target)
                    if len(target_norm) < 2:
                        continue
                    if target_norm in ocr_norm or ocr_norm in target_norm:
                        print(f"[tower_loop] found {target!r} (fuzzy: '{ocr_text}') at {result.box}")
                        return result.box

        return None

    def _try_reroll_buff(self, context: Context) -> bool:
        """嘗試點擊 buff 選擇畫面右下角的重置按鈕。成功點擊回傳 True。"""
        img = context.tasker.controller.post_screencap().wait().get()
        result = context.run_recognition("塔_buff_重置按鈕", img)
        if result and result.hit and result.best_result:
            bx, by, bw, bh = result.best_result.box
            cx, cy = bx + bw // 2, by - 25
            context.tasker.controller.post_click(cx, cy).wait()
            print(f"[tower_loop] buff reroll clicked at ({cx}, {cy})")
            return True
        # fallback 固定座標
        print("[tower_loop] buff reroll OCR failed, fallback click (1210, 635)")
        context.tasker.controller.post_click(1210, 635).wait()
        return True

    def _select_card_and_take(
        self,
        context: Context,
        img,
        priority_dict: Dict,
        fallback_box: Optional[Tuple],
    ):
        """掃描 priority_dict，點最高優先卡，再點拿走。
        若無命中且有優先清單，最多重置 2 次後再選。
        """
        self._priority_dict = priority_dict
        MAX_BUFF_REROLLS = 2
        reroll_count = 0

        while True:
            target_box = self._find_priority_card(context, img)

            if target_box is not None:
                break

            if priority_dict and reroll_count < MAX_BUFF_REROLLS:
                print(f"[tower_loop] no priority match, rerolling buff ({reroll_count + 1}/{MAX_BUFF_REROLLS})")
                self._try_reroll_buff(context)
                reroll_count += 1
                time.sleep(1.5)
                img = context.tasker.controller.post_screencap().wait().get()
                continue

            # 無法再重置或無優先清單 → fallback
            if fallback_box is not None:
                target_box = fallback_box
                print(f"[tower_loop] no priority match after {reroll_count} reroll(s), using fallback")
            else:
                target_box = (350, 430, 90, 30)
                print("[tower_loop] no match, clicking first card area")
            break

        cx, cy = _box_center(target_box)
        context.tasker.controller.post_click(cx, cy).wait()
        time.sleep(1.0)

        # 點拿走
        img2 = context.tasker.controller.post_screencap().wait().get()
        take = context.run_recognition("塔_OCR_拿走", img2)
        if take and take.hit and take.best_result:
            cx2, cy2 = _box_center(take.best_result.box)
            context.tasker.controller.post_click(cx2, cy2).wait()
            print("[tower_loop] 拿走 clicked")
        else:
            print("[tower_loop] 拿走 not found, fallback click at fixed position")
            context.tasker.controller.post_click(335, 710).wait()
        time.sleep(1.5)

    # ──────────────────────────────────────────────────────────────
    # 商店
    # ──────────────────────────────────────────────────────────────

    def _handle_shop_node(self, context: Context, img):
        """商店節點選擇畫面：點「商店購物」進入購物。"""
        # 偵測是否為最終商店（同一畫面出現「離開星塔」而非「上樓」）
        if self._hit(context, img, "塔_偵測_最終離開"):
            self._is_final_room = True
            print("[tower_loop] final room detected (離開星塔 visible)")
        self._click_hit(context, img, "塔_偵測_商店節點")
        time.sleep(2.0)

    def _handle_shop_main(self, context: Context, img) -> bool:
        """商店主界面：掃描 8 格，買有折扣的 buff / 音符；幣多則重置繼續買。

        Returns:
            True  — 正常掃完並離開商店
            False — 商店中途自動關閉（買 buff 後彈出選卡畫面等），交由主迴圈處理
        """
        for reroll_round in range(3):  # 最多原始 + 2 次重置
            items_bought = 0
            shop_closed_early = False
            for grid_idx, roi in _GRID_ROIS.items():
                current_img = context.tasker.controller.post_screencap().wait().get()
                if not self._hit(context, current_img, "塔_偵測_商店主界面"):
                    print(f"[tower_loop] shop main gone at grid {grid_idx}")
                    shop_closed_early = True
                    break
                if self._process_grid(context, grid_idx, roi):
                    items_bought += 1

            if shop_closed_early:
                return False

            if reroll_round < 2 and self._try_reroll_shop(context):
                print(f"[tower_loop] shop rerolled (round {reroll_round + 1}, bought {items_bought})")
                self._log(f"商店第{reroll_round + 1}輪結束：買{items_bought}件 → 刷新繼續")
                time.sleep(1.5)
            else:
                print(f"[tower_loop] shop done (round {reroll_round + 1}, bought {items_bought})")
                self._log(f"商店結束：第{reroll_round + 1}輪 買{items_bought}件 → 離開")
                break

        time.sleep(0.5)
        self._exit_shop_main(context)
        return True

    def _try_reroll_shop(self, context: Context) -> bool:
        """嘗試點擊商店重置按鈕。若成功回傳 True，無法重置回傳 False。"""
        skip_n = self._config.get("skip_shop_rerolls", 0)
        if self._shop_visit_count <= skip_n:
            print(f"[tower_loop] shop reroll skipped: visit #{self._shop_visit_count} <= skip_shop_rerolls {skip_n}")
            return False

        img = context.tasker.controller.post_screencap().wait().get()

        # 幣數不足 650 不刷新（刷新本身要花幣，刷出來的也買不起）
        coins = self._read_coin_amount(context, img)
        if coins < 650:
            print(f"[tower_loop] shop reroll skipped: coins={coins} < 650")
            return False

        result = context.run_recognition("塔_商店_重置按鈕", img)
        if not (result and result.hit and result.best_result):
            print("[tower_loop] reroll button not found, skip")
            return False

        cx, cy = _box_center(result.best_result.box)
        context.tasker.controller.post_click(cx, cy).wait()
        time.sleep(1.0)

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
        time.sleep(0.8)

        img = context.tasker.controller.post_screencap().wait().get()

        # 售罄 → 跳過
        if self._hit(context, img, "塔_商店_售罄"):
            self._log(f"格{grid_idx} 售罄")
            return False

        # 錢不夠 → 跳過
        if self._hit(context, img, "塔_商店_錢不夠"):
            self._log(f"格{grid_idx} 錢不夠")
            return False

        # 沒有打開詳情面板 → 跳過
        if not self._hit(context, img, "塔_商店_購買按鈕"):
            return False

        is_buff = self._hit(context, img, "塔_商店_buff類型")
        is_note = (not is_buff) and self._hit(context, img, "塔_商店_音符類型")
        has_discount = self._hit(context, img, "塔_商店_優惠")

        if is_buff:
            if self._is_final_room or has_discount:
                # 最終商店或有折扣：直接買
                print(f"[tower_loop] grid {grid_idx}: buff ({'final' if self._is_final_room else 'discounted'}), buying")
                self._do_buy(context)
                return True

            # 無折扣：檢查幣數是否充裕（>預留值+200，200 為 buff 原價）
            if not self._strengthen_done_this_room and self._strengthen_reserve > 0:
                coins = self._read_coin_amount(context, img)
                if coins > 0 and coins - 200 < self._strengthen_reserve:
                    print(f"[tower_loop] grid {grid_idx}: buff (no discount), coins={coins} < reserve+200, skip")
                    self._log(f"格{grid_idx} 潛能(原價) 幣={coins} → 跳過(預留{self._strengthen_reserve})")
                    self._close_detail(context, img)
                    return False

            # 無折扣但幣充裕 → 也買（潛能是養成關鍵）
            print(f"[tower_loop] grid {grid_idx}: buff (no discount, coins sufficient), buying")
            self._do_buy(context)
            return True

        if is_note:
            is_activated = self._hit(context, img, "塔_商店_音符激活")

            if self._is_final_room and is_activated:
                # 最終商店：已激活音符也買（幣帶不走）
                print(f"[tower_loop] grid {grid_idx}: activated note (final room), buying")
                self._do_buy(context)
                return True

            if not is_activated:
                self._log(f"格{grid_idx} 音符(未激活) → 跳過")
                self._close_detail(context, img)
                return False

            # 已激活音符：檢查幣數預留
            if not self._strengthen_done_this_room and self._strengthen_reserve > 0:
                coins = self._read_coin_amount(context, img)
                if coins > 0 and coins - 100 < self._strengthen_reserve:
                    print(f"[tower_loop] grid {grid_idx}: activated note, coins={coins} < reserve+100, skip")
                    self._close_detail(context, img)
                    return False

            print(f"[tower_loop] grid {grid_idx}: activated note, buying")
            self._do_buy(context)
            return True

        self._log(f"格{grid_idx} 非潛能/音符 → 跳過")
        self._close_detail(context, img)
        return False

    def _do_buy(self, context: Context):
        """點擊購買確認按鈕。"""
        img = context.tasker.controller.post_screencap().wait().get()
        result = context.run_recognition("塔_商店_購買確認", img)
        if result and result.hit and result.best_result:
            cx, cy = _box_center(result.best_result.box)
            context.tasker.controller.post_click(cx, cy).wait()
            time.sleep(1.5)
            img2 = context.tasker.controller.post_screencap().wait().get()
            if self._hit(context, img2, "塔_商店_錢不夠"):
                context.tasker.controller.post_click(640, 400).wait()
                time.sleep(0.5)
            elif self._hit(context, img2, "塔_偵測_點選空白"):
                self._click_hit(context, img2, "塔_偵測_點選空白")
                time.sleep(1.0)

    def _close_detail(self, context: Context, img):
        """關閉格子詳情面板。"""
        result = context.run_recognition("塔_商店_關閉按鈕", img)
        if result and result.hit and result.best_result:
            cx, cy = _box_center(result.best_result.box)
            context.tasker.controller.post_click(cx, cy).wait()
        else:
            context.tasker.controller.post_click(471 + 335 // 2, 486 + 216 // 2).wait()
        time.sleep(0.6)

    def _exit_shop_main(self, context: Context):
        """從商店主界面返回選擇畫面。"""
        img = context.tasker.controller.post_screencap().wait().get()
        result = context.run_recognition("星塔_节点_商店_返回_agent", img)
        if result and result.hit and result.best_result:
            cx, cy = _box_center(result.best_result.box)
            context.tasker.controller.post_click(cx, cy).wait()
            time.sleep(2.0)
            return
        context.tasker.controller.post_click(50, 35).wait()
        time.sleep(2.0)

    # ──────────────────────────────────────────────────────────────
    # 對話選項
    # ──────────────────────────────────────────────────────────────

    def _handle_dialogue_option(self, context: Context, img):
        """點擊識別到的對話選項文字。若 OCR 失敗則 fallback。"""
        result = context.run_recognition("塔_偵測_對話選項", img)
        if result and result.hit and result.best_result:
            cx, cy = _box_center(result.best_result.box)
            context.tasker.controller.post_click(cx, cy).wait()
            time.sleep(0.5)
            return

        # Fallback 1: 使用突發事件的模板按鈕偵測（藍色圓圈按鈕）
        event_result = context.run_recognition("塔_偵測_突發事件", img)
        if event_result and event_result.hit and event_result.best_result:
            cx, cy = _box_center(event_result.best_result.box)
            context.tasker.controller.post_click(cx, cy).wait()
            print("[tower_loop] dialogue_option OCR failed, used template fallback")
            time.sleep(0.5)
            return

        # Fallback 2: 固定座標點擊第一個對話選項位置
        print("[tower_loop] dialogue_option all fallbacks, clicking fixed position (785, 280)")
        context.tasker.controller.post_click(785, 280).wait()
        time.sleep(0.5)
