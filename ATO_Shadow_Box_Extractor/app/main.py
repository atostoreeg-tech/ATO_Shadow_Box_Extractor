"""Single-origin FastAPI site and API; short-lived job output (no database)."""
from __future__ import annotations

import io
import json
import os
import secrets
import shutil
import time
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from .processing import (ProcessingError, guided_segment, image_corners,
                         mask_png, pack_zip, produce, read_alpha_mask, read_rgb)

ROOT = Path(__file__).resolve().parent
JOB_DIR = Path(os.environ.get("ATO_JOB_DIR", "/tmp/ato-extractor-jobs"))
JOB_DIR.mkdir(parents=True, exist_ok=True)
JOB_TTL = 60*60  # 1 hour; job IDs are unguessable access capabilities
MAX_UPLOAD = 18*1024*1024
FILES = {"Background.png", "Logo.dxf", "Logo.svg", "Processing_Report.json", "ATO_Exports.zip"}
app = FastAPI(title="ATO Shadow Box Extractor", version="1.0.0", docs_url="/api/docs")


def authorized(key: str | None):
    configured = os.getenv("ATO_ACCESS_KEY", "")
    if configured and not secrets.compare_digest(configured, key or ""):
        raise HTTPException(401,"Incorrect access key.")


async def get_upload(upload: UploadFile, max_size: int = MAX_UPLOAD) -> bytes:
    if not upload.filename:
        raise HTTPException(400,"Upload filename missing.")
    data = await upload.read(max_size+1)
    if len(data) > max_size:
        raise HTTPException(413,f"Upload exceeds {max_size//1024//1024} MB limit.")
    return data


def cleanup_jobs():
    now = time.time()
    for path in JOB_DIR.iterdir():
        if path.is_dir() and now - path.stat().st_mtime > JOB_TTL:
            shutil.rmtree(path,ignore_errors=True)


def new_job(files: dict[str,bytes]) -> str:
    cleanup_jobs()
    token = secrets.token_urlsafe(24)
    job = JOB_DIR / token
    job.mkdir(mode=0o700)
    for name,content in files.items():
        if name not in FILES:
            continue
        (job/name).write_bytes(content)
    (job/"ATO_Exports.zip").write_bytes(pack_zip(files))
    return token


@app.exception_handler(ProcessingError)
async def processing_error_handler(request,exc:ProcessingError):
    return JSONResponse(status_code=422,content={"detail":str(exc)})


@app.get("/api/health")
def health():
    return {"status":"ok","engine":"guided-cv-v1"}


@app.post("/api/corners")
async def corners(image: UploadFile=File(...), x_ato_key: str|None=Header(None)):
    authorized(x_ato_key)
    photo = read_rgb(await get_upload(image))
    result = await run_in_threadpool(image_corners,photo)
    return {"corners":result,
            "notice":"Heuristic candidate only: move all four corners to the INNER artwork boundary."}


@app.post("/api/segment")
async def segment(image: UploadFile=File(...), rect_json: str=Form(...),
                  x_ato_key: str|None=Header(None)):
    authorized(x_ato_key)
    photo = read_rgb(await get_upload(image))
    try:
        rect = json.loads(rect_json)
        if not isinstance(rect,list) or len(rect)!=4:
            raise ValueError()
    except (ValueError,TypeError):
        raise ProcessingError("Invalid selection rectangle.")
    output = await run_in_threadpool(guided_segment,photo,rect)
    return Response(mask_png(output),media_type="image/png")


@app.post("/api/process")
async def process(image: UploadFile=File(...), logo_mask: UploadFile=File(...),
                  engrave_mask: UploadFile=File(...),corners_json:str=Form(...),
                  artwork_width_mm:float=Form(...),dpi:int=Form(300),
                  inpaint_radius:int=Form(5),simplify_px:float=Form(.8),
                  min_contour_area_px:float=Form(6),
                  x_ato_key:str|None=Header(None)):
    authorized(x_ato_key)
    photo_bytes = await get_upload(image)
    mask_bytes = await get_upload(logo_mask)
    engrave_bytes = await get_upload(engrave_mask)
    photo = read_rgb(photo_bytes)
    logo = read_alpha_mask(mask_bytes,photo.shape[:2])
    engrave = read_alpha_mask(engrave_bytes,photo.shape[:2])
    try:
        corners_data = json.loads(corners_json)
        if not isinstance(corners_data,list) or len(corners_data)!=4:
            raise ValueError()
        if any(not isinstance(pt,list) or len(pt)!=2 for pt in corners_data):
            raise ValueError()
    except (ValueError,TypeError):
        raise ProcessingError("Please select four valid corner points.")
    generated,report = await run_in_threadpool(
        produce,photo,logo,engrave,corners_data,artwork_width_mm,dpi,
        inpaint_radius,simplify_px,min_contour_area_px)
    job_id = await run_in_threadpool(new_job,generated)
    return {"job_id":job_id,"report":report,
            "files":{name:f"/api/files/{job_id}/{name}" for name in (*generated.keys(),"ATO_Exports.zip")},
            "expires_in_minutes":60}


@app.get("/api/files/{job_id}/{filename}")
def download(job_id:str,filename:str):
    if not all(c.isalnum() or c in "_-" for c in job_id) or len(job_id)>80:
        raise HTTPException(404,"Not found")
    if filename not in FILES:
        raise HTTPException(404,"Not found")
    job = JOB_DIR / job_id
    file = job / filename
    if not file.is_file() or time.time()-job.stat().st_mtime > JOB_TTL:
        raise HTTPException(404,"File expired or not found")
    media = {".png":"image/png", ".svg":"image/svg+xml",
             ".dxf":"application/dxf", ".zip":"application/zip",
             ".json":"application/json"}.get(file.suffix,"application/octet-stream")
    # The job token is an unguessable temporary capability URL; no index endpoint exists.
    return FileResponse(file,media_type=media,filename=filename if filename != "Logo.svg" else None,
                        content_disposition_type="attachment" if file.suffix != ".svg" else "inline",
                        headers={"Cache-Control":"private, max-age=60", "X-Content-Type-Options":"nosniff"})


app.mount("/static",StaticFiles(directory=ROOT/"static"),name="static")


@app.get("/")
def home():
    return FileResponse(ROOT/"static"/"index.html",headers={"Cache-Control":"no-store"})
