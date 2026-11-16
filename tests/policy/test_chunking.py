"""Chunking tests: pure text functions, no PDF and no pypdf needed."""
from agents.policy import chunking


def test_guarantee_from_title():
    assert chunking.guarantee_of("Exclusions de la garantie dommage collision") == "collision"
    assert chunking.guarantee_of("R11 Bris de glaces - Objet de la garantie") == "bris_de_glace"
    assert chunking.guarantee_of("La prescription") == "general"


def test_guarantee_matches_whole_words_only():
    assert chunking.guarantee_of("Vol du véhicule") == "vol"
    assert chunking.guarantee_of("R16 Perte Totale-Vol - Exclusions") == "vol"
    assert chunking.guarantee_of("Franchise prêt du volant") == "franchise"   # not "vol"
    assert chunking.guarantee_of("Remplacement du volant") == "general"
    assert chunking.guarantee_of("Les franchises") == "franchise"


def test_axa_style_sections_and_long_text_split():
    lines = [(5, "Article 15 : Dommages collision"), (5, "Nous garantissons. " * 200),
             (6, "Article 16 : Exclusions de la garantie dommage collision"),
             (6, "Nous ne garantissons pas les dommages intentionnels.")]
    chunks = chunking.to_chunks("AXA", chunking.split_sections(lines, "articles"), 1500)
    assert chunks[0]["title"] == "Dommages collision"
    assert len(chunks) > 2                      # the long article was cut into parts
    assert chunks[-1]["is_exclusion"] is True
    assert all(len(c["text"]) <= 1600 for c in chunks)
