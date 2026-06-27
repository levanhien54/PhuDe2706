"""
Stub out heavy ML packages that are not installed in the test environment.
These stubs must be inserted into sys.modules before any project code is imported.
"""
import sys
import types

_STUBS = [
    "pyrubberband",
    "librosa",
    "paddleocr",
    "paddle",
    "cv2",
]

for _mod in _STUBS:
    if _mod not in sys.modules:
        stub = types.ModuleType(_mod)
        sys.modules[_mod] = stub
        # Provide a no-op PaddleOCR class to satisfy `from paddleocr import PaddleOCR`
        if _mod == "paddleocr":
            stub.PaddleOCR = type("PaddleOCR", (), {})
