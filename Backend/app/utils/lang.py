"""Deterministic language detection for the three supported languages (en / hi / kn), including romanised Hindi/Kannada
('aaj tamatar ka bhav kya hai'). No network, no model: reproducible and testable."""
import re

from app.utils.crops import normalize_text

SUPPORTED = ("en", "hi", "kn")
LANG_NAMES = {"en": "English", "hi": "Hindi", "kn": "Kannada"}
_HI_ROMAN = {"bhav", "bhaav", "kya", "aaj", "aj", "mein", "me", "ka", "ki", "ke", "hai", "hain", "kitna", "kitne", "kaise", "mera",
             "meri", "mere", "bhai", "tamatar", "pyaz", "aloo", "bech", "bechu", "bechna", "daam", "kimat", "batao", "bataiye",
             "chahiye", "nahi", "kal", "pichhle", "hafte", "mahine", "abhi", "kharid", "kharidna", "mujhe", "kahan"}
_KN_ROMAN = {"beku", "eshtu", "bele", "ide", "yaava", "nanage", "ittu", "illi", "yelli", "inna", "indu", "nimma", "nanna",
             "hege", "yenu", "maaruvudu", "kodi", "bhaava", "eerulli", "akki", "ragi", "alugadde", "gelu", "heli", "tilisi"}


def script_counts(text: str) -> tuple[int, int, int]:
    dev = sum(1 for c in text if "ऀ" <= c <= "ॿ")
    kan = sum(1 for c in text if "ಀ" <= c <= "೿")
    lat = sum(1 for c in text if c.isascii() and c.isalpha())
    return dev, kan, lat


def detect_language(text: str, hint: str | None = None) -> str:
    dev, kan, lat = script_counts(text)
    if dev + kan > 0 and dev + kan >= lat * 0.5:  # mostly native script
        return "hi" if dev >= kan else "kn"
    toks = set(re.findall(r"[a-z]+", normalize_text(text)))
    hi, kn = len(toks & _HI_ROMAN), len(toks & _KN_ROMAN)
    if hi >= 2 and hi > kn:
        return "hi"
    if kn >= 2 and kn > hi:
        return "kn"
    if hint in SUPPORTED and (hi or kn):  # weak romanised signal + a client hint
        return hint
    if hi == 1 and kn == 0 and len(toks) <= 4:
        return "hi"
    return "en"
