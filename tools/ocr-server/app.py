"""
星塔作業 OCR Server
-------------------
用法：
  pip install -r requirements.txt
  python app.py

預設監聽 0.0.0.0:5000
"""

import re
import numpy as np
import cv2
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from paddleocr import PaddleOCR

app = Flask(__name__, static_folder="static")
CORS(app)

# 延遲初始化，第一次請求時載入模型（避免啟動過慢）
_ocr_engine = None


def get_ocr() -> PaddleOCR:
    global _ocr_engine
    if _ocr_engine is None:
        print("[ocr-server] 載入 PaddleOCR 模型中...")
        _ocr_engine = PaddleOCR(
            use_angle_cls=True,
            lang="chinese_cht",   # 繁體中文；若模型不存在改 lang='ch'
            show_log=False,
        )
        print("[ocr-server] 模型載入完成")
    return _ocr_engine


# 節點標籤 → priority
SECTION_MAP = {
    "核心": 3,
    "一般": 2,
    "可選": 1,
    "可选": 1,  # 簡體 fallback
}

# 固定 UI 文字，不視為 buff 名稱
SKIP_TEXTS = {
    "主位", "副位", "副位1", "副位2", "副位 1", "副位 2",
    "STELLABASE", "主力唱片", "替補唱片",
    "核心", "一般", "可選", "可选",
}

# 過濾 regex（純數字、純英文、純符號等）
_SKIP_RE = re.compile(
    r"^[\d★☆✦♦△○◇\s]+$"   # 純數字 / 符號 / 星星
    r"|^[A-Za-z0-9\s\-_\.]+$"  # 純 ASCII
)


def _should_skip(text: str) -> bool:
    t = text.strip()
    if not t:
        return True
    if t in SKIP_TEXTS:
        return True
    if len(t) < 2 or len(t) > 25:
        return True
    if _SKIP_RE.match(t):
        return True
    # 至少要有一個中文字
    if not any("\u4e00" <= c <= "\u9fff" for c in t):
        return True
    return False


def _box_center(box: dict):
    return box["cx"], box["cy"]


def _assign_sections(headers: list, content: list) -> tuple[dict, list]:
    """
    以空間位置將 content 文字分配到最近的上方 section header。
    同欄判斷：水平距離 < 450px 視為同欄。
    回傳 (grouped_dict, unassigned_list)
    """
    grouped = {3: [], 2: [], 1: []}
    unassigned = []

    for box in content:
        best_header = None
        best_score = float("inf")

        for h in headers:
            # header 必須在 content 上方
            if h["cy"] >= box["cy"]:
                continue
            x_dist = abs(h["cx"] - box["cx"])
            y_dist = box["cy"] - h["cy"]

            # 水平距離過大 → 不同欄，跳過
            if x_dist > 450:
                continue

            # score：垂直距離為主，水平偏差為輔
            score = y_dist + x_dist * 0.4
            if score < best_score:
                best_score = score
                best_header = h

        if best_header is not None:
            p = best_header["priority"]
            if box["text"] not in grouped[p]:
                grouped[p].append(box["text"])
        else:
            unassigned.append(box["text"])

    return grouped, unassigned


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/ocr", methods=["POST"])
def ocr_endpoint():
    if "image" not in request.files:
        return jsonify({"error": "請上傳 image 欄位"}), 400

    img_bytes = request.files["image"].read()
    nparr = np.frombuffer(img_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return jsonify({"error": "無法解析圖片，請確認格式"}), 400

    try:
        result = get_ocr().ocr(img, cls=True)
    except Exception as e:
        return jsonify({"error": f"OCR 失敗：{e}"}), 500

    if not result or not result[0]:
        return jsonify({"error": "OCR 未識別到文字"}), 500

    # 解析 OCR 結果
    boxes = []
    for line in result[0]:
        pts, (text, conf) = line
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
        boxes.append({
            "text": text.strip(),
            "x1": x1, "y1": y1, "x2": x2, "y2": y2,
            "cx": (x1 + x2) / 2,
            "cy": (y1 + y2) / 2,
            "conf": round(conf, 3),
        })

    # 分離 section header 和內容文字
    headers = []
    content = []
    for b in boxes:
        if b["text"] in SECTION_MAP:
            headers.append({**b, "priority": SECTION_MAP[b["text"]]})
        elif not _should_skip(b["text"]):
            content.append(b)

    if not headers:
        return jsonify({"error": "未找到「核心」「一般」「可選」標籤，請確認圖片格式"}), 422

    grouped, unassigned = _assign_sections(headers, content)

    return jsonify({
        "grouped": grouped,
        "unassigned": unassigned,
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
