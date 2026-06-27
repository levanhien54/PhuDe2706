import os
import cv2
import math
import shutil
from paddleocr import PaddleOCR

# Khởi tạo mô hình OCR một lần (singleton hoặc global) để tiết kiệm thời gian
_ocr_instance = None

def get_ocr_instance():
    global _ocr_instance
    if _ocr_instance is None:
        # Sử dụng lang='en', tắt angle_cls để tiết kiệm thời gian
        # Dùng GPU nếu có sẵn
        _ocr_instance = PaddleOCR(use_angle_cls=False, lang='en', use_gpu=True)
    return _ocr_instance

def apply_blur_to_frame(frame, boxes):
    """Làm mờ các vùng chứa chữ trong frame bằng Gaussian Blur"""
    height, width = frame.shape[:2]
    for (x, y, w, h) in boxes:
        # Lấy vùng ROI (Region of Interest)
        roi = frame[y:y+h, x:x+w]
        if roi.size == 0:
            continue
        
        # Áp dụng bộ lọc mờ (kích thước kernel lẻ và lớn để mờ nhòe chữ)
        # Kích thước kernel phụ thuộc vào độ lớn của hộp, nhưng cố định 51x51 cũng đủ tốt
        kernel_w = min(w if w % 2 != 0 else w - 1, 51)
        kernel_h = min(h if h % 2 != 0 else h - 1, 51)
        kernel_w = max(3, kernel_w)
        kernel_h = max(3, kernel_h)
        
        blurred_roi = cv2.GaussianBlur(roi, (kernel_w, kernel_h), 0)
        frame[y:y+h, x:x+w] = blurred_roi
        
    return frame

def remove_watermark_from_video(input_path: str, output_path: str):
    """
    Tự động phát hiện và làm mờ toàn bộ chữ động trong video.
    Quét OCR 2 lần mỗi giây, sau đó áp dụng Blur lên từng khung hình.
    """
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
    
    # Chuẩn bị VideoWriter
    # Sử dụng mã mp4v (hoặc avc1). Khuyến nghị mp4v để tương thích cao trên OpenCV
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
    
    ocr = get_ocr_instance()
    
    # Tính toán chu kỳ quét (Chỉ quét 2 lần 1 giây)
    frame_skip = max(1, int(fps / 2))
    
    cached_boxes = []
    frame_count = 0
    
    print(f"[VideoProcess] Tổng số frame: {total_frames}, Quét OCR mỗi {frame_skip} frames.")
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        # 1. Gọi AI OCR ở các khung hình được chọn
        if frame_count % frame_skip == 0:
            # Gợi ý tối ưu: Nếu chỉ cần nhận diện tọa độ (không cần đọc nội dung chữ), 
            # có thể cấu hình PaddleOCR(det=True, rec=False) ở bản cập nhật sau để nhanh gấp 5 lần.
            result = ocr.ocr(frame, cls=False)
            
            current_boxes = []
            if result and result[0]:
                for line in result[0]:
                    try:
                        box = line[0] # box = [[x1, y1], [x2, y2], [x3, y3], [x4, y4]]
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
                        w = min(width - x, w_box + pad * 2)
                        h = min(height - y, h_box + pad * 2)
                        
                        if w > 0 and h > 0:
                            current_boxes.append((x, y, w, h))
                    except Exception as e:
                        pass # Bỏ qua nếu có lỗi parse box
            
            # Cập nhật cache tọa độ mới
            cached_boxes = current_boxes
        
        # 2. Áp dụng làm mờ dựa trên danh sách tọa độ đang có
        if cached_boxes:
            frame = apply_blur_to_frame(frame, cached_boxes)
            
        # 3. Ghi vào video
        out.write(frame)
        
        frame_count += 1
        if frame_count % (int(fps) * 5) == 0:
            print(f"[VideoProcess] Đã xử lý {frame_count}/{total_frames} frames...")

    cap.release()
    out.release()
    print(f"[VideoProcess] Hoàn tất xóa chữ động: {output_path}")

if __name__ == "__main__":
    pass
