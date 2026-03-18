"""
星塔作業 OCR Server
-------------------
使用 PP-OCRv5 ONNX 模型，不需要安裝 PaddlePaddle。

設定模型路徑（擇一）：
  1. 環境變數：OCR_MODEL_DIR=/path/to/ppocr_v5-zh_cn
  2. 直接修改下方 MODEL_DIR 常數

VPS 部署：
  pip install -r requirements.txt
  OCR_MODEL_DIR=/path/to/ppocr_v5-zh_cn python app.py
"""

import os
import re
import numpy as np
import cv2
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from rapidocr_onnxruntime import RapidOCR

app = Flask(__name__, static_folder="static")
CORS(app)

# ── 模型路徑設定 ──────────────────────────────────────────────────
MODEL_DIR = os.environ.get(
    "OCR_MODEL_DIR",
    os.path.join(os.path.dirname(__file__), "models"),  # 預設放在 models/ 子目錄
)
DET_MODEL = os.path.join(MODEL_DIR, "det.onnx")
REC_MODEL = os.path.join(MODEL_DIR, "rec.onnx")
KEYS_FILE  = os.path.join(MODEL_DIR, "keys.txt")
# ──────────────────────────────────────────────────────────────────

_ocr_engine = None


def get_ocr() -> RapidOCR:
    global _ocr_engine
    if _ocr_engine is None:
        print(f"[ocr-server] 載入模型：{MODEL_DIR}")
        _ocr_engine = RapidOCR(
            det_model_path=DET_MODEL,
            rec_model_path=REC_MODEL,
            rec_keys_path=KEYS_FILE,
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

# 固定 UI 文字
SKIP_TEXTS = {
    "主位", "副位", "副位1", "副位2", "副位 1", "副位 2",
    "STELLABASE", "主力唱片", "替補唱片",
    "核心", "一般", "可選", "可选",
}

_SKIP_RE = re.compile(
    r"^[\d★☆✦♦△○◇\s]+$"   # 純數字 / 符號
    r"|^[A-Za-z0-9\s\-_\.]+$"  # 純 ASCII
)


def _should_skip(text: str) -> bool:
    t = text.strip()
    if not t or t in SKIP_TEXTS:
        return True
    if len(t) < 2 or len(t) > 25:
        return True
    if _SKIP_RE.match(t):
        return True
    if not any("\u4e00" <= c <= "\u9fff" for c in t):
        return True
    return False


def _assign_sections(headers: list, content: list) -> tuple[dict, list]:
    """依空間位置將 content 文字分配到最近的上方 section header。"""
    grouped = {3: [], 2: [], 1: []}
    unassigned = []

    for box in content:
        best_header = None
        best_score = float("inf")

        for h in headers:
            if h["cy"] >= box["cy"]:
                continue
            x_dist = abs(h["cx"] - box["cx"])
            y_dist = box["cy"] - h["cy"]
            if x_dist > 450:  # 不同欄
                continue
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
        result, _ = get_ocr()(img)
    except Exception as e:
        return jsonify({"error": f"OCR 失敗：{e}"}), 500

    if not result:
        return jsonify({"error": "OCR 未識別到文字"}), 500

    # rapidocr 回傳格式：[[box_pts, text, confidence], ...]
    boxes = []
    for item in result:
        pts, text, conf = item
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
    return jsonify({"grouped": grouped, "unassigned": unassigned})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
