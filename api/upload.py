"""Claim upload for the customer web app (webapp/, served at /app).

POST /claims/upload (multipart/form-data) takes 1 to 5 photos plus the claim
fields, saves the photos under data/uploads/<claim_id>/ and runs the same
pipeline as POST /claims/analyze (same response). GET /claims/options gives the
web app the valid contracts and the limits, so nothing is written twice.

Errors are JSON with a stable code (the web app shows a French message for each):
    {"detail": {"code": "photo_too_large", "message": "...", ...}}

Settings (env vars):
    CLAIMSPILOT_MAX_PHOTO_MB   size limit per photo, default 10
    CLAIMSPILOT_UPLOADS_DIR    where photos are saved, default <repo>/data/uploads
No authentication and no CORS: the web app is served by the API (same origin).
"""
import os
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from api.pipeline import ClaimAnalysis, analyze_claim
from claimspilot.schemas import ClaimInput

REPO_ROOT = Path(__file__).resolve().parents[1]
MAX_PHOTOS = 5
LANGUAGES = ("fr", "en", "ar")
# Magic bytes: the photo must really be a JPEG or a PNG, whatever its name says.
SIGNATURES = {"jpg": b"\xff\xd8\xff", "png": b"\x89PNG\r\n\x1a\n"}
# Readable names for the contracts of agents/policy/config.yaml (French, shown to customers).
FORMULA_NAMES = {"TR": "Tous risques", "TIERS": "Au tiers (responsabilité civile)"}

router = APIRouter()


def max_photo_bytes() -> int:
    return int(float(os.getenv("CLAIMSPILOT_MAX_PHOTO_MB", "10")) * 1024 * 1024)


def uploads_dir() -> Path:
    return Path(os.getenv("CLAIMSPILOT_UPLOADS_DIR", REPO_ROOT / "data/uploads"))


def policies() -> list[dict]:
    """Every valid policy_id = insurer x formula of the policy agent's config."""
    from agents.policy.settings import CONFIG

    return [{"policy_id": f"{insurer}-{formula}", "insurer": insurer, "formula": formula,
             "formula_name": FORMULA_NAMES.get(formula, formula)}
            for insurer in CONFIG["insurers"] for formula in CONFIG["formulas"]]


def error(status: int, code: str, message: str, **details) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message,
                                                     **details})


def photo_extension(content: bytes) -> str | None:
    return next((ext for ext, magic in SIGNATURES.items() if content.startswith(magic)), None)


@router.get("/claims/options")
def claim_options() -> dict:
    """What the web app may send: contracts, photo limits, languages."""
    return {"policies": policies(), "max_photos": MAX_PHOTOS,
            "max_photo_mb": max_photo_bytes() / (1024 * 1024), "languages": list(LANGUAGES)}


@router.post("/claims/upload", response_model=ClaimAnalysis)
def upload_claim(photos: Annotated[list[UploadFile], File()],
                 policy_id: Annotated[str, Form()],
                 text: Annotated[str, Form()] = "",
                 language: Annotated[str, Form()] = "fr") -> ClaimAnalysis:
    """Save the photos, then run the same pipeline as /claims/analyze."""
    valid = {p["policy_id"] for p in policies()}
    if policy_id not in valid:
        raise error(400, "unknown_policy", f"Unknown policy_id {policy_id!r}.",
                    valid=sorted(valid))
    if language not in LANGUAGES:
        raise error(400, "unknown_language", f"language must be one of {list(LANGUAGES)}.")
    if not 1 <= len(photos) <= MAX_PHOTOS:
        raise error(400, "too_many_photos" if photos else "no_photo",
                    f"Send between 1 and {MAX_PHOTOS} photos.", max_photos=MAX_PHOTOS)

    limit = max_photo_bytes()
    contents = []
    for photo in photos:
        content = photo.file.read(limit + 1)
        if len(content) > limit:
            raise error(413, "photo_too_large", f"{photo.filename}: more than "
                        f"{limit / (1024 * 1024):g} MB.", filename=photo.filename,
                        max_photo_mb=limit / (1024 * 1024))
        extension = photo_extension(content)
        if extension is None:
            raise error(415, "not_an_image", f"{photo.filename}: only JPEG or PNG photos.",
                        filename=photo.filename)
        contents.append((content, extension))

    claim_id = f"WEB-{uuid.uuid4().hex[:10].upper()}"
    folder = uploads_dir() / claim_id
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for number, (content, extension) in enumerate(contents, start=1):
        path = folder / f"photo_{number}.{extension}"
        path.write_bytes(content)
        paths.append(str(path.resolve()))
    return analyze_claim(ClaimInput(claim_id=claim_id, photo_paths=paths, text=text.strip(),
                                    policy_id=policy_id, language=language))
