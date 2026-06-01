import os
import tempfile
from io import BytesIO

import fitz
from fastapi import FastAPI, File, UploadFile, HTTPException, Query
from fastapi.responses import Response, JSONResponse
from PIL import Image

app = FastAPI(title="Sunrise Renderer", version="2.0")


API_KEY = os.getenv("RENDERER_API_KEY", "DEIN_RENDERER_API_KEY")


@app.get("/")
def root():
    return {
        "ok": True,
        "service": "sunrise-renderer",
        "version": "2.0"
    }


@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "sunrise-renderer"
    }


@app.post("/render-pdf-page")
async def render_pdf_page(
    key: str = Query(...),
    page: int = Query(0, ge=0),
    scale: float = Query(2.0, ge=0.2, le=5.0),
    format: str = Query("png"),
    file: UploadFile = File(...)
):
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    output_format = format.lower().strip()

    if output_format not in ["png", "jpg", "jpeg", "webp"]:
        raise HTTPException(status_code=400, detail="Unsupported format")

    pdf_bytes = await file.read()

    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Empty PDF file")

    try:
        pdf = fitz.open(stream=pdf_bytes, filetype="pdf")

        if page >= pdf.page_count:
            raise HTTPException(
                status_code=400,
                detail=f"Page index out of range. PDF has {pdf.page_count} pages."
            )

        pdf_page = pdf.load_page(page)

        matrix = fitz.Matrix(scale, scale)
        pix = pdf_page.get_pixmap(matrix=matrix, alpha=False)

        image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        buffer = BytesIO()

        if output_format in ["jpg", "jpeg"]:
            image.save(buffer, format="JPEG", quality=95, optimize=True)
            media_type = "image/jpeg"
        elif output_format == "webp":
            image.save(buffer, format="WEBP", quality=95, method=6)
            media_type = "image/webp"
        else:
            image.save(buffer, format="PNG", optimize=True)
            media_type = "image/png"

        pdf.close()

        return Response(
            content=buffer.getvalue(),
            media_type=media_type
        )

    except HTTPException:
        raise

    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": f"Render fehlgeschlagen: {str(exc)}"
            }
        )