"""Image rectification, guided masking, background cleanup and CAD export.

This is a guided computer-vision pipeline, NOT generative AI. It cannot recover
exact unseen art or guarantee faithful vector lettering from a single photo.
"""
from __future__ import annotations

import io
import json
import math
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
from xml.sax.saxutils import escape as xml_escape

import cv2
import ezdxf
import numpy as np
from PIL import Image, ImageOps

MAX_SOURCE_PIXELS = 20_000_000
MAX_OUTPUT_PIXELS = 24_000_000
MAX_RECTIFIED_SIDE = 7000


class ProcessingError(ValueError):
    """A user-correctable invalid source or processing condition."""


def read_rgb(data: bytes) -> np.ndarray:
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > MAX_SOURCE_PIXELS:
                raise ProcessingError("Image exceeds 20 megapixels.")
            image = ImageOps.exif_transpose(image)
            image = image.convert("RGB")
            return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
    except ProcessingError:
        raise
    except Exception as exc:
        raise ProcessingError("Invalid or unreadable photo.") from exc


def read_alpha_mask(data: bytes, expected_shape: tuple[int, int]) -> np.ndarray:
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.size != (expected_shape[1], expected_shape[0]):
                raise ProcessingError("Mask dimensions must match the uploaded oriented photo.")
            # PNG alpha contains brush opacity. Grayscale masks without alpha
            # are supported only when mode is L; RGB with opaque alpha is not.
            if im.mode == "L":
                out = np.array(im, dtype=np.uint8)
            elif "A" in im.getbands():
                out = np.array(im.getchannel("A"), dtype=np.uint8)
            else:
                raise ProcessingError("Use a transparent PNG mask (alpha channel).")
            return np.where(out >= 100, 255, 0).astype(np.uint8)
    except ProcessingError:
        raise
    except Exception as exc:
        raise ProcessingError("Invalid mask PNG.") from exc


def sort_clockwise_tl(pts: np.ndarray) -> np.ndarray:
    """Return TL, TR, BR, BL from four uniquely spaced convex points."""
    pts = np.asarray(pts, dtype=np.float32).reshape(4, 2)
    if not np.all(np.isfinite(pts)):
        raise ProcessingError("Corners contain invalid values.")
    hull = cv2.convexHull(pts).reshape(-1, 2)
    if len(hull) != 4 or abs(cv2.contourArea(hull)) < 400:
        raise ProcessingError("Select four distinct corners forming a convex rectangle.")
    center = hull.mean(axis=0)
    angles = np.arctan2(hull[:, 1] - center[1], hull[:, 0] - center[0])
    cycle = hull[np.argsort(angles)]
    start = np.argmin(cycle[:, 0] + cycle[:, 1])
    ordered = np.roll(cycle, -int(start), axis=0)
    # Angle sorted in image coordinates leads TL->TR->BR->BL.
    if ordered[1, 0] < ordered[-1, 0]:
        ordered = np.array([ordered[0], ordered[3], ordered[2], ordered[1]])
    return ordered.astype(np.float32)


def image_corners(image: np.ndarray) -> list[list[float]]:
    """Heuristic candidate of the inner rectangular artwork; user MUST verify."""
    h, w = image.shape[:2]
    scaled = image
    ratio = 1.0
    if max(h, w) > 1250:
        ratio = 1250 / max(h, w)
        scaled = cv2.resize(image, None, fx=ratio, fy=ratio)
    gray = cv2.cvtColor(scaled, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, 45, 130)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    min_area = scaled.shape[0] * scaled.shape[1] * 0.13
    candidates = []
    for c in sorted(contours, key=cv2.contourArea, reverse=True)[:120]:
        perimeter = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, .025 * perimeter, True)
        if len(approx) != 4 or cv2.contourArea(approx) < min_area:
            continue
        try:
            poly = sort_clockwise_tl(approx[:, 0, :].astype(float) / ratio)
        except ProcessingError:
            continue
        # Prefer large quadrilateral with modest center proximity penalty.
        area = cv2.contourArea(approx)
        candidates.append((area, poly))
    if candidates:
        return candidates[0][1].round(2).tolist()
    inset = .04
    return [[w*inset,h*inset],[w*(1-inset),h*inset],
            [w*(1-inset),h*(1-inset)],[w*inset,h*(1-inset)]]


def rectangle_dimensions(corners: np.ndarray) -> tuple[int, int]:
    tl, tr, br, bl = corners
    width = max(np.linalg.norm(tr-tl), np.linalg.norm(br-bl))
    height = max(np.linalg.norm(bl-tl), np.linalg.norm(br-tr))
    w, h = int(round(width)), int(round(height))
    if min(w, h) < 80 or max(w, h) > MAX_RECTIFIED_SIDE or w*h > MAX_OUTPUT_PIXELS:
        raise ProcessingError("Artwork is too small or exceeds processing resolution limits.")
    return w, h


def rectify(image: np.ndarray, corners: np.ndarray,
            interpolation: int = cv2.INTER_CUBIC) -> tuple[np.ndarray, np.ndarray]:
    width, height = rectangle_dimensions(corners)
    to_pts = np.array([[0,0],[width-1,0],[width-1,height-1],[0,height-1]], np.float32)
    matrix = cv2.getPerspectiveTransform(corners, to_pts)
    warped = cv2.warpPerspective(image, matrix, (width,height),
                                 flags=interpolation, borderMode=cv2.BORDER_CONSTANT,
                                 borderValue=0)
    return warped, matrix


def guided_segment(image: np.ndarray, rect: Sequence[float]) -> np.ndarray:
    """OpenCV GrabCut foreground candidate from user-selected ROI (not semantic AI)."""
    h, w = image.shape[:2]
    x1,y1,x2,y2 = [int(round(float(v))) for v in rect]
    x1,x2 = sorted((max(0,min(x1,w-1)),max(0,min(x2,w-1))))
    y1,y2 = sorted((max(0,min(y1,h-1)),max(0,min(y2,h-1))))
    if x2-x1 < 15 or y2-y1 < 15:
        raise ProcessingError("Select a larger logo rectangle for Auto Select.")
    # GrabCut may require the source ROI to be distinguishable from its margins.
    mask = np.zeros((h,w), dtype=np.uint8)
    bg, fg = np.zeros((1,65), np.float64), np.zeros((1,65), np.float64)
    try:
        cv2.grabCut(image, mask, (x1,y1,x2-x1,y2-y1), bg, fg, 5, cv2.GC_INIT_WITH_RECT)
    except cv2.error as exc:
        raise ProcessingError("Auto Select could not separate the object. Use the brush tool.") from exc
    return np.where(np.isin(mask, [cv2.GC_FGD, cv2.GC_PR_FGD]), 255, 0).astype(np.uint8)


def mask_png(mask: np.ndarray) -> bytes:
    rgba = np.zeros((*mask.shape,4), dtype=np.uint8)
    rgba[:,:,:3] = 255
    rgba[:,:,3] = mask
    b = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(b, format="PNG")
    return b.getvalue()


def clean_mask(mask: np.ndarray) -> np.ndarray:
    # Only tiny isolated pixels are removed, avoiding unnecessary logo redesign.
    count, comps, stats, _ = cv2.connectedComponentsWithStats((mask > 0).astype(np.uint8), 8)
    keep = np.zeros_like(mask)
    for idx in range(1, count):
        if stats[idx, cv2.CC_STAT_AREA] >= 8:
            keep[comps == idx] = 255
    return keep


@dataclass
class ContourPath:
    points: np.ndarray  # (N,2) float pixels relative to logo bounds
    layer: str


def make_contours(binary: np.ndarray, min_area: float, simplify_px: float,
                  dx: float = 0.0, dy: float = 0.0,
                  engraving: bool = False) -> list[ContourPath]:
    raw, hierarchy = cv2.findContours(binary, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return []
    hierarchy = hierarchy[0]
    result = []
    for index, contour in enumerate(raw):
        if abs(cv2.contourArea(contour)) < min_area:
            continue
        approx = cv2.approxPolyDP(contour, simplify_px, True).reshape(-1,2)
        if len(approx) < 3 or len(np.unique(approx, axis=0)) < 3:
            continue
        parent = int(hierarchy[index][3])
        depth = 0
        while parent >= 0:
            depth += 1
            parent = int(hierarchy[parent][3])
        layer = "ENGRAVE_DETAILS" if engraving else (
            "OUTER_CONTOURS" if depth % 2 == 0 else "INTERNAL_CUTOUTS")
        pts = approx.astype(float)
        pts[:,0] -= dx
        pts[:,1] -= dy
        result.append(ContourPath(pts, layer))
    return result


def to_svg(contours: list[ContourPath], width: float, height: float,
           px_to_mm: float) -> bytes:
    def fmt(v: float) -> str:
        return f"{v:.4f}".rstrip("0").rstrip(".") or "0"
    def path(c: ContourPath) -> str:
        xy = c.points * px_to_mm
        return "M" + " L".join(f"{fmt(x)},{fmt(y)}" for x,y in xy) + " Z"
    shape_paths = [path(c) for c in contours if c.layer != "ENGRAVE_DETAILS"]
    engrave_paths = [path(c) for c in contours if c.layer == "ENGRAVE_DETAILS"]
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{fmt(width)}mm" height="{fmt(height)}mm" viewBox="0 0 {fmt(width)} {fmt(height)}">',
           '<title>ATO Extracted Logo (vector preview)</title>',
           '<desc>Closed contours; dark paths are solid. Internal holes use evenodd fill.</desc>']
    if shape_paths:
        svg.append(f'<path id="solid-logo" d="{xml_escape(" ".join(shape_paths))}" fill="#182B42" fill-rule="evenodd"/>')
    if engrave_paths:
        svg.append(f'<path id="engrave-details" d="{xml_escape(" ".join(engrave_paths))}" fill="#EA9B20" fill-rule="evenodd"/>')
    svg.append('</svg>')
    return "\n".join(svg).encode("utf-8")


def to_dxf(contours: list[ContourPath], bbox_h_px: int,
           scale_mm_per_px: float) -> bytes:
    doc = ezdxf.new("R2010")
    doc.units = ezdxf.units.MM
    doc.header["$INSUNITS"] = 4
    for name, color in (("OUTER_CONTOURS",7),("INTERNAL_CUTOUTS",1),("ENGRAVE_DETAILS",3)):
        doc.layers.new(name, dxfattribs={"color": color})
    model = doc.modelspace()
    for contour in contours:
        points = [((float(x))*scale_mm_per_px,
                   (bbox_h_px-1-float(y))*scale_mm_per_px)
                  for x,y in contour.points]
        model.add_lwpolyline(points, close=True, dxfattribs={"layer":contour.layer})
    # Preserve precision and standard DXF header via ezdxf.
    buffer = io.StringIO()
    doc.write(buffer)
    return buffer.getvalue().encode("utf-8")


def to_png(bgr: np.ndarray, dpi: int) -> bytes:
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    file = io.BytesIO()
    Image.fromarray(rgb).save(file, format="PNG", dpi=(dpi,dpi), optimize=True)
    return file.getvalue()


def produce(image: np.ndarray, logo_mask: np.ndarray, engrave_mask: np.ndarray,
            corners_input: Sequence[Sequence[float]], artwork_width_mm: float,
            dpi: int = 300, inpaint_radius: int = 5, simplify_px: float = .8,
            min_contour_area_px: float = 6.0) -> tuple[dict[str,bytes], dict]:
    if not (20 <= float(artwork_width_mm) <= 2500):
        raise ProcessingError("Enter the real printed artwork width (20–2500 mm).")
    if dpi not in (150, 300, 600):
        raise ProcessingError("DPI must be 150, 300 or 600.")
    if not (2 <= inpaint_radius <= 20 and .1 <= simplify_px <= 5 and 0 <= min_contour_area_px <= 300):
        raise ProcessingError("Processing options are outside allowed ranges.")
    h,w = image.shape[:2]
    if logo_mask.shape != (h,w) or engrave_mask.shape != (h,w):
        raise ProcessingError("Mask size differs from source image.")
    if np.count_nonzero(logo_mask) < 30:
        raise ProcessingError("Paint the raised logo or use Auto Select before exporting.")
    corners = sort_clockwise_tl(np.array(corners_input,dtype=np.float32))
    for x,y in corners:
        if x < 0 or y < 0 or x > w-1 or y > h-1:
            raise ProcessingError("All four artwork corners must be inside the photo.")
    rect, transform = rectify(image, corners)
    rh,rw = rect.shape[:2]
    m = cv2.warpPerspective(logo_mask, transform, (rw,rh), flags=cv2.INTER_NEAREST)
    m = clean_mask(m)
    e = cv2.warpPerspective(engrave_mask, transform, (rw,rh), flags=cv2.INTER_NEAREST)
    if np.count_nonzero(m) < 30:
        raise ProcessingError("Logo is outside artwork bounds. Move corners or repaint the logo.")

    scale = float(artwork_width_mm)/rw  # mm/pixel based on a real user-measured dimension
    target_w = int(round(artwork_width_mm / 25.4 * dpi))
    target_h = int(round(target_w * rh / rw))  # preserve aspect ratio
    if target_w*target_h > MAX_OUTPUT_PIXELS or min(target_w,target_h)<100:
        raise ProcessingError("Requested print size/DPI exceeds 24 megapixels or is too small.")

    # Remove raised geometry PLUS adjacent rim/shadow pixels by a small dilation.
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5,5))
    removal = cv2.dilate(m,kernel,iterations=1)
    background = cv2.inpaint(rect, removal, inpaint_radius, cv2.INPAINT_TELEA)
    background = cv2.resize(background,(target_w,target_h),interpolation=cv2.INTER_LANCZOS4)

    ys,xs = np.where(m > 0)
    left,top,right,bottom = int(xs.min()),int(ys.min()),int(xs.max()),int(ys.max())
    tight = m[top:bottom+1,left:right+1]
    etight = e[top:bottom+1,left:right+1]
    paths = make_contours(tight,min_contour_area_px,simplify_px)
    paths += make_contours(etight,min_contour_area_px,simplify_px,engraving=True)
    if not any(p.layer == "OUTER_CONTOURS" for p in paths):
        raise ProcessingError("Logo mask has no manufacturable closed external contours.")
    bbox_w,bbox_h = right-left+1,bottom-top+1
    svg = to_svg(paths,bbox_w*scale,bbox_h*scale,scale)
    dxf = to_dxf(paths,bbox_h,scale)
    count = {layer:sum(c.layer==layer for c in paths) for layer in
             ("OUTER_CONTOURS","INTERNAL_CUTOUTS","ENGRAVE_DETAILS")}
    warnings = [
        "Background behind the raised logo is estimated by OpenCV inpainting; obscured text/patterns cannot be recovered exactly.",
        "DXF accuracy depends on the manually checked mask; confirm all lettering, holes and boundaries before fabrication.",
        "300 DPI metadata and upscaling cannot create detail absent from the original photo.",
        "This export uses user-provided artwork width, not guessed physical dimensions.",
    ]
    report = {"engine":"ATO CV Guided MVP v1", "image_source_px":[w,h],
              "artwork_rectified_px":[rw,rh], "print_px":[target_w,target_h],
              "artwork_print_mm":[round(artwork_width_mm,3),round(rh*scale,3)],
              "logo_bounds_mm":[round(bbox_w*scale,3),round(bbox_h*scale,3)],
              "dpi":dpi,"mm_per_original_rectified_pixel":round(scale,7),
              "dxf_units":"mm", "contour_counts":count,
              "all_dxf_loops_closed":True, "warnings":warnings}
    return {"Background.png":to_png(background,dpi),
            "Logo.dxf":dxf, "Logo.svg":svg,
            "Processing_Report.json":json.dumps(report,indent=2).encode("utf-8")},report


def pack_zip(files: dict[str,bytes]) -> bytes:
    bio = io.BytesIO()
    with zipfile.ZipFile(bio,"w",zipfile.ZIP_DEFLATED,compresslevel=7) as zf:
        for name,data in files.items():
            zf.writestr(name,data)
    return bio.getvalue()
