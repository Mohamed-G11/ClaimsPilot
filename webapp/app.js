/* ClaimsPilot customer web app: plain JavaScript, no framework, no build step.
 *
 * Screens (hash routes): #/ (accueil), #/contrat, #/photos, #/description,
 * #/envoi, #/resultat/<claim_id>, #/declarations.
 * API (same origin): GET /claims/options, GET /ready, POST /claims/upload.
 * History: localStorage (every access in try/catch; the app works without it).
 * Code and comments in English; only the text shown to the user is French.
 */
"use strict";

const HISTORY_KEY = "claimspilot.history.v1";
const HISTORY_MAX = 30;
const READY_POLL_MS = 3000;
const READY_TIMEOUT_MS = 6 * 60 * 1000;
const UPLOAD_TIMEOUT_MS = 10 * 60 * 1000;

const DECISIONS = {
  approve: { label: "Acceptée", sub: "Votre sinistre est pris en charge.",
             icon: '<path d="M5 12.5l4.5 4.5L19 7.5"/>' },
  reject: { label: "Refusée", sub: "Votre contrat ne couvre pas ce sinistre.",
            icon: '<path d="M6 6l12 12M18 6L6 18"/>' },
  human_review: { label: "Examen par un conseiller",
                  sub: "Un conseiller va étudier votre dossier et vous recontacter.",
                  icon: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>' },
};

const PARTS = {
  front_bumper: "Pare-chocs avant", rear_bumper: "Pare-chocs arrière", door: "Portière",
  hood: "Capot", trunk: "Coffre", fender: "Aile", headlight: "Phare avant",
  taillight: "Feu arrière", windshield: "Pare-brise", side_mirror: "Rétroviseur",
  wheel: "Roue", other: "Autre partie",
};
const DAMAGE_TYPES = { dent: "enfoncement", scratch: "rayure", crack: "fissure",
                       glass_shatter: "bris de glace" };

// The API's decision reasons are in English (for claims handlers): only the ones a
// customer needs are shown, in French. Unknown reasons are not shown.
const REASONS = [
  ["not covered by the policy", "Les dommages déclarés ne sont pas couverts par votre contrat."],
  ["could not decide the coverage", "La prise en charge doit être vérifiée par un conseiller."],
  ["does not match the damage seen", "La description ne correspond pas aux dommages visibles sur les photos."],
  ["could not be compared with the photos", "La description et les photos n'ont pas pu être comparées automatiquement."],
  ["low text/photo consistency", "La description et les photos ne concordent pas suffisamment."],
  ["damage needs a human check", "Les dommages semblent importants : un conseiller doit les vérifier."],
  ["no damage detected", "Aucun dommage n'a été détecté sur les photos."],
  ["low vision confidence", "Les dommages sont difficiles à voir sur les photos."],
  ["stub result used", "Un service est momentanément indisponible : un conseiller prend le relais."],
  ["no automatic decision", "Un service est momentanément indisponible : un conseiller prend le relais."],
];

const ERRORS = {
  photo_too_large: (d) => `La photo « ${d.filename || ""} » est trop lourde (maximum ${fmtMb(d.max_photo_mb)}). Choisissez une autre photo.`,
  not_an_image: (d) => `Le fichier « ${d.filename || ""} » n'est pas une photo JPEG ou PNG.`,
  too_many_photos: () => "Vous pouvez envoyer au maximum 5 photos.",
  no_photo: () => "Ajoutez au moins une photo.",
  unknown_policy: () => "Ce contrat n'est pas reconnu. Revenez à l'étape « Contrat ».",
  unknown_language: () => "Cette langue n'est pas prise en charge.",
};

const state = {
  policies: [], maxPhotos: 5, maxPhotoMb: 10,
  insurer: null, formula: null, photos: [], text: "", language: "fr",
  sending: false, steps: null,
};

/* ---------- small helpers ---------------------------------------------- */

const $ = (selector) => document.querySelector(selector);

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child !== null && child !== undefined) node.append(child);   // strings = plain text
  }
  return node;
}

function fmtMb(mb) {
  return `${Number(mb || state.maxPhotoMb).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} Mo`;
}

function fmtDate(iso) {
  try {
    return new Date(iso).toLocaleString("fr-FR", { day: "numeric", month: "long",
      year: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch { return iso; }
}

function policyLabel(policyId) {
  const p = state.policies.find((x) => x.policy_id === policyId);
  return p ? `${p.insurer} · ${p.formula_name}` : policyId;
}

function show(error, message) {
  error.textContent = message || "";
  error.hidden = !message;
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/* ---------- history (localStorage, never required) ---------------------- */

function readHistory() {
  try {
    const raw = window.localStorage.getItem(HISTORY_KEY);
    const list = raw ? JSON.parse(raw) : [];
    return Array.isArray(list) ? list : [];
  } catch { return null; }                 // null = storage unavailable
}

function saveToHistory(entry) {
  try {
    const list = readHistory() || [];
    const next = [entry, ...list.filter((e) => e.claim_id !== entry.claim_id)].slice(0, HISTORY_MAX);
    window.localStorage.setItem(HISTORY_KEY, JSON.stringify(next));
    return true;
  } catch { return false; }
}

// The last result is also kept in memory, so it can be shown without storage.
let lastEntry = null;

function findEntry(claimId) {
  if (lastEntry && lastEntry.claim_id === claimId) return lastEntry;
  return (readHistory() || []).find((e) => e.claim_id === claimId) || null;
}

/* ---------- API ---------------------------------------------------------- */

async function loadOptions() {
  try {
    const response = await fetch("/claims/options");
    if (!response.ok) throw new Error(String(response.status));
    const body = await response.json();
    state.policies = body.policies;
    state.maxPhotos = body.max_photos;
    state.maxPhotoMb = body.max_photo_mb;
    return true;
  } catch { return false; }
}

async function waitUntilReady(onWaiting) {
  const start = Date.now();
  for (;;) {
    let response;
    try { response = await fetch("/ready", { cache: "no-store" }); }
    catch { throw new Error("network"); }
    if (response.ok || response.status === 404) return;      // 404: API without /ready
    if (Date.now() - start > READY_TIMEOUT_MS) throw new Error("not_ready");
    onWaiting();
    await sleep(READY_POLL_MS);
  }
}

async function upload() {
  const form = new FormData();
  state.photos.forEach((p) => form.append("photos", p.file, p.file.name));
  form.append("text", state.text);
  form.append("policy_id", `${state.insurer}-${state.formula}`);
  form.append("language", state.language);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), UPLOAD_TIMEOUT_MS);
  let response;
  try {
    response = await fetch("/claims/upload", { method: "POST", body: form,
                                               signal: controller.signal });
  } catch (err) {
    throw new Error(err.name === "AbortError" ? "timeout" : "network");
  } finally { clearTimeout(timer); }
  let body = null;
  try { body = await response.json(); } catch { /* not JSON */ }
  if (!response.ok) {
    const detail = body && body.detail && body.detail.code ? body.detail : null;
    const error = new Error(detail ? detail.code : `http_${response.status}`);
    error.detail = detail;
    throw error;
  }
  return body;
}

function errorMessage(err) {
  if (err.detail && ERRORS[err.detail.code]) return ERRORS[err.detail.code](err.detail);
  if (err.message === "network") return "Impossible de joindre le service. Vérifiez votre connexion internet et réessayez.";
  if (err.message === "timeout") return "Le service met trop de temps à répondre. Réessayez dans quelques minutes.";
  if (err.message === "not_ready") return "Le système n'est pas encore prêt. Réessayez dans quelques minutes.";
  return "Une erreur est survenue de notre côté. Votre déclaration n'a pas été envoyée : réessayez dans un instant.";
}

/* ---------- result: API response -> stored entry -> screen --------------- */

function toEntry(analysis) {
  const decision = analysis.decision;
  const reasons = [];
  for (const reason of decision.reasons) {
    const match = REASONS.find(([key]) => reason.includes(key));
    if (match && !reasons.includes(match[1])) reasons.push(match[1]);
  }
  // The policy answer starts with the contract verdict ("Décision : COUVERT…"), which
  // can differ from the final decision (e.g. covered but sent to an adviser): drop it.
  const explanation = (analysis.policy.answer || "")
    .replace(/^\s*\**\s*D[ée]cision\s*:\s*(NON\s+)?COUVERT\s*\**\.?\s*/i, "")
    .replace(/^(\[[A-Z]+-[\d-]+(?:,\s*[A-Z]+-[\d-]+)*\]\s*\.?\s*)+/, "")
    .trim();
  return {
    claim_id: decision.claim_id,
    date: new Date().toISOString(),
    policy_id: `${state.insurer}-${state.formula}`,
    decision: decision.decision,
    confidence: decision.confidence,
    explanation,
    answer: analysis.policy.answer || "",
    reasons,
    clauses: (analysis.policy.clauses || []).map((c) => ({ id: c.clause_id, text: c.text })),
    damages: (analysis.vision.damages || []).map((d) => ({ part: d.part, type: d.damage_type,
                                                           confidence: d.confidence })),
    photo_count: state.photos.length,
  };
}

function renderResult(entry) {
  const box = $("#result");
  box.replaceChildren();
  const look = DECISIONS[entry.decision] || DECISIONS.human_review;
  const badge = el("div", { class: `badge ${entry.decision}`, role: "status" });
  badge.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">${look.icon}</svg>`;  // static icon
  badge.append(el("div", {}, look.label, el("small", {}, look.sub)));
  box.append(el("p", { class: "meta" }, `Déclaration ${entry.claim_id} · ${fmtDate(entry.date)}`),
             badge);

  if (entry.reasons.length && entry.decision !== "approve") {
    box.append(el("div", { class: "card" },
      el("h2", {}, entry.decision === "reject" ? "Pourquoi ?" : "Pourquoi un conseiller ?"),
      el("ul", {}, entry.reasons.map((r) => el("li", {}, r)))));
  }
  if (entry.explanation) {
    box.append(el("div", { class: "card" }, el("h2", {}, "Ce que dit votre contrat"),
                  el("p", {}, entry.explanation)));
  }
  if (entry.clauses.length) {
    // Clauses cited in the explanation first; the other evidence the agent checked
    // (often exclusion clauses) stays folded, so it does not look like a reason.
    const cited = entry.clauses.filter((c) => (entry.answer || "").includes(c.id));
    const shown = cited.length ? cited : entry.clauses;
    const others = entry.clauses.filter((c) => !shown.includes(c));
    const clause = (c) => el("details", { class: "clause" }, el("summary", {}, c.id),
                             el("p", {}, c.text));
    box.append(el("div", { class: "card" }, el("h2", {}, "Clauses citées"), shown.map(clause),
      others.length ? el("details", { class: "more" },
        el("summary", {}, `Autres clauses vérifiées (${others.length})`), others.map(clause))
        : null));
  }
  box.append(el("div", { class: "card" }, el("h2", {}, "Dommages détectés sur les photos"),
    entry.damages.length
      ? el("ul", { class: "damages" }, entry.damages.map((d) => el("li", { class: "damage" },
          el("span", {}, `${PARTS[d.part] || d.part} – ${DAMAGE_TYPES[d.type] || d.type}`),
          el("span", {}, `${Math.round(d.confidence * 100)} %`))))
      : el("p", { class: "meta" }, "Aucun dommage détecté automatiquement.")));
  box.append(el("p", { class: "meta" }, `Contrat : ${policyLabel(entry.policy_id)} · `
                + `${entry.photo_count} photo${entry.photo_count > 1 ? "s" : ""}`));
}

/* ---------- screens ------------------------------------------------------ */

const STEP_SCREENS = { contrat: 1, photos: 2, description: 3 };

function goto(hash) { window.location.hash = hash; }

function showScreen(name) {
  document.querySelectorAll(".screen").forEach((s) => { s.hidden = s.dataset.screen !== name; });
  $("#back").hidden = name === "accueil" || name === "envoi";
  $("#step-count").textContent = STEP_SCREENS[name] ? `Étape ${STEP_SCREENS[name]} sur 3` : "";
  window.scrollTo(0, 0);
}

function renderContract() {
  const insurers = [...new Set(state.policies.map((p) => p.insurer))];
  const formulas = [...new Map(state.policies.map((p) => [p.formula, p.formula_name]))];
  const describe = { TR: "Couvre aussi les dommages à votre véhicule.",
                     TIERS: "Couvre les dommages causés aux autres." };
  $("#insurers").replaceChildren(...insurers.map((name) => el("button", {
    class: "choice", type: "button", "aria-pressed": String(state.insurer === name),
    onclick: () => { state.insurer = name; renderContract(); },
  }, el("strong", {}, name))));
  $("#formulas").replaceChildren(...formulas.map(([code, label]) => el("button", {
    class: "choice", type: "button", "aria-pressed": String(state.formula === code),
    onclick: () => { state.formula = code; renderContract(); },
  }, el("strong", {}, label), describe[code] ? el("small", {}, describe[code]) : null)));
  $("#contract-next").disabled = !(state.insurer && state.formula);
}

function addPhotos(fileList) {
  const errorBox = $("#photo-error");
  show(errorBox, "");
  for (const file of fileList) {
    if (state.photos.length >= state.maxPhotos) {
      show(errorBox, `Vous pouvez ajouter au maximum ${state.maxPhotos} photos.`);
      break;
    }
    if (!["image/jpeg", "image/png"].includes(file.type)) {
      show(errorBox, `« ${file.name} » n'est pas une photo JPEG ou PNG.`);
      continue;
    }
    if (file.size > state.maxPhotoMb * 1024 * 1024) {
      show(errorBox, `La photo « ${file.name} » est trop lourde (maximum ${fmtMb(state.maxPhotoMb)}).`);
      continue;
    }
    state.photos.push({ file, url: URL.createObjectURL(file) });
  }
  renderPhotos();
}

function renderPhotos() {
  $("#photo-hint").textContent = `Ajoutez de 1 à ${state.maxPhotos} photos nettes des dégâts `
    + `(${state.photos.length}/${state.maxPhotos}).`;
  $("#previews").replaceChildren(...state.photos.map((photo, index) => el("li", {},
    el("img", { src: photo.url, alt: `Photo ${index + 1}` }),
    el("button", { class: "remove", type: "button", "aria-label": `Retirer la photo ${index + 1}`,
      onclick: () => { URL.revokeObjectURL(photo.url); state.photos.splice(index, 1);
                       show($("#photo-error"), ""); renderPhotos(); } }, "×"))));
  $("#photos-next").disabled = state.photos.length === 0;
  const full = state.photos.length >= state.maxPhotos;
  $("#camera-input").disabled = full;
  $("#gallery-input").disabled = full;
}

function renderDescription() {
  $("#text").value = state.text;
  $("#language").value = state.language;
  $("#send").disabled = !state.text.trim();
  $("#summary").replaceChildren(
    el("span", {}, `Contrat : ${policyLabel(`${state.insurer}-${state.formula}`)}`),
    el("span", {}, `${state.photos.length} photo${state.photos.length > 1 ? "s" : ""}`));
}

function setStep(name, status) {
  const item = document.querySelector(`#steps li[data-step="${name}"]`);
  if (item) item.className = status;
}

async function send() {
  if (state.sending) return;
  state.sending = true;
  goto("#/envoi");
  show($("#send-error"), "");
  $("#send-error").hidden = true;
  $("#steps").hidden = false;
  ["photos", "description", "contrat", "decision"].forEach((s) => setStep(s, ""));
  $("#sending-title").textContent = "Envoi de votre déclaration…";
  $("#sending-hint").textContent = "Gardez cette page ouverte.";
  const timers = [];
  try {
    await waitUntilReady(() => {
      $("#sending-title").textContent = "Préparation du système…";
      $("#sending-hint").textContent = "Le service démarre, cela peut prendre une ou deux minutes. Votre déclaration partira automatiquement.";
    });
    $("#sending-title").textContent = "Analyse en cours…";
    $("#sending-hint").textContent = "Cela prend généralement moins d'une minute. Gardez cette page ouverte.";
    // The API answers once at the end: the steps below show progress, not live server events.
    setStep("photos", "active");
    timers.push(setTimeout(() => { setStep("photos", "done"); setStep("description", "active"); }, 2500));
    timers.push(setTimeout(() => { setStep("description", "done"); setStep("contrat", "active"); }, 5000));
    timers.push(setTimeout(() => { setStep("contrat", "done"); setStep("decision", "active"); }, 9000));
    const analysis = await upload();
    timers.forEach(clearTimeout);
    ["photos", "description", "contrat", "decision"].forEach((s) => setStep(s, "done"));
    lastEntry = toEntry(analysis);
    saveToHistory(lastEntry);
    resetDraft();
    goto(`#/resultat/${encodeURIComponent(lastEntry.claim_id)}`);
  } catch (err) {
    timers.forEach(clearTimeout);
    $("#sending-title").textContent = "La déclaration n'a pas pu être envoyée";
    $("#sending-hint").textContent = "";
    $("#steps").hidden = true;
    $("#send-error-text").textContent = errorMessage(err);
    $("#send-error").hidden = false;
  } finally {
    state.sending = false;
  }
}

function resetDraft() {
  state.photos.forEach((p) => URL.revokeObjectURL(p.url));
  Object.assign(state, { insurer: null, formula: null, photos: [], text: "", language: "fr" });
}

function renderHistory() {
  const list = readHistory();
  const box = $("#history");
  if (list === null) {
    $("#history-note").textContent = "L'historique n'est pas disponible sur cet appareil "
      + "(stockage du navigateur désactivé).";
    box.replaceChildren();
    return;
  }
  $("#history-note").textContent = "Enregistrées uniquement sur cet appareil.";
  if (!list.length) {
    box.replaceChildren(el("li", { class: "empty" }, "Aucune déclaration pour le moment."));
    return;
  }
  box.replaceChildren(...list.map((e) => el("li", {}, el("a", {
    href: `#/resultat/${encodeURIComponent(e.claim_id)}`,
  }, el("span", { class: "date" }, fmtDate(e.date)),
     el("span", { class: `pill ${e.decision}` }, (DECISIONS[e.decision] || DECISIONS.human_review).label),
     el("span", { class: "contract" }, policyLabel(e.policy_id))))));
}

function renderHome() {
  const list = readHistory();
  $("#history-link").textContent = list && list.length
    ? `Mes déclarations (${list.length})` : "Mes déclarations";
}

/* ---------- router ------------------------------------------------------- */

function route() {
  const [, name = "", param = ""] = (window.location.hash || "#/").split("/");
  switch (name) {
    case "contrat":
      renderContract(); showScreen("contrat"); break;
    case "photos":
      if (!(state.insurer && state.formula)) return goto("#/contrat");
      renderPhotos(); showScreen("photos"); break;
    case "description":
      if (!state.photos.length) return goto(state.insurer ? "#/photos" : "#/contrat");
      renderDescription(); showScreen("description"); break;
    case "envoi":
      if (!state.sending && $("#send-error").hidden) return goto("#/");
      showScreen("envoi"); break;
    case "resultat": {
      const entry = findEntry(decodeURIComponent(param));
      if (!entry) return goto("#/declarations");
      renderResult(entry); showScreen("resultat"); break;
    }
    case "declarations":
      renderHistory(); showScreen("declarations"); break;
    default:
      renderHome(); showScreen("accueil");
  }
}

/* ---------- start -------------------------------------------------------- */

async function start() {
  $("#back").addEventListener("click", () => window.history.back());
  $("#contract-next").addEventListener("click", () => goto("#/photos"));
  $("#camera-input").addEventListener("change", (e) => { addPhotos(e.target.files); e.target.value = ""; });
  $("#gallery-input").addEventListener("change", (e) => { addPhotos(e.target.files); e.target.value = ""; });
  $("#photos-next").addEventListener("click", () => goto("#/description"));
  $("#text").addEventListener("input", (e) => { state.text = e.target.value;
                                               $("#send").disabled = !state.text.trim(); });
  $("#language").addEventListener("change", (e) => { state.language = e.target.value; });
  $("#send").addEventListener("click", send);
  $("#retry").addEventListener("click", send);
  window.addEventListener("hashchange", route);

  if (!(await loadOptions())) {
    show($("#contract-error"), "Impossible de charger les contrats. Vérifiez votre connexion et rechargez la page.");
  }
  route();
}

start();
