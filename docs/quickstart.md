# Quickstart: Palace

[English](quickstart.md) · [简体中文](quickstart.zh-CN.md) · [Overview](../README.md) · [Reference](reference.md)

Palace is a small world with archive access, a secret, and a reward that can be claimed once. This guide first runs it in ordinary Python, then stages the same example for Ren’Py. Basic Python is enough; you do not need SQL or database experience.

Ordinary Python programs import `LogicDB` from `renpy_relations`; Ren’Py integrations use `RenpyLogicDB` from the same package.

## Facts, tables, and rules

A **relation** is table-shaped data. Here it means more than a relationship score: `Sponsor` records who sponsors access to which place. Each **row** records one fact, and each named **column** holds part of that fact:

| character | location |
| --- | --- |
| hero | archive |

The row says that `hero` has sponsorship for `archive`. Python records it with `logic.add("Sponsor", character="hero", location="archive")`. A **schema** declares the relations and their columns and types. This excerpt from [Palace’s schema](../examples/palace/schema.json) declares two text columns:

```json
{
  "facts": {
    "Sponsor": {"columns": {"character": "text", "location": "text"}}
  }
}
```

This is an excerpt, not a replacement schema. The complete file also declares four other fact relations and three derived relations:

| Relation | Meaning | Supplied by |
| --- | --- | --- |
| `Member` | A character belongs to a faction | Game actions |
| `FactionAccess` | A faction may enter a location | Game setup or actions |
| `Sponsor` | A character has sponsorship for a location | Game actions |
| `Knows` | A character knows a secret | Game actions |
| `RewardClaimed` | A character has received a reward | Game actions |
| `CanEnter` | A character currently has access | Rules |
| `CanInvestigate` | Access and knowledge permit investigation | Rules |
| `CanClaimReward` | An investigation reward remains available | Rules |

Facts are inputs. **Derived answers** follow from those inputs and the rules; you query them instead of inserting them. A **query** asks for matching rows or whether a matching row exists. The schema can also declare an optional key to identify a fact row uniquely; Palace uses complete tuples without extra keys.

A database stores tables and evaluates queries. SQL is the query language that the compiler produces. [SQLite](https://www.sqlite.org/about.html) runs inside the game process, so there is no separate database server to configure. `LogicDB` starts an in-memory world and can capture its facts as a native database image for saving. Python changes facts, Logica compiles rules during development, and SQLite evaluates their SQL during play.

## Prepare the environment

You need `uv`, a source checkout, and Python 3.12 for this walkthrough. Run these commands from the project root, which contains `pyproject.toml`:

```sh
uv sync --locked --python 3.12
PALACE_WORK="$(mktemp -d /tmp/renpy-relations-palace.XXXXXX)"
```

Keep this shell open: later commands use `PALACE_WORK`. The fresh directory holds your compiled bundle and staged example. The locked environment includes the development-time Logica compiler. The initial Python exercise uses Python’s SQLite driver; Ren’Py’s native driver is installed separately during staging.

## Read the first rule

This is one of the rules in [world.l](../examples/palace/world.l):

```prolog
CanEnter(character: c, location: l) distinct :-
  Sponsor(character: c, location: l);
```

Read it as “A character can enter a location if there is a matching sponsorship.” `CanEnter` and `Sponsor` name relations, also called predicates in Logica. `character:` and `location:` are named columns. The variables `c` and `l` carry matching values from the condition to the answer. `:-` means “holds if”; `distinct` requests unique answer rows; `;` ends the rule. Quoted text such as `"hero"` is a literal value, whereas `c` is a variable.

For the input `Sponsor(character="hero", location="archive")`, this rule derives `CanEnter(character="hero", location="archive")`. Python reads that answer with:

```python
logic.query("CanEnter", character="hero")
# [{'character': 'hero', 'location': 'archive'}]
```

Learn more in the official Logica guides to [rules](https://logica-lang.github.io/usrguide/rules.html), [named arguments](https://logica-lang.github.io/usrguide/named-arguments.html), and [duplicate rows and distinct](https://logica-lang.github.io/usrguide/multi-semantics.html).

Palace defines a second way to enter:

```prolog
CanEnter(character: c, location: l) distinct :-
  Member(character: c, faction: f),
  FactionAccess(faction: f, location: l);
```

The comma means both conditions must hold. Repeating `f` matches a membership’s faction with a faction-access row: this connection is a **join**. For example, membership in `scholars` and access for `scholars` to `archive` together yield archive access. The two `CanEnter` rules provide alternatives: sponsorship **or** matching membership is enough. If both apply, `distinct` keeps one answer row.

Investigation combines access and knowledge:

```prolog
CanInvestigate(character: c) distinct :-
  CanEnter(character: c, location: "archive"),
  Knows(character: c, secret: "forged_letter");
```

Finally, a claim is eligible only while no matching claim is recorded:

```prolog
CanClaimReward(character: c, reward: "investigation") distinct :-
  CanInvestigate(character: c),
  ~RewardClaimed(character: c, reward: "investigation");
```

`~` checks that the matching row is absent. This rule describes a condition; it does not execute the investigation, award an item, or insert a claim. Your script owns those effects.

In this project, declare game facts in schema JSON and insert them with `logic.add(...)`; use `.l` for derivation rules. The upstream [Logica user guide](https://logica-lang.github.io/usrguide/) also shows facts written directly in Logica source. This project’s compiler rejects source definitions of game-supplied fact relations because those inputs belong to the runtime tables.

## Compile for SQLite

Compile the shipped source and complete schema into your fresh workspace:

```sh
uv run --locked renpy-relations-compile examples/palace/world.l \
  --schema examples/palace/schema.json \
  --backend sqlite \
  --output "$PALACE_WORK/palace.rules.json"
```

The command prints `Built … (3 derived relations)`. The JSON **rule bundle** contains the schema, compiled SQL, and dependency information the runtime needs. Compilation happens before play. The next command loads this exact output.

## Run the Python world

Run this complete exercise from the source root:

```sh
uv run --locked python - "$PALACE_WORK/palace.rules.json" <<'PY'
import sys
from renpy_relations import LogicDB

logic = LogicDB(sys.argv[1])
try:
    print("Initial access:", logic.has("CanEnter", character="hero"))

    logic.add("Sponsor", character="hero", location="archive")
    print("Sponsored access:", logic.query("CanEnter", character="hero"))

    with logic.batch():
        logic.add("Knows", character="hero", secret="forged_letter")
        logic.add("Member", character="hero", faction="scholars")
        logic.add("FactionAccess", faction="scholars", location="archive")
    print("Reward eligible:", logic.has("CanClaimReward", character="hero"))

    logic.remove("Sponsor", character="hero", location="archive")
    print("Access through membership:", logic.has("CanEnter", character="hero"))

    before_claim = logic.snapshot()
    # The application decides to grant the reward and records that decision.
    logic.add("RewardClaimed", character="hero", reward="investigation")
    print("Eligible after claim:", logic.has("CanClaimReward", character="hero"))

    logic.restore(before_claim)
    print("Eligible after restore:", logic.has("CanClaimReward", character="hero"))
finally:
    logic.close()
PY
```

Expected output:

```text
Initial access: False
Sponsored access: [{'character': 'hero', 'location': 'archive'}]
Reward eligible: True
Access through membership: True
Eligible after claim: False
Eligible after restore: True
```

`has(...)` answers a yes/no question; `query(...)` returns dictionaries for matching rows. Keyword filters use equality. Removing sponsorship leaves membership access effective because the rules combine independent access sources.

`batch()` groups changes into one transaction: either they commit together or an exception rolls them back. Read after leaving the batch; reads inside a batch are rejected. `add` requires every column and ignores an identical tuple. `remove` deletes rows matching its filters and requires at least one filter.

If your own schema declares `Member` with `"key": ["character"]`, only one faction can be recorded per character. Replace an existing keyed row by removing it and adding the replacement in one batch:

```python
with logic.batch():
    logic.remove("Member", character="hero")
    logic.add("Member", character="hero", faction="scholars")
# Query after the batch exits.
```

This pattern also works with Palace’s unkeyed schema, but it deliberately removes all of that character’s memberships. See the [reference](reference.md) before changing a game’s fact schema.

The **snapshot** above contains facts and format/schema metadata. Restoring it recovers the pre-claim facts and recomputes answers under the currently loaded rules. It does not save arbitrary Python variables or freeze the rule source. `restore(None)` starts an empty fact world. Close a standalone `LogicDB` when finished.

## Stage and play Palace

For this route, use a Linux x86_64 Ren’Py SDK with Python 3.12. Release tooling pins SDK version `8.5.3.26051504`. Set `RELATIONS_SDK` to your SDK directory, which contains `renpy.sh`, then stage into a destination that does not exist yet:

```sh
RELATIONS_SDK="/path/to/your/renpy-sdk"
PALACE_PROJECT="$PALACE_WORK/palace-game"
uv run --locked python -m tools.prepare_game \
  --game examples/palace \
  --out "$PALACE_PROJECT" \
  --backend sqlite \
  --sdk "$RELATIONS_SDK"
"$RELATIONS_SDK/renpy.sh" "$PALACE_PROJECT"
```

Replace the SDK placeholder before running. Staging copies the example and its shipped bundles, installs locked dependencies into `game/python-packages`, and checks imports using the SDK interpreter. It does **not** consume `$PALACE_WORK/palace.rules.json`; that bundle was used by the standalone exercise. The staged example reads `game/relations.rules.json`.

Click **Start** and advance to the choices. Try these actions:

1. **Ask for a sponsor** makes **Enter the archive** available.
2. **Learn about the forged letter** makes **Investigate and claim the reward** available.
3. **Investigate and claim the reward** records `RewardClaimed`; the claim choice disappears.
4. In a new game, ask for a sponsor and **Join the scholars**, then **Revoke the sponsorship**. Archive access remains because of membership.

Use the top **Save** button after gaining sponsorship, revoke it, then click **Load**. The saved sponsorship and its derived access return. Use **Rollback** to move back across the sponsorship choice; repeat if needed to reach the earlier interaction. At that point the sponsorship and access disappear. These controls exercise Ren’Py’s saved and rollback state, including the adapter’s fact snapshot. In developer mode, **F8** opens the relation inspector.

## Connect your own Ren’Py script

The staged [Palace script](../examples/palace/game/script.rpy) contains the complete example. Its integration pattern is:

```renpy
default logic_snapshot = None
default reward_points = 0

init python:
    import os
    import sys
    sys.path.insert(0, os.path.join(config.gamedir, "python-packages"))
    from renpy_relations import RenpyLogicDB as LogicDB

    logic = LogicDB(os.path.join(config.gamedir, "relations.rules.json"))
    logic.install_renpy(config)

    def seed_world():
        with logic.batch():
            logic.add("Member", character="hero", faction="visitors")
            logic.add("FactionAccess", faction="scholars", location="archive")

label start:
    $ seed_world()
    "The archive is restricted."
    jump court

label court:
    menu:
        "Ask for a sponsor" if not logic.has("Sponsor", character="hero", location="archive"):
            $ logic.add("Sponsor", character="hero", location="archive")
            "A courtier sponsors your visit."
        "Learn about the forged letter" if not logic.has("Knows", character="hero", secret="forged_letter"):
            $ logic.add("Knows", character="hero", secret="forged_letter")
            "You learn about a forgery in the archive."
        "Investigate and claim the reward" if logic.has("CanClaimReward", character="hero", reward="investigation"):
            $ logic.add("RewardClaimed", character="hero", reward="investigation")
            $ reward_points += 1
            "You receive one reward point."
        "Finish":
            return
    jump court
```

Use this pattern in a game with the staged runtime and bundle. Install the adapter during initialization and seed facts in `label start`, when starting a new game. Keep `logic_snapshot` as a Ren’Py `default` variable. The adapter publishes a fact snapshot after a changed commit and restores the database from that variable through Ren’Py’s lifecycle callbacks. Ordinary game effects, such as `reward_points`, remain your script’s responsibility and should use Ren’Py’s normal saved/rollback variables.

Do not assign the database object to `logic_snapshot`; the adapter manages that variable. For lifecycle details and supported reload behavior, see [Ren’Py integration in the reference](reference.md).

## Change a rule

Edit the staged `$PALACE_PROJECT/world.l` to try a different condition without changing the source checkout. For example, replace its `CanInvestigate` rule with:

```prolog
CanInvestigate(character: c) distinct :-
  CanEnter(character: c, location: "archive");
```

Now access alone permits investigation. Compile explicitly into the bundle that the staged game actually loads:

```sh
uv run --locked renpy-relations-compile "$PALACE_PROJECT/world.l" \
  --schema "$PALACE_PROJECT/schema.json" \
  --backend sqlite \
  --output "$PALACE_PROJECT/game/relations.rules.json"
```

Restart the game and start a new playthrough. Asking for a sponsor now makes the reward claim available before learning the secret. Restore the original condition by copying its rule back and recompiling. When adapting this world, change schema declarations for new fact types, `.l` rules for eligibility, and Python/Ren’Py actions for effects.

Palace also enables developer rule watching: after a successful rebuild it can load a changed bundle at an interaction, or you can press **F6** to reload. Compiler `--watch` rebuilds source changes; adapter `watch_rules=True` loads changed bundles. These are separate steps. Rule reload keeps facts and requires the same fact schema and backend; old snapshots use the current rules after reload. See [snapshots and reload](reference.md) for the full contract.

## Next steps

Stay with SQLite until this exercise works. For optional DuckDB installation, backend-specific compilation, query modes, and rule-watching commands, continue to the [reference](reference.md). The [Tidelight guide](../examples/tidelight/README.md) shows how a complete story selects encounters from eligible answers. The [benchmark guide](../benchmarks/README.md) covers measurement, and [maintenance](maintaining.md) covers changes and releases.
