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
    text = re.sub(r"\s*&\s*", " and ", text)
    text = re.sub(r"\d[\d.,]*\d|\d", _read_en_number, text)
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
    # ja / ko / zh / fr / ... : the model reads the script; just the shared pre-clean is applied.
    return text
