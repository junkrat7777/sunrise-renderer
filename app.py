import io
import os
from typing import Tuple

from flask import Flask, request, Response, jsonify
from PIL import Image
import pypdfium2 as pdfium

app = Flask(__name__)

API_KEY = os.environ.get("API_KEY", "DEIN_RENDERER_API_KEY")
MAX_FILE_MB = int(os.environ.get("MAX_FILE_MB", "25"))
DEFAULT_SCALE = float(os.environ.get("DEFAULT_SCALE", "2.4"))
DEFAULT_FORMAT = os.environ.get("DEFAULT_FORMAT", "png").lower()


def error_response(message: str, status: int = 400):
    return jsonify({
        "ok": False,
        "error": message
    }), status


def require_api_key() -> Tuple[bool, Response]:
    key = request.args.get("key", "").strip()
    if not API_KEY or key != API_KEY:
        return False, Response("Unauthorized", status=401)
    return True, None


def get_uploaded_pdf():
    file = request.files.get("file")
    if file is None:
        return None, "Datei 'file' fehlt."

    filename = (file.filename or "").lower()
    content_type = (file.content_type or "").lower()

    raw = file.read()
    if not raw:
        return None, "Leere Datei erhalten."

    if len(raw) > MAX_FILE_MB * 1024 * 1024:
        return None, f"Datei zu groß. Maximal {MAX_FILE_MB} MB."

    if not filename.endswith(".pdf") and "pdf" not in content_type:
        return None, "Datei ist keine PDF."

    return raw, None


def clamp_page(page: int, page_count: int) -> int:
    if page < 0:
        return 0
    if page >= page_count:
        return max(0, page_count - 1)
    return page


def render_pdf_page(pdf_bytes: bytes, page_index: int, scale: float, out_format: str) -> Tuple[bytes, str]:
    pdf = pdfium.PdfDocument(pdf_bytes)
    try:
        page_count = len(pdf)
        if page_count <= 0:
          raise ValueError("PDF enthält keine Seiten.")

        page_index = clamp_page(page_index, page_count)
        page = pdf[page_index]

        bitmap = page.render(
            scale=scale,
            rotation=0,
            crop=(0, 0, 0, 0),
            maybe_alpha=False
        )

        pil_image: Image.Image = bitmap.to_pil()

        out = io.BytesIO()

        if out_format == "jpg" or out_format == "jpeg":
            if pil_image.mode != "RGB":
                pil_image = pil_image.convert("RGB")
            pil_image.save(out, format="JPEG", quality=95, optimize=True)
            return out.getvalue(), "image/jpeg"

        if out_format == "webp":
            if pil_image.mode != "RGB":
                pil_image = pil_image.convert("RGB")
            pil_image.save(out, format="WEBP", quality=95, method=6)
            return out.getvalue(), "image/webp"

        pil_image.save(out, format="PNG", optimize=True)
        return out.getvalue(), "image/png"
    finally:
        pdf.close()


@app.route("/health", methods=["GET"])
def health():
    ok, resp = require_api_key()
    if not ok:
        return resp
    return jsonify({
        "ok": True,
        "service": "sunrise-pdf-renderer"
    })


@app.route("/render-pdf-page", methods=["POST"])
def render_pdf_page_route():
    ok, resp = require_api_key()
    if not ok:
        return resp

    pdf_bytes, err = get_uploaded_pdf()
    if err:
        return error_response(err, 400)

    try:
        page = int(request.args.get("page", "0"))
    except ValueError:
        return error_response("Ungültiger Parameter 'page'.", 400)

    try:
        scale = float(request.args.get("scale", str(DEFAULT_SCALE)))
    except ValueError:
        return error_response("Ungültiger Parameter 'scale'.", 400)

    out_format = request.args.get("format", DEFAULT_FORMAT).strip().lower()
    if out_format not in {"png", "jpg", "jpeg", "webp"}:
        return error_response("Ungültiger Parameter 'format'. Erlaubt: png, jpg, jpeg, webp", 400)

    if scale <= 0 or scale > 8:
        return error_response("Parameter 'scale' muss > 0 und <= 8 sein.", 400)

    try:
        image_bytes, content_type = render_pdf_page(
            pdf_bytes=pdf_bytes,
            page_index=page,
            scale=scale,
            out_format=out_format
        )
    except Exception as exc:
        return error_response(f"Render fehlgeschlagen: {exc}", 500)

    return Response(
        image_bytes,
        status=200,
        content_type=content_type,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"
        }
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)