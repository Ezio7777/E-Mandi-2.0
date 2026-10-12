"""Small offline gazetteer of major Indian mandi cities + haversine distance. No external geocoding calls.
Straight-line distance is an approximation used for ranking only; unknown places are handled explicitly."""
import math
from dataclasses import dataclass

from app.utils.crops import normalize_text


@dataclass(frozen=True)
class GeoPoint:
    lat: float
    lon: float
    city: str | None = None  # canonical gazetteer city, if resolved by name


_CITIES: dict[str, tuple[float, float]] = {
    "bengaluru": (12.9716, 77.5946), "mysuru": (12.2958, 76.6394), "hubballi": (15.3647, 75.1240),
    "belagavi": (15.8497, 74.4977), "mangaluru": (12.9141, 74.8560), "kalaburagi": (17.3297, 76.8343),
    "ballari": (15.1394, 76.9214), "davanagere": (14.4644, 75.9218), "shivamogga": (13.9299, 75.5681),
    "tumakuru": (13.3379, 77.1173), "hassan": (13.0068, 76.0996), "kolar": (13.1360, 78.1294),
    "chikkaballapur": (13.4355, 77.7315), "mandya": (12.5218, 76.8951), "chennai": (13.0827, 80.2707),
    "hyderabad": (17.3850, 78.4867), "pune": (18.5204, 73.8567), "mumbai": (19.0760, 72.8777),
    "nashik": (19.9975, 73.7898), "delhi": (28.6139, 77.2090), "ahmedabad": (23.0225, 72.5714),
    "kolkata": (22.5726, 88.3639), "coimbatore": (11.0168, 76.9558), "kochi": (9.9312, 76.2673),
    "vijayawada": (16.5062, 80.6480), "nagpur": (21.1458, 79.0882), "lucknow": (26.8467, 80.9462),
    "jaipur": (26.9124, 75.7873), "indore": (22.7196, 75.8577),
}
_ALIASES = {"bangalore": "bengaluru", "mysore": "mysuru", "hubli": "hubballi", "belgaum": "belagavi", "mangalore": "mangaluru",
            "gulbarga": "kalaburagi", "bellary": "ballari", "bombay": "mumbai", "calcutta": "kolkata", "madras": "chennai",
            "cochin": "kochi", "new delhi": "delhi", "bengaluru urban": "bengaluru", "bangalore urban": "bengaluru"}


def canonical_city(name: str | None) -> str | None:
    """'Yeshwanthpur, Bangalore' -> 'bengaluru' (tries the whole string, then each comma/dash-separated part)."""
    if not name:
        return None
    parts = [normalize_text(name)] + [normalize_text(p) for p in name.replace("-", ",").split(",")]
    for p in parts:
        p = _ALIASES.get(p, p)
        if p in _CITIES:
            return p
    return None


def resolve_point(name: str | None, lat: float | None = None, lon: float | None = None) -> GeoPoint | None:
    city = canonical_city(name)
    if lat is not None and lon is not None:
        return GeoPoint(float(lat), float(lon), city)
    return GeoPoint(*_CITIES[city], city=city) if city else None


def haversine_km(a: GeoPoint, b: GeoPoint) -> float:
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dphi, dl = p2 - p1, math.radians(b.lon - a.lon)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


# Native-script / common spellings for spoken queries (voice). Additive: used only by find_city_in_text.
_NATIVE = {"बेंगलुरु": "bengaluru", "बैंगलोर": "bengaluru", "बेंगलोर": "bengaluru", "ಬೆಂಗಳೂರು": "bengaluru", "ಬೆಂಗಳೂರ": "bengaluru",
           "मैसूर": "mysuru", "ಮೈಸೂರು": "mysuru", "हुबली": "hubballi", "ಹುಬ್ಬಳ್ಳಿ": "hubballi", "बेलगाम": "belagavi",
           "ಬೆಳಗಾವಿ": "belagavi", "मंगलोर": "mangaluru", "ಮಂಗಳೂರು": "mangaluru", "ತುಮಕೂರು": "tumakuru", "ಹಾಸನ": "hassan",
           "कोलार": "kolar", "ಕೋಲಾರ": "kolar", "मुंबई": "mumbai", "दिल्ली": "delhi", "पुणे": "pune", "चेन्नई": "chennai",
           "हैदराबाद": "hyderabad", "नाशिक": "nashik", "कोलकाता": "kolkata", "जयपुर": "jaipur", "लखनऊ": "lucknow",
           "इंदौर": "indore", "नागपुर": "nagpur", "ದಾವಣಗೆರೆ": "davanagere", "ಮಂಡ್ಯ": "mandya", "ಶಿವಮೊಗ್ಗ": "shivamogga"}


def find_city_in_text(text: str) -> str | None:
    """First gazetteer city mentioned in free text (English names/aliases, Devanagari or Kannada script). Canonical key."""
    import re
    t = normalize_text(text)
    forms = {**_NATIVE, **{a[:-2]: c for a, c in _NATIVE.items() if a.endswith("\u0cc1") and len(a) > 5}}  # Kannada: ಮೈಸೂರು -> ಮೈಸೂರಿನಲ್ಲಿ
    for alias, canon in sorted(forms.items(), key=lambda kv: -len(kv[0])):
        if alias in t:  # native scripts inflect ('बेंगलुरु में'), so substring match
            return canon
    names = sorted({*_CITIES, *_ALIASES}, key=len, reverse=True)
    for n in names:
        if re.search(rf"(?<![\w]){re.escape(n)}(?![\w])", t):
            return _ALIASES.get(n, n)
    return None
