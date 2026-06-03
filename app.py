from io import BytesIO
import os

import fitz
from flask import Flask, request, jsonify, Response
from PIL import Image, ImageChops

app = Flask(__name__)

API_KEY = "DEIN_RENDERER_API_KEY"


@app.get("/")
def root():
    return jsonify({"ok": True, "service": "sunrise-renderer"})


@app.get("/health")
def health():
    return jsonify({"ok": True})


def trim_white_border(image):
    bg = Image.new(image.mode, image.size, (255, 255, 255))
    diff = ImageChops.difference(image, bg)
    diff = ImageChops.add(diff, diff, 2.0, -20)

    bbox = diff.getbbox()

    if bbox:
        return image.crop(bbox)

    return image


@app.post("/render-pdf-page")
def render_pdf_page():
    try:
        key = request.args.get("key", "")
        page = int(request.args.get("page", "0"))
        scale = float(request.args.get("scale", "2.0"))
        fmt = request.args.get("format", "png").lower()

        if key != API_KEY:
            return jsonify({"ok": False, "error": "Unauthorized"}), 401

        uploaded = request.files.get("file")

        if not uploaded:
            return jsonify({"ok": False, "error": "file missing"}), 400

        pdf_bytes = uploaded.read()

        if not pdf_bytes:
            return jsonify({"ok": False, "error": "empty pdf"}), 400

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")

        if page < 0 or page >= doc.page_count:
            return jsonify({
                "ok": False,
                "error": "page out of range",
                "page_count": doc.page_count
            }), 400

        pix = doc.load_page(page).get_pixmap(
            matrix=fitz.Matrix(scale, scale),
            alpha=False
        )

        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        img = trim_white_border(img)

        buf = BytesIO()

        if fmt in ["jpg", "jpeg"]:
            img.save(buf, format="JPEG", quality=95)
            media_type = "image/jpeg"
        else:
            img.save(buf, format="PNG")
            media_type = "image/png"

        doc.close()

        return Response(buf.getvalue(), mimetype=media_type)

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e),
            "type": type(e).__name__
        }), 500