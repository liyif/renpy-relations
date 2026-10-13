import json
import hashlib
from pathlib import Path
import random
import re

import pytest

from compile_rules import compile_rules
from examples.tidelight.game.night import Night
from renpy_relations import LogicDB


ROOT = Path(__file__).resolve().parents[1] / "examples/tidelight"
CONTENT = ROOT / "game/content.json"


@pytest.fixture(scope="module", params=["sqlite", "duckdb"])
def bundle(request, tmp_path_factory):
    if request.param == "duckdb":
        pytest.importorskip("duckdb")
    output = tmp_path_factory.mktemp("tidelight") / "rules.json"
    compile_rules(ROOT / "world.l", ROOT / "schema.json", output, backend=request.param)
    return output


@pytest.fixture(params=["cached", "live", "materialized"])
def night(bundle, request):
    db = LogicDB(bundle, mode=request.param)
    story = Night(db, CONTENT)
    story.seed()
    yield story
    db.close()


def drain(story):
    trace = []
    while story.forced() and story.forced() != "last_broadcast":
        scene = story.forced()
        story.resolve(scene, "apologize" if scene == "rumor" else "default")
        trace.append(scene)
    return trace


def play(story, scene, action="default"):
    drain(story)
    assert scene in {row["scene"] for row in story.options()}, (scene, story.time(), story.options())
    story.resolve(scene, action)
    drain(story)


def prepare_broadcast(story):
    # This order obtains the circuit diagram from Yao, and meets Cheng deeply
    # without first playing her cut-tape encounter.
    plan = [("yao_ticket", "support"), ("yao_fuse", "borrow"), ("mi_names", "ask"),
            ("master_copy", "default"), ("catalog", "default"),
            ("mi_departure", "support"), ("cheng_letter", "ask"), ("repair", "default")]
    for scene, action in plan:
        play(story, scene, action)
    assert story.logic.has("BroadcastReady")
    assert not story.logic.has("Seen", scene="cheng_pause")


def reach_midnight(story):
    for _ in range(20):
        drain(story)
        if story.forced() == "last_broadcast":
            return
        story.wait()
    pytest.fail("The finite night did not reach its final decision")


@pytest.mark.parametrize("ending", ["cheng", "yao", "mi", "harbor", "quiet"])
def test_all_five_endings_are_reachable_through_visible_opportunities(night, ending):
    if ending != "quiet":
        prepare_broadcast(night)
        if ending == "cheng":
            play(night, "cheng_pause", "listen")
            play(night, "cheng_future", "promise")
        elif ending in ("yao", "mi"):
            play(night, ending + "_future", "promise")
    reach_midnight(night)
    assert night.tick() == 12
    if ending == "quiet":
        assert not night.can("last_broadcast", "broadcast")
        with pytest.raises(ValueError, match="unavailable"):
            night.resolve("last_broadcast", "broadcast")
        night.resolve("last_broadcast", "silence")
    else:
        night.resolve("last_broadcast", "keep" if ending == "mi" else "broadcast")
    assert night.ending() == ending
    assert night.logic.query("NextEnding") == [{"ending": ending}]


def test_information_sources_reorder_encounters_instead_of_unlocking_a_fixed_chain(night):
    assert not night.can("yao_fuse", "borrow")
    play(night, "cheng_pause", "listen")
    play(night, "catalog")
    assert night.can("yao_fuse", "borrow")
    assert not night.logic.has("Seen", scene="yao_ticket")
    play(night, "yao_fuse", "borrow")
    night.wait()
    drain(night)
    assert night.can("mi_departure", "support")
    assert not night.logic.has("Seen", scene="mi_names")
    assert night.logic.query("Here", person="mi") == [{"person": "mi", "place": "archive"}]


@pytest.mark.parametrize("person", ["cheng", "yao", "mi"])
def test_a_mutual_future_does_not_require_repairing_or_broadcasting(night, person):
    if person == "cheng":
        play(night, "cheng_pause", "listen")
        play(night, "catalog")
    elif person == "yao":
        play(night, "yao_ticket", "support")
        play(night, "yao_fuse", "borrow")
    else:
        play(night, "mi_names", "ask")
    # At tick 5 Mi has moved to the dock, where the ship conversation is
    # no longer outranked by the available archive collection encounter.
    while night.tick() < (5 if person == "mi" else 4):
        night.wait()
        drain(night)
    if person == "cheng":
        play(night, "cheng_letter", "ask")
    elif person == "mi":
        play(night, "mi_departure", "support")
    earliest = 6 if person == "mi" else 5
    while night.tick() < earliest:
        night.wait()
        drain(night)
    play(night, person + "_future", "promise")
    reach_midnight(night)
    assert night.choice("power", "off")
    assert not night.logic.has("BroadcastReady")
    night.resolve("last_broadcast", "keep")
    assert night.ending() == person


def test_preparing_a_broadcast_still_allows_a_quiet_ending(night):
    prepare_broadcast(night)
    reach_midnight(night)
    assert night.can("last_broadcast", "broadcast")
    night.resolve("last_broadcast", "silence")
    assert night.ending() == "quiet"


def test_consent_and_private_broadcast_cannot_be_bypassed(night):
    play(night, "cheng_pause", "publish")
    assert night.logic.has("Seen", scene="rumor")
    assert night.choice("privacy", "repaired")
    assert not night.logic.has("Consent", person="cheng", topic="recording")
    play(night, "catalog")
    assert not night.can("master_copy", "default")
    reach_midnight(night)
    assert not night.can("last_broadcast", "broadcast")
    night.resolve("last_broadcast", "keep")
    assert night.ending() == "quiet"


def test_restoring_a_snapshot_branches_time_people_items_and_story_eligibility(night):
    play(night, "yao_ticket", "support")
    snapshot = night.logic.snapshot()
    play(night, "yao_fuse", "borrow")
    assert night.logic.has("Item", item="spare_fuse", holder="station")
    night.logic.restore(snapshot)
    assert night.tick() == 1
    assert not night.logic.has("Seen", scene="yao_fuse")
    assert night.logic.has("Item", item="spare_fuse", holder="yao")
    play(night, "mi_names", "ask")
    assert night.tick() == 2
    assert not night.logic.has("Consent", person="yao", topic="help")


def test_choosing_one_mutual_future_does_not_silently_commit_to_another(night):
    prepare_broadcast(night)
    play(night, "yao_future", "promise")
    assert not night.can("mi_future", "promise")
    assert not night.can("cheng_future", "promise")
    assert night.logic.query("MutualFuture") == [{"person": "yao"}]


def test_script_and_data_have_no_unwritten_encounters_or_choice_effects():
    data = json.loads(CONTENT.read_text())
    script = (ROOT / "game/story.rpy").read_text()
    scenes = {row["scene"] for row in data["facts"]["Scene"]}
    assert set(re.findall(r"^label scene_(\w+):", script, re.MULTILINE)) == scenes
    written = {(s, a or "default") for s, a in re.findall(r'night\.resolve\("(\w+)"(?:, "(\w+)")?\)', script)}
    declared = {(s, a) for s, choices in data["actions"].items() for a in choices}
    assert written == declared
    assert not re.search(r"\b(?:jump|call) scene_", script)
    assert set(re.findall(r"^label ending_(\w+):", script, re.MULTILINE)) == {"cheng", "yao", "mi", "harbor", "quiet"}


def test_shipped_bundles_match_the_current_source_and_compiler(bundle):
    compiled = json.loads(bundle.read_text())
    name = "relations.duckdb.rules.json" if compiled["backend"] == "duckdb" else "relations.rules.json"
    shipped = json.loads((ROOT / "game" / name).read_text())
    assert shipped["source"]["sha256"] == hashlib.sha256((ROOT / "world.l").read_bytes()).hexdigest()
    for key in ("facts", "derived", "dependencies", "backend"):
        assert shipped[key] == compiled[key]


def test_sampled_legal_playthroughs_end_without_deadlocks(bundle):
    rng = random.Random(20261014)
    for _ in range(12):
        db = LogicDB(bundle)
        story = Night(db, CONTENT)
        story.seed()
        try:
            for step in range(25):
                if story.ending():
                    break
                scene = story.forced()
                if scene is None:
                    options = story.options()
                    if not options or rng.randrange(4) == 0:
                        story.wait()
                        continue
                    scene = rng.choice(options)["scene"]
                actions = db.query("AvailableAction", scene=scene)
                assert actions, (scene, story.time())
                story.resolve(scene, rng.choice(actions)["action"])
            assert story.ending() in {"cheng", "yao", "mi", "harbor", "quiet"}
            assert story.tick() == 12
        finally:
            db.close()


def test_shipped_font_contains_every_character_used_by_the_game():
    fonts = pytest.importorskip("fontTools.ttLib")
    text = "".join(p.read_text() for p in (ROOT / "game").glob("*.rpy")) + CONTENT.read_text()
    with fonts.TTFont(ROOT / "game/fonts/tidelight.otf") as font:
        assert not {ord(c) for c in text if not c.isspace()} - set(font.getBestCmap())
