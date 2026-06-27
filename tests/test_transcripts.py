from app.transcripts import TranscriptProvider


class FakeResponse:
    status_code = 200
    headers = {}

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload

    def raise_for_status(self):
        return None


def test_supadata_always_requests_native_text(monkeypatch):
    captured = {}

    def fake_get(url, **kwargs):
        captured.update(url=url, **kwargs)
        return FakeResponse({"content": "caption text"})

    monkeypatch.setattr("app.transcripts.requests.get", fake_get)
    result = TranscriptProvider("supadata", "key", 100).fetch("video")
    assert result.outcome == "success"
    assert captured["params"]["mode"] == "native"
    assert captured["params"]["text"] == "true"


def test_scribetube_segments_are_normalized(monkeypatch):
    monkeypatch.setattr(
        "app.transcripts.requests.get",
        lambda *args, **kwargs: FakeResponse({"segments": [{"text": "one"}, {"text": "two"}]}),
    )
    result = TranscriptProvider("scribetube", "key", 1000).fetch("video")
    assert result.text == "one two"


def test_generated_asr_is_rejected(monkeypatch):
    monkeypatch.setattr(
        "app.transcripts.requests.get",
        lambda *args, **kwargs: FakeResponse({"source": "asr", "transcript": [{"text": "generated"}]}),
    )
    result = TranscriptProvider("transcriptapi_io", "key", 100).fetch("video")
    assert result.outcome == "no_captions"
