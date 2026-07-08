"""Korean number normalization for TTS (Sino vs native by counter)."""
from orchestrator.text_normalize import (
    _ko_read_sino, _ko_read_native, normalize_korean, normalize_for_tts,
)


def test_sino_cardinals():
    assert _ko_read_sino(0) == "영"
    assert _ko_read_sino(1) == "일"
    assert _ko_read_sino(10) == "십"
    assert _ko_read_sino(11) == "십일"
    assert _ko_read_sino(100) == "백"
    assert _ko_read_sino(123) == "백이십삼"
    assert _ko_read_sino(1000) == "천"
    assert _ko_read_sino(3500) == "삼천오백"
    assert _ko_read_sino(10000) == "만"        # not 일만
    assert _ko_read_sino(21000) == "이만천"
    assert _ko_read_sino(100000000) == "억"


def test_native_attributive():
    assert _ko_read_native(1, True) == "한"
    assert _ko_read_native(2, True) == "두"
    assert _ko_read_native(3, True) == "세"
    assert _ko_read_native(4, True) == "네"
    assert _ko_read_native(5, True) == "다섯"
    assert _ko_read_native(10, True) == "열"
    assert _ko_read_native(20, True) == "스무"
    assert _ko_read_native(21, True) == "스물한"
    assert _ko_read_native(99, True) == "아흔아홉"
    assert _ko_read_native(100, True) is None   # native tops out at 99


def test_hour_native_minute_sino():
    # The classic mixed case: 시 (hour) = native, 분 (minute) = Sino.
    out = normalize_korean("3시 30분")
    assert "세 시" in out
    assert "삼십" in out
    assert "3" not in out and "30" not in out


def test_native_counters_items_people():
    assert "다섯 개" in normalize_korean("5개")
    assert "세 명" in normalize_korean("3명")
    assert "스무 살" in normalize_korean("20살")


def test_sino_money_and_year():
    assert "삼천오백" in normalize_korean("3500원")      # 원 = Sino
    assert "이천이십육" in normalize_korean("2026년")     # 년 = Sino


def test_months_gaewol_stays_sino_not_native_gae():
    # 3개월 must read Sino (삼 개월), NOT native 개 (세 개...).
    out = normalize_korean("3개월")
    assert "삼" in out and "개월" in out
    assert "세 개" not in out


def test_percent_currency_symbols():
    assert "오십퍼센트" in normalize_korean("50%")
    assert "오 달러" in normalize_korean("$5")
    assert "그리고" in normalize_korean("A & B")


def test_trailing_euro_and_pound_currency():
    # 0.5: € had only a leading rule; £ was missing entirely. Add mirrored + pound.
    assert "오 유로" in normalize_korean("5€")
    assert "십 파운드" in normalize_korean("£10")
    assert "십 파운드" in normalize_korean("10£")


def test_negative_sign():
    # T5: a standalone leading minus verbalizes as "마이너스".
    assert normalize_korean("-5") == "마이너스 오"


def test_huge_number_no_indexerror():
    # 0.3: a >=21-digit number overflows the 5-entry 만/억/조/경 table -> must fall back, not crash.
    out = _ko_read_sino(int("9" * 21))
    assert isinstance(out, str) and out         # no IndexError, non-empty
    assert "경" in _ko_read_sino(int("9" * 20))  # 20 digits still fits the table (up to 경)


def test_decimal_and_phone():
    assert "삼 점 일 사" in normalize_korean("3.14")
    out = normalize_korean("010-1234-5678")
    assert out.startswith("공")                          # 0 -> 공, spelled digit by digit
    assert "1234" not in out


def test_large_bare_number_is_sino_not_phone():
    # A long plain number must read as a Sino cardinal, not spelled digit by digit.
    assert normalize_korean("100000000") == "억"
    assert normalize_korean("1234567") == "백이십삼만사천오백육십칠"


def test_dispatch_ko_uses_korean(monkeypatch):
    out = normalize_for_tts("5개를 샀어요", "ko")
    assert "다섯 개" in out
    # Hangul must NOT be stripped on the ko path (only the vi path strips CJK/Hangul).
    assert "샀어요" in out


def test_dispatch_ko_phone_not_garbled_by_ranges():
    # 0.2: through normalize_for_tts, _ranges_to_words previously turned the hyphens into '에서'
    # BEFORE the phone detector ran, so '010-1234-5678' read as garbage cardinals. _ko_pre must
    # now run first, spelling it digit by digit (0 -> 공) with no range word.
    out = normalize_for_tts("010-1234-5678", "ko")
    assert out.startswith("공")
    assert "에서" not in out
    assert "1234" not in out and "5678" not in out
    # digit-by-digit: 0 1 0 1 2 3 4 5 6 7 8
    assert out == "공 일 공 일 이 삼 사 오 육 칠 팔"
