define config.name = "潮汐替我们保管"
define config.version = "0.3.0"
define config.screen_width = 1280
define config.screen_height = 800
define config.save_directory = "renpy-relations-tidelight-" + os.environ.get("RELATIONS_BACKEND", "sqlite")
define config.developer = not renpy.loadable("release.json")
define gui.text_font = "fonts/tidelight.otf"
define gui.name_text_font = "fonts/tidelight.otf"
define gui.interface_text_font = "fonts/tidelight.otf"

default logic_snapshot = None
default current_place = "station"

init -2 python:
    gui.init(1280, 800)

init python:
    import os
    import sys
    from pathlib import Path
    packages = os.path.join(config.gamedir, "python-packages")
    sys.path.insert(0, packages)
    if not os.path.isfile(os.path.join(packages, "renpy_relations.py")):
        sys.path.append(os.path.abspath(os.path.join(config.gamedir, "..", "..", "..")))
    from renpy_relations import LogicDB
    from night import Night
    tidelight_backend = os.environ.get("RELATIONS_BACKEND", "sqlite")
    tidelight_rules = "relations.duckdb.rules.json" if tidelight_backend == "duckdb" else "relations.rules.json"
    logic = LogicDB(os.path.join(config.gamedir, tidelight_rules), backend=tidelight_backend,
                    mode=os.environ.get("RELATIONS_MODE", "cached"))
    logic.install_renpy(config)
    night = Night(logic, os.path.join(config.gamedir, "content.json"))
    scene_palette = {"station": "#172a37", "roof": "#263245", "workshop": "#34332e",
                     "archive": "#28362f", "dock": "#19383f", "generator": "#30303b", "seawall": "#172b3b"}
    ending_names = {"cheng": "把空白留给明天", "yao": "抵达以后，记得来信", "mi": "不为作品的一次见面",
                    "harbor": "一座没有屋顶的电台", "quiet": "没有播出的晚安"}

    def open_diary():
        renpy.show_screen("diary", clues=night.diary())

    def toggle_weave_inspector():
        if renpy.get_screen("weave_inspector"):
            renpy.hide_screen("weave_inspector")
        else:
            names = ("Clock", "Here", "Trust", "Consent", "Choice", "EligibleScene",
                     "NextForced", "Opportunity", "BroadcastReady", "NextEnding")
            renpy.show_screen("weave_inspector", rows=[(name, logic.query(name)) for name in names])

define s = Character("沈川", color="#e9dfca")
define c = Character("许澄", color="#b9d9ef")
define y = Character("林遥", color="#efc492")
define m = Character("陆弥", color="#b8ddbd")
define phone = Character("电话里的声音", color="#c8c8d4")
define tape = Character("磁带里的许闻", color="#d4cfb8")

style default:
    font "fonts/tidelight.otf"
    size 25
    color "#e8e4dc"
    language "unicode"
style button:
    padding (18, 12)
    background Solid("#243e4b")
    hover_background Solid("#3a5968")
style button_text:
    color "#e8e4dc"
    hover_color "#ffffff"
style say_dialogue:
    size 28
    line_spacing 10
style say_label:
    size 29
style window:
    background Solid("#0c1723ee")
    xpadding 58
    ypadding 26

screen main_menu():
    tag menu
    add Solid("#142632")
    add Solid("#95b6b2") xpos 100 ypos 150 xsize 3 ysize 430
    vbox:
        xpos 145
        ypos 180
        spacing 22
        text "潮汐替我们保管" size 58
        text "一座电台的最后一夜" size 25 color "#a6bfca"
        null height 45
        textbutton "开始这一夜" action Start()
        textbutton "关于这个故事" action Show("about_story")
        textbutton "离开" action Quit(confirm=False)
    text "有些声音可以带走。有些人，需要重新约好见面。" xpos 145 ypos 680 size 23 color "#a6bfca"

screen about_story():
    modal True
    add Solid("#0d1c29f5")
    frame:
        align (0.5, 0.5)
        xsize 1000
        padding (40, 35)
        background Solid("#203744")
        vbox:
            spacing 20
            text "潮汐替我们保管" size 38
            text "完整短篇 · 三位成年女主角 · 五个结局"
            text "你有从二十点到午夜的一夜。去哪里、先听谁说话，由你决定。人物会移动，事情会互相影响；不必寻找唯一正确的顺序。"
            text "每次外出或长谈约二十分钟。突发事件不额外扣时间。手记会保留已知的事。"
            text "这是文字演出版，未配立绘、配音与音乐。"
            textbutton "回到标题" action Hide("about_story")

screen say(who, what):
    window:
        id "window"
        xfill True
        yalign 1.0
        ysize 238
        vbox:
            spacing 15
            if who:
                text who id "who"
            text what id "what"

screen choice(items):
    vbox:
        align (0.5, 0.43)
        xsize 1050
        spacing 15
        for item in items:
            textbutton item.caption action item.action xfill True

screen night_controls():
    zorder 100
    text "[night.time()]  ·  [night.place_name(current_place)]" xpos 35 ypos 24 size 23 color "#b8cbd2"
    hbox:
        xpos 740
        ypos 16
        spacing 10
        textbutton "存档" action FileSave("1") text_size 20
        textbutton "读档" action FileLoad("1", confirm=False) text_size 20
        textbutton "回退" action Rollback() text_size 20
        textbutton "手记" action Function(open_diary) text_size 20
        textbutton "标题" action MainMenu(confirm=False) text_size 20
    if config.developer:
        key "K_F8" action Function(toggle_weave_inspector)

screen night_map(opportunities, whereabouts):
    modal True
    add Solid("#122633")
    frame:
        xpos 40
        ypos 100
        xsize 790
        ysize 650
        padding (25, 22)
        background Solid("#1b3442")
        vbox:
            spacing 14
            text "今晚，你想先去哪里？" size 34
            text "每次长谈或外出，约二十分钟。" size 21 color "#adbec5"
            viewport:
                xsize 740
                ysize 430
                child_size (710, None)
                mousewheel True
                draggable True
                vbox:
                    xsize 710
                    spacing 12
                    for option in opportunities:
                        button:
                            xsize 710
                            action Return(option["scene"])
                            vbox:
                                spacing 5
                                text option["title"] size 24
                                text (night.place_name(option["place"]) + "  ·  " + night.person_name(option["actor"])) size 20 color "#b9cdd1"
            textbutton "留在电台，听一会儿雨" action Return("wait") xfill True text_size 23
    frame:
        xpos 855
        ypos 100
        xsize 385
        ysize 650
        padding (25, 25)
        background Solid("#1a2d38")
        vbox:
            spacing 20
            text "雨里的灯" size 30
            for person in ("cheng", "yao", "mi"):
                text night.person_name(person) size 26
                if person in whereabouts:
                    text night.place_name(whereabouts[person]) size 22 color "#b9cdd1"
            null height 15
            text "午夜，电台交还钥匙。\n在那之前，谁的话都值得听完。" size 23 line_spacing 8
            textbutton "翻开手记" action Function(open_diary) text_size 22

screen diary(clues):
    modal True
    zorder 200
    add Solid("#0b1825f5")
    frame:
        align (0.5, 0.5)
        xsize 1100
        ysize 650
        padding (35, 30)
        background Solid("#263b45")
        vbox:
            spacing 18
            text "带走的声音" size 34
            viewport:
                xsize 1030
                ysize 480
                child_size (1010, None)
                mousewheel True
                draggable True
                vbox:
                    xsize 1010
                    spacing 22
                    if not clues:
                        text "这一夜才刚开始。听完的话，会记在这里。" size 24
                    for clue in clues:
                        text clue size 24 line_spacing 7
            textbutton "合上手记" action Hide("diary")

screen weave_inspector(rows):
    modal True
    zorder 250
    add Solid("#08131cf9")
    frame:
        align (0.5, 0.5)
        xsize 1160
        ysize 710
        padding (25, 25)
        background Solid("#1b303c")
        vbox:
            spacing 12
            text "编排观察 · F8" size 30
            viewport:
                xsize 1110
                ysize 570
                child_size (1090, None)
                mousewheel True
                draggable True
                vbox:
                    xsize 1090
                    spacing 16
                    for relation, values in rows:
                        text relation size 23 color "#a8cbd1"
                        text str(values).replace("{", "{{") substitute False size 18
            textbutton "继续这一夜" action Hide("weave_inspector")
    key "K_F8" action Function(toggle_weave_inspector)

screen ending_card(ending):
    modal True
    add Solid("#172b37")
    vbox:
        align (0.5, 0.47)
        spacing 30
        text ending_names[ending] size 48 xalign 0.5
        text "潮汐替我们保管 · 完" size 25 xalign 0.5 color "#aec6ce"
        null height 20
        textbutton "回到标题" action Return() xalign 0.5

label set_stage(place):
    $ current_place = place
    scene expression Solid(scene_palette[place]) with Dissolve(0.25)
    return

label start:
    $ night.seed()
    show screen night_controls
    call set_stage("station")
    call prologue
    jump weave

# The only dispatcher. Encounters return here; none names a following encounter.
label weave:
    $ selected_ending = night.ending()
    if selected_ending:
        hide screen night_controls
        call expression "ending_" + selected_ending
        call screen ending_card(selected_ending)
        return
    $ selected_scene = night.forced()
    if not selected_scene:
        call screen night_map(night.options(), {r["person"]: r["place"] for r in logic.query("Here")})
        $ selected_scene = _return
    if selected_scene == "wait":
        call waiting
    else:
        call expression "scene_" + selected_scene
    jump weave
