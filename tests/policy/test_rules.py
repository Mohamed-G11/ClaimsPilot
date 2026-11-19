"""Rule tests: cause, exclusions and photo compatibility (pure Python, no model)."""
import pytest

from agents.policy import rules
from claimspilot.schemas import Damage


def damages(*pairs):
    return [Damage(part=p, damage_type=t, bbox=[0, 0, 1, 1], confidence=0.8) for p, t in pairs]


@pytest.mark.parametrize(("text", "cause"), [
    ("Collision avec une autre voiture au rond-point.", "collision"),
    ("J'ai eu un accident hier soir.", "collision"),
    ("Un choc à l'arrière sur le parking.", "collision"),
    ("On a volé ma voiture cette nuit.", "vol"),
    ("Ma voiture a été volée devant chez moi.", "vol"),
    ("My car was stolen last night.", "vol"),
    ("Theft of the vehicle in the street.", "vol"),
    ("Un incendie s'est déclaré dans le moteur.", "incendie"),
    ("Le véhicule a pris feu sur l'autoroute.", "incendie"),
    ("The engine caught fire.", "incendie"),
    ("Un gravillon a fissuré mon pare-brise.", "bris_de_glace"),
    ("Bris de glace sur la vitre avant.", "bris_de_glace"),
    ("A stone cracked my windshield.", "bris_de_glace"),
    ("Acte de vandalisme : la carrosserie a été rayée.", "vandalisme"),
    ("My car was vandalized in the car park.", "vandalisme"),
    ("Voiture endommagée par une inondation.", "catastrophe_naturelle"),
    ("Dégâts après une catastrophe naturelle.", "catastrophe_naturelle"),
    ("The car was damaged in a flood.", "catastrophe_naturelle"),
])
def test_cause_from_text(text, cause):
    assert rules.detect_cause(text) == cause


@pytest.mark.parametrize("text", [
    "Le pare-chocs avant est enfoncé.",
    "La portière gauche est rayée.",
    "Je tenais le volant quand j'ai vu la rayure.",       # "volant" is not "vol"
    "Le feu arrière gauche est cassé.",                    # a light, not a fire
    "J'étais arrêté au feu rouge.",
    "Mon pare-choc est abîmé.",                            # "pare-choc" is not "choc"
    "",
])
def test_no_cause_in_text(text):
    assert rules.detect_cause(text) is None


def test_first_cause_of_the_config_wins_when_several_are_found():
    text = "Collision avec un camion, le pare-brise est fissuré."
    assert rules.detect_causes(text) == ["collision", "bris_de_glace"]
    assert rules.detect_cause(text) == "collision"


@pytest.mark.parametrize(("text", "exclusion"), [
    ("J'avais bu de l'alcool avant de conduire.", "alcool"),
    ("Le conducteur était en état d'ébriété.", "alcool"),
    ("I was drunk when I hit the wall.", "alcool"),
    ("Mon fils conduisait sans permis.", "sans_permis"),
    ("He was driving without a license.", "sans_permis"),
    ("L'accident a eu lieu pendant un rallye.", "course"),
    ("We were racing on the highway.", "course"),
    ("J'ai volontairement percuté le mur.", "intentionnel"),
    ("I damaged the car on purpose.", "intentionnel"),
])
def test_exclusions_from_text(text, exclusion):
    assert rules.detect_exclusions(text) == [exclusion]


def test_no_exclusion_in_an_ordinary_claim():
    assert rules.detect_exclusions("Collision sur un parking, je faisais mes courses.") == []


@pytest.mark.parametrize(("cause", "pairs", "expected"), [
    ("collision", [("front_bumper", "dent")], True),
    ("collision", [("taillight", "crack")], True),
    ("collision", [("windshield", "crack")], False),      # glass only: not body nor light
    ("collision", [], False),
    ("bris_de_glace", [("windshield", "crack")], True),
    ("bris_de_glace", [("headlight", "crack")], True),
    ("bris_de_glace", [("door", "glass_shatter")], True),
    ("bris_de_glace", [("rear_bumper", "dent")], False),
    ("vandalisme", [("door", "scratch")], True),
    ("vandalisme", [("hood", "dent")], True),
    ("vandalisme", [("side_mirror", "broken")], True),
    ("vandalisme", [("windshield", "crack")], False),
    ("vol", [], True),
    ("incendie", [], True),
    ("incendie", [("hood", "dent")], True),
])
def test_photo_compatibility(cause, pairs, expected):
    assert rules.is_compatible(cause, damages(*pairs)) is expected


def test_guarantees_from_damages():
    assert rules.guarantees_from_damages(damages(("windshield", "crack")))[0] == "bris_de_glace"
    assert rules.guarantees_from_damages(damages(("door", "dent"))) == ["collision",
                                                                         "tous_risques"]
    assert rules.guarantees_from_damages([]) == []


def test_every_cause_has_a_compatibility_rule():
    from agents.policy.settings import CONFIG

    assert set(CONFIG["causes"]) == set(CONFIG["compatibility"])
