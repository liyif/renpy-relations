"""The palace example's conditions, expressed directly with Python sets.

This deliberately small reference is for comparing rule expression, not a
second implementation of transactions, save integration, or caching.
"""

from dataclasses import dataclass, field


@dataclass
class Palace:
    members: set = field(default_factory=set)
    faction_access: set = field(default_factory=set)
    sponsors: set = field(default_factory=set)
    knowledge: set = field(default_factory=set)
    rewards_claimed: set = field(default_factory=set)

    def can_enter(self, character, location):
        return (character, location) in self.sponsors or any(
            member == character and (faction, location) in self.faction_access
            for member, faction in self.members
        )

    def can_investigate(self, character):
        return self.can_enter(character, "archive") and (
            character, "forged_letter"
        ) in self.knowledge

    def can_claim_reward(self, character):
        return self.can_investigate(character) and (
            character, "investigation"
        ) not in self.rewards_claimed
