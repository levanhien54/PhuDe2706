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
from paddleocr import PaddleOCR

# --- NVENC caching ---
_NVENC_AVAILABLE: bool | None = None

def _check_nvenc_cached() -> bool:
    global _NVENC_AVAILABLE
    if _NVENC_AVAILABLE is None:
        try:
            res = subprocess.run(
                ['ffmpeg', '-hide_banner', '-encoders'],
                capture_output=True, text=True
            )
            _NVENC_AVAILABLE = 'h264_nvenc' in res.stdout
        except Exception:
            _NVENC_AVAILABLE = False
    return _NVENC_AVAILABLE

# --- Opt 7: Threading lock for OCR singleton (multi-job safety) ---
_ocr_lock = _threading.Lock()
_ocr_instance = None

def get_ocr_instance():
    global _ocr_instance
    with _ocr_lock:
        if _ocr_instance is None:
            # Opt 1: Detection-only mode (rec=False) — 5x faster, no text recognition needed
            _ocr_instance = PaddleOCR(use_angle_cls=False, lang='en', use_gpu=True, rec=False)
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


def _parse_ocr_boxes(result, scale, width, height):
    """Parse OCR result (rec=False format) into list of (x, y, w, h) tuples."""
    boxes = []
    if not result or not result[0]:
        return boxes
    # rec=False: result[0] = list of [box, score]
    for item in result[0]:
        try:
            box = item[0]  # [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
            x_coords = [p[0] for p in box]
            y_coords = [p[1] for p in box]

            x_min = int(min(x_coords))
            y_min = int(min(y_coords))
            x_max = int(max(x_coords))
            y_max = int(max(y_coords))

            w_box = x_max - x_min
            h_box = y_max - y_min

            pad = 5
            x = max(0, x_min - pad)
            y = max(0, y_min - pad)
            w_final = min(width - x, w_box + pad * 2)
            h_final = min(height - y, h_box + pad * 2)

            if w_final > 0 and h_final > 0:
                # Scale box back to original frame size
                if scale != 1.0:
                    x = int(x / scale)
                    y = int(y / scale)
                    w_final = int(w_final / scale)
                    h_final = int(h_final / scale)
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
            small, scale = _scale_frame_for_ocr(frame)
            with _ocr_lock:
                result = ocr.ocr(small, cls=False)
            boxes = _parse_ocr_boxes(result, scale, width, height)
            for box in boxes:
                x, y, w, h = box
                key = (x // 20, y // 20)
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
    """
    Inpaint static boxes từ temporal reference (pixel copy, rất nhanh).
    Inpaint dynamic boxes bằng TELEA (như cũ).
    Nếu reference=None, gộp static vào dynamic để TELEA xử lý hết.
    """
    result = frame.copy()

    if reference is not None:
        h_f, w_f = frame.shape[:2]
        for (x, y, w, h) in static_boxes:
            y2 = min(y + h, h_f)
            x2 = min(x + w, w_f)
            result[y:y2, x:x2] = reference[y:y2, x:x2]
        all_dynamic = list(dynamic_boxes)
    else:
        # Fallback: xử lý static bằng TELEA
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
    """Pre-pass: batch OCR on OCR frames. Returns {frame_index: [(x,y,w,h),...]}."""
    frame_skip = max(1, int(fps / ocr_fps))
    ocr_indices = list(range(0, total_frames, frame_skip))

    results: dict[int, list[tuple]] = {}
    batch_smalls: list = []
    batch_scales: list = []
    batch_frame_indices: list[int] = []

    cap = cv2.VideoCapture(input_path)
    try:
        def _flush_batch():
            if not batch_smalls:
                return
            with _ocr_lock:
                ocr_results = ocr.ocr(batch_smalls, cls=False)
            for i, fi in enumerate(batch_frame_indices):
                results[fi] = _parse_ocr_boxes([ocr_results[i]], batch_scales[i], width, height)
            batch_smalls.clear()
            batch_scales.clear()
            batch_frame_indices.clear()

        for fi in ocr_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
            ret, frame = cap.read()
            if not ret or frame is None:
                continue
            small, scale = _scale_frame_for_ocr(frame)
            batch_smalls.append(small)
            batch_scales.append(scale)
            batch_frame_indices.append(fi)

            if len(batch_smalls) >= ocr_batch_size:
                _flush_batch()

        _flush_batch()  # flush remaining
    finally:
        cap.release()
    return results


def remove_watermark_from_video(
    input_path: str,
    output_path: str,
    mask_only: bool = False,
    settings=None,
):
    """
    Tự động phát hiện và xóa toàn bộ chữ động trong video.
    Quét OCR 2 lần mỗi giây (detection-only), inpaint các vùng phát hiện.
    Optimizations: det-only OCR, downscale, static boxes, inpaint, threading, FFV1, lock.
    """
    _ocr_fps = settings.ocr_fps if settings is not None else 2.0
    _ocr_batch_size = settings.ocr_batch_size if settings is not None else 4

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

    ocr = get_ocr_instance()

    # --- Pre-pass A: static box detection (30 frames across full video) ---
    print(f"[VideoProcess] Quét {STATIC_SCAN_FRAMES} frames toàn video để tìm watermark tĩnh...")
    try:
        static_boxes = _detect_static_boxes(input_path, ocr, fps, width, height, total_frames)
    except Exception as e:
        print(f"[VideoProcess] Cảnh báo static scan: {e}")
        static_boxes = []
    print(f"[VideoProcess] Phát hiện {len(static_boxes)} static box(es).")

    # --- Pre-pass B: temporal reference (only needed for normal inpainting) ---
    if not mask_only:
        print("[VideoProcess] Xây dựng temporal reference...")
        try:
            temporal_ref = build_temporal_reference(input_path, n_samples=20)
            if temporal_ref is None:
                print("[VideoProcess] Video quá ngắn, dùng TELEA fallback.")
        except Exception as e:
            print(f"[VideoProcess] Cảnh báo temporal reference: {e}")
            temporal_ref = None
    else:
        temporal_ref = None

    # --- Pre-pass C: OCR batch pre-computation ---
    if not mask_only:
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
                    cmd.extend(['-c:v', 'libx264', '-crf', '18', '-preset', 'fast'])
                    print(f"[VideoProcess] FFmpeg Writer: {path} (libx264 CPU)")
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
    write_q = queue.Queue()  
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
                        frame = apply_temporal_inpaint(frame, temporal_ref, static_boxes, list(cached))
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
        cap.release()
        out.release()
        raise RuntimeError(f"Video processing thread error: {error_q.get()}")

    cap.release()
    out.release()

    print(f"[VideoProcess] Hoàn tất xóa chữ động: {output_path}")


if __name__ == "__main__":
    pass
