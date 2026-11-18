# ATO Shadow Box Extractor

A working, **guided** online web app for separating photographed 3D Shadow Boxes into independently downloadable:

- `Background.png` — flattened, rectified artwork with selected raised objects removed by classical OpenCV inpainting and 150 / 300 / 600 DPI metadata.
- `Logo.dxf` — actual AutoCAD R2010 DXF with **closed LWPOLYLINEs**, millimeter units, and separate `OUTER_CONTOURS`, `INTERNAL_CUTOUTS` and `ENGRAVE_DETAILS` layers.
- `Logo.svg` — real SVG vector paths, including an even-odd cutout preview.
- `Processing_Report.json` — traceable dimensions, counts and production warnings.
- `ATO_Exports.zip` — all files together.

## Honest capabilities and limitations

**This version is a working, human-guided computer-vision MVP, not a trained generative AI model.** It supports automatic **candidate** artwork corners (OpenCV contour heuristics) and optional automatic **candidate** logo selection (GrabCut inside a rectangle) plus a precise manual mask editor. The resulting vector quality is limited by the painted mask and the photographed object's geometry. All tiny engravings, internal letters and holes must be visible in the source and correctly selected, or manually painted/erased. Inpainting **estimates**, not reproduces, printed matter hidden behind raised items, especially lettering and complex textures. 300 DPI is output pixel density, not restoration of unknown source resolution. Production-ready **file formats** do not guarantee production-ready **design fidelity**. Inspect and repair complex jobs before CNC, laser cutting or 3D extrusion.

## How to use

1. Upload a clear Shadow Box image (up to 18 MB / 20 MP).
2. Drag 4 yellow handles onto the **inside corners of the printable artwork**. `Detect corners` can propose candidate corners, but verify them.
3. Choose `Auto Select ROI` and drag a rectangle around a raised logo to run OpenCV GrabCut. Or choose `Paint Logo` and brush all the raised pieces. Use `Erase Logo` for internal holes and any wrongly selected background. `Engrave` paints a separate DXF engraving contour layer.
4. Enter the **real physical width of the background artwork** in mm, measured by you. The program preserves the rectified aspect ratio and derives height, logo scaling and pixel print dimensions. It never guesses scale from the photograph.
5. Choose DPI and extraction parameters, then click `Generate production files`.
6. Inspect the transparent logo preview and reconstructed PNG, download PNG / DXF / SVG separately or get ZIP. Files expire after **60 minutes** from server storage.

## Local development

Requires Python 3.11 or newer (3.11 recommended). In project root:

```bash
python -m venv .venv
# Windows Powershell:
.venv\Scripts\Activate.ps1
# macOS / Linux:
# source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Visit <http://127.0.0.1:8000/>. API docs: <http://127.0.0.1:8000/api/docs>. Run tests with `pytest -q`.

### Docker run

```bash
docker build -t ato-extractor .
docker run --rm -p 10000:10000 -e ATO_ACCESS_KEY="your-long-secret-key" ato-extractor
```

Visit <http://localhost:10000>. Leave `ATO_ACCESS_KEY` unset **only** when you're comfortable with a publicly usable processing endpoint (not advised for online deployment). The app has no account system or payment, and the access key only gates processing. Unpredictable temporary download URLs are not login-protected; do not share their links.

## Deploy online (Render)

1. Push the extracted project folder to a **private GitHub repository**. If working from project root, initialize repository and push code (never put `.env` or customer photos in Git).
2. Log in to [Render](https://render.com), click **New → Web Service**, and connect the repository. Choose **Docker** (auto-detected from `Dockerfile`).
3. Choose **Starter** or higher with enough available RAM (OpenCV memory may grow substantially for 20 MP photos). Use `render.yaml` as a Blueprint alternative, if preferred.
4. Set environment variable `ATO_ACCESS_KEY` to a long random secret in Render dashboard. Health-check path: `/api/health`.
5. After deploy, open your Render HTTPS domain. The UI and backend share the same domain, so no CORS configuration or separate front-end deployment is required.
6. For a custom ATO domain, add a **Custom Domain** in Render dashboard and configure DNS as instructed there.

Hosting behavior: single-worker CPU processing; temporary files under `/tmp/ato-extractor-jobs` expire after 60 minutes and may disappear earlier on restart/redeploy. Output storage is not persistent. If many users process photos concurrently, add an authenticated job queue and external object storage (e.g., S3/R2), then GPU/hosted AI segmentation & inpainting if needed. Deployment to Render requires the user's own account/repository; this ZIP alone does not provision a live URL.

## Routes

- `GET /` — web app
- `GET /api/health` — health response
- `POST /api/corners` — heuristic 4-corner proposal; multipart `image`
- `POST /api/segment` — guided GrabCut; multipart `image`, `rect_json=[x1,y1,x2,y2]`
- `POST /api/process` — multipart `image`, `logo_mask`, `engrave_mask`, `corners_json` (four `[x,y]` source-pixel points), `artwork_width_mm`, `dpi`, `inpaint_radius`, `simplify_px`, `min_contour_area_px`
- `GET /api/files/{job_id}/{filename}` — retrieve one short-lived output file (job token acts as access capability)

`X-ATO-Key` header is required on POST endpoints if `ATO_ACCESS_KEY` is set.

## Security, privacy & future improvements

Uploads are never intentionally retained; process memory data is released after request, only exported output is stored temporarily. Use HTTPS in production; use an application-level login or VPN for customer designs; avoid embedding production API keys in front-end code. Temporary result links aren't authenticated. File limits, pixel caps, no user-provided filenames for writes, SVG generated only from numeric coordinates, DXF unit metadata and time-limited exports reduce basic risk, but this is **not a fully security-audited SaaS**. Add account login, rate limiting, queues, quotas, audit logging, backup policies, object-storage lifecycle policies, and virus scanning before opening to the public.

**Recommended v2:** production AI mask (SAM2 served on GPU), sophisticated diffusion/AI inpainting, native vector text / shape corrections, contour topology and self-intersection audit, multiple logo parts, masking import/export, batch queue, true uncertainty markers when art is occluded, and a printer/CAD calibration check against a physical reference. A regular photograph can't reveal the actual 3D depth; `Logo.dxf` is 2D profile geometry only.
