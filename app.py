from io import BytesIO
import os

from fastapi import FastAPI, File, UploadFile, HTTPException, Query
from fastapi.responses import Response

app = FastAPI()

API_KEY = os.getenv("API_KEY", "DEIN_RENDERER_API_KEY")

@app.get("/")
def root():
    return {"ok": True, "service": "sunrise-renderer"}


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/render-pdf-page")
async def render_pdf_page(
    key: str = Query(...),
    page: int = Query(0),
    scale: float = Query(2.0),
    format: str = Query("png"),
    file: UploadFile = File(...)
):
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    import fitz
    from PIL import Image

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Empty PDF")

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    if page < 0 or page >= doc.page_count:
        raise HTTPException(status_code=400, detail="Page out of range")

    pix = doc.load_page(page).get_pixmap(
        matrix=fitz.Matrix(scale, scale),
        alpha=False
    )

    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    buf = BytesIO()

    fmt = format.lower()

    if fmt in ["jpg", "jpeg"]:
        img.save(buf, format="JPEG", quality=95)
        media = "image/jpeg"
    else:
        img.save(buf, format="PNG")
        media = "image/png"

    doc.close()

    return Response(content=buf.getvalue(), media_type=media)