"""ClaimsPilot - claims page (Streamlit).

Sends a claim (photos + text) to the API `POST /claims` and shows the decision
with its reasons. Run, with the API already started:
    uvicorn api.main:app --port 8000          # terminal 1
    streamlit run ui/app.py                   # terminal 2

Env vars:
    CLAIMSPILOT_API_URL   default http://localhost:8000
    CLAIMSPILOT_UPLOADS   folder where uploaded photos are saved (default: system temp)

The API takes photo *paths* (ClaimInput.photo_paths), so uploaded photos are saved to
a folder the API can read: this works when the UI and the API run on the same machine
(or share a docker volume).
"""
import os
import tempfile
import uuid
from pathlib import Path

import httpx
import streamlit as st

API_URL = os.getenv("CLAIMSPILOT_API_URL", "http://localhost:8000").rstrip("/")
UPLOADS = Path(os.getenv("CLAIMSPILOT_UPLOADS",
                         Path(tempfile.gettempdir()) / "claimspilot_uploads"))
SAMPLES = Path("data/vision/car_dent_scratch_split/test/images")

BADGE = {
    "approve": ("Approved", "green"),
    "reject": ("Rejected", "red"),
    "human_review": ("Sent to a claims handler", "orange"),
}


def api_is_up() -> bool:
    try:
        return httpx.get(f"{API_URL}/health", timeout=3).status_code == 200
    except httpx.HTTPError:
        return False


def save_uploads(claim_id: str, files) -> list[str]:
    folder = UPLOADS / claim_id
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for f in files:
        path = folder / Path(f.name).name
        path.write_bytes(f.getvalue())
        paths.append(str(path.resolve()))
    return paths


st.set_page_config(page_title="ClaimsPilot", page_icon=":car:", layout="wide")
st.title("ClaimsPilot - new claim")

if api_is_up():
    st.caption(f"API: {API_URL} - online")
else:
    st.error(f"The API is not reachable at {API_URL}. Start it with "
             "`uvicorn api.main:app --port 8000`.")

with st.form("claim"):
    col_text, col_photos = st.columns(2)
    with col_text:
        text = st.text_area("What happened?", height=150,
                            placeholder="Le pare-chocs arrière a été enfoncé sur un parking.")
        policy_id = st.text_input("Policy number", value="POL-123")
        language = st.selectbox("Language", ["fr", "en", "ar"])
    with col_photos:
        uploads = st.file_uploader("Photos of the damage", type=["jpg", "jpeg", "png"],
                                   accept_multiple_files=True)
        samples = sorted(p.name for p in SAMPLES.glob("*.jpg")) if SAMPLES.exists() else []
        picked = st.multiselect("...or test photos from the dataset", samples)
    submitted = st.form_submit_button("Submit the claim", type="primary")

if submitted:
    claim_id = f"C-{uuid.uuid4().hex[:8]}"
    photo_paths = save_uploads(claim_id, uploads or [])
    photo_paths += [str((SAMPLES / name).resolve()) for name in picked]
    if not text.strip() or not photo_paths:
        st.warning("Please describe what happened and add at least one photo.")
        st.stop()

    claim = {"claim_id": claim_id, "photo_paths": photo_paths, "text": text,
             "policy_id": policy_id, "language": language}
    with st.spinner("The agents are analysing the claim..."):
        try:
            response = httpx.post(f"{API_URL}/claims", json=claim, timeout=120)
            response.raise_for_status()
        except httpx.HTTPError as err:
            st.error(f"The API returned an error: {err}")
            st.stop()
    decision = response.json()

    label, color = BADGE.get(decision["decision"], (decision["decision"], "gray"))
    st.subheader(f"Claim {decision['claim_id']}")
    st.markdown(f"### :{color}[{label}]")
    st.metric("Confidence", f"{decision['confidence']:.0%}")

    st.markdown("**Why**")
    for reason in decision["reasons"]:
        st.markdown(f"- {reason}")
    if decision.get("trace_id"):
        st.caption(f"Langfuse trace: {decision['trace_id']}")

    st.image(photo_paths, width=240, caption=[Path(p).name for p in photo_paths])