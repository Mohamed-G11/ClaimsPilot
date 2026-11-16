"""Turn the insurers' PDF general conditions into clauses (JSONL).

Usage:  python -m agents.policy.chunking
Input:  data/policy/raw/<INSURER>.pdf      (DVC)
Output: data/policy/processed/clauses.jsonl (DVC) - one clause per line
"""
import json
import re
import unicodedata
from pathlib import Path

from agents.policy.settings import CONFIG, data_path

# Lines repeated on every page (headers, footers, page numbers) - removed.
NOISE = re.compile(
    r"^\s*(\d{1,3}|Assurance Automobile.*|Visa N.*|Conditions G.n.rales.*Assur.Auto.*)\s*$"
)

# Section titles, per insurer style.
HEADINGS = {
    "articles": [re.compile(r"^\s*Article\s+(\d+)\s*:\s*(.+)$")],
    "risks": [
        re.compile(r"^\s*(\d+)\.\s*Risque\s+(R\d+)\s*:\s*(.+)$"),          # 5. Risque R7 : Dommages collision
        re.compile(r"^\s*(\d+\.\d+)\.\s+([A-ZÉÈ].{2,70})$"),               # 5.1. Objet de la garantie
        re.compile(r"^\s*(TITRE\s+[IVX]+)\b\s*:?\s*(.*)$"),                # TITRE III : ...
        re.compile(r"^\s*([IVX]+)\.?\s+([A-ZÉ][A-Za-zÀ-ÿ' ()0-9]{3,60})$"),  # III Protection du Véhicule
        re.compile(r"^\s*(\d{1,2})\.\s+([A-ZÉ][^.;:]{3,60})$"),            # 7. Fausses déclarations
    ],
}

# Which guarantee a clause belongs to, from words in its title (order matters).
# The words are matched as WHOLE words: "vol" matches "Vol du véhicule" but not
# "volant". A final "s" is accepted ("bris de glaces", "franchises").
GUARANTEES = [
    ("exclusions generales", "exclusions_generales"),   # SANLAM "TITRE III"
    ("exclusions communes", "exclusions_generales"),    # AXA article 23
    ("bris de glace", "bris_de_glace"),
    ("collision", "collision"),
    ("tous accidents", "tous_risques"),
    ("tous risques", "tous_risques"),
    ("dommages au vehicule", "tous_risques"),
    ("incendie", "incendie"),
    ("vol", "vol"),
    ("vandalisme", "vandalisme"),
    ("inondation", "catastrophe_naturelle"),
    ("evenements climatiques", "catastrophe_naturelle"),
    ("responsabilite civile", "rc"),
    ("defense", "defense_recours"),
    ("recours", "defense_recours"),
    ("franchise", "franchise"),
]


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def has_words(words: str, plain_text: str) -> bool:
    """True if `words` appears in `plain_text` as whole words (optional plural s)."""
    return re.search(rf"(?<!\w){re.escape(words)}s?(?!\w)", plain_text) is not None


def guarantee_of(title: str) -> str:
    plain = _plain(title)
    for words, guarantee in GUARANTEES:
        if has_words(words, plain):
            return guarantee
    return "general"


def read_lines(pdf_path: Path, start_page: int, end_page: int) -> list[tuple[int, str]]:
    """(page number, line) for every useful line between start_page and end_page."""
    from pypdf import PdfReader  # lazy import: only needed to read the PDFs

    lines = []
    for number, page in enumerate(PdfReader(pdf_path).pages, start=1):
        if number < start_page or number > end_page:
            continue
        for line in (page.extract_text() or "").splitlines():
            if line.strip() and not NOISE.match(line):
                lines.append((number, line.rstrip()))
    return lines


def split_sections(lines, style: str) -> list[dict]:
    """Cut the text at each section title."""
    sections, current, parent = [], None, ""
    for page, line in lines:
        found = next(((i, m) for i, p in enumerate(HEADINGS[style]) if (m := p.match(line))), None)
        if found:
            kind, match = found
            groups = [g for g in match.groups() if g]
            title = " ".join(groups[1:]).strip() or groups[0]
            if style == "risks" and kind == 0:
                parent = f"{groups[1]} {groups[2]}"           # e.g. "R7 Dommages collision"
                title = parent
            elif style == "risks" and kind == 1 and parent:
                title = f"{parent} - {title}"                  # e.g. "R7 Dommages collision - Exclusions"
            elif style == "risks":
                parent = ""
            current = {"title": title, "number": groups[0], "page": page, "lines": [],
                       "untitled": len(groups) == 1}
            sections.append(current)
        elif current and current["untitled"] and not current["lines"] \
                and len(line) < 80 and line == line.upper():
            # "TITRE III" alone on its line: its title is the next line, in capitals.
            current["title"] = f"{current['title']} {line.strip()}"
            current["untitled"] = False
        elif current:
            current["lines"].append(line)
    return sections


def to_chunks(insurer: str, sections: list[dict], max_chars: int) -> list[dict]:
    """One clause per section; long sections are cut into parts of ~max_chars."""
    chunks = []
    for index, section in enumerate(sections, start=1):
        text = re.sub(r"\s+", " ", " ".join(section["lines"])).strip()
        if len(text) < 40:          # empty title-only section
            continue
        parts, part = [], ""
        pieces = re.split(r"(?<=[;.])\s+", text)
        # very long sentences (tables, lists without punctuation): hard cut
        pieces = [p[i:i + max_chars] for p in pieces for i in range(0, len(p), max_chars)]
        for sentence in pieces:
            if part and len(part) + len(sentence) > max_chars:
                parts.append(part)
                part = ""
            part = f"{part} {sentence}".strip()
        parts.append(part)
        for n, part in enumerate(parts, start=1):
            suffix = f"-{n}" if len(parts) > 1 else ""
            chunks.append({
                "insurer": insurer,
                "clause_id": f"{insurer}-{index:03d}{suffix}",
                "title": section["title"],
                "guarantee": guarantee_of(section["title"]),
                "is_exclusion": "exclusion" in _plain(section["title"]),
                "page": section["page"],
                "text": part,
            })
    return chunks


def main() -> None:
    raw_dir = data_path("raw_dir")
    out = data_path("clauses_file")
    out.parent.mkdir(parents=True, exist_ok=True)
    all_chunks = []
    for insurer, cfg in CONFIG["insurers"].items():
        lines = read_lines(raw_dir / cfg["file"], cfg["start_page"], cfg.get("end_page", 999))
        chunks = to_chunks(insurer, split_sections(lines, cfg["style"]), CONFIG["max_chunk_chars"])
        print(f"{insurer}: {len(chunks)} clauses")
        all_chunks += chunks
    with out.open("w", encoding="utf-8") as f:
        for chunk in all_chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")
    print(f"Saved {len(all_chunks)} clauses to {out}")


if __name__ == "__main__":
    main()
