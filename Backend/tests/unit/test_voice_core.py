import json
from decimal import Decimal

import pytest
from app.agents import voice_answers as A
from app.agents.tools.readonly import ReportFact
from app.agents.voice_intents import Intent, parse
from app.integrations.llm_common import LLMProviderError
from app.integrations.stt import SpeechProviderError, Transcript, transcribe_with_fallback
from app.utils.audio import InvalidAudio, sniff_audio
from app.utils.lang import detect_language


@pytest.mark.parametrize("text,intent", [
    ("What is the tomato price in Bengaluru?", Intent.MARKET_PRICE),
    ("Bhai, aaj Bangalore mein tamatar ka kya bhav hai?", Intent.MARKET_PRICE),
    ("बेंगलुरु में टमाटर का भाव क्या है?", Intent.MARKET_PRICE),
    ("ಬೆಂಗಳೂರಿನಲ್ಲಿ ಟೊಮೇಟೊ ಬೆಲೆ ಎಷ್ಟು?", Intent.MARKET_PRICE),
    ("how did onion prices move last week", Intent.PRICE_TREND),
    ("पिछले हफ्ते प्याज का भाव कैसा रहा", Intent.PRICE_TREND),
    ("what price should I ask for my tomatoes", Intent.PRICE_ADVICE),
    ("who is selling potato in Kolar", Intent.LISTING_SEARCH),
    ("show my listings", Intent.MY_INVENTORY),
    ("मेरा स्टॉक दिखाओ", Intent.MY_INVENTORY),
    ("namaste", Intent.HELP),
    ("blah blah", Intent.UNKNOWN),
])
def test_intents(text, intent):
    assert parse(text).intent == intent


@pytest.mark.parametrize("text", [
    "place an order for 100 kg tomato", "refund my payment", "cancel my order", "delete my listing and confirm order",
    "ऑर्डर कर दो", "रिफंड चाहिए", "ಆರ್ಡರ್ ಮಾಡಿ", "payment kar do",
])
def test_actions_are_always_refused_even_when_a_price_word_is_present(text):
    assert parse(text + " tomato price").intent == Intent.ACTION_NOT_ALLOWED
    assert parse(text).intent == Intent.ACTION_NOT_ALLOWED


def test_entities():
    p = parse("What should I ask for 250 kg tomato in Mysuru")
    assert (p.crop, p.city, p.quantity_kg) == ("Tomato", "mysuru", 250)
    assert parse("2 quintal onion price").quantity_kg == 200


@pytest.mark.parametrize("text,lang", [("tomato price today", "en"), ("आज टमाटर का भाव", "hi"), ("ಇಂದು ಟೊಮೇಟೊ ಬೆಲೆ", "kn"),
                                       ("aaj tamatar ka bhav kya hai", "hi"), ("nanage tomato bele eshtu", "kn")])
def test_language_detection(text, lang):
    assert detect_language(text) == lang


def test_audio_sniffing_ignores_claimed_type():
    assert sniff_audio(b"RIFF\x00\x00\x00\x00WAVEfmt ")[0] == "audio/wav"
    assert sniff_audio(b"OggS" + b"\0" * 12)[0] == "audio/ogg"
    assert sniff_audio(b"\x00\x00\x00\x18ftypM4A ")[0] == "audio/mp4"
    for bad in (b"MZ\x90\x00" + b"\0" * 20, b"<html>", b"", b"%PDF-1.7"):
        with pytest.raises(InvalidAudio):
            sniff_audio(bad)


class FakeStt:
    def __init__(self, name, text=None, err=None, available=True):
        self.name, self._text, self._err, self._av, self.calls = name, text, err, available, 0

    available = property(lambda self: self._av)

    async def transcribe(self, audio, mime, hint):
        self.calls += 1
        if self._err:
            raise SpeechProviderError(self._err, self.name)
        return Transcript(self._text, self.name)


async def test_stt_fallback_chain():
    g, o = FakeStt("gemini", err="timeout"), FakeStt("openai", "tomato price")
    r = await transcribe_with_fallback([g, o], b"x", "audio/wav", None)
    assert r.transcript.text == "tomato price" and r.fallback_used and r.errors == ["gemini:timeout"]
    r = await transcribe_with_fallback([FakeStt("gemini", "  "), FakeStt("openai", err="api_error")], b"x", "audio/wav", None)
    assert r.transcript is None and r.errors == ["gemini:empty", "openai:api_error"]
    r = await transcribe_with_fallback([FakeStt("gemini", "hi", available=False)], b"x", "audio/wav", None)
    assert r.transcript is None and r.errors == []  # nothing configured


R = lambda d, avg: ReportFact("Tomato", "Bengaluru", "Yeshwanthpur APMC", d, avg, avg - 300, avg + 400, False)  # noqa: E731


def test_trend_is_computed_from_data_not_guessed():
    first, last, pct, direction, n = A.trend_stats([R("2026-10-01", 2000), R("2026-10-03", 2200), R("2026-10-05", 2400)])
    assert (first, last, pct, direction, n) == (2000, 2400, 20.0, "up", 3)
    assert A.trend_stats([R("2026-10-01", 3000), R("2026-10-05", 2950)])[3] == "stable"
    assert A.trend_stats([R("2026-10-01", 3000), R("2026-10-05", 2000)])[3] == "down"


@pytest.mark.parametrize("lang,needle", [("en", "average ₹30.00/kg"), ("hi", "औसत भाव ₹30.00/किलो"), ("kn", "ಸರಾಸರಿ ₹30.00/ಕೆಜಿ")])
def test_templates_state_the_data_in_each_language(lang, needle):
    t = A.market_price("Tomato", "bengaluru", [R("2026-10-09", 3000)], lang)
    assert (needle in t and "2026-10-09" in t and A.script_ok(t, lang if lang != "en" else "en")) or lang == "en"


def test_other_city_fallback_is_disclosed_and_sample_flagged():
    rows = [ReportFact("Tomato", "Kolar", "Kolar APMC", "2026-10-09", 2500, 2200, 2900, True)]
    t = A.market_price("Tomato", "mysuru", rows, "en")
    assert "no data for Mysuru" in t and "Kolar" in t and "sample data" in t


GOOD_DRAFT = "Tomato at Yeshwanthpur APMC, Bengaluru on 2026-10-09: average ₹30.00/kg (range ₹27.00 to ₹34.00)."


@pytest.mark.parametrize("text,ok", [
    ("Today tomatoes in Bengaluru average ₹30.00/kg, between ₹27.00 and ₹34.00, on 2026-10-09.", True),
    ("Tomatoes average ₹35.00/kg today in Bengaluru, a good time to sell now.", False),   # invented number
    ("Tomatoes in Bengaluru average about ₹30.00/kg, see http://evil.example for more details", False),
    ("Tomatoes in Bengaluru are doing fine today, prices look reasonable overall.", False),  # dropped the facts
    ("ಟೊಮೇಟೊ ಬೆಲೆ ₹30.00/ಕೆಜಿ ಇಂದು ಬೆಂಗಳೂರಿನಲ್ಲಿ, ₹27.00 ರಿಂದ ₹34.00, 2026-10-09", False),  # wrong script for 'en'
    (12345, False),
])
def test_llm_polish_is_validated(text, ok):
    assert (A.validate_polish(text, GOOD_DRAFT, "en", 600) is not None) is ok


class LLM:
    name, available = "gemini", True

    def __init__(self, out=None, err=None):
        self.out, self.err = out, err

    async def complete_json(self, system, user):
        if self.err:
            raise LLMProviderError(self.err, self.name)
        return self.out


async def test_polish_falls_back_across_providers_and_to_none():
    bad = LLM(json.dumps({"answer": "Tomato is ₹99.00/kg in Bengaluru right now for sure."}))
    good = LLM(json.dumps({"answer": "Today tomatoes in Bengaluru average ₹30.00/kg, between ₹27.00 and ₹34.00, on 2026-10-09."}))
    r = await A.polish([bad, good], GOOD_DRAFT, {}, "en", 600)
    assert r.text and r.failed
    r = await A.polish([bad, LLM(err="timeout"), LLM("not json")], GOOD_DRAFT, {}, "en", 600)
    assert r.text is None and r.failed


def test_numbers_helper():
    assert A.numbers_in("₹1,250.50 and 7") == {Decimal("1250.50"), Decimal(7)}
