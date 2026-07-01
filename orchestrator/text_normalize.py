"""Text normalization for TTS.

OmniVoice does NO text normalization of its own (no g2p / number reader — it feeds raw
graphemes to a subword tokenizer), so the caller MUST expand numbers / % / currency / acronyms
to spoken words, keep sentence punctuation for prosody, and feed NFC-normalized Unicode.

- All languages get a shared pre-clean: NFC, drop URLs/emails, un-fuse alphanumerics ("12B"→"12 B").
- Vietnamese is fully expanded (numbers, %, $, ₫, acronyms) via VietNormalizer (+ a built-in fallback).
- English gets number / % / $ expansion (via `inflect`).
- Other languages (ja/ko/zh/fr/...) get the shared pre-clean only; the model handles their script.
"""
import re
import unicodedata

# CJK / kana / Hangul / fullwidth ranges. A Vietnamese dub must never contain these — strip them
# at the TTS boundary so the engine never speaks the wrong language (only on the vi path).
_CJK_RE = re.compile(
    "[⺀-⻿⼀-⿟　-〿぀-ヿ㄀-ㄯ"
    "㄰-㆏㐀-䶿一-鿿ꀀ-꓏가-힯"
    "豈-﫿︰-﹏＀-￯]"
)


def strip_cjk(text: str) -> str:
    """Remove CJK/kana/Hangul/fullwidth chars and tidy the resulting spacing/punctuation."""
    out = _CJK_RE.sub("", text or "")
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)   # no space before punctuation left behind
    return re.sub(r"\s{2,}", " ", out).strip()


# ── Vietnamese number reader ────────────────────────────────────────────────────────────────
_ONES = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]
_SCALES = ["", " nghìn", " triệu", " tỷ", " nghìn tỷ", " triệu tỷ", " tỷ tỷ"]


def _read_three(n: int, full: bool) -> str:
    tr, ch, dv = n // 100, (n % 100) // 10, n % 10
    out = []
    if tr > 0:
        out.append(_ONES[tr] + " trăm")
    elif full and (ch > 0 or dv > 0):
        out.append("không trăm")
    if ch > 1:
        out.append(_ONES[ch] + " mươi")
        if dv == 1:
            out.append("mốt")
        elif dv == 5:
            out.append("lăm")
        elif dv == 4:
            out.append("tư")
        elif dv > 0:
            out.append(_ONES[dv])
    elif ch == 1:
        out.append("mười")
        if dv == 5:
            out.append("lăm")
        elif dv > 0:
            out.append(_ONES[dv])
    else:
        if dv > 0:
            if tr > 0 or full:
                out.append("lẻ")
            out.append(_ONES[dv])
    return " ".join(out)


def read_number(num: int) -> str:
    if num == 0:
        return "không"
    digits = str(num)
    if len(digits) > len(_SCALES) * 3:
        return " ".join(_ONES[int(d)] for d in digits)
    groups = []
    while num > 0:
        groups.append(num % 1000)
        num //= 1000
    groups.reverse()
    n_groups = len(groups)
    parts = []
    for i, g in enumerate(groups):
        if g == 0:
            continue
        scale_idx = n_groups - 1 - i
        parts.append(_read_three(g, full=(i != 0)) + _SCALES[scale_idx])
    return " ".join(p for p in parts if p).strip()


def _read_number_token(tok: str) -> str:
    """Read a numeric token ('.' thousands, ',' decimal — also handles English '3.14' decimals
    and leading-zero codes spelled digit by digit)."""
    if "," in tok:
        intp, frac = tok.split(",", 1)
        intp = intp.replace(".", "")
        frac = re.sub(r"\D", "", frac)
    elif "." in tok:
        parts = tok.split(".")
        if len(parts) == 2 and len(parts[1]) != 3:
            intp, frac = parts[0], parts[1]
        else:
            intp, frac = tok.replace(".", ""), ""
    else:
        intp, frac = tok, ""
    intp = re.sub(r"\D", "", intp) or "0"
    if len(intp) > 1 and intp[0] == "0":
        words = " ".join(_ONES[int(d)] for d in intp)
    elif len(intp) > 18:
        words = " ".join(_ONES[int(d)] for d in intp)
    else:
        words = read_number(int(intp))
    if frac:
        words += " phẩy " + " ".join(_ONES[int(d)] for d in frac)
    return words


_LETTER_VN = {
    "A": "a", "B": "bê", "C": "xê", "D": "đê", "E": "e", "F": "ép", "G": "gờ",
    "H": "hắt", "I": "i", "J": "gi", "K": "ca", "L": "lờ", "M": "mờ", "N": "nờ",
    "O": "ô", "P": "pê", "Q": "quy", "R": "rờ", "S": "ét", "T": "tê", "U": "u",
    "V": "vê", "W": "vê kép", "X": "ích", "Y": "i", "Z": "dét",
}


def _spell_acronym(m: re.Match) -> str:
    return " ".join(_LETTER_VN[c] for c in m.group())


# ── Shared, language-agnostic pre-clean ─────────────────────────────────────────────────────
_URL_RE = re.compile(r"https?://\S+|www\.[^\s]+|\b[\w.+-]+@[\w-]+\.[\w.-]+\b", re.IGNORECASE)
_L = "A-Za-zÀ-ỹ"  # latin + Vietnamese letters


def _pre_clean(text: str) -> str:
    text = unicodedata.normalize("NFC", text)               # NFC: decomposed VN breaks pacing
    text = re.sub("[​-‏﻿­]", "", text)   # zero-width / BOM / soft hyphen
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)  # control chars (keep \t \n \r)
    text = re.sub(r"[*`~#]+", " ", text)                    # LLM markdown (**bold**, `code`, # ~~) -> space
    text = re.sub(r"([!?])\1+", r"\1", text)                # collapse "!!!"/"???" so TTS doesn't over-emote
    text = _URL_RE.sub(" ", text)                           # URLs/emails are read as garbage
    text = re.sub(rf"(?<=[{_L}])(?=\d)", " ", text)         # "page2" -> "page 2"
    text = re.sub(rf"(?<=\d)(?=[{_L}])", " ", text)         # "12B"/"5km" -> "12 B" / "5 km"
    return text


def _ranges_to_words(text: str, joiner: str) -> str:
    """'10-20' -> '10 <joiner> 20' so a numeric range isn't misread as a date/score."""
    return re.sub(r"(?<=\d)\s*-\s*(?=\d)", f" {joiner} ", text)


# ── Vietnamese ──────────────────────────────────────────────────────────────────────────────
def normalize_vietnamese(text: str) -> str:
    if not text:
        return text
    text = re.sub(r"(\d)\s*%", r"\1 phần trăm", text)
    text = re.sub(r"\$\s*(\d[\d.,]*)", r"\1 đô la", text)   # whole amount after a leading $
    text = re.sub(r"(\d[\d.,]*)\s*\$", r"\1 đô la", text)
    text = re.sub(r"€\s*(\d[\d.,]*)", r"\1 euro", text)
    text = re.sub(r"(\d[\d.,]*)\s*€", r"\1 euro", text)
    text = re.sub(r"£\s*(\d[\d.,]*)", r"\1 bảng Anh", text)
    text = re.sub(r"(\d[\d.,]*)\s*£", r"\1 bảng Anh", text)
    text = re.sub(r"(\d)\s*[₫đ](?=\b)", r"\1 đồng", text)
    text = re.sub(r"(\d[\d.,]*)\s*VND\b", r"\1 đồng", text)
    text = re.sub(r"\s*&\s*", " và ", text)
    text = re.sub(r"\d[\d.,]*\d|\d", lambda m: " " + _read_number_token(m.group()) + " ", text)
    text = re.sub(r"\b[A-Z]{2,4}\b", _spell_acronym, text)
    return re.sub(r"\s{2,}", " ", text).strip()


def _vi_fix_number_seps(text: str) -> str:
    """Make number separators unambiguous for VietNormalizer (it mishandles both '1.234'
    thousands and '3.5' decimals): first collapse grouped-thousands dots ('1.234.567' ->
    '1234567'), then turn any remaining digit-dot-digit (a decimal) into a comma so VN says 'phẩy'."""
    text = re.sub(r"\d{1,3}(?:\.\d{3})+(?=\D|$)", lambda m: m.group().replace(".", ""), text)
    return re.sub(r"(?<=\d)\.(?=\d)", ",", text)


# Phone numbers / long digit runs that VietNormalizer would (wrongly) read as one giant cardinal.
_VI_PHONE_RE = re.compile(r"(?<!\d)(\+?\d[\d \-]{7,12}\d)(?!\d)")


def _vi_pre(text: str) -> str:
    """Fix patterns VietNormalizer mishandles, BEFORE handing it the text."""
    # Phone numbers (and 10+ digit codes) → spelled digit by digit. Runs first so the inner
    # '-' separators aren't turned into 'đến' by the range pass.
    def _phone(m):
        raw = m.group(1)
        digs = re.sub(r"\D", "", raw)
        if len(digs) >= 9 and (digs[0] == "0" or raw.lstrip()[:1] == "+" or len(digs) >= 10):
            return " " + " ".join(_ONES[int(c)] for c in digs) + " "
        return raw
    text = _VI_PHONE_RE.sub(_phone, text)
    # Currency suffix đ/₫/VND → 'đồng' (VN drops a bare trailing 'đ').
    text = re.sub(r"(\d[\d.,]*)\s*[đ₫](?![\wÀ-ỹ])", r"\1 đồng", text)
    text = re.sub(r"(\d[\d.,]*)\s*VND\b", r"\1 đồng", text, flags=re.IGNORECASE)
    text = re.sub(r"€\s*(\d[\d.,]*)", r"\1 euro", text)
    text = re.sub(r"(\d[\d.,]*)\s*€", r"\1 euro", text)
    text = re.sub(r"£\s*(\d[\d.,]*)", r"\1 bảng Anh", text)
    text = re.sub(r"(\d[\d.,]*)\s*£", r"\1 bảng Anh", text)
    # Arithmetic symbols between numbers.
    text = re.sub(r"(?<=\d)\s*\+\s*(?=\d)", " cộng ", text)
    text = re.sub(r"(?<=\d)\s*=\s*(?=\d)", " bằng ", text)
    return text


def _vi_post(text: str) -> str:
    """Clean up after VietNormalizer — it prepends 'ngày'/'tháng' to dates, doubling the word
    when the source already had it ('ngày 15/3' → 'ngày ngày mười lăm...')."""
    text = re.sub(r"\b(ngày|tháng|năm|giờ)\s+\1\b", r"\1", text, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", text).strip()


# ── English ─────────────────────────────────────────────────────────────────────────────────
try:
    import inflect
    _EN = inflect.engine()
except Exception:
    _EN = None


def _read_en_number(m: re.Match) -> str:
    if _EN is None:
        return m.group()
    try:
        words = _EN.number_to_words(m.group().replace(",", ""), andword="")
        return " " + words.replace(",", "") + " "
    except Exception:
        return m.group()


def normalize_english(text: str) -> str:
    text = re.sub(r"(\d)\s*%", r"\1 percent", text)
    text = re.sub(r"\$\s*(\d[\d.,]*)", r"\1 dollars", text)
    text = re.sub(r"(\d[\d.,]*)\s*\$", r"\1 dollars", text)
    text = re.sub(r"€\s*(\d[\d.,]*)", r"\1 euros", text)
    text = re.sub(r"£\s*(\d[\d.,]*)", r"\1 pounds", text)
    text = re.sub(r"\s*&\s*", " and ", text)
    text = re.sub(r"\d[\d.,]*\d|\d", _read_en_number, text)
    return re.sub(r"\s{2,}", " ", text).strip()


# ── Korean number reader (Sino vs native, by counter) ───────────────────────────────────────
# Korean picks its number system by the FOLLOWING counter: minutes/months/won/year/day and most
# measures use Sino-Korean (일 이 삼 …); hours/items/people/age use native Korean (하나 둘 셋 …,
# attributive 한/두/세/네/스무). Picking the wrong system is the #1 tell of synthetic Korean TTS.
# Native tops out at 99; above that we fall back to Sino even with a native counter. We stay
# CONSERVATIVE — native only for a short list of unambiguous high-value counters; everything else
# (money, dates, phone, math, measures) reads Sino, which is the safe majority case.
_KO_SINO = ["영", "일", "이", "삼", "사", "오", "육", "칠", "팔", "구"]
_KO_BIG_UNITS = ["", "만", "억", "조", "경"]
_KO_NATIVE_ONES = ["", "하나", "둘", "셋", "넷", "다섯", "여섯", "일곱", "여덟", "아홉"]
_KO_NATIVE_TENS = ["", "열", "스물", "서른", "마흔", "쉰", "예순", "일흔", "여든", "아흔"]
_KO_NATIVE_ATTR = {1: "한", 2: "두", 3: "세", 4: "네"}   # forms used directly before a counter
_KO_NATIVE_COUNTERS = ["시간", "시", "개", "명", "살"]     # longest first (시간 before 시)
_KO_SINO_PROTECT = ["개월"]                              # Sino counter containing a native substring


def _ko_read_sino_4(n: int) -> str:
    """Read 1..9999 in Sino-Korean (일 omitted before 천/백/십)."""
    out = ""
    for place, unit in ((1000, "천"), (100, "백"), (10, "십")):
        d = (n // place) % 10
        if d:
            out += ("" if d == 1 else _KO_SINO[d]) + unit
    if n % 10:
        out += _KO_SINO[n % 10]
    return out


def _ko_read_sino(n: int) -> str:
    if n == 0:
        return "영"
    groups = []
    while n > 0:
        groups.append(n % 10000)
        n //= 10000
    out = ""
    for gi in range(len(groups) - 1, -1, -1):
        if groups[gi]:
            out += _ko_read_sino_4(groups[gi]) + _KO_BIG_UNITS[gi]
    for u in ("만", "억", "조", "경"):            # 10000 -> 만, not 일만 (drop leading 일)
        if out.startswith("일" + u):
            out = out[1:]
            break
    return out


def _ko_read_native(n: int, attributive: bool):
    """Read 1..99 in native Korean; returns None outside that range (caller falls back to Sino)."""
    if n < 1 or n > 99:
        return None
    tens, ones = n // 10, n % 10
    if attributive:
        if ones == 0:
            return "스무" if n == 20 else _KO_NATIVE_TENS[tens]
        head = _KO_NATIVE_TENS[tens]
        return head + (_KO_NATIVE_ATTR[ones] if ones in _KO_NATIVE_ATTR else _KO_NATIVE_ONES[ones])
    head = _KO_NATIVE_TENS[tens]
    return head + _KO_NATIVE_ONES[ones] if ones else head


def _ko_digits(s: str) -> str:
    """Spell a digit run one digit at a time (0 -> 공, phone/code style)."""
    return " ".join("공" if c == "0" else _KO_SINO[int(c)] for c in s)


def normalize_korean(text: str) -> str:
    if not text:
        return text
    text = re.sub(r"\s*&\s*", " 그리고 ", text)
    text = re.sub(r"(\d)\s*%", r"\1퍼센트", text)
    text = re.sub(r"\$\s*(\d[\d.,]*)", r"\1 달러", text)
    text = re.sub(r"(\d[\d.,]*)\s*\$", r"\1 달러", text)
    text = re.sub(r"€\s*(\d[\d.,]*)", r"\1 유로", text)

    # Phone numbers / codes → digit by digit (0 -> 공). Only hyphenated runs (010-1234-5678) or
    # leading-zero runs are treated as codes; a bare number like 100000000 stays a Sino cardinal.
    def _ko_phone(m):
        digs = re.sub(r"\D", "", m.group())
        if len(digs) >= 9 or (digs.startswith("0") and len(digs) >= 8):
            return " " + _ko_digits(digs) + " "
        return m.group()                                   # short hyphenated (e.g. a range/score)
    text = re.sub(r"(?<!\d)\+?\d[\d]*(?:-\d[\d]*)+(?!\d)", _ko_phone, text)   # hyphenated
    text = re.sub(r"(?<!\d)0\d{7,}(?!\d)",
                  lambda m: " " + _ko_digits(m.group()) + " ", text)          # bare leading-zero

    # Decimals: 3.14 -> 삼 점 일사.
    text = re.sub(r"(?<!\d)(\d+)\.(\d+)",
                  lambda m: _ko_read_sino(int(m.group(1))) + " 점 " + _ko_digits(m.group(2)), text)

    # Sino-protected counters (개월) BEFORE the native pass so 3개월 -> 삼 개월, not 세 개월.
    for c in _KO_SINO_PROTECT:
        text = re.sub(rf"(\d+)\s*{c}",
                      lambda m, c=c: _ko_read_sino(int(m.group(1))) + " " + c, text)

    # Native-counter numbers (attributive form); >99 falls back to Sino.
    def _native(counter):
        def repl(m):
            n = int(m.group(1))
            nat = _ko_read_native(n, attributive=True)
            return (nat if nat is not None else _ko_read_sino(n)) + " " + counter
        return repl
    for c in _KO_NATIVE_COUNTERS:
        text = re.sub(rf"(\d+)\s*{c}", _native(c), text)

    # Everything else → Sino cardinal.
    text = re.sub(r"\d+", lambda m: _ko_read_sino(int(m.group())), text)
    return re.sub(r"\s{2,}", " ", text).strip()


# ── German number reader (cardinals + ordinals) ─────────────────────────────────────────────
# German writes 0..999,999 as ONE concatenated word (einhundertdreiundzwanzig); millions get a
# space + Million(en). Decimal uses a comma ("Komma"); "." is a thousands separator or an ordinal
# marker (a number + "." before a space/word = ordinal). Ordinal declension is context-dependent
# (der dritte / am dritten); we emit the base -te/-ste form, which reads naturally in most cases.
_DE_ONES = ["null", "eins", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun"]
_DE_TEENS = {10: "zehn", 11: "elf", 12: "zwölf", 13: "dreizehn", 14: "vierzehn", 15: "fünfzehn",
             16: "sechzehn", 17: "siebzehn", 18: "achtzehn", 19: "neunzehn"}
_DE_TENS = {20: "zwanzig", 30: "dreißig", 40: "vierzig", 50: "fünfzig", 60: "sechzig",
            70: "siebzig", 80: "achtzig", 90: "neunzig"}
_DE_ORD_IRREG = {1: "erste", 3: "dritte", 7: "siebte", 8: "achte"}


def _de_below_100(n: int) -> str:
    if n in _DE_TEENS:
        return _DE_TEENS[n]
    if n < 10:
        return _DE_ONES[n]                       # 1 -> eins (standalone)
    if n in _DE_TENS:
        return _DE_TENS[n]
    u, t = n % 10, (n // 10) * 10
    return ("ein" if u == 1 else _DE_ONES[u]) + "und" + _DE_TENS[t]   # 21 -> einundzwanzig


def _de_below_1000(n: int) -> str:
    h, r = n // 100, n % 100
    out = (("ein" if h == 1 else _DE_ONES[h]) + "hundert") if h else ""   # 100 -> einhundert
    return out + (_de_below_100(r) if r else "")


def _de_read(n: int) -> str:
    if n == 0:
        return "null"
    mill, rest = n // 1_000_000, n % 1_000_000
    th, r3 = rest // 1000, rest % 1000
    word = ""
    if th:
        word += (("ein" if th == 1 else _de_below_1000(th)) + "tausend")   # 1000 -> eintausend
    if r3:
        word += _de_below_1000(r3)
    if mill:
        m_str = "eine Million" if mill == 1 else _de_read(mill) + " Millionen"
        return (m_str + " " + word).strip() if word else m_str
    return word


def _de_ordinal(n: int) -> str:
    if n in _DE_ORD_IRREG:
        return _DE_ORD_IRREG[n]
    return _de_read(n) + ("te" if n < 20 else "ste")   # vierte / zwanzigste / einundzwanzigste


def normalize_german(text: str) -> str:
    if not text:
        return text
    text = re.sub(r"\s*&\s*", " und ", text)
    text = re.sub(r"(\d)\s*%", r"\1 Prozent", text)
    text = re.sub(r"€\s*(\d[\d.,]*)", r"\1 Euro", text)
    text = re.sub(r"(\d[\d.,]*)\s*€", r"\1 Euro", text)
    text = re.sub(r"\$\s*(\d[\d.,]*)", r"\1 Dollar", text)
    # Ordinal: a number + "." before a space/word/end (e.g. "3. Mai") — do BEFORE separators.
    text = re.sub(r"(?<!\d)(\d+)\.(?=\s|$|[A-Za-zÄÖÜäöü])",
                  lambda m: _de_ordinal(int(m.group(1))), text)
    # Thousands separator dots ("1.234.567" -> "1234567").
    text = re.sub(r"(\d{1,3})(?:\.(\d{3}))+(?=\D|$)", lambda m: m.group().replace(".", ""), text)
    # Decimal (German comma, or a leftover English dot) -> "Komma" + digit-by-digit fraction.
    def _de_dec(m):
        return _de_read(int(m.group(1))) + " Komma " + " ".join(_DE_ONES[int(d)] for d in m.group(2))
    text = re.sub(r"(?<!\d)(\d+)[.,](\d+)", _de_dec, text)
    # Remaining integers -> cardinal.
    text = re.sub(r"\d+", lambda m: _de_read(int(m.group())), text)
    return re.sub(r"\s{2,}", " ", text).strip()


# ── Japanese number reader (Sino-Japanese, kana output) ─────────────────────────────────────
# Output kana (not kanji) so OmniVoice — which does no g2p — pronounces numbers reliably. Handles
# 百/千 rendaku (300 さんびゃく, 600 ろっぴゃく, 3000 さんぜん, 8000 はっせん) and 万/億. Counter
# rendaku (一本 いっぽん, 一個 いっこ …) is NOT modelled beyond the two most common native cases
# (人: 一人 ひとり/二人 ふたり; つ: ひとつ…とお); other counters get the Sino reading + the counter.
_JA_DIGITS = ["", "いち", "に", "さん", "よん", "ご", "ろく", "なな", "はち", "きゅう"]
_JA_HYAKU = {1: "ひゃく", 2: "にひゃく", 3: "さんびゃく", 4: "よんひゃく", 5: "ごひゃく",
             6: "ろっぴゃく", 7: "ななひゃく", 8: "はっぴゃく", 9: "きゅうひゃく"}
_JA_SEN = {1: "せん", 2: "にせん", 3: "さんぜん", 4: "よんせん", 5: "ごせん",
           6: "ろくせん", 7: "ななせん", 8: "はっせん", 9: "きゅうせん"}
_JA_BIG = ["", "まん", "おく", "ちょう", "けい"]
_JA_TSU = {1: "ひとつ", 2: "ふたつ", 3: "みっつ", 4: "よっつ", 5: "いつつ",
           6: "むっつ", 7: "ななつ", 8: "やっつ", 9: "ここのつ", 10: "とお"}


def _ja_4(n: int) -> str:
    """Read 1..9999 in Sino-Japanese kana with 百/千 rendaku."""
    s, h, t, o = n // 1000, (n // 100) % 10, (n // 10) % 10, n % 10
    out = ""
    if s:
        out += _JA_SEN[s]
    if h:
        out += _JA_HYAKU[h]
    if t:
        out += "じゅう" if t == 1 else _JA_DIGITS[t] + "じゅう"
    if o:
        out += _JA_DIGITS[o]
    return out


def _ja_read(n: int) -> str:
    if n == 0:
        return "ゼロ"
    groups = []
    while n > 0:
        groups.append(n % 10000)
        n //= 10000
    out = ""
    for gi in range(len(groups) - 1, -1, -1):
        if groups[gi]:
            out += _ja_4(groups[gi]) + _JA_BIG[gi]      # 一万 = いちまん (no leading-strip, unlike Korean)
    return out


def _ja_frac(digits: str) -> str:
    return "".join("ゼロ" if d == "0" else _JA_DIGITS[int(d)] for d in digits)


def normalize_japanese(text: str) -> str:
    if not text:
        return text
    text = re.sub(r"\s*&\s*", " と ", text)
    text = re.sub(r"(\d)\s*%", r"\1パーセント", text)
    text = re.sub(r"\$\s*(\d[\d.,]*)", r"\1ドル", text)
    text = re.sub(r"(\d[\d.,]*)\s*\$", r"\1ドル", text)
    text = re.sub(r"(?<!\d)(\d+)\.(\d+)",
                  lambda m: _ja_read(int(m.group(1))) + "てん" + _ja_frac(m.group(2)), text)
    # 人: 一人 ひとり / 二人 ふたり are irregular; 3+ take Sino + にん.
    text = re.sub(r"(\d+)\s*人",
                  lambda m: {"1": "ひとり", "2": "ふたり"}.get(m.group(1), _ja_read(int(m.group(1))) + "にん"), text)
    # つ: native counting 1..10 (ひとつ…とお).
    text = re.sub(r"(\d+)\s*つ",
                  lambda m: _JA_TSU.get(int(m.group(1)), _ja_read(int(m.group(1))) + "つ"), text)
    text = re.sub(r"\d+", lambda m: _ja_read(int(m.group())), text)
    return re.sub(r"\s{2,}", " ", text).strip()


# ── VietNormalizer (mature lib; optional) ───────────────────────────────────────────────────
try:
    from vietnormalizer import VietnameseNormalizer
    _VN = VietnameseNormalizer()
except Exception:
    _VN = None


def normalize_for_tts(text: str, lang_code: str) -> str:
    """Normalize `text` for OmniVoice. `lang_code` is the OUTPUT-text language (e.g. 'vi')."""
    if not text:
        return text
    text = _pre_clean(text)   # all languages: NFC, URL/email strip, alphanumeric un-fusing
    if lang_code == "vi":
        # Final safety net: never let CJK leak into a Vietnamese dub's audio.
        if _CJK_RE.search(text):
            text = strip_cjk(text)
            if not text:
                return text
        text = _vi_pre(text)
        text = _ranges_to_words(text, "đến")
        if _VN is not None:
            try:
                return _vi_post(_VN.normalize(_vi_fix_number_seps(text)))
            except Exception:
                pass  # fall back to the built-in normalizer
        return _vi_post(normalize_vietnamese(text))
    if lang_code == "en":
        return normalize_english(_ranges_to_words(text, "to"))
    if lang_code == "ko":
        # Korean uses its own script — do NOT strip Hangul; expand numbers by Sino/native counter.
        return normalize_korean(_ranges_to_words(text, "에서"))
    if lang_code == "ja":
        return normalize_japanese(_ranges_to_words(text, "から"))
    if lang_code == "de":
        return normalize_german(_ranges_to_words(text, "bis"))
    # zh / fr / ... : the model reads the script; just the shared pre-clean is applied.
    return text
