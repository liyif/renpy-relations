"""Application actions and presentation for Tidelight; plot eligibility lives in Logica."""

import json
from pathlib import Path


class Night:
    def __init__(self, logic, content):
        self.logic = logic
        self.content = json.loads(Path(content).read_text(encoding="utf-8"))

    def seed(self):
        if self.logic.has("Clock", world="night"):
            return
        with self.logic.batch():
            for relation, rows in self.content["facts"].items():
                for row in rows:
                    self.logic.add(relation, **row)

    def tick(self):
        rows = self.logic.query("Clock", world="night")
        return rows[0]["tick"] if rows else 0  # Ren'Py can predict screens before new-game seeding.

    def time(self):
        # The cutoff encounter occupies the last on-air minute, without an
        # additional action cost. Time is approximate outside that final minute.
        minutes = min(20 * 60 + self.tick() * 20, 23 * 60 + 59)
        return f"{minutes // 60:02d}:{minutes % 60:02d}"

    def forced(self):
        rows = self.logic.query("NextForced")
        return rows[0]["scene"] if rows else None

    def ending(self):
        rows = self.logic.query("NextEnding")
        return rows[0]["ending"] if rows else None

    def options(self):
        rows = self.logic.query("Opportunity")
        return sorted(rows, key=lambda row: (row["place"], row["scene"]))

    def resolve(self, scene, action="default"):
        """Apply the selected action, mark the encounter and advance time atomically."""
        pending = self.forced()
        if self.ending() or (pending is not None and pending != scene):
            raise ValueError("Resolve the pending event before choosing another encounter")
        if not self.logic.has("AvailableAction", scene=scene, action=action):
            raise ValueError(f"Encounter is unavailable: {scene}")
        effects = self.content["actions"][scene][action]
        cost = self.logic.query("Scene", scene=scene)[0]["cost"]
        tick = self.tick()
        with self.logic.batch():
            for clue in effects.get("knows", []):
                self.logic.add("Knows", clue=clue)
            for person, reason, weight in effects.get("bond", []):
                self.logic.remove("Bond", person=person, reason=reason)
                self.logic.add("Bond", person=person, reason=reason, weight=weight)
            for person, topic in effects.get("consent", []):
                self.logic.add("Consent", person=person, topic=topic)
            for item, holder in effects.get("item", []):
                self.logic.remove("Item", item=item)
                self.logic.add("Item", item=item, holder=holder)
            for topic, value in effects.get("choice", []):
                self.logic.remove("Choice", topic=topic)
                self.logic.add("Choice", topic=topic, value=value)
            self.logic.add("Seen", scene=scene, at_tick=tick)
            self.logic.remove("Clock", world="night")
            self.logic.add("Clock", world="night", tick=tick + cost)

    def wait(self):
        if self.forced() or self.ending():
            raise ValueError("There is a pending event")
        tick = self.tick()
        with self.logic.batch():
            self.logic.remove("Clock", world="night")
            self.logic.add("Clock", world="night", tick=tick + 1)

    def choice(self, topic, value):
        return self.logic.has("Choice", topic=topic, value=value)

    def can(self, scene, action):
        return self.logic.has("AvailableAction", scene=scene, action=action)

    def place_name(self, place):
        return self.content["places"][place]

    def person_name(self, person):
        return self.content["people"].get(person, "独自")

    def location(self, scene):
        return self.logic.query("EligibleScene", scene=scene)[0]["place"]

    def diary(self):
        return [self.content["clues"][row["clue"]] for row in
                sorted(self.logic.query("Knows"), key=lambda row: row["clue"])]
