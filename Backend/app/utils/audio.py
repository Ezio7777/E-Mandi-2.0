"""Server-side audio validation: magic-byte sniffing (never trusts the client's content-type header)."""


class InvalidAudio(ValueError):
    pass


def sniff_audio(data: bytes) -> tuple[str, str]:
    """Returns (mime, extension) for supported containers, else raises InvalidAudio."""
    h = data[:16]
    if h[:4] == b"RIFF" and h[8:12] == b"WAVE":
        return "audio/wav", "wav"
    if h[:4] == b"OggS":
        return "audio/ogg", "ogg"
    if h[:4] == b"\x1a\x45\xdf\xa3":
        return "audio/webm", "webm"
    if h[:4] == b"fLaC":
        return "audio/flac", "flac"
    if h[4:8] == b"ftyp":
        return "audio/mp4", "m4a"
    if h[:3] == b"ID3" or (len(h) > 1 and h[0] == 0xFF and (h[1] & 0xE0) == 0xE0):
        return "audio/mpeg", "mp3"
    raise InvalidAudio("Unsupported audio format. Allowed: WAV, MP3, M4A/MP4, OGG, WebM, FLAC")
