import io
import os
from typing import Tuple

from flask import Flask, request, Response, jsonify
from PIL import Image
import pypdfium2 as pdfium

app = Flask(__name__)

API_KEY = os.environ.get("API_KEY", "DEIN_RENDERER_API_KEY")
MAX_FILE_MB = int(os.environ.get("MAX_FILE_MB", "25"))
DEFAULT_SCALE = float(os.environ.get("DEFAULT_SCALE", "1.0"))
DEFAULT_FORMAT = os.environ.get("DEFAULT_FORMAT", "jpg").lower()


def error_response(message: str, status: int = 400):
    return jsonify({
        "ok": False,
        "error": message
    }), status


def require_api_key() -> Tuple[bool, Response | None]:
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


def is_background_pixel(pixel, threshold=235):
    """
    Erkennt helle Hintergrundpixel.
    Schneidet damit auch hellgraue / fast weiße Flächen weg.
    """
    if isinstance(pixel, int):
        return pixel >= threshold

    if len(pixel) >= 3:
        r, g, b = pixel[0], pixel[1], pixel[2]
        return r >= threshold and g >= threshold and b >= threshold

    return False


def find_content_bounds(
    image: Image.Image,
    bg_threshold: int = 235,
    min_non_bg_ratio_row: float = 0.02,
    min_non_bg_ratio_col: float = 0.02
):
    """
    Findet die tatsächlichen Inhaltsgrenzen und ignoriert helle Randflächen.
    """
    if image.mode not in ("RGB", "RGBA", "L"):
        image = image.convert("RGB")

    width, height = image.size
    px = image.load()

    top = 0
    bottom = height - 1
    left = 0
    right = width - 1

    # Top
    for y in range(height):
      non_bg = 0
      for x in range(width):
          if not is_background_pixel(px[x, y], bg_threshold):
              non_bg += 1
      if (non_bg / width) >= min_non_bg_ratio_row:
          top = y
          break

    # Bottom
    for y in range(height - 1, -1, -1):
      non_bg = 0
      for x in range(width):
          if not is_background_pixel(px[x, y], bg_threshold):
              non_bg += 1
      if (non_bg / width) >= min_non_bg_ratio_row:
          bottom = y
          break

    # Left
    for x in range(width):
      non_bg = 0
      for y in range(height):
          if not is_background_pixel(px[x, y], bg_threshold):
              non_bg += 1
      if (non_bg / height) >= min_non_bg_ratio_col:
          left = x
          break

    # Right
    for x in range(width - 1, -1, -1):
      non_bg = 0
      for y in range(height):
          if not is_background_pixel(px[x, y], bg_threshold):
              non_bg += 1
      if (non_bg / height) >= min_non_bg_ratio_col:
          right = x
          break

    return left, top, right, bottom


def trim_background_borders(image: Image.Image) -> Image.Image:
    """
    Entfernt helle / leere Randflächen an allen Seiten.
    """
    if image.mode not in ("RGB", "RGBA", "L"):
        image = image.convert("RGB")

    left, top, right, bottom = find_content_bounds(
        image,
        bg_threshold=235,
        min_non_bg_ratio_row=0.02,
        min_non_bg_ratio_col=0.02
    )

    if right <= left or bottom <= top:
        return image

    return image.crop((left, top, right + 1, bottom + 1))


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
            crop=(0, 0, 0, 0)
        )

        image: Image.Image = bitmap.to_pil()
        image = trim_background_borders(image)

        out = io.BytesIO()

        if out_format in {"jpg", "jpeg"}:
            if image.mode != "RGB":
                image = image.convert("RGB")
            image.save(out, format="JPEG", quality=92, optimize=True)
            return out.getvalue(), "image/jpeg"

        if out_format == "webp":
            if image.mode != "RGB":
                image = image.convert("RGB")
            image.save(out, format="WEBP", quality=92, method=6)
            return out.getvalue(), "image/webp"

        image.save(out, format="PNG", optimize=True)
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