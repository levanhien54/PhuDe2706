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


def test_english_trailing_euro_pound():
    # 0.5: trailing symbols must mirror the leading ones (5€ / 10£), like the Vietnamese path.
    assert "euros" in normalize_english("5€")
    assert "pounds" in normalize_english("10£")


def test_vn_acronym_five_and_six_letters():
    # T6: the speller used to cap at 4 letters, leaving 5-6 letter acronyms unspoken.
    assert normalize_vietnamese("UNESCO") == "u nờ e ét xê ô"
    assert normalize_vietnamese("HTTPS") == "hắt tê tê pê ét"


def test_pre_clean_keeps_times_and_divide_signs():
    # T6: × (U+00D7) and ÷ (U+00F7) are math operators, not letters — must not be split from digits.
    assert _pre_clean("2×3") == "2×3"
    assert _pre_clean("6÷2") == "6÷2"


def test_dispatch_pre_clean_applies_all_langs():
    assert "*" not in normalize_for_tts("**Xin chào**", "vi")
    assert normalize_for_tts("Tuyệt!!!", "vi").count("!") == 1
