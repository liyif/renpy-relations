# Run with Ren'Py 8.5+: renpy.sh examples/palace test relations
init python:
    import json
    from pathlib import Path

testsuite global:
    setup:
        skip until screen "main_menu"

testsuite relations:
    before testcase:
        if not screen "main_menu":
            run MainMenu(confirm=False)
        click "Start"
        advance until screen "choice"
        assert eval not logic.has("Sponsor")
        assert eval not logic.has("CanEnter", character="hero", location="archive")

    after testcase:
        $ renpy.unlink_save("relations-test")
        run Function(logic.reload_rules, relations_rules_path)
        $ (Path(config.gamedir) / "cache" / "relations-watch-test.json").unlink(missing_ok=True)

    testcase combined_rules_and_reward:
        click "Ask for a sponsor"
        advance until screen "choice"
        assert eval logic.has("CanEnter", character="hero", location="archive")
        assert eval not logic.has("CanClaimReward")
        click "Learn about the forged letter"
        advance until screen "choice"
        assert eval logic.has("CanClaimReward", character="hero", reward="investigation")
        click "Investigate and claim the reward"
        advance until screen "choice"
        assert eval logic.has("RewardClaimed", character="hero", reward="investigation")
        assert eval not logic.has("CanClaimReward")
        click "Revoke the sponsorship"
        advance until screen "choice"
        assert eval not logic.has("CanEnter", character="hero", location="archive")
        assert eval logic.has("RewardClaimed")
        click "Join the scholars"
        advance until screen "choice"
        assert eval logic.has("CanInvestigate", character="hero")
        assert eval not logic.has("CanClaimReward")

    testcase save_and_load:
        click "Ask for a sponsor"
        advance until screen "choice"
        run Function(renpy.save, "relations-test")
        click "Revoke the sponsorship"
        advance until screen "choice"
        assert eval not logic.has("CanEnter", character="hero", location="archive")
        run Function(renpy.load, "relations-test")
        advance until screen "choice"
        assert eval logic.has("Sponsor", character="hero", location="archive")
        assert eval logic.has("CanEnter", character="hero", location="archive")

    testcase rollback:
        click "Ask for a sponsor"
        advance until screen "choice"
        assert eval logic.has("CanEnter", character="hero", location="archive")
        run Rollback() repeat 2
        assert eval not logic.has("Sponsor", character="hero", location="archive")
        assert eval not logic.has("CanEnter", character="hero", location="archive")

    testcase new_game:
        click "Ask for a sponsor"
        advance until screen "choice"
        run MainMenu(confirm=False)
        click "Start"
        advance until screen "choice"
        assert eval not logic.has("Sponsor")
        assert eval not logic.has("RewardClaimed")
        assert eval not logic.has("CanEnter", character="hero", location="archive")

    testcase hot_reload:
        click "Ask for a sponsor"
        advance until screen "choice"
        assert eval logic.has("CanEnter", character="hero", location="archive")
        $ changed = RuleSet.load(relations_rules_path).document
        $ changed["derived"]["CanEnter"]["sql"] = "SELECT character, location FROM Sponsor WHERE 0"
        $ changed["dependencies"]["CanEnter"] = ["Sponsor"]
        run Function(logic.reload_rules, RuleSet(changed))
        assert eval logic.has("Sponsor", character="hero", location="archive")
        assert eval not logic.has("CanEnter", character="hero", location="archive")
        run Function(logic.reload_rules, relations_rules_path)
        assert eval logic.has("CanEnter", character="hero", location="archive")

    testcase inspector:
        keysym "K_F8"
        assert screen "relations_inspector"
        keysym "K_F8"
        assert not screen "relations_inspector"

    testcase auto_reload:
        click "Ask for a sponsor"
        advance until screen "choice"
        $ original = RuleSet.load(relations_rules_path).document
        $ watched = Path(config.gamedir) / "cache" / "relations-watch-test.json"
        $ watched.parent.mkdir(parents=True, exist_ok=True)
        $ watched.write_text(json.dumps(original), encoding="utf-8")
        run Function(logic.reload_rules, str(watched))
        assert eval logic.has("CanEnter", character="hero", location="archive")
        $ changed = RuleSet(original).document
        $ changed["derived"]["CanEnter"]["sql"] = "SELECT character, location FROM Sponsor WHERE 0"
        $ changed["dependencies"]["CanEnter"] = ["Sponsor"]
        $ watched.write_text(json.dumps(changed), encoding="utf-8")
        run Function(renpy.restart_interaction)
        assert eval not logic.has("CanEnter", character="hero", location="archive")
        assert eval logic.has("Sponsor", character="hero", location="archive")
        $ watched.write_text("{", encoding="utf-8")
        run Function(renpy.restart_interaction)
        assert eval not logic.has("CanEnter", character="hero", location="archive")
        $ watched.write_text(json.dumps(original), encoding="utf-8")
        run Function(renpy.restart_interaction)
        assert eval logic.has("CanEnter", character="hero", location="archive")
