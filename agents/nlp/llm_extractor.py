import json
import os
from pathlib import Path
from urllib import error, request

import yaml

from claimspilot.schemas import PARTS

CONFIG_PATH = Path(__file__).with_name("config.yaml")


def load_config():
    with CONFIG_PATH.open(encoding="utf-8-sig") as file:
        return yaml.safe_load(file)["llm"]


def extract_with_llm(text, generator=None):
    """Return validated LLM extraction, or None on failure."""
    config = load_config()

    if not config.get("enabled", False):
        return None

    allowed_parts = set(PARTS)

    prompt = (
        "Extract vehicle parts described as damaged in this insurance claim. "
        "Support French and English. Do not infer damage from parts mentioned "
        "as undamaged. Return ONLY a JSON object with these keys: "
        "parts_damaged (array), parts_explicitly_not_damaged (array), "
        "reason (short string). "
        f"Allowed part names: {json.dumps(PARTS)}. "
        "Use only allowed part names. "
        "A part cannot appear in both arrays.\n\n"
        f"Claim text: {json.dumps(text, ensure_ascii=False)}"
    )

    try:
        if generator is not None:
            raw = generator(prompt)
        else:
            host = os.getenv(
                "OLLAMA_HOST", "http://localhost:11434"
            ).rstrip("/")

            payload = json.dumps({
                "model": config["model"],
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": config.get("temperature", 0),
                    "num_predict": config.get("max_tokens", 1024),
                },
            }).encode("utf-8")

            req = request.Request(
                f"{host}/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with request.urlopen(
                req,
                timeout=config.get("timeout_seconds", 150),
            ) as response:
                envelope = json.load(response)

            raw = envelope["response"]

        if isinstance(raw, str):
            result = json.loads(raw)
        else:
            result = raw

        if not isinstance(result, dict):
            return None

        if set(result) != {
            "parts_damaged",
            "parts_explicitly_not_damaged",
            "reason",
        }:
            return None

        damaged = result["parts_damaged"]
        undamaged = result["parts_explicitly_not_damaged"]
        reason = result["reason"]

        if (
            not isinstance(damaged, list)
            or not isinstance(undamaged, list)
            or not isinstance(reason, str)
        ):
            return None

        if any(type(part) is not str for part in damaged + undamaged):
            return None

        if not set(damaged + undamaged).issubset(allowed_parts):
            return None

        if set(damaged) & set(undamaged):
            return None

        return {
            "parts_damaged": sorted(set(damaged)),
            "parts_explicitly_not_damaged": sorted(set(undamaged)),
            "reason": reason,
        }

    except (OSError, TimeoutError, ValueError, TypeError, KeyError, error.URLError):
        # Invalid JSON, unavailable Ollama, timeout, or invalid response.
        # The caller must fall back to keyword extraction.
        return None
