import os
import collections
import cv2
import math
import shutil
import queue
import threading as _threading
import subprocess
import tempfile
import numpy as np
# PaddleOCR is imported lazily inside get_ocr_instance() to avoid crashing
# the orchestrator at startup when torch/paddle DLLs are unavailable.

# --- NVENC caching ---
_NVENC_AVAILABLE: bool | None = None

def _check_nvenc_cached() -> bool:
    global _NVENC_AVAILABLE
    if _NVENC_AVAILABLE is None:
        try:
            # Being LISTED in -encoders does not mean a session can actually be opened with our
            # params (driver/session-limit/unsupported -preset/-tune all fail at open time and
            # used to crash the whole writer). Do a real 1-frame test encode WITH the same params
            # we use below; fall back to libx264 if it fails.
            res = subprocess.run(
                ['ffmpeg', '-hide_banner', '-f', 'lavfi', '-i', 'color=c=black:s=256x256:d=0.2',
                 '-c:v', 'h264_nvenc', '-preset', 'p6', '-tune', 'hq', '-b:v', '5M', '-f', 'null', '-'],
                capture_output=True, timeout=25
            )
            _NVENC_AVAILABLE = (res.returncode == 0)
            if not _NVENC_AVAILABLE:
                print("[VideoProcess] h264_nvenc không khả dụng (test encode lỗi) → dùng libx264.")
        except Exception:
            _NVENC_AVAILABLE = False
    return _NVENC_AVAILABLE

# --- Opt 7: Threading lock for OCR singleton (multi-job safety) ---
_ocr_lock = _threading.Lock()
_ocr_instance = None

class _EasyOCRDetector:
    """Adapter exposing PaddleOCR's `.ocr(img, det, rec, cls)` over EasyOCR's CRAFT text detector
    (pure PyTorch → runs on the working cuDNN-9 GPU, unlike paddlepaddle which needs cuDNN 8).
    Returns Paddle-style 4-point polygon lists so `_parse_ocr_boxes` and every caller work unchanged."""

    def __init__(self, reader):
        self._reader = reader

    @staticmethod
    def _to_polys(horiz, free):
        polys = []
        for b in (horiz or []):                        # axis-aligned: [xmin, xmax, ymin, ymax]
            x1, x2, y1, y2 = int(b[0]), int(b[1]), int(b[2]), int(b[3])
            polys.append([[x1, y1], [x2, y1], [x2, y2], [x1, y2]])
        for quad in (free or []):                       # rotated quads: [[x,y]*4]
            if quad:
                polys.append([[int(p[0]), int(p[1])] for p in quad])
        return polys

    def ocr(self, img, det=True, rec=False, cls=False):
        # CRAFT is trained on RGB; callers pass BGR (cv2 frames / ffmpeg bgr24) → convert.
        horiz, free = self._reader.detect(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        return [self._to_polys(horiz[0] if horiz else [], free[0] if free else [])]

    def ocr_batch(self, imgs_bgr):
        """Detect text on a batch of SAME-SIZE BGR frames in ONE GPU forward pass.
        EasyOCR's detect() already batches when given a 4-D array with reformat=False
        (test_net stacks the batch → one CRAFT forward). Returns a list (per frame) of
        [polys] — identical shape/grouping to ocr() called per frame, just far fewer GPU
        launches. All frames MUST share the same H×W (they do: each is downscaled to the
        same OCR size)."""
        if not imgs_bgr:
            return []
        rgb = np.stack([cv2.cvtColor(im, cv2.COLOR_BGR2RGB) for im in imgs_bgr])  # [K,H,W,3]
        horiz_agg, free_agg = self._reader.detect(rgb, reformat=False)
        return [[self._to_polys(h, f)] for h, f in zip(horiz_agg, free_agg)]


def get_ocr_instance():
    global _ocr_instance
    with _ocr_lock:
        if _ocr_instance is None:
            import easyocr
            weights_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models", "easyocr")
            try:
                import torch
                want_gpu = bool(torch.cuda.is_available())
            except Exception:
                want_gpu = False

            def _make(gpu):
                # detector-only (recognizer=False) — we only need text boxes, the pipeline does its
                # own blur/inpaint. Offline: load the vendored craft weight, never download.
                return easyocr.Reader(['en'], gpu=gpu, recognizer=False, verbose=False,
                                      download_enabled=False, model_storage_directory=weights_dir)

            def _ok(reader):
                try:
                    reader.detect(np.zeros((64, 64, 3), dtype=np.uint8))
                    return True
                except Exception as e:
                    print(f"[VideoProcess] EasyOCR GPU smoke test failed: {e}")
                    return False

            reader = _make(want_gpu)
            if want_gpu and not _ok(reader):
                print("[VideoProcess] EasyOCR GPU unavailable → CPU.")
                reader = _make(False)
                want_gpu = False
            _ocr_instance = _EasyOCRDetector(reader)
            print(f"[VideoProcess] EasyOCR (CRAFT) detector ready on {'GPU' if want_gpu else 'CPU'}.")
        return _ocr_instance


# --- Opt 2: Downscale frame for OCR, scale boxes back ---
OCR_MAX_H = 480

def _scale_frame_for_ocr(frame):
    h, w = frame.shape[:2]
    if h <= OCR_MAX_H:
        return frame, 1.0
    scale = OCR_MAX_H / h
    small = cv2.resize(frame, (int(w * scale), OCR_MAX_H), interpolation=cv2.INTER_AREA)
    return small, scale


def _parse_ocr_boxes(result, small_w, small_h, width, height):
    """Parse OCR result (rec=False format) into list of (x, y, w, h) tuples in ORIGINAL-frame coords.

    OCR runs on a frame downscaled to (small_w × small_h), so detections must be back-projected to
    the original (width × height). The horizontal and vertical ratios are computed INDEPENDENTLY
    (sx = width/small_w, sy = height/small_h): the downscaled width is rounded to an even number
    (out_w -= out_w%2) / truncated (int(w*scale)), so it does NOT preserve the exact aspect ratio —
    using a single isotropic scalar drifted every X coordinate a few px (worse toward the right
    edge). Padding + edge clamp are done in DOWNSCALED space (so the ~10px margin keeps its intended
    on-screen size after back-projection, and the clamp uses the matching small_w/small_h instead of
    the original dims it was wrongly compared against before)."""
    boxes = []
    if not result or not result[0]:
        return boxes
    sx = width / small_w if small_w else 1.0
    sy = height / small_h if small_h else 1.0
    # Robust to both PaddleOCR output shapes:
    #   det+rec  → item = [box, (text, score)]   → box = item[0]
    #   det-only → item IS the box ([[x1,y1],...]) (rec=False)
    for item in result[0]:
        try:
            first = item[0]
            if isinstance(first, (list, tuple)) and first and isinstance(first[0], (list, tuple)):
                box = first      # item = [box, rec_result]
            else:
                box = item       # item is the polygon itself (rec=False)
            x_coords = [p[0] for p in box]
            y_coords = [p[1] for p in box]

            # Pad + clamp in downscaled space (the space the coords are actually in)...
            pad = 10
            xs0 = max(0, min(x_coords) - pad)
            ys0 = max(0, min(y_coords) - pad)
            xs1 = min(small_w, max(x_coords) + pad)
            ys1 = min(small_h, max(y_coords) + pad)

            # ...then back-project to the original frame with independent x/y scale.
            x = int(round(xs0 * sx))
            y = int(round(ys0 * sy))
            w_final = int(round((xs1 - xs0) * sx))
            h_final = int(round((ys1 - ys0) * sy))

            if w_final > 0 and h_final > 0:
                boxes.append((x, y, w_final, h_final))
        except Exception:
            pass
    return boxes


# --- Opt 3: Static box detection across full video ---
STATIC_SCAN_FRAMES = 30
STATIC_THRESHOLD = 0.7  # box must appear in 70% of scan frames

def _detect_static_boxes(input_path: str, ocr, fps: float, width: int, height: int, total_frames: int) -> list[tuple]:
    """Scan 30 frames phân bố đều toàn video để tìm watermark tĩnh."""
    n = min(STATIC_SCAN_FRAMES, max(3, total_frames))
    if total_frames <= 1:
        return []  # Not enough frames for meaningful static detection
    indices = [int(i * (total_frames - 1) / (n - 1)) for i in range(n)]

    box_counts: dict = {}
    box_map: dict = {}
    scanned = 0

    cap = cv2.VideoCapture(input_path)
    try:
        for fi in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
            ret, frame = cap.read()
            if not ret or frame is None:
                continue
            small, _ = _scale_frame_for_ocr(frame)
            sh, sw = small.shape[:2]
            with _ocr_lock:
                result = ocr.ocr(small, det=True, rec=False, cls=False)
            boxes = _parse_ocr_boxes(result, sw, sh, width, height)
            for box in boxes:
                x, y, w, h = box
                key = (x // _GRID, y // _GRID)
                box_counts[key] = box_counts.get(key, 0) + 1
                box_map[key] = box
            scanned += 1
    finally:
        cap.release()

    threshold = max(1, int(scanned * STATIC_THRESHOLD))
    return [box_map[k] for k, cnt in box_counts.items() if cnt >= threshold]


def build_temporal_reference(input_path: str, n_samples: int = 20) -> np.ndarray | None:
    """Sample n_samples frames đều toàn video, tính median → clean background."""
    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        return None

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames < 3:
        cap.release()
        return None

    n = min(n_samples, total_frames)
    if n < 2:
        cap.release()
        return None

    indices = [int(i * (total_frames - 1) / (n - 1)) for i in range(n)]

    frames = []
    for idx in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if ret and frame is not None:
            frames.append(frame)

    cap.release()

    if len(frames) < 3:
        return None

    stack = np.stack(frames, axis=0).astype(np.float32)
    return np.median(stack, axis=0).astype(np.uint8)


def apply_temporal_inpaint(
    frame: np.ndarray,
    reference: np.ndarray | None,
    static_boxes: list[tuple],
    dynamic_boxes: list[tuple],
) -> np.ndarray:
    """Legacy TELEA inpainting — kept for backward compatibility. Use apply_blur_to_frame instead."""
    result = frame.copy()

    if reference is not None:
        h_f, w_f = frame.shape[:2]
        for (x, y, w, h) in static_boxes:
            y2 = min(y + h, h_f)
            x2 = min(x + w, w_f)
            result[y:y2, x:x2] = reference[y:y2, x:x2]
        all_dynamic = list(dynamic_boxes)
    else:
        all_dynamic = list(static_boxes) + list(dynamic_boxes)

    if not all_dynamic:
        return result

    mask = np.zeros(frame.shape[:2], dtype=np.uint8)
    for (x, y, w, h) in all_dynamic:
        pad = 3
        x1 = max(0, x - pad)
        y1 = max(0, y - pad)
        x2 = min(frame.shape[1], x + w + pad)
        y2 = min(frame.shape[0], y + h + pad)
        mask[y1:y2, x1:x2] = 255

    if mask.max() == 0:
        return result

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        cx1 = max(0, x - 10)
        cy1 = max(0, y - 10)
        cx2 = min(frame.shape[1], x + w + 10)
        cy2 = min(frame.shape[0], y + h + 10)
        crop_frame = result[cy1:cy2, cx1:cx2]
        crop_mask = mask[cy1:cy2, cx1:cx2]
        result[cy1:cy2, cx1:cx2] = cv2.inpaint(crop_frame, crop_mask, 3, cv2.INPAINT_TELEA)

    return result


def apply_blur_to_frame(
    frame: np.ndarray,
    static_boxes: list[tuple],
    dynamic_boxes: list[tuple],
) -> np.ndarray:
    """
    Smooth blur path: Cực kỳ thu nhỏ sau đó phóng to nội suy CUBIC.
    Tạo ra một vệt màu gradient mịn màng xóa hoàn toàn nét chữ, mượt hơn pixelate blocky.
    """
    all_boxes = list(static_boxes) + list(dynamic_boxes)
    if not all_boxes:
        return frame
    result = frame.copy()
    h_f, w_f = frame.shape[:2]
    for (x, y, w, h) in all_boxes:
        x2 = min(x + w, w_f)
        y2 = min(y + h, h_f)
        region = result[y:y2, x:x2]
        rh, rw = region.shape[:2]
        if rh < 3 or rw < 3:
            continue
        
        # Làm mờ siêu mịn bằng extreme downscale + CUBIC upscale
        # Chỉ giữ lại 4x4 pixel màu trung bình, sau đó phóng to lên lại
        small = cv2.resize(region, (4, 4), interpolation=cv2.INTER_AREA)
        blurred_region = cv2.resize(small, (rw, rh), interpolation=cv2.INTER_CUBIC)
        
        # Tùy chọn: Thêm một chút viền mềm (feather) ở viền
        blurred_region = cv2.GaussianBlur(blurred_region, (7, 7), sigmaX=3)
        
        result[y:y2, x:x2] = blurred_region
    return result


# --- Dynamic content detection: quick whole-video scan ---
_DYNAMIC_CHECK_FRAMES = 8

def _has_dynamic_text(
    input_path: str,
    ocr,
    static_boxes: list[tuple],
    total_frames: int,
    width: int,
    height: int,
) -> bool:
    """
    Sample _DYNAMIC_CHECK_FRAMES frames trải đều TOÀN BỘ video (0–100%).
    Trả về True nếu phát hiện chữ NẰM NGOÀI vùng watermark tĩnh đã biết.
    Bias về độ nhạy: bỏ sót ở đây = chữ động không bao giờ được làm mờ, còn báo nhầm
    chỉ tốn thêm một lần Pre-pass C. (Trước đây chỉ quét 20%–80% nên bỏ sót phụ đề
    chỉ xuất hiện ở 20% đầu hoặc cuối video.)
    """
    if total_frames < _DYNAMIC_CHECK_FRAMES:
        return False

    # Build coarse grid (20px cells) of known static watermark area for fast lookup
    static_grid: set = set()
    for (bx, by, bw, bh) in static_boxes:
        for gx in range(bx // _GRID, (bx + bw) // _GRID + 1):
            for gy in range(by // _GRID, (by + bh) // _GRID + 1):
                static_grid.add((gx, gy))

    # Evenly spaced across the entire timeline (not just the middle 60%).
    indices = [int(i * (total_frames - 1) / (_DYNAMIC_CHECK_FRAMES - 1)) for i in range(_DYNAMIC_CHECK_FRAMES)]

    cap = cv2.VideoCapture(input_path)
    found = False
    try:
        for fi in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
            ret, frame = cap.read()
            if not ret or frame is None:
                continue
            small, _ = _scale_frame_for_ocr(frame)
            sh, sw = small.shape[:2]
            with _ocr_lock:
                result = ocr.ocr(small, det=True, rec=False, cls=False)
            boxes = _parse_ocr_boxes(result, sw, sh, width, height)
            for (cx, cy, cw, ch) in boxes:
                if (cx // _GRID, cy // _GRID) not in static_grid:
                    found = True
                    break
            if found:
                break
    finally:
        cap.release()
    return found


# --- Opt 4: cv2.inpaint instead of GaussianBlur ---
def apply_inpaint_to_frame(frame, boxes, mask_only=False):
    """Inpaint text regions using TELEA algorithm on localized crops for massive speedup, or return mask."""
    mask = np.zeros(frame.shape[:2], dtype=np.uint8)
    for (x, y, w, h) in boxes:
        # expand mask slightly for better inpainting
        pad = 3
        x1 = max(0, x - pad)
        y1 = max(0, y - pad)
        x2 = min(frame.shape[1], x + w + pad)
        y2 = min(frame.shape[0], y + h + pad)
        mask[y1:y2, x1:x2] = 255
        
    if mask_only:
        return cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
        
    if mask.max() == 0:
        return frame
        
    # OPTIMIZATION: Crop-based inpainting
    # Instead of full-frame inpaint, only inpaint the bounding boxes of the mask.
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    res = frame.copy()
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        # expand crop by 10px context to give the algorithm surrounding pixels to sample
        cx1 = max(0, x - 10)
        cy1 = max(0, y - 10)
        cx2 = min(frame.shape[1], x + w + 10)
        cy2 = min(frame.shape[0], y + h + 10)
        
        crop_frame = res[cy1:cy2, cx1:cx2]
        crop_mask = mask[cy1:cy2, cx1:cx2]
        
        inpainted_crop = cv2.inpaint(crop_frame, crop_mask, inpaintRadius=3, flags=cv2.INPAINT_TELEA)
        res[cy1:cy2, cx1:cx2] = inpainted_crop
        
    return res


def precompute_ocr_results(
    input_path: str,
    total_frames: int,
    fps: float,
    ocr_fps: float,
    ocr_batch_size: int,
    width: int,
    height: int,
    ocr,
) -> dict[int, list[tuple]]:
    """Pre-pass OCR on frames sampled at `ocr_fps`. Returns {frame_index: [(x,y,w,h),...]}.

    Frames are pulled with a SINGLE sequential ffmpeg decode (fps filter + downscale) instead of
    thousands of random cv2 seeks — H.264 random-seek re-decodes from the nearest keyframe each
    time (~100ms/seek on 1080p), so this collapses the OCR sampling from ~tens-of-seconds to ~1-2s.
    """
    frame_skip = max(1, round(fps / ocr_fps))
    eff_fps = fps / frame_skip

    out_h = OCR_MAX_H if height > OCR_MAX_H else height
    scale = out_h / height
    out_w = max(2, int(round(width * scale)))
    out_w -= out_w % 2
    frame_bytes = out_w * out_h * 3

    cmd = [
        'ffmpeg', '-hide_banner', '-loglevel', 'error', '-i', input_path,
        '-vf', f'fps={eff_fps:.6f},scale={out_w}:{out_h}',
        '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-',
    ]
    results: dict[int, list[tuple]] = {}
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    rc = None
    try:
        i = 0
        while True:
            raw = proc.stdout.read(frame_bytes)
            if not raw or len(raw) < frame_bytes:
                break
            # frombuffer is read-only; copy so any in-place op downstream is safe.
            small = np.frombuffer(raw, dtype=np.uint8).reshape(out_h, out_w, 3).copy()
            with _ocr_lock:
                res = ocr.ocr(small, det=True, rec=False, cls=False)
            fi = min(i * frame_skip, max(0, total_frames - 1))
            results[fi] = _parse_ocr_boxes(res, out_w, out_h, width, height)
            i += 1
    finally:
        try:
            if proc.stdout:
                proc.stdout.close()
        except Exception:
            pass
        rc = proc.wait()
    # A failed decode that yielded NOTHING must not look like "no text" (that would silently leave
    # all subtitles un-blurred yet report success) — raise so the caller falls back to the pipeline.
    if rc not in (0, None) and not results:
        raise RuntimeError(f"precompute: ffmpeg trích frame thất bại (rc={rc}, 0 frame).")
    return results


# =====================================================================================
# FAST PATH — single-pass ffmpeg region blur.
# The old threaded pipeline (read→ocr→blur→write) decoded every frame in Python (cv2) and
# piped ~13.5GB of raw BGR to the encoder → ~59s for a 72s 1080×1918 video, ALL of it
# Python-loop + raw-pipe overhead (ffmpeg alone decodes the whole file in ~1.3s). Instead we
# let EasyOCR find the text regions, then do decode+blur+encode in ONE ffmpeg pass with
# crop+boxblur+overlay on those regions → ~6s (~10x). Static watermark boxes are blurred for
# the whole clip; dynamic (subtitle) regions are merged into a band and time-gated to the
# windows where text actually appears. Used for ocr_mode="blur"; inpaint/mask_only keep the
# precise per-frame pipeline below.
# =====================================================================================

# Safety constants. KEY guarantee against "blur the whole frame": the INSTANTANEOUS blurred area
# (what is blurred at any single moment, NOT the union over time) is capped at _MAX_INSTANT_FRAC.
# Time-gating means a roaming subtitle blurs only ~1 row at a time, so its union over the clip can
# be large while the instant footprint stays small — that distinction is the whole trick.
_GRID = 20
_PERSIST_FRAC = 0.12       # text must recur in ≥12% of text-frames to count (kills one-off noise)
_PERSIST_MIN = 3
_ROW_DIV = 26              # frame split into ~26 horizontal rows for subtitle-band detection
_MAX_REGION_FRAC = 0.35    # drop any single static box bigger than this share of the frame
_MAX_INSTANT_FRAC = 0.45   # never blur more than this share of the frame at any one instant


def _plan_blur_regions(ocr_lookup, static_boxes, W, H, total_frames, frame_skip):
    """Plan every region to blur, GUARANTEEING the instantaneous blurred area never exceeds
    _MAX_INSTANT_FRAC of the frame (so it can never blur the whole / most of a frame).

    Static watermark boxes → always-on regions (area-capped per box).
    Dynamic text → HORIZONTAL ROW BANDS: each row that holds recurring text becomes a region
    spanning that row's text x-extent, time-gated to the frames where the row has text. Rows are
    kept SEPARATE (not merged into one tall block) so a subtitle roaming over the lower third
    blurs only its current row at any instant — not the whole zone (the old connected-components
    union made one 38%-tall block and dropped it, leaving subtitles un-removed).

    A greedy pass then drops the lowest temporal-spread regions (transient scene text on busy
    frames) until the worst-case simultaneous (instantaneous) blurred area is within the cap,
    while keeping persistent subtitles/watermarks (which have high spread).

    Returns region dicts: {x, y, w, h, radius, frames(set|None), spread, always}.
    """
    frame_area = float(W * H)
    if frame_area <= 0:
        return []

    cands: list = []
    static_grid: set = set()

    # --- static watermark boxes (always on, per-box area cap) ---
    for (x, y, w, h) in static_boxes:
        if (w * h) / frame_area > _MAX_REGION_FRAC:
            print(f"[VideoProcess] ⚠ Bỏ static box quá lớn ({w}x{h}px).")
            continue
        r = _clamp_even(x, y, w, h, W, H)
        if not r:
            continue
        r.update(frames=None, spread=1.0, always=True)
        cands.append(r)
        for gx in range(x // _GRID, (x + w) // _GRID + 1):
            for gy in range(y // _GRID, (y + h) // _GRID + 1):
                static_grid.add((gx, gy))

    # --- dynamic text → horizontal row bands ---
    ROW_H = max(40, round(H / _ROW_DIV))
    n_rows = (H + ROW_H - 1) // ROW_H
    row_frames = [set() for _ in range(n_rows)]
    row_xmin = [W] * n_rows
    row_xmax = [0] * n_rows
    text_frames: set = set()
    for fi, boxes in ocr_lookup.items():
        had = False
        for (x, y, w, h) in boxes:
            if (x // _GRID, y // _GRID) in static_grid:   # skip known static watermark cells
                continue
            had = True
            r0 = max(0, y // ROW_H)
            r1 = min(n_rows - 1, (y + h) // ROW_H)
            for ri in range(r0, r1 + 1):
                row_frames[ri].add(fi)
                row_xmin[ri] = min(row_xmin[ri], x)
                row_xmax[ri] = max(row_xmax[ri], x + w)
        if had:
            text_frames.add(fi)

    n_text = len(text_frames)
    if n_text > 0:
        thr = max(_PERSIST_MIN, int(_PERSIST_FRAC * n_text))
        denom = float(total_frames) if (total_frames and total_frames > 0) else float(max(text_frames) + 1)
        for ri in range(n_rows):
            orig = row_frames[ri]
            if len(orig) < thr:                  # persistence on REAL detections only
                continue
            fr = set(orig)
            if frame_skip > 0:                   # close single-sample detection holes (anti-flicker);
                for fi in sorted(orig):          # the filled frame is then budgeted like any other
                    if (fi + 2 * frame_skip) in orig and (fi + frame_skip) not in orig:
                        fr.add(fi + frame_skip)
            y0 = ri * ROW_H
            r = _clamp_even(row_xmin[ri], y0, row_xmax[ri] - row_xmin[ri], min(ROW_H, H - y0), W, H)
            if not r:
                continue
            spread = (max(fr) - min(fr)) / denom if len(fr) > 1 else 0.0
            r.update(frames=fr, spread=spread, always=False)
            cands.append(r)

    if not cands:
        return []

    # --- PER-INSTANT area cap: the real "never blur the whole frame" guarantee ---
    # Keep the simultaneously-blurred area ≤ _MAX_INSTANT_FRAC at EVERY moment. Instead of dropping
    # a row for the whole clip (which would lose its subtitle everywhere just because ONE busy frame
    # is crowded), exclude a row only at the specific frames that are over budget — dropping the
    # lowest temporal-spread (most likely transient scene text) rows first. A row stays blurred at
    # all its other frames, so subtitles are removed wherever there's room.
    budget = _MAX_INSTANT_FRAC * frame_area

    # Static boxes are always on; if they alone blow the budget, drop the largest until they fit.
    statics = sorted((c for c in cands if c["always"]), key=lambda c: c["w"] * c["h"], reverse=True)
    static_area = sum(c["w"] * c["h"] for c in statics)
    n_drop_static = 0
    while statics and static_area > budget:
        d = statics.pop(0)
        static_area -= d["w"] * d["h"]
        cands.remove(d)
        n_drop_static += 1
    if n_drop_static:
        print(f"[VideoProcess] ⚠ Bỏ {n_drop_static} watermark tĩnh quá lớn (tổng vượt {_MAX_INSTANT_FRAC:.0%}).")

    frame_active: dict = {}
    for c in cands:
        if c["always"]:
            continue
        for fi in c["frames"]:
            frame_active.setdefault(fi, []).append(c)
    capped = 0
    for fi, act in frame_active.items():
        total = static_area + sum(c["w"] * c["h"] for c in act)
        if total <= budget:
            continue
        # drop the least-"real" rows first: low temporal-spread AND low density = transient scene text;
        # persistent subtitles (high spread + high density) are kept.
        for c in sorted(act, key=lambda c: (c["spread"], len(c["frames"]), c["w"] * c["h"])):
            if total <= budget:
                break
            c["frames"].discard(fi)        # blur this row at its other frames, just not this crowded one
            total -= c["w"] * c["h"]
            capped += 1
    if capped:
        print(f"[VideoProcess] Giới hạn mờ tức thời ≤ {_MAX_INSTANT_FRAC:.0%}: loại {capped} lượt hàng-khung quá đông.")

    cands = [c for c in cands if c["always"] or c["frames"]]
    return cands


def _frames_to_time_windows(active, fps, frame_skip, total_frames, pad_s=0.0, merge_gap_s=0.1):
    """Merge OCR-frame indices that held text into [t0,t1] second-windows.

    pad_s=0 (NO padding) is deliberate: each frame fi covers exactly its sample interval
    [fi/fps, (fi+frame_skip)/fps], so adjacent samples' windows ABUT without overlapping and the
    rendered timeline matches the per-frame budget grid used by _plan_blur_regions. Any padding
    would let two adjacent samples' (different) kept rows co-render in the overlap and DOUBLE the
    blurred area — breaking the per-instant area cap on the actual output. merge_gap_s=0.1 only
    fuses abutting intervals (a real ≥1-sample gap is left un-blurred, as the budget intended)."""
    active = sorted(set(active))
    if not active or fps <= 0:
        return []
    dur = total_frames / fps
    intervals = []
    for idx in active:
        t0 = max(0.0, idx / fps - pad_s)
        t1 = min(dur, (idx + frame_skip) / fps + pad_s)
        intervals.append((t0, t1))
    intervals.sort()
    merged = [list(intervals[0])]
    for t0, t1 in intervals[1:]:
        if t0 <= merged[-1][1] + merge_gap_s:
            merged[-1][1] = max(merged[-1][1], t1)
        else:
            merged.append([t0, t1])
    return [(round(a, 2), round(b, 2)) for a, b in merged]


def _clamp_even(x, y, w, h, W, H, pad=6):
    """Pad a box, clamp to frame, snap all coords/sizes to even ints (libx264 needs even dims)."""
    x0 = max(0, x - pad)
    y0 = max(0, y - pad)
    x1 = min(W, x + w + pad)
    y1 = min(H, y + h + pad)
    x0 -= x0 % 2
    y0 -= y0 % 2
    bw = (x1 - x0)
    bh = (y1 - y0)
    bw -= bw % 2
    bh -= bh % 2
    if x0 + bw > W:
        bw = (W - x0) - ((W - x0) % 2)
    if y0 + bh > H:
        bh = (H - y0) - ((H - y0) % 2)
    if bw < 8 or bh < 8:
        return None
    # yuv420p chroma plane is dim/2, and ffmpeg's boxblur requires radius STRICTLY < dim/4, so a
    # radius of exactly dim//4 (when a side is a multiple of 4) makes ffmpeg abort the WHOLE
    # filtergraph with "-22 Invalid chroma_param radius". Keep it strictly below.
    radius = max(1, min(22, min(bw, bh) // 4 - 1))
    return {"x": x0, "y": y0, "w": bw, "h": bh, "radius": radius}


def _build_blur_filter(regions: list[dict]) -> tuple[str, str]:
    """Build an ffmpeg filter_complex that blurs each region (crop→boxblur→overlay)."""
    n = len(regions)
    splits = "".join(f"[s{i}]" for i in range(n))
    parts = [f"[0:v]split={n + 1}[base]{splits}"]
    for i, r in enumerate(regions):
        parts.append(f"[s{i}]crop={r['w']}:{r['h']}:{r['x']}:{r['y']},boxblur={r['radius']}:2[b{i}]")
    prev = "base"
    for i, r in enumerate(regions):
        out = "v" if i == n - 1 else f"o{i}"
        en = r.get("enable")
        en_s = f":enable='{en}'" if en else ""
        parts.append(f"[{prev}][b{i}]overlay={r['x']}:{r['y']}{en_s}[{out}]")
        prev = out
    return ";".join(parts), "v"


def _fast_blur_ffmpeg(input_path, output_path, fps, width, height,
                      static_boxes, ocr_lookup, frame_skip, total_frames):
    """Single ffmpeg pass: blur the regions planned by _plan_blur_regions (static always-on +
    dynamic time-gated row bands). The planner caps instantaneous blur area, so this can never
    blur the whole frame."""
    regions = _plan_blur_regions(ocr_lookup, static_boxes, width, height, total_frames, frame_skip)
    if not regions:
        print("[VideoProcess] Không có vùng chữ hợp lệ → copy nguyên video.")
        shutil.copy(input_path, output_path)
        return

    for r in regions:
        # Static watermark → always on. Dynamic rows → EXACT between() windows; NEVER promote a
        # dynamic row to always-on (that would re-blur the crowded frames the planner dropped and
        # break the per-instant cap). pad_s=0 windows render exactly the budgeted frames.
        if r["always"] or not r["frames"]:
            r["enable"] = None
            continue
        windows = _frames_to_time_windows(sorted(r["frames"]), fps, frame_skip, total_frames)
        r["enable"] = "+".join(f"between(t,{a},{b})" for a, b in windows) if windows else None

    if len(regions) > 40:  # bound only the filtergraph depth (cmdline length is no longer a limit)
        regions.sort(key=lambda r: (r["always"], len(r["frames"]) if r["frames"] else 10 ** 9), reverse=True)
        cut = len(regions) - 40
        regions = regions[:40]
        print(f"[VideoProcess] ⚠ Quá nhiều vùng — giữ 40 vùng bền nhất, bỏ {cut} vùng (chữ có thể còn sót).")

    n_static = sum(1 for r in regions if r["always"])
    filt, final = _build_blur_filter(regions)
    print(f"[VideoProcess] Single-pass ffmpeg blur: {len(regions)} vùng "
          f"({n_static} watermark tĩnh + {len(regions) - n_static} dải chữ động).")
    # Write the filtergraph to a file and read it with ffmpeg's "-/option <file>" syntax: a long
    # between(...) chain passed inline can blow the Windows 32K command-line limit. (ffmpeg-master
    # dropped the old -filter_complex_script; -/filter_complex is the current file form.)
    fd, filt_path = tempfile.mkstemp(suffix=".txt", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(filt)
        cmd = [
            'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-i', input_path,
            '-/filter_complex', filt_path, '-map', f'[{final}]', '-an',
            '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-pix_fmt', 'yuv420p',
            output_path,
        ]
        res = subprocess.run(cmd, capture_output=True)
    finally:
        try:
            os.remove(filt_path)
        except Exception:
            pass
    if res.returncode != 0 or not os.path.exists(output_path):
        raise RuntimeError(
            "ffmpeg single-pass blur thất bại:\n" + res.stderr.decode('utf-8', 'replace')[-1000:])


def _precise_blur_per_frame(input_path, output_path, fps, width, height,
                            static_boxes, ocr, total_frames, mask_only=False,
                            ocr_mode="blur", batch_size=16, det_every=2):
    """PRECISE per-frame text blur — replaces the coarse full-width row-band fast path.

    Blurs ONLY the exact detected text boxes (+ static watermark boxes) so the blur tracks the
    real text instead of smearing a full-width strip across faces/background. FULLY pipelined
    for this machine — five stages run concurrently:
        producer (ffmpeg decode + copy + OCR-downscale) ║ main (GPU CRAFT, batched) ║
        blur thread-pool ║ writer (re-orders results) ║ ffmpeg encode.
    det_every: detect every Nth frame and reuse those boxes for the (N-1) frames in between —
    subtitles are static across a few frames at 30 fps, so N=2 roughly doubles throughput with
    no visible change. batch_size: frames per CRAFT forward pass. Output stays strictly ordered.
    """
    from concurrent.futures import ThreadPoolExecutor

    frame_bytes = width * height * 3
    det_every = max(1, int(det_every))
    dec = subprocess.Popen(
        ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-i', input_path,
         '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    enc = subprocess.Popen(
        ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
         '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{width}x{height}', '-r', f'{fps:.6f}',
         '-i', '-', '-an', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
         '-pix_fmt', 'yuv420p', output_path],
        stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    enc_err: collections.deque = collections.deque(maxlen=64)
    _et = _threading.Thread(
        target=lambda: [enc_err.append(l.decode('utf-8', 'replace')) for l in enc.stderr],
        daemon=True)
    _et.start()

    n_workers = max(2, (os.cpu_count() or 4) - 2)
    pool = ThreadPoolExecutor(max_workers=n_workers)
    MAX_INFLIGHT = max(n_workers * 4, batch_size * 2)
    rc = None
    print(f"[VideoProcess] Precise blur: OCR mỗi {det_every} frame (batch={batch_size}), "
          f"{n_workers} luồng blur, pipeline producer/OCR/blur/writer.")

    def blur_one(frame, boxes):
        if not static_boxes and not boxes:
            return frame
        if mask_only or ocr_mode == "inpaint":
            return apply_inpaint_to_frame(frame, list(static_boxes) + list(boxes), mask_only=mask_only)
        return apply_blur_to_frame(frame, static_boxes, boxes)

    # --- decode + downscale producer (downscales ONLY the frames that will be OCR'd) ---
    prep_q: queue.Queue = queue.Queue(maxsize=batch_size * 3)
    PREP_SENTINEL = object()
    prep_err: list = []

    def _producer():
        i = 0
        try:
            while True:
                raw = dec.stdout.read(frame_bytes)
                if not raw or len(raw) < frame_bytes:
                    break
                frame = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 3).copy()
                small = _scale_frame_for_ocr(frame)[0] if (i % det_every == 0) else None
                prep_q.put((frame, small))
                i += 1
        except Exception as e:
            prep_err.append(e)
        finally:
            prep_q.put(PREP_SENTINEL)

    # --- ordered writer: pulls blur futures FIFO and feeds the encoder, so the main (OCR)
    #     thread never blocks on encode I/O. write_q is bounded → backpressure to the producer. ---
    write_q: queue.Queue = queue.Queue(maxsize=MAX_INFLIGHT)
    WRITE_SENTINEL = object()
    write_err: list = []

    def _writer():
        try:
            while True:
                fut = write_q.get()
                if fut is WRITE_SENTINEL:
                    break
                enc.stdin.write(fut.result().tobytes())
        except Exception as e:
            write_err.append(e)
            try:
                while write_q.get() is not WRITE_SENTINEL:   # drain so producers can't deadlock
                    pass
            except Exception:
                pass

    last_boxes: list = []

    def _flush(items):
        nonlocal last_boxes
        if not items:
            return
        ocr_pos = [k for k, (_f, s) in enumerate(items) if s is not None]
        boxes_at: dict = {}
        if ocr_pos:
            smalls = [items[k][1] for k in ocr_pos]
            sh, sw = smalls[0].shape[:2]
            with _ocr_lock:
                results = ocr.ocr_batch(smalls)
            for k, res in zip(ocr_pos, results):
                boxes_at[k] = _parse_ocr_boxes(res, sw, sh, width, height)
        for k, (frame, _s) in enumerate(items):
            if k in boxes_at:
                last_boxes = boxes_at[k]            # refresh on detected frames
            write_q.put(pool.submit(blur_one, frame, last_boxes))   # reuse on skipped frames

    prod = _threading.Thread(target=_producer, daemon=True)
    writer = _threading.Thread(target=_writer, daemon=True)
    prod.start()
    writer.start()

    try:
        batch: list = []
        idx = 0
        while True:
            item = prep_q.get()
            if item is PREP_SENTINEL:
                break
            batch.append(item)
            idx += 1
            if len(batch) >= batch_size:
                _flush(batch)
                batch = []
                if total_frames and (idx // batch_size) % 5 == 0:
                    print(f"[VideoProcess] Precise blur {idx}/{total_frames} frames...")
        _flush(batch)
        write_q.put(WRITE_SENTINEL)
        writer.join()
        if prep_err:
            raise prep_err[0]
        if write_err:
            raise write_err[0]
    finally:
        prod.join(timeout=5)
        if writer.is_alive():
            write_q.put(WRITE_SENTINEL)
            writer.join(timeout=10)
        pool.shutdown(wait=True)
        try:
            if dec.stdout:
                dec.stdout.close()
        except Exception:
            pass
        dec.wait()
        try:
            if enc.stdin:
                enc.stdin.close()
        except Exception:
            pass
        rc = enc.wait()
        _et.join(timeout=5)
    if rc not in (0, None) or not os.path.exists(output_path):
        raise RuntimeError("precise blur ffmpeg encode thất bại:\n" + ''.join(enc_err)[-1000:])
    print(f"[VideoProcess] Hoàn tất (precise per-frame blur): {output_path}")


def _probe_frame_count(input_path, fps):
    """Recover a frame count via ffprobe when cv2 reports <=0 (some MKV/streamed/VFR files)."""
    try:
        r = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=nb_frames,duration', '-of', 'default=nw=1:nk=1', input_path],
            capture_output=True, text=True, timeout=30)
        toks = r.stdout.split()
    except Exception:
        return 0
    for t in toks:                         # prefer an explicit frame count
        if t.isdigit() and int(t) > 0:
            return int(t)
    for t in toks:                         # else derive from duration × fps
        try:
            d = float(t)
            if d > 0:
                return int(d * fps)
        except ValueError:
            pass
    return 0


def remove_watermark_from_video(
    input_path: str,
    output_path: str,
    mask_only: bool = False,
    settings=None,
    ocr_mode: str = "blur",
):
    """
    Tự động phát hiện và xóa toàn bộ chữ động trong video.
    Quét OCR 2 lần mỗi giây (detection-only), inpaint các vùng phát hiện.
    Optimizations: det-only OCR, downscale, static boxes, inpaint, threading, FFV1, lock.
    """
    _ocr_fps = settings.ocr_fps if settings is not None else 2.0
    _ocr_batch_size = settings.ocr_batch_size if settings is not None else 4
    _ocr_mode = getattr(settings, "ocr_mode", ocr_mode) if settings is not None else ocr_mode

    print(f"[VideoProcess] Bắt đầu xử lý xóa chữ động cho: {input_path}")

    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        print(f"[VideoProcess] Lỗi: Không thể mở video {input_path}")
        return

    fps = cap.get(cv2.CAP_PROP_FPS)
    if math.isnan(fps) or fps == 0:
        fps = 25.0

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames <= 0:                  # some MKV/streamed/VFR containers report 0 via cv2
        total_frames = _probe_frame_count(input_path, fps)
        print(f"[VideoProcess] cv2 báo 0 frame → ffprobe ước lượng {total_frames} frame.")

    ocr = get_ocr_instance()

    # --- Pre-pass A: static box detection (30 frames across full video) ---
    print(f"[VideoProcess] Quét {STATIC_SCAN_FRAMES} frames toàn video để tìm watermark tĩnh...")
    try:
        static_boxes = _detect_static_boxes(input_path, ocr, fps, width, height, total_frames)
    except Exception as e:
        print(f"[VideoProcess] Cảnh báo static scan: {e}")
        static_boxes = []
    print(f"[VideoProcess] Phát hiện {len(static_boxes)} static box(es).")

    # --- Dynamic content check: 5-frame quick scan ---
    # Nếu video chỉ có watermark tĩnh → bỏ qua Pre-pass C, tiết kiệm 2–3 giây.
    temporal_ref = None  # Blur mode: không cần temporal reference

    if not mask_only:
        if 0 < total_frames < _DYNAMIC_CHECK_FRAMES:
            # Too short for the sample-check (which bails False) → just run the full OCR; it's cheap.
            has_dynamic = True
            print("[VideoProcess] Clip rất ngắn — chạy OCR đầy đủ.")
        else:
            print(f"[VideoProcess] Kiểm tra nhanh chữ động ({_DYNAMIC_CHECK_FRAMES} frames)...")
            try:
                has_dynamic = _has_dynamic_text(input_path, ocr, static_boxes, total_frames, width, height)
            except Exception as e:
                print(f"[VideoProcess] Cảnh báo dynamic check: {e}")
                has_dynamic = True  # fallback an toàn: chạy full scan
            if has_dynamic:
                print("[VideoProcess] Phát hiện chữ động — bật OCR scan đầy đủ.")
            else:
                print("[VideoProcess] Chỉ watermark tĩnh — bỏ qua Pre-pass C (fast path).")
    else:
        has_dynamic = False

    # No text anywhere → nothing to blur; copy the original and skip the expensive full re-encode.
    if not mask_only and not static_boxes and not has_dynamic:
        print("[VideoProcess] Không phát hiện chữ → copy nguyên video (bỏ qua re-encode).")
        cap.release()
        shutil.copy(input_path, output_path)
        print(f"[VideoProcess] Hoàn tất (copy nguyên bản): {output_path}")
        return

    # --- Pre-pass C: OCR batch pre-computation ---
    # Only the inpaint 4-thread pipeline still consumes ocr_lookup. The default "blur" mode now
    # uses _precise_blur_per_frame, which OCRs every frame itself, so precompute is skipped there.
    if not mask_only and has_dynamic and _ocr_mode == "inpaint":
        print(f"[VideoProcess] Pre-compute OCR theo batch (batch_size={_ocr_batch_size})...")
        try:
            ocr_lookup = precompute_ocr_results(
                input_path, total_frames, fps, _ocr_fps, _ocr_batch_size,
                width, height, ocr
            )
        except Exception as e:
            print(f"[VideoProcess] Cảnh báo OCR precompute: {e}")
            ocr_lookup = {}
    else:
        ocr_lookup = {}

    # --- PRECISE per-frame blur (default ocr_mode="blur") ---
    # Blurs the EXACT detected text boxes on every frame (no full-width row bands that smeared
    # across faces/background). GPU-BATCHED OCR ║ CPU blur pool ║ ffmpeg decode/encode in parallel.
    # OCR_BATCH=16 (default) frames per GPU forward pass; raise on a big GPU for more throughput.
    # inpaint (cv2 TELEA) and mask_only (ProPainter mask) still use the 4-thread pipeline below.
    if not mask_only and _ocr_mode != "inpaint":
        cap.release()
        try:
            batch_size = max(1, int(os.environ.get("OCR_BATCH", "16")))
        except ValueError:
            batch_size = 16
        try:
            det_every = max(1, int(os.environ.get("OCR_DET_EVERY", "2")))
        except ValueError:
            det_every = 2
        try:
            _precise_blur_per_frame(input_path, output_path, fps, width, height,
                                    static_boxes, ocr, total_frames, mask_only=False,
                                    ocr_mode=_ocr_mode, batch_size=batch_size, det_every=det_every)
            return
        except Exception as e:
            print(f"[VideoProcess] Precise path lỗi ({e}) → fallback pipeline per-frame.")
            cap = cv2.VideoCapture(input_path)
            if not cap.isOpened():
                raise RuntimeError(f"Không mở lại được {input_path} cho fallback pipeline.")

    # Rewind main cap to start
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    class FFmpegWriter:
        def __init__(self, path, w, h, f, lossless):
            self.path = path
            codec = 'h264_nvenc' if _check_nvenc_cached() else 'libx264'
            cmd = [
                'ffmpeg', '-y', '-f', 'rawvideo', '-vcodec', 'rawvideo',
                '-s', f'{w}x{h}', '-pix_fmt', 'bgr24', '-r', str(f),
                '-i', '-'
            ]
            if lossless:
                cmd.extend(['-c:v', 'libx264', '-crf', '0'])
                print(f"[VideoProcess] FFmpeg Writer: {path} (libx264 Lossless)")
            else:
                if codec == 'h264_nvenc':
                    cmd.extend(['-c:v', 'h264_nvenc', '-preset', 'p6', '-tune', 'hq', '-b:v', '5M'])
                    print(f"[VideoProcess] FFmpeg Writer: {path} (h264_nvenc GPU Accelerated)")
                else:
                    cmd.extend(['-c:v', 'libx264', '-crf', '23', '-preset', 'veryfast'])
                    print(f"[VideoProcess] FFmpeg Writer: {path} (libx264 CPU, veryfast)")
            cmd.append(path)
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
            self._stderr_tail = collections.deque(maxlen=64)
            def _drain():
                for line in self.proc.stderr:
                    self._stderr_tail.append(line.decode('utf-8', 'replace'))
            self._stderr_thread = _threading.Thread(target=_drain, daemon=True)
            self._stderr_thread.start()

        def write(self, frame):
            if self.proc.stdin:
                self.proc.stdin.write(frame.tobytes())

        def release(self):
            if self.proc.stdin:
                self.proc.stdin.close()
            rc = self.proc.wait()
            self._stderr_thread.join(timeout=5)
            if rc != 0:
                tail = ''.join(self._stderr_tail)
                raise RuntimeError(f'ffmpeg exited {rc} for {self.path}:\n{tail}')

        def isOpened(self):
            return self.proc.poll() is None

    out = FFmpegWriter(output_path, width, height, fps, lossless=mask_only)
    if not out.isOpened():
        cap.release()
        raise RuntimeError(f"Failed to open FFmpegWriter at {output_path}")

    print(f"[VideoProcess] Tổng số frame: {total_frames}, Quét OCR mỗi {max(1, int(fps / _ocr_fps))} frames.")

    # --- Opt 5: Threading pipeline with dual queues ---
    QUEUE_SIZE = 16
    read_q = queue.Queue(maxsize=QUEUE_SIZE)
    ocr_q = queue.Queue(maxsize=QUEUE_SIZE)
    # Bounded: without a cap, a slow encoder lets decoded frames pile up here and blow up RAM
    # on long/high-res videos. Backpressure makes the inpaint stage wait for the writer.
    write_q = queue.Queue(maxsize=QUEUE_SIZE)
    SENTINEL = object()  # signals end of stream

    # Fix 2: Error queue for thread exception propagation
    error_q = queue.Queue()

    def reader_thread():
        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                read_q.put(frame)
        except Exception as e:
            error_q.put(e)
        finally:
            read_q.put(SENTINEL)

    def ocr_thread():
        try:
            cached: list = []
            idx = 0
            while True:
                frame = read_q.get()
                if frame is SENTINEL:
                    break
                if idx in ocr_lookup:
                    cached = ocr_lookup[idx]
                ocr_q.put((frame, cached, idx))
                idx += 1
        except Exception as e:
            error_q.put(e)
        finally:
            ocr_q.put(SENTINEL)

    def inpaint_thread():
        try:
            while True:
                item = ocr_q.get()
                if item is SENTINEL:
                    break
                frame, cached, idx = item
                if mask_only:
                    all_boxes = list(static_boxes) + list(cached)
                    if all_boxes:
                        frame = apply_inpaint_to_frame(frame, all_boxes, mask_only=True)
                else:
                    if static_boxes or cached:
                        if _ocr_mode == "inpaint":
                            all_boxes = list(static_boxes) + list(cached)
                            frame = apply_inpaint_to_frame(frame, all_boxes, mask_only=False)
                        else:
                            frame = apply_blur_to_frame(frame, static_boxes, list(cached))
                write_q.put(frame)

                if idx > 0 and idx % max(1, int(fps) * 5) == 0:
                    print(f"[VideoProcess] Đã xử lý {idx}/{total_frames} frames...")
        except Exception as e:
            error_q.put(e)
        finally:
            write_q.put(SENTINEL)

    def writer_thread():
        try:
            while True:
                frame = write_q.get()
                if frame is SENTINEL:
                    break
                out.write(frame)
        except Exception as e:
            error_q.put(e)
            # Keep draining so the inpaint thread can't deadlock on a full write_q (which would
            # hang the whole stage on join()). The error is already captured above.
            try:
                while write_q.get() is not SENTINEL:
                    pass
            except Exception:
                pass

    threads = [
        _threading.Thread(target=reader_thread, daemon=True),
        _threading.Thread(target=ocr_thread, daemon=True),
        _threading.Thread(target=inpaint_thread, daemon=True),
        _threading.Thread(target=writer_thread, daemon=True),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Fix 2: Raise if any thread failed
    if not error_q.empty():
        # Release without letting a cleanup error (e.g. FFmpegWriter.release() raising on a
        # non-zero ffmpeg exit) mask the real thread error we want to surface.
        try:
            cap.release()
        except Exception:
            pass
        try:
            out.release()
        except Exception:
            pass
        raise RuntimeError(f"Video processing thread error: {error_q.get()}")

    cap.release()
    out.release()

    print(f"[VideoProcess] Hoàn tất xóa chữ động: {output_path}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 5:
        print("Usage: python video_process.py <input> <output> <mask_only> <ocr_mode>")
        sys.exit(1)
    
    input_path = sys.argv[1]
    output_path = sys.argv[2]
    mask_only = sys.argv[3].lower() == "true"
    ocr_mode = sys.argv[4]

    class DummySettings:
        def __init__(self, mode):
            self.ocr_mode = mode
            self.ocr_fps = 2.0
            self.ocr_batch_size = 4
            
    remove_watermark_from_video(input_path, output_path, mask_only, DummySettings(ocr_mode))
