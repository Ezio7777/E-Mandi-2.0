"""Deterministic intent + entity extraction for farmer/buyer voice queries (English, Hindi, Kannada, romanised).
The intent set is CLOSED. An LLM may only help classify an otherwise-UNKNOWN utterance into this set (see voice_graph);
crops and cities are always resolved through our own gazetteers, so free-form model output never reaches a tool."""
import re
from dataclasses import dataclass
from enum import StrEnum

from app.utils.crops import find_crop_in_text, normalize_text
from app.utils.geo import find_city_in_text


class Intent(StrEnum):
    MARKET_PRICE = "MARKET_PRICE"          # what is crop X selling for (reference data)
    PRICE_TREND = "PRICE_TREND"            # how did the price move recently
    PRICE_ADVICE = "PRICE_ADVICE"          # what should I ask for (deterministic pricing engine)
    LISTING_SEARCH = "LISTING_SEARCH"      # what is available to buy (public listing facts only)
    MY_INVENTORY = "MY_INVENTORY"          # my own listings (FARMER only)
    ACTION_NOT_ALLOWED = "ACTION_NOT_ALLOWED"  # orders / payments / refunds / deletions are never done by voice
    HELP = "HELP"
    UNKNOWN = "UNKNOWN"


# (pattern, native?) native-script patterns use substring matching (those scripts inflect); Latin uses word boundaries.
def _rx(*words: str) -> re.Pattern[str]:
    parts = [re.escape(w) if not w.isascii() else rf"(?<![a-z]){re.escape(w)}(?![a-z])" for w in words]
    return re.compile("|".join(parts))


_ACTION = _rx("place order", "place an order", "pay for", "make payment", "make a payment", "refund", "cancel my", "cancel the order",
              "delete my", "transfer money", "approve", "confirm order", "order kar", "payment kar", "paise bhej", "cancel kar",
              "ऑर्डर कर", "आर्डर कर", "भुगतान कर", "पेमेंट कर", "रिफंड", "कैंसल कर", "रद्द कर", "ಆರ್ಡರ್ ಮಾಡಿ", "ಪಾವತಿ ಮಾಡಿ", "ರದ್ದು ಮಾಡಿ",
              "ರಿಫಂಡ್", "ಹಣ ಕಳುಹಿಸಿ")
_MINE = _rx("my listing", "my listings", "my stock", "my inventory", "my crops", "my produce", "mere listing", "meri listing",
            "mera stock", "mere stock", "mera maal", "mere maal", "मेरी लिस्टिंग", "मेरा स्टॉक", "मेरे स्टॉक", "मेरा माल", "मेरी फसल",
            "ನನ್ನ ಲಿಸ್ಟಿಂಗ್", "ನನ್ನ ಸ್ಟಾಕ್", "ನನ್ನ ಬೆಳೆ", "nanna stock", "nanna listing")
_ADVICE = _rx("should i sell", "sell my", "sell at", "what price should", "ask price", "asking price", "suggest a price",
              "suggested price", "kitne mein bech", "kis bhav", "bechna chahiye", "bechu", "bechun", "kitne ka bech", "बेचूं", "बेचना",
              "बेचूँ", "किस भाव", "ಮಾರಬೇಕು", "ಎಷ್ಟಕ್ಕೆ ಮಾರ", "maaralu", "eshtakke maara")
_TREND = _rx("trend", "history", "historical", "last week", "last month", "past week", "past month", "this week", "going up",
             "going down", "increase", "decrease", "pichhle", "pichle", "hafte", "mahine", "badh", "gir ", "बढ़", "गिर", "पिछले",
             "हफ्ते", "महीने", "ಹಿಂದಿನ", "ಏರಿಕೆ", "ಇಳಿಕೆ", "ವಾರ", "ತಿಂಗಳು", "haudu", "bele eri")
_LIST = _rx("available", "who is selling", "who sells", "for sale", "buy", "purchase", "kharid", "kharidna", "milega", "milta",
            "खरीद", "उपलब्ध", "मिलेगा", "बिक्री के लिए", "ಲಭ್ಯ", "ಖರೀದಿ", "ಸಿಗುತ್ತದೆ", "sigutte", "labhya")
_PRICE = _rx("price", "rate", "rates", "cost", "bhav", "bhaav", "bhaw", "daam", "dam", "kimat", "keemat", "how much", "mandi",
             "कीमत", "भाव", "दाम", "रेट", "मंडी", "ಬೆಲೆ", "ದರ", "ಭಾವ", "ರೇಟ್", "bele", "dara", "bhaava", "eshtu")
_HELP = _rx("help", "what can you do", "hello", "hi", "hey", "namaste", "namaskar", "नमस्ते", "मदद", "ನಮಸ್ಕಾರ", "ಸಹಾಯ", "madad")


@dataclass
class Parsed:
    intent: Intent
    crop: str | None = None
    city: str | None = None            # canonical gazetteer key, e.g. "bengaluru"
    days: int = 14                     # lookback for trend questions
    quantity_kg: int | None = None
    source: str = "rules"              # rules | llm | context


_QTY = re.compile(r"(\d{1,6})\s*(?:kg|kgs|kilo|kilos|किलो|ಕೆಜಿ|ಕೆ\.ಜಿ)", re.IGNORECASE)
_QUINTAL = re.compile(r"(\d{1,4})\s*(?:quintal|quintals|क्विंटल|ಕ್ವಿಂಟಾಲ್)", re.IGNORECASE)


def extract_days(t: str) -> int:
    if re.search(r"month|mahine|महीन|ತಿಂಗಳ", t):
        return 30
    if re.search(r"week|hafte|हफ्त|ವಾರ", t):
        return 7
    return 14


def extract_quantity_kg(t: str) -> int | None:
    m = _QTY.search(t)
    if m:
        return min(int(m.group(1)), 1_000_000)
    q = _QUINTAL.search(t)
    return min(int(q.group(1)) * 100, 1_000_000) if q else None


def classify(text: str) -> Intent:
    t = normalize_text(text)
    if _ACTION.search(t):
        return Intent.ACTION_NOT_ALLOWED
    if _MINE.search(t):
        return Intent.MY_INVENTORY
    if _ADVICE.search(t):
        return Intent.PRICE_ADVICE
    if _TREND.search(t):
        return Intent.PRICE_TREND
    if _LIST.search(t) and not _PRICE.search(t):
        return Intent.LISTING_SEARCH
    if _PRICE.search(t):
        return Intent.MARKET_PRICE
    if _LIST.search(t):
        return Intent.LISTING_SEARCH
    if _HELP.search(t):
        return Intent.HELP
    return Intent.UNKNOWN


def parse(text: str) -> Parsed:
    t = normalize_text(text)
    intent = classify(text)
    crop = find_crop_in_text(text)
    if intent == Intent.UNKNOWN and crop:  # "tomato in Kolar?" -> they want the price
        intent = Intent.MARKET_PRICE
    return Parsed(intent=intent, crop=crop, city=find_city_in_text(text), days=extract_days(t), quantity_kg=extract_quantity_kg(t))
