"""
TeamSelectAction — 爬塔前自動切換到正確隊伍

在快速戰鬥的隊伍選擇畫面，根據 preset config.team_members
OCR 識別角色名稱，不符則點右箭頭切換，最多 MAX_SWIPE 次。
找到或超次後皆回傳 True，不中斷後續流程。
"""

import time
from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction

from .tower_loop import _load_preset, _box_center


@AgentServer.custom_action("team_select")
class TeamSelectAction(CustomAction):
    MAX_SWIPE = 20

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        _, config = _load_preset(argv.custom_action_param)
        team_members = config.get("team_members", [])

        if not team_members:
            print("[team_select] no team_members configured, skipping")
            return True

        print(f"[team_select] looking for team: {team_members}")

        for attempt in range(self.MAX_SWIPE + 1):
            img = context.tasker.controller.post_screencap().wait().get()

            if self._team_matches(context, img, team_members):
                print(f"[team_select] found team at attempt {attempt}")
                return True

            if attempt >= self.MAX_SWIPE:
                print(f"[team_select] max swipe ({self.MAX_SWIPE}) reached, proceeding anyway")
                return True

            print(f"[team_select] not matched, clicking right arrow (attempt {attempt + 1})")
            self._click_right_arrow(context, img)
            time.sleep(1.5)

        return True

    def _team_matches(self, context: Context, img, team_members: list) -> bool:
        for name in team_members:
            result = context.run_recognition(
                "塔_選隊_角色名稱",
                img,
                pipeline_override={
                    "塔_選隊_角色名稱": {
                        "recognition": "OCR",
                        "expected": name,
                        "action": "DoNothing",
                    }
                },
            )
            if not (result and result.hit):
                print(f"[team_select] '{name}' not found on screen")
                return False
        return True

    def _click_right_arrow(self, context: Context, img):
        result = context.run_recognition("塔_選隊_右箭頭", img)
        if result and result.hit and result.best_result:
            cx, cy = _box_center(result.best_result.box)
            context.tasker.controller.post_click(cx, cy).wait()
            print(f"[team_select] right arrow OCR at ({cx}, {cy})")
        else:
            context.tasker.controller.post_click(1250, 330).wait()
            print("[team_select] right arrow fallback (1250, 330)")
