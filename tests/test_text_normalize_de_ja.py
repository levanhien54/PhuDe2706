"""German + Japanese number normalization for TTS (pure Python, no num2words)."""
from orchestrator.text_normalize import (
    _de_read, normalize_german, _ja_read, normalize_japanese, normalize_for_tts,
)


# ── German ──────────────────────────────────────────────────────────────────────────────────
def test_de_cardinals():
    assert _de_read(0) == "null"
    assert _de_read(1) == "eins"
    assert _de_read(21) == "einundzwanzig"
    assert _de_read(100) == "einhundert"
    assert _de_read(123) == "einhundertdreiundzwanzig"
    assert _de_read(1000) == "eintausend"
    assert _de_read(1234) == "eintausendzweihundertvierunddreißig"
    assert _de_read(1_000_000) == "eine Million"
    assert _de_read(2_000_000) == "zwei Millionen"


def test_de_symbols_and_decimal():
    assert normalize_german("50%") == "fünfzig Prozent"
    assert normalize_german("20 €") == "zwanzig Euro"
    assert normalize_german("$5") == "fünf Dollar"
    assert normalize_german("3,14") == "drei Komma eins vier"      # German decimal comma
    assert normalize_german("1.234") == "eintausendzweihundertvierunddreißig"  # thousands dot


def test_de_ordinal():
    assert normalize_german("3. Mai").startswith("dritte")
    assert normalize_german("1. Platz").startswith("erste")


def test_de_sentence_final_number_is_cardinal_with_period():
    # 0.4: a sentence-final integer used to become an ordinal AND drop the period.
    out = normalize_german("Die Antwort ist 42.")
    assert "zweiundvierzig" in out
    assert "zweiundvierzigste" not in out       # NOT an ordinal
    assert out.rstrip().endswith(".")           # sentence period preserved


def test_de_ordinal_still_fires_before_a_word():
    # 0.4: the ordinal reading must still apply when a word follows ("am 3. Mai").
    assert "dritte" in normalize_german("am 3. Mai")


def test_de_trailing_dollar():
    # 0.5: German had a leading '$' rule but no trailing one.
    assert normalize_german("5$") == "fünf Dollar"


def test_de_negative_sign():
    # T5: a standalone leading minus verbalizes as "minus".
    assert normalize_german("-5") == "minus fünf"


def test_de_dispatch(monkeypatch):
    assert "Prozent" in normalize_for_tts("50%", "de")


# ── Japanese ────────────────────────────────────────────────────────────────────────────────
def test_ja_rendaku_hundreds_thousands():
    assert _ja_read(100) == "ひゃく"
    assert _ja_read(300) == "さんびゃく"
    assert _ja_read(600) == "ろっぴゃく"
    assert _ja_read(800) == "はっぴゃく"
    assert _ja_read(1000) == "せん"
    assert _ja_read(3000) == "さんぜん"
    assert _ja_read(8000) == "はっせん"


def test_ja_big_units_keep_ichi():
    assert _ja_read(10000) == "いちまん"        # 一万 (Japanese keeps いち, unlike Korean 만)
    assert _ja_read(100000000) == "いちおく"     # 一億


def test_ja_people_and_tsu_counters():
    assert normalize_japanese("1人") == "ひとり"
    assert normalize_japanese("2人") == "ふたり"
    assert normalize_japanese("3人") == "さんにん"
    assert normalize_japanese("3つ") == "みっつ"
    assert normalize_japanese("10つ") == "とお"


def test_ja_symbols_and_decimal():
    assert normalize_japanese("5%") == "ごパーセント"
    assert normalize_japanese("$5") == "ごドル"
    assert normalize_japanese("3.14") == "さんてんいちよん"


def test_ja_negative_sign():
    # T5: a standalone leading minus verbalizes as "マイナス".
    assert normalize_japanese("-5") == "マイナスご"


def test_ja_huge_number_no_indexerror():
    # 0.3: a >=21-digit number overflows the 5-entry 万/億/兆/京 table -> must fall back, not crash.
    out = _ja_read(int("9" * 21))
    assert isinstance(out, str) and out         # no IndexError, non-empty
    # 20 digits still fits the table (up to 京) and reads with unit words.
    assert "けい" in _ja_read(int("9" * 20))


def test_ja_dispatch():
    assert normalize_for_tts("3人", "ja") == "さんにん"


def test_ja_counter_gemination():
    assert normalize_japanese("1個") == "いっこ"
    assert normalize_japanese("3個") == "さんこ"
    assert normalize_japanese("6個") == "ろっこ"
    assert normalize_japanese("10個") == "じゅっこ"
    assert normalize_japanese("1本") == "いっぽん"
    assert normalize_japanese("3本") == "さんぼん"      # rendaku h->b
    assert normalize_japanese("6本") == "ろっぽん"
    assert normalize_japanese("1分") == "いっぷん"
    assert normalize_japanese("4分") == "よんぷん"
    assert normalize_japanese("3匹") == "さんびき"
    assert normalize_japanese("8杯") == "はっぱい"


def test_ja_age_and_oclock_irregulars():
    assert normalize_japanese("20歳") == "はたち"      # irregular age
    assert normalize_japanese("8歳") == "はっさい"
    assert normalize_japanese("4時") == "よじ"          # irregular o'clock
    assert normalize_japanese("7時") == "しちじ"
    assert normalize_japanese("9時") == "くじ"
    assert normalize_japanese("3時") == "さんじ"


def test_ja_counter_over_ten_keeps_kanji_and_jikan_guard():
    # >10 keeps the kanji counter so the model reads it (avoids forced-wrong kana).
    assert normalize_japanese("15本") == "じゅうご本"
    # 時間 (duration) must NOT be read as an o'clock; kanji stays for the model.
    assert "時間" in normalize_japanese("3時間")
