"""ClaimsPilot – claims handler page.

Run the API first (uvicorn api.main:app --reload), then:
    streamlit run ui/app.py
"""
import uuid
from pathlib import Path

import requests
import streamlit as st
from PIL import Image, ImageDraw

UPLOAD_DIR = Path("data/uploads")
INSURERS = {"AXA": "AXA", "Sanlam": "SANLAM"}
FORMULAS = {"Tous risques": "TR", "Tiers": "TIERS"}
EXAMPLES = {
    "— écrire ma propre déclaration —": "",
    "Choc arrière au parking": "En reculant sur le parking, une voiture a heurté l'arrière "
    "de mon véhicule. Le pare-chocs arrière est enfoncé.",
    "Pare-brise fissuré": "Un gravillon a frappé mon pare-brise sur l'autoroute, il est "
    "maintenant fissuré.",
    "Phare cassé": "J'ai percuté un poteau en sortant du garage, le phare avant est cassé.",
}
DECISION_STYLE = {
    "approve": ("✅ Approuvé automatiquement", "success"),
    "reject": ("❌ Refusé", "error"),
    "human_review": ("🧑‍💼 Envoyé à un gestionnaire", "warning"),
}

st.set_page_config(page_title="ClaimsPilot", page_icon="🚗", layout="wide")

with st.sidebar:
    st.header("⚙️ Configuration")
    api_url = st.text_input("Adresse de l'API", "http://127.0.0.1:8000")
    try:
        ok = requests.get(f"{api_url}/health", timeout=3).json().get("status") == "ok"
    except requests.RequestException:
        ok = False
    st.write("API :", "🟢 en ligne" if ok else "🔴 hors ligne")

st.title("🚗 ClaimsPilot")
st.caption("Assistant multi-agents pour les sinistres automobiles : "
           "vision (photos) · NLP (déclaration) · RAG (contrat) · décision")

with st.form("claim"):
    left, right = st.columns(2)
    with left:
        insurer = st.selectbox("Assureur", list(INSURERS))
        formula = st.selectbox("Formule souscrite", list(FORMULAS))
        example = st.selectbox("Exemple", list(EXAMPLES))
    with right:
        photos = st.file_uploader("Photos du véhicule", type=["jpg", "jpeg", "png"],
                                  accept_multiple_files=True)
    text = st.text_area("Description du sinistre", EXAMPLES[example], height=110)
    submitted = st.form_submit_button("Analyser le sinistre", type="primary")

if submitted:
    claim_id = f"C-{uuid.uuid4().hex[:6].upper()}"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    paths = []
    for photo in photos or []:
        path = UPLOAD_DIR / f"{claim_id}_{photo.name}"
        path.write_bytes(photo.getbuffer())
        paths.append(str(path.resolve()))
    claim = {"claim_id": claim_id, "photo_paths": paths, "text": text,
             "policy_id": f"{INSURERS[insurer]}-{FORMULAS[formula]}"}

    with st.spinner("Les agents analysent le sinistre…"):
        try:
            response = requests.post(f"{api_url}/claims/analyze", json=claim, timeout=180)
            response.raise_for_status()
            result = response.json()
        except requests.RequestException as error:
            st.error(f"Appel à l'API impossible : {error}")
            st.stop()

    decision, agents = result["decision"], result["agents"]
    label, kind = DECISION_STYLE[decision["decision"]]
    getattr(st, kind)(f"### {label}\nDossier **{claim_id}** · contrat **{claim['policy_id']}**"
                      f" · confiance {decision['confidence']:.0%}")
    for reason in decision["reasons"]:
        st.write("•", reason)

    def badge(name):
        status = agents.get(name, "?")
        return "🟢 agent réel" if status == "real" else f"🟡 {status}"

    col_vision, col_nlp, col_policy = st.columns(3)

    with col_vision:
        vision = result["vision"]
        st.subheader("👁️ Vision")
        st.caption(badge("vision"))
        st.metric("Gravité", vision["severity"])
        for path in paths:
            image = Image.open(path).convert("RGB")
            draw = ImageDraw.Draw(image)
            for d in vision["damages"]:
                draw.rectangle(d["bbox"], outline="red", width=4)
                draw.text((d["bbox"][0] + 4, d["bbox"][1] + 4),
                          f"{d['part']} / {d['damage_type']}", fill="red")
            st.image(image, width="stretch")
        if vision["damages"]:
            st.table([{"pièce": d["part"], "dommage": d["damage_type"],
                       "confiance": f"{d['confidence']:.0%}"} for d in vision["damages"]])
        else:
            st.info("Aucun dommage détecté.")

    with col_nlp:
        nlp = result["nlp"]
        st.subheader("📝 Déclaration")
        st.caption(badge("nlp"))
        st.metric("Cohérence texte / photos", nlp["consistency"], f"score {nlp['score']:.2f}")
        st.write("Pièces citées dans le texte :",
                 ", ".join(nlp["described_parts"]) or "aucune")

    with col_policy:
        policy = result["policy"]
        st.subheader("📄 Contrat (RAG)")
        st.caption(badge("policy"))
        covered = {True: "Couvert", False: "Non couvert", None: "Indéterminé"}
        st.metric("Garantie", covered[policy["covered"]])
        st.write(policy["answer"])
        for clause in policy["clauses"]:
            with st.expander(f"{clause['clause_id']} · pertinence {clause['relevance']:.2f}"):
                st.write(clause["text"])

    with st.expander("Réponse brute de l'API (JSON)"):
        st.json(result)
