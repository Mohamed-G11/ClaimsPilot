"""Phone-size screenshots of every screen of the customer web app (and a real claim).

Usage (the Docker stack must be running and ready):
    pip install playwright==1.65.2 && python -m playwright install chromium   # once
    python -m mlops.webapp_screenshots [--url http://localhost:8000/app/] [--photo <jpg>]

Saves PNG files in docs/screenshots/web-app/ (390 x 844, mobile, touch). The claim is
REAL: it goes through the API and the agents. Two states are simulated in the
browser only (route interception, nothing changes on the server): "Préparation du
système…" (/ready answers 503) and the photo-type error (a PDF is added).
"""
import argparse
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs/screenshots/web-app"
PHOTO = (REPO / "data/vision/car_dent_scratch_split/test/images/"
         "back_light-1---92-_jpg.rf.2883d651ea3c3807b5c2f61b3695946b.jpg")
TEXT = ("En sortant d'une place de parking, j'ai heurté un poteau en béton. "
        "Le pare-chocs avant est enfoncé.")
PHONE = {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True,
         "device_scale_factor": 1, "locale": "fr-FR"}


def shot(page, name: str, full_page: bool = False) -> None:
    page.wait_for_timeout(300)                      # let CSS transitions end
    path = OUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=full_page)
    print("saved", path.relative_to(REPO))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://localhost:8000/app/")
    parser.add_argument("--photo", type=Path, default=PHOTO)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(**PHONE).new_page()

        page.goto(args.url)
        page.wait_for_selector("text=Nouvelle déclaration")
        shot(page, "01-accueil")

        page.click("text=Nouvelle déclaration")
        page.click("#insurers >> text=AXA")
        page.click("#formulas >> text=Tous risques")
        shot(page, "02-contrat")

        page.click("#contract-next")
        page.set_input_files("#gallery-input", {"name": "document.pdf",
                                                "mimeType": "application/pdf",
                                                "buffer": b"%PDF-1.7"})
        shot(page, "03b-photos-erreur")
        page.set_input_files("#gallery-input", str(args.photo))
        page.wait_for_selector("#previews img")
        shot(page, "03-photos")

        page.click("#photos-next")
        page.fill("#text", TEXT)
        shot(page, "04-description")

        page.click("#send")
        page.wait_for_selector("#steps li.active", timeout=60_000)
        shot(page, "05-envoi")
        start = time.time()
        page.wait_for_url("**/app/#/resultat/*", timeout=600_000)
        page.wait_for_selector(".badge")
        print(f"real claim answered in {time.time() - start:.1f} s:",
              page.inner_text(".badge").replace("\n", " | "))
        shot(page, "06-resultat", full_page=True)

        page.goto(args.url + "#/declarations")
        page.wait_for_selector("#history a")
        shot(page, "07-declarations")
        page.click("#history a >> nth=0")
        page.wait_for_selector(".badge")
        shot(page, "08-resultat-depuis-historique")

        # Simulated in this browser only: the API is still warming up.
        waiting = browser.new_context(**PHONE).new_page()
        waiting.route("**/ready", lambda route: route.fulfill(
            status=503, content_type="application/json",
            body='{"ready": false, "warmup": {"llm": "running"}, "failed": []}'))
        waiting.goto(args.url + "#/contrat")
        waiting.click("#insurers >> text=SANLAM")
        waiting.click("#formulas >> text=Au tiers")
        waiting.click("#contract-next")
        waiting.set_input_files("#gallery-input", str(args.photo))
        waiting.click("#photos-next")
        waiting.fill("#text", TEXT)
        waiting.click("#send")
        waiting.wait_for_selector("text=Préparation du système…")
        shot(waiting, "05b-envoi-preparation")
        browser.close()


if __name__ == "__main__":
    main()
