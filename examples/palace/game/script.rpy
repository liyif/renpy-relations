define config.name = "Ren'Py Relations - Palace"
define config.version = "0.1"
define config.screen_width = 960
define config.screen_height = 640
define config.save_directory = "renpy-relations-palace"
define config.developer = True

default logic_snapshot = None

init -2 python:
    gui.init(960, 640)

init python:
    import os
    import sys

    # Repository demo only. In a packaged game put the module in python-packages.
    sys.path.insert(0, os.path.abspath(os.path.join(config.gamedir, "..", "..", "..")))
    from renpy_relations import LogicDB, RuleSet

    logic = LogicDB(
        os.path.join(config.gamedir, "relations.rules.json"),
        mode=os.environ.get("RELATIONS_MODE", "cached"),
    )
    logic.install_renpy(config, watch_rules=True)

    def seed_relations_world():
        with logic.batch():
            logic.add("Member", character="hero", faction="visitors")
            logic.add("FactionAccess", faction="scholars", location="archive")

screen main_menu():
    tag menu
    add Solid("#172132")
    vbox:
        align (0.5, 0.5)
        spacing 24
        text "Ren'Py Relations" size 42
        text "A small experiment in facts, rules, and choices."
        textbutton "Start" action Start()
        textbutton "Quit" action Quit(confirm=False)

screen say(who, what):
    window:
        id "window"
        xfill True
        yalign 1.0
        padding (40, 24)
        vbox:
            spacing 12
            if who:
                text who id "who"
            text what id "what"

screen choice(items):
    vbox:
        align (0.5, 0.42)
        spacing 12
        for item in items:
            textbutton item.caption action item.action

screen relations_controls():
    zorder 100
    hbox:
        align (0.5, 0.02)
        spacing 22
        textbutton "Save" action FileSave("1")
        textbutton "Load" action FileLoad("1", confirm=False)
        textbutton "Rollback" action Rollback()
        textbutton "Main menu" action MainMenu(confirm=False)
    if config.developer:
        key "K_F6" action Function(logic.reload_rules)
        key "K_F8" action ToggleScreen("relations_inspector")

screen relations_inspector():
    zorder 200
    modal True
    default relation = "CanEnter"
    frame:
        align (0.5, 0.5)
        xsize 900
        ysize 550
        padding (24, 24)
        vbox:
            spacing 12
            text "Relations inspector (F8)" size 28
            hbox:
                spacing 16
                for name in ("Member", "Sponsor", "Knows", "RewardClaimed", "CanEnter", "CanInvestigate", "CanClaimReward"):
                    textbutton name text_size 16 action SetScreenVariable("relation", name)
            viewport:
                mousewheel True
                draggable True
                yfill True
                vbox:
                    spacing 12
                    text str(logic.describe(relation)).replace("{", "{{") substitute False size 18
                    text str(logic.query(relation)).replace("{", "{{") substitute False size 22
                    text str(logic.stats()).replace("{", "{{") substitute False size 18
            textbutton "Close" action Hide("relations_inspector")
    key "K_F8" action Hide("relations_inspector")

label start:
    $ seed_relations_world()
    scene expression Solid("#172132")
    show screen relations_controls
    "You arrive at the palace. The archive is restricted."
    "Membership or a sponsor can grant access. A secret gives you a reason to investigate."
    jump court

label court:
    menu:
        "Ask for a sponsor" if not logic.has("Sponsor", character="hero", location="archive"):
            $ logic.add("Sponsor", character="hero", location="archive")
            "A courtier agrees to sponsor your archive visit."

        "Revoke the sponsorship" if logic.has("Sponsor", character="hero", location="archive"):
            $ logic.remove("Sponsor", character="hero", location="archive")
            "The sponsorship is revoked. Other sources of access still apply."

        "Join the scholars" if not logic.has("Member", character="hero", faction="scholars"):
            $ logic.add("Member", character="hero", faction="scholars")
            "The scholars welcome you. Their members may enter the archive."

        "Leave the scholars" if logic.has("Member", character="hero", faction="scholars"):
            $ logic.remove("Member", character="hero", faction="scholars")
            "You leave the scholars."

        "Learn about the forged letter" if not logic.has("Knows", character="hero", secret="forged_letter"):
            $ logic.add("Knows", character="hero", secret="forged_letter")
            "You learn that a forged letter is hidden in the archive."

        "Enter the archive" if logic.has("CanEnter", character="hero", location="archive"):
            "The guard lets you enter the archive."

        "Investigate and claim the reward" if logic.has("CanClaimReward", character="hero", reward="investigation"):
            $ logic.add("RewardClaimed", character="hero", reward="investigation")
            "You expose the forgery and receive the reward. It cannot be claimed twice."

        "Finish":
            "Try another route, reload a save, or roll back to a previous choice."
            return
    jump court
