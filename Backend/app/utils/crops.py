"""Deterministic crop-name normalisation across English / Hindi / Kannada (incl. common transliterations).
Used by market search, pricing and (later) the voice agent so 'tamatar' / 'टमाटर' / 'ಟೊಮೇಟೊ' all mean Tomato."""
import re
import unicodedata

_ALIASES: dict[str, tuple[str, ...]] = {
    "Tomato": ("tomato", "tomatoes", "tamatar", "tamaatar", "टमाटर", "ಟೊಮೇಟೊ", "ಟೊಮ್ಯಾಟೊ", "tomate"),
    "Onion": ("onion", "onions", "pyaz", "pyaaz", "pyaj", "प्याज", "प्याज़", "ಈರುಳ್ಳಿ", "eerulli", "ullipaya"),
    "Potato": ("potato", "potatoes", "aloo", "aalu", "आलू", "ಆಲೂಗಡ್ಡೆ", "alugadde"),
    "Chilli": ("chilli", "chili", "chillies", "mirch", "mirchi", "मिर्च", "मिर्ची", "ಮೆಣಸಿನಕಾಯಿ", "menasinakayi"),
    "Brinjal": ("brinjal", "eggplant", "baingan", "बैंगन", "ಬದನೆಕಾಯಿ", "badanekayi"),
    "Cabbage": ("cabbage", "patta gobhi", "pattagobhi", "पत्ता गोभी", "ಎಲೆಕೋಸು", "elekosu"),
    "Carrot": ("carrot", "carrots", "gajar", "गाजर", "ಗಜ್ಜರಿ", "gajjari"),
    "Banana": ("banana", "bananas", "kela", "केला", "ಬಾಳೆಹಣ್ಣು", "balehannu"),
    "Mango": ("mango", "mangoes", "aam", "आम", "ಮಾವಿನಹಣ್ಣು", "mavinahannu"),
    "Rice": ("rice", "paddy", "chawal", "चावल", "ಅಕ್ಕಿ", "akki"),
    "Wheat": ("wheat", "gehun", "gehu", "गेहूं", "गेहूँ", "ಗೋಧಿ", "godhi"),
    "Ragi": ("ragi", "finger millet", "रागी", "ಎರಾಗಿ", "ರಾಗಿ"),
    "Maize": ("maize", "corn", "makka", "makai", "मक्का", "ಮೆಕ್ಕೆಜೋಳ", "mekkejola"),
}
_INDEX: dict[str, str] = {}
for canon, names in _ALIASES.items():
    _INDEX[canon.lower()] = canon
    for n in names:
        _INDEX[unicodedata.normalize("NFC", n.lower())] = canon
_TOKEN = re.compile(r"[\w]+", re.UNICODE)


def normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s).strip().lower())


def canonical_crop(name: str) -> str | None:
    """Exact alias lookup for a crop name; None if unknown."""
    return _INDEX.get(normalize_text(name))


def crop_or_title(name: str) -> str:
    """Canonical crop if known, else a cleaned Title Case version (so unknown crops still group consistently)."""
    return canonical_crop(name) or normalize_text(name).title()


def find_crop_in_text(text: str) -> str | None:
    """Find the first known crop mentioned in free text (multi-word aliases supported)."""
    t = normalize_text(text)
    for alias in sorted(_INDEX, key=len, reverse=True):  # longest alias first ('patta gobhi' before 'gobhi')
        if len(alias) >= 3 and re.search(rf"(?<![\w]){re.escape(alias)}(?![\w])", t):
            return _INDEX[alias]
    return None
