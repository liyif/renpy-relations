# Tidelight — 潮汐替我们保管

Tidelight is a complete Chinese-language, text-only short story about the last night of a coastal radio station. You play 沈川 and choose where to go and whom to listen to between 20:00 and midnight. Its three adult heroines are 许澄, 林遥, and 陆弥. There are five endings. The sample has no character art, voice acting, or music; it uses text, simple backgrounds, and a bundled Chinese font.

## Play

If you have the standalone Linux archive, extract it and run `./tidelight.sh` from its directory. It includes the engine and runtime dependencies. The default backend is SQLite. To use DuckDB, run `RELATIONS_BACKEND=duckdb ./tidelight.sh`. Saves use a separate directory for each backend; start a new game when switching. Snapshots cannot be exchanged between backends.

From source, use Linux x86_64, `uv`, and Ren’Py **8.5.3.26051504** with its Python 3.12 interpreter. Other deployment targets are unverified. Run these commands from the source archive or repository root, replacing the SDK path with your installation. Choose a destination that does not already exist, outside the source example:

```sh
uv sync --locked --extra duckdb --group renpy-linux
SDK=/path/to/renpy-8.5.3-sdk
GAME=/tmp/tidelight-play
uv run --locked --extra duckdb python -m tools.prepare_game \
  --game examples/tidelight --out "$GAME" --backend duckdb --sdk "$SDK"
"$SDK/renpy.sh" "$GAME"
```

Staging with `--backend duckdb` installs both database drivers. It does not change the game's default selector. Launch the staged project with `RELATIONS_BACKEND=duckdb "$SDK/renpy.sh" "$GAME"` to select DuckDB. For SQLite alone, use `--backend sqlite` and omit `--extra duckdb`. Staging copies the shipped rule bundles and checks imports with the SDK; it does not compile your edited `.l` file.

At the title screen, **开始这一夜** starts the story and **关于这个故事** opens its introduction. Click or advance dialogue, then select a visible conversation or destination on the map. **留在电台，听一会儿雨** waits. Most outings or long conversations cost roughly twenty minutes; forced events cost no additional time. Characters move as the night advances, and the most pressing eligible subject at each location appears first. There is no required single encounter order.

The top bar provides **存档** (save to slot 1), **读档** (load slot 1), **回退** (rollback), **手记** (known clues), and **标题** (return to title). The diary records knowledge, not a route checklist. In a development project, F8 shows the relation inspector. The packaged release disables this development control.

## How the story is assembled

| File | Responsibility |
| --- | --- |
| [world.l](world.l) | Derives presence, trust, scene and action eligibility, priority, broadcast readiness, and endings. |
| [schema.json](schema.json) | Declares game facts and exported derived relations. |
| [game/content.json](game/content.json) | Supplies starting facts, scene requirements, effects for each action, and display names. |
| [game/night.py](game/night.py) | Seeds the world, queries available choices, and applies each selected action atomically. |
| [game/script.rpy](game/script.rpy) | Initializes the runtime, installs save/rollback integration, draws screens, and dispatches encounters. |
| [game/story.rpy](game/story.rpy) | Contains the prose, menus, scene labels, and ending labels. |
| `game/relations.rules.json`, `game/relations.duckdb.rules.json` | Compiled SQLite and DuckDB bundles, respectively. |

The single `weave` dispatcher checks an ending first, then a forced encounter, then the player's map choice. Every encounter returns to it. Story labels do not name a subsequent encounter. This is an application design for this sample; Ren’Py Relations does not require this dispatcher, JSON effect format, or priority scheme.

For example, scene requirements are facts. `MissingKnowledge` derives which scenes still lack a clue:

```prolog
MissingKnowledge(scene: s) distinct :-
  NeedKnowledge(scene: s, clue: k), ~Knows(clue: k);
```

`EligibleScene` combines location and time with the absence of missing knowledge, items, consent, choices, and trust; `~Seen(scene: s)` prevents replaying the same encounter. `Opportunity` then keeps the highest-priority eligible subject at each place below the forced-event threshold of 100. Equal priorities use the scene identifier as a deterministic tie-breaker. Time places people and bounds eligibility rather than selecting a chapter.

One concrete chain is the conversation about 林遥's ticket. Its `support` action in `content.json` adds knowledge of `yao_leaving` and `breaker_map`, and a `Bond` row with reason `ticket` and weight 1. The fuse conversation requires the `breaker_map` clue and the spare fuse held by 林遥. Her current location and other available priorities also affect whether it appears. The same clue can come from the catalog; this is a shared condition rather than an instruction to play the ticket scene first.

After a player chooses `borrow` in the fuse conversation, `Night.resolve("yao_fuse", "borrow")` first verifies `AvailableAction`. In one batch it adds consent for 林遥's help, transfers `spare_fuse` to the station, records a positive bond, marks the scene seen, and advances the clock. The next dispatcher pass queries the changed world. Queries answer eligibility; the action supplies effects. Reads and action validation occur outside the batch. For the runtime's complete API, snapshot, and mode contracts, use the [reference](../../docs/reference.md).

## Adapt the sample

Start with the [Palace quickstart](../../docs/quickstart.md) for a smaller integration exercise. In Tidelight, edit prose in `game/story.rpy`, display data and action effects in `game/content.json`, requirements and scheduling in `world.l`, and relation declarations in `schema.json`. Keep scene/action identifiers consistent across these files. A new scene needs a declared scene, actions and effects, and a corresponding `scene_<identifier>` label; a new ending needs its rules and `ending_<identifier>` label.

Compile both backends after changing rules or schema. From the source root:

```sh
uv run --locked renpy-relations-compile examples/tidelight/world.l \
  --schema examples/tidelight/schema.json \
  --output examples/tidelight/game/relations.rules.json
uv run --locked --extra duckdb renpy-relations-compile examples/tidelight/world.l \
  --schema examples/tidelight/schema.json --backend duckdb \
  --output examples/tidelight/game/relations.duckdb.rules.json
uv run --locked --extra duckdb --group assets pytest -q tests/test_tidelight.py
```

Then stage into another fresh directory. If editing an already staged project, use `renpy-relations-compile` from the source distribution with the staged `world.l` and `schema.json`, and point `--output` explicitly at that project's selected `game/relations*.rules.json`. The compiler is a development tool and is not part of the standalone game's runtime dependencies. Restart the game after content or prose edits. Schema changes require a deliberate save policy; existing fact snapshots are not automatically migrated.

The focused tests check bundle synchronization, legal action effects, all five ending routes, state restoration, sampled playthroughs, and font coverage. Sampled paths are useful evidence, not exhaustive exploration of every ordering. See [maintenance](../../docs/maintaining.md) for SDK lint and real-engine tests.

## Font and license

The shipped `game/fonts/tidelight.otf` is **Tidelight Sans**, a renamed subset of **Noto Sans CJK SC**. Its [SIL Open Font License](game/fonts/OFL.txt) stays beside the font. The source and story use the project's MIT license; the source distribution's [third-party notices](../../THIRD_PARTY_NOTICES.md) explain the other components. The [Noto CJK project](https://github.com/notofonts/noto-cjk) is the upstream font source.

The repository does not record the exact version or SHA256 of the original input font. Rebuilding from a newly supplied Noto font therefore does not prove byte-for-byte reproduction of the shipped subset. Record your chosen source font's identity when making a replacement.

From the source root, provide a local font collection and select its SC face:

```sh
uv run --locked --group assets python examples/tidelight/build_font.py \
  --source-font /path/to/NotoSansCJK-Regular.ttc --font-number 2
uv run --locked --group assets pytest -q tests/test_tidelight.py \
  -k shipped_font_contains_every_character
```

`--source-font` is required. `--font-number` defaults to 2, the SC face in the standard Noto CJK collection; check the face ordering of your actual input. The script checks source coverage, subsets it, renames its family to Tidelight Sans, and writes `game/fonts/tidelight.otf` beside the script. Glyph inputs are every top-level `game/*.rpy`, the complete `game/content.json`, printable ASCII U+0020–U+007E, and a space; other whitespace is excluded. Text added elsewhere needs an explicit extension of that input set. Rebuild and check coverage when changing Chinese text, and preserve OFL.txt when distributing the font.

## Optional spoiler: 许澄's ending

The following visible-choice route corresponds to the `ending_cheng` real-engine testcase. Allow each forced event to finish before selecting the next opportunity. Save before experimenting if you want to branch later.

1. **看看林遥压在工具箱下的车票** → **票都买好了。等到了，先告诉我那边食堂怎么样。**
2. **向林遥借一枚备用保险** → **借给我好吗？今晚我来换，你只在旁边看着。**
3. **听陆弥说起录音上的名字** → **我想借走，先让许澄决定怎么处理。登记写在哪里？**
4. **把母带带回电台**, then **翻开最后一册工作簿**.
5. **和陆弥看一张暂时失效的船票** → **那就现在问。等你安顿下来，我能去看看你的工作室吗？**
6. **问许澄，空白后面是什么** → **不用替所有人决定。今晚，你愿意怎么听、怎么让别人听？**
7. **带备用保险去配电房**.
8. **陪许澄听那段突然结束的录音** → **先别按播放。你想听见后面是什么吗？**
9. **把明天的问题留给许澄回答** → **不用。明天先一起吃早饭，然后认真商量下一次。**
10. Choose **留在电台，听一会儿雨** twice, then **按大家同意的方式，做完最后一场广播。**

This reaches **把空白留给明天**. A mutual future has higher ending priority than the harbor broadcast ending. The other endings are **抵达以后，记得来信** (林遥), **不为作品的一次见面** (陆弥), **一座没有屋顶的电台** (harbor), and **没有播出的晚安** (quiet). Romance does not require repairing the transmitter or broadcasting: those are separate conditions in this story.
