<!-- markdownlint-disable MD033 MD041 -->

<div align="center">
    <img src="assets/logo.png" alt="StellaSora-Auto-Helper" width="200" />
    <h1>MaaStellaSora <sub><sup>TW</sup></sub></h1>
    <p>星塔助手台服版（MaaStellaSora_TW）— 繁體中文台服適配，由 MaaFramework 強力驅動</p>
    <p><i>Fork 自 <a href="https://github.com/MaaStellaSora/MaaStellaSora">MaaStellaSora/MaaStellaSora</a>，由台服玩家獨立維護</i></p>
</div>

---

## 🇹🇼 台服版說明

本版本為 [MaaStellaSora](https://github.com/MaaStellaSora/MaaStellaSora) 的台服（繁體中文）適配 Fork，由台服玩家 [Arcelibs](https://github.com/Arcelibs) 維護。

**下載請至本 Fork 的 [Releases 頁面](https://github.com/Arcelibs/MaaStellaSora/releases)**

### 台服版特色

- 🌏 **全繁體中文 OCR 適配** — 所有介面文字、Buff 名稱、按鈕識別均已繁化
- 🏰 **爬塔自動抄作業** — 以 Python 狀態機驅動，支援自訂 Buff 優先清單（preset）
- 👥 **自動選隊伍** — 爬塔前根據 preset 設定自動切換至指定隊伍組合
- 🛒 **智慧商店購物** — 自動判斷折扣 buff、已激活音符；購買 buff 觸發選卡後可自動銜接
- 🔄 **接續爬塔作業** — 可從中途中斷的爬塔狀態直接接管，不消耗票

### 現有隊伍 Preset

| 隊伍 | 作業檔 |
|---|---|
| 千都世＋蒼蘭＋特麗莎（水） | `qiandushi-water.json` |
| 希婭＋密捏瓦＋緹莉婭（夜兔流） | `xiya_miniewa_tiliya_yetuliu.json` |
| 希婭＋密捏瓦＋緹莉婭（雪兔流） | `xiya_miniewa_tiliya_xuetu.json` |
| 風影＋夏花＋杏子（普攻流） | `fengying_xiahua_xingzi_pugong.json` |
| 翡冷翠＋縹莉姬＋珂賽特（技傷流） | `feilengcui_piaoliji_kesaite_jishang.json` |

---

## 功能

- [x] 登录游戏并签到
- [x] 清理活动
- [x] 赠礼
- [x] 五次邀约
- [x] 领取&发送好友干劲
- [x] 领取委托并重新派遣
- [x] 领取任务
- [x] 自动爬塔（含台服繁體適配與抄作業功能）
- [x] 自动进行指定关卡
- [ ] 自动刷记录（根据优先度）
- [ ] 更多内容实现中

## 安装与使用

> 星塔助手目前只对比例为16:9的游戏客户端提供支持，如果你的游戏客户端比例不为16:9请自行寻找改分辨率方法或是使用模拟器

1. 前往本 Fork 的 [Releases 頁面](https://github.com/Arcelibs/MaaStellaSora/releases) 下載最新版本
2. 解壓縮至任意目錄，執行 `依赖库安装.bat`
3. 啟動 `MFAAvalonia.exe`（ADB 模式直接啟動即可，不需要管理員權限）
4. **資源類型請選「台服」**（已設為預設值）

---

## 鸣谢

本项目由 **[MaaFramework](https://github.com/MaaXYZ/MaaFramework)** 强力驱动！

本项目部分功能使用 **[MaaPipelineEditor](https://github.com/kqcoxn/MaaPipelineEditor)** 进行辅助编辑

感谢原作者及以下开发者对上游项目作出的贡献:

[![Contributors](https://contrib.rocks/image?repo=MaaStellaSora/MaaStellaSora&max=1000)](https://github.com/MaaStellaSora/MaaStellaSora/graphs/contributors)

## 相关项目

- **[MaaStellaSora](https://github.com/MaaStellaSora/MaaStellaSora)** 上游原版項目
- **[MaaFramework](https://github.com/MaaXYZ/MaaFramework)** 基于图像识别的自动化黑盒测试框架
- **[MFAAvalonia](https://github.com/SweetSmellFox/MFAAvalonia)** 基于 Avalonia 的 通用 GUI。由 MaaFramework 强力驱动！
- **[MaaPipelineEditor](https://github.com/kqcoxn/MaaPipelineEditor)** 可视化阅读与构建 Pipeline，功能完备，极致轻量跨平台
