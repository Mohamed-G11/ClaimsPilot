"""POST /claims/upload and GET /claims/options (customer web app). Small generated
images, a temporary uploads folder, agents replaced by fakes or stubs."""
import struct
import zlib

import pytest
from fastapi.testclient import TestClient

from api import pipeline, upload
from api.main import app
from claimspilot.schemas import ClaimInput

client = TestClient(app)


def png(width: int = 2, height: int = 2) -> bytes:
    """A valid, tiny PNG (white pixels), built without any image library."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    raw = b"".join(b"\x00" + b"\xff\xff\xff" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64           # JPEG signature (content not decoded here)


@pytest.fixture
def uploads(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAIMSPILOT_UPLOADS_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def seen_claims(monkeypatch):
    """Replace the pipeline: record the ClaimInput, answer like /claims/analyze with stubs."""
    claims = []

    def fake_analyze(claim: ClaimInput):
        claims.append(claim)
        vision = pipeline.vision_stub(claim)
        nlp, policy = pipeline.nlp_stub(claim, vision), pipeline.policy_stub(claim, vision)
        decision, how = pipeline.make_decision(claim, vision, nlp, policy, stubs=[])
        return pipeline.ClaimAnalysis(vision=vision, nlp=nlp, policy=policy, decision=decision,
                                      agents={"decision": how})

    monkeypatch.setattr(upload, "analyze_claim", fake_analyze)
    return claims


def send(photos, text="Collision sur un parking.", policy_id="AXA-TR", language="fr"):
    files = [("photos", (name, content, kind)) for name, content, kind in photos]
    return client.post("/claims/upload", files=files,
                       data={"text": text, "policy_id": policy_id, "language": language})


def test_options_list_every_contract_with_readable_names():
    body = client.get("/claims/options").json()
    ids = {p["policy_id"] for p in body["policies"]}
    assert ids == {"AXA-TR", "AXA-TIERS", "SANLAM-TR", "SANLAM-TIERS"}
    assert {p["formula_name"] for p in body["policies"]} == {
        "Tous risques", "Au tiers (responsabilité civile)"}
    assert body["max_photos"] == 5 and body["max_photo_mb"] == 10


def test_upload_saves_the_photos_and_runs_the_pipeline(uploads, seen_claims):
    response = send([("front.png", png(), "image/png"), ("side.jpg", JPEG, "image/jpeg")])
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"vision", "nlp", "policy", "decision", "agents"}  # = /claims/analyze
    claim = seen_claims[0]
    assert claim.claim_id.startswith("WEB-") and body["decision"]["claim_id"] == claim.claim_id
    assert claim.text == "Collision sur un parking." and claim.policy_id == "AXA-TR"
    folder = uploads / claim.claim_id
    assert sorted(p.name for p in folder.iterdir()) == ["photo_1.png", "photo_2.jpg"]
    assert claim.photo_paths == [str((folder / "photo_1.png").resolve()),
                                 str((folder / "photo_2.jpg").resolve())]
    assert (folder / "photo_1.png").read_bytes() == png()


def test_upload_runs_the_real_pipeline_end_to_end(uploads, monkeypatch):
    def unavailable(*_args):
        raise ImportError("library not installed")

    for name in ("vision_real", "nlp_real", "policy_real"):
        monkeypatch.setattr(pipeline, name, unavailable)
    body = send([("front.png", png(), "image/png")]).json()
    assert body["agents"]["decision"] == "safety: stub used"     # same rules as /claims/analyze
    assert body["decision"]["decision"] == "human_review"


@pytest.mark.parametrize(("kwargs", "status", "code"), [
    ({"photos": []}, 422, None),                                  # FastAPI: field required
    ({"photos": [("p.png", png(), "image/png")] * 6}, 400, "too_many_photos"),
    ({"photos": [("doc.pdf", b"%PDF-1.7 ...", "application/pdf")]}, 415, "not_an_image"),
    ({"photos": [("fake.jpg", b"not really a jpeg", "image/jpeg")]}, 415, "not_an_image"),
    ({"photos": [("p.png", png(), "image/png")], "policy_id": "XYZ-TR"}, 400, "unknown_policy"),
    ({"photos": [("p.png", png(), "image/png")], "language": "de"}, 400, "unknown_language"),
])
def test_bad_requests_get_a_clear_json_error(uploads, seen_claims, kwargs, status, code):
    response = send(**kwargs)
    assert response.status_code == status
    if code:
        assert response.json()["detail"]["code"] == code
    assert seen_claims == []                                      # the pipeline never ran
    assert list(uploads.iterdir()) == []                          # nothing saved


def test_photo_over_the_size_limit_is_refused(uploads, seen_claims, monkeypatch):
    monkeypatch.setenv("CLAIMSPILOT_MAX_PHOTO_MB", "0.001")      # about 1 KB
    response = send([("big.jpg", JPEG + b"\x00" * 2000, "image/jpeg")])
    assert response.status_code == 413
    detail = response.json()["detail"]
    assert detail["code"] == "photo_too_large" and detail["filename"] == "big.jpg"
    assert seen_claims == []


def test_web_app_is_served_at_app():
    response = client.get("/app/")
    assert response.status_code == 200 and "text/html" in response.headers["content-type"]
    assert client.get("/app/app.js").status_code == 200
