@Engine("sqlite");

# Permissions can come from membership or a personal sponsor.
CanEnter(character: c, location: l) distinct :-
  Member(character: c, faction: f),
  FactionAccess(faction: f, location: l);
CanEnter(character: c, location: l) distinct :-
  Sponsor(character: c, location: l);

# Knowledge and access combine; neither alone is enough.
CanInvestigate(character: c) distinct :-
  CanEnter(character: c, location: "archive"),
  Knows(character: c, secret: "forged_letter");

# Eligibility is a query. The script records the actual grant as a fact.
CanClaimReward(character: c, reward: "investigation") distinct :-
  CanInvestigate(character: c),
  ~RewardClaimed(character: c, reward: "investigation");
