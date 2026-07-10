"""ProPainter mask must include DYNAMIC subtitle boxes, not just static watermarks.

Bug: in mask_only (ProPainter) mode the OCR precompute was gated `not mask_only`, so ocr_lookup was
always empty and the mask held only static watermark boxes — ProPainter then inpainted watermarks
but left the moving subtitles on screen. _should_precompute_ocr now forces precompute for mask_only.

These tests pin the decision logic. End-to-end mask/frame alignment still needs a real ProPainter
run on the target GPU to confirm."""
from orchestrator.video_process import _should_precompute_ocr


def test_mask_only_always_precomputes():
    # the fix: ProPainter mask path must precompute regardless of has_dynamic / ocr_mode
    assert _should_precompute_ocr(mask_only=True, has_dynamic=False, ocr_mode="inpaint") is True
    assert _should_precompute_ocr(mask_only=True, has_dynamic=False, ocr_mode="blur") is True
    assert _should_precompute_ocr(mask_only=True, has_dynamic=True, ocr_mode="inpaint") is True


def test_inpaint_precomputes_only_with_dynamic_text():
    assert _should_precompute_ocr(mask_only=False, has_dynamic=True, ocr_mode="inpaint") is True
    assert _should_precompute_ocr(mask_only=False, has_dynamic=False, ocr_mode="inpaint") is False


def test_default_blur_path_never_precomputes_here():
    # the default blur path OCRs each frame itself in _precise_blur_per_frame
    assert _should_precompute_ocr(mask_only=False, has_dynamic=True, ocr_mode="blur") is False
