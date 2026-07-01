"""Shared pre-clean (markdown/control/zero-width) + €/£ currency for VI & EN."""
from orchestrator.text_normalize import (
    _pre_clean, normalize_vietnamese, normalize_english, normalize_for_tts,
)


def test_pre_clean_strips_markdown_and_control():
    assert "*" not in _pre_clean("**đậm** và *nghiêng*")
    assert "`" not in _pre_clean("dùng `lệnh` này")
    assert _pre_clean("A​B﻿C") == "ABC"          # zero-width + BOM removed


def test_pre_clean_collapses_repeated_punct():
    assert _pre_clean("Tuyệt!!!") == "Tuyệt!"
    assert _pre_clean("Thật sao???") == "Thật sao?"


def test_vietnamese_euro_pound():
    assert "euro" in normalize_vietnamese("5€")
    assert "năm euro" in normalize_vietnamese("5€")
    assert "bảng Anh" in normalize_vietnamese("10£")


def test_english_euro_pound():
    # inflect may be absent in this venv (numbers stay digits) — the currency symbol still expands.
    assert "euros" in normalize_english("€5")
    assert "pounds" in normalize_english("£10")


def test_dispatch_pre_clean_applies_all_langs():
    assert "*" not in normalize_for_tts("**Xin chào**", "vi")
    assert normalize_for_tts("Tuyệt!!!", "vi").count("!") == 1
