@Engine("sqlite");

# Time locates people; it does not select a chapter.
Here(person: p, place: l) distinct :-
  Clock(world: "night", tick: t), Presence(person: p, place: l, start: a, stop: b),
  t >= a, t < b;
Here(person: "self", place: l) distinct :-
  Clock(world: "night", tick: t), Place(place: l, start: a, stop: b), t >= a, t < b;

Trust(person: p, score? += w) distinct :- Bond(person: p, reason: reason, weight: w);

MissingKnowledge(scene: s) distinct :- NeedKnowledge(scene: s, clue: k), ~Knows(clue: k);
MissingItem(scene: s) distinct :- NeedItem(scene: s, item: i, holder: h), ~Item(item: i, holder: h);
MissingConsent(scene: s) distinct :- NeedConsent(scene: s, person: p, topic: t), ~Consent(person: p, topic: t);
MissingChoice(scene: s) distinct :- NeedChoice(scene: s, topic: t, value: v), ~Choice(topic: t, value: v);
MissingBond(scene: s) distinct :- NeedBond(scene: s, person: p, minimum: m), Trust(person: p, score: n), n < m;
MissingBond(scene: s) distinct :- NeedBond(scene: s, person: p, minimum: m), ~Trust(person: p);

SceneLocation(scene: s, place: l) distinct :- Scene(scene: s, place: "with_actor", actor: p), Here(person: p, place: l);
SceneLocation(scene: s, place: l) distinct :- Scene(scene: s, place: l, actor: p), l != "with_actor", Here(person: p, place: l);

EligibleScene(scene: s, title: title, place: l, actor: p, priority: priority, cost: cost) distinct :-
  Scene(scene: s, title: title, actor: p, earliest: a, latest: b, priority: priority, cost: cost),
  SceneLocation(scene: s, place: l), Clock(world: "night", tick: t), t >= a, t < b,
  ~Seen(scene: s), ~MissingKnowledge(scene: s), ~MissingItem(scene: s),
  ~MissingConsent(scene: s), ~MissingChoice(scene: s), ~MissingBond(scene: s);

HigherForced(scene: s) distinct :-
  EligibleScene(scene: s, priority: p), EligibleScene(scene: other, priority: q), q >= 100, q > p;
HigherForced(scene: s) distinct :-
  EligibleScene(scene: s, priority: p), EligibleScene(scene: other, priority: p), p >= 100, other < s;
NextForced(scene: s) distinct :- EligibleScene(scene: s, priority: p), p >= 100, ~HigherForced(scene: s);

# At each location the most pressing available subject is offered first.
HigherAtPlace(scene: s) distinct :-
  EligibleScene(scene: s, place: l, priority: p), EligibleScene(scene: other, place: l, priority: q),
  p < 100, q < 100, q > p;
HigherAtPlace(scene: s) distinct :-
  EligibleScene(scene: s, place: l, priority: p), EligibleScene(scene: other, place: l, priority: p),
  p < 100, other < s;
Opportunity(scene: s, title: title, place: l, actor: p, cost: cost) distinct :-
  EligibleScene(scene: s, title: title, place: l, actor: p, priority: p0, cost: cost),
  p0 < 100, ~HigherAtPlace(scene: s);

BroadcastReady(ready: "yes") distinct :-
  Choice(topic: "power", value: "on"), Item(item: "master_tape", holder: "station"),
  Knows(clue: "recording_edited"), Knows(clue: "voice_identity"),
  Consent(person: "cheng", topic: "recording"), Consent(person: "mi", topic: "broadcast");
MissingActionPresence(scene: s, action: a) distinct :-
  ActionNeedsHere(scene: s, action: a, person: p, place: l), ~Here(person: p, place: l);
MissingActionBroadcast(scene: s, action: a) distinct :-
  ActionNeedsBroadcast(scene: s, action: a), ~BroadcastReady(ready: "yes");
MissingActionChoice(scene: s, action: a) distinct :-
  ActionNeedsChoice(scene: s, action: a, topic: t, value: v), ~Choice(topic: t, value: v);
SelectableScene(scene: s) distinct :- Opportunity(scene: s);
SelectableScene(scene: s) distinct :- NextForced(scene: s);
AvailableAction(scene: s, action: a) distinct :-
  Action(scene: s, action: a), SelectableScene(scene: s),
  ~MissingActionPresence(scene: s, action: a), ~MissingActionBroadcast(scene: s, action: a),
  ~MissingActionChoice(scene: s, action: a);
MutualFuture(person: p) distinct :-
  Choice(topic: "partner", value: p), Consent(person: p, topic: "future"), Trust(person: p, score: n), n >= 3;

EligibleEnding(ending: "cheng", priority: 100) distinct :-
  Choice(topic: "final", value: v), v != "undecided", MutualFuture(person: "cheng");
EligibleEnding(ending: "yao", priority: 100) distinct :-
  Choice(topic: "final", value: v), v != "undecided", MutualFuture(person: "yao");
EligibleEnding(ending: "mi", priority: 100) distinct :-
  Choice(topic: "final", value: v), v != "undecided", MutualFuture(person: "mi");
EligibleEnding(ending: "harbor", priority: 50) distinct :-
  Choice(topic: "final", value: "broadcast"), BroadcastReady(ready: "yes");
EligibleEnding(ending: "quiet", priority: 0) distinct :- Choice(topic: "final", value: v), v != "undecided";
HigherEnding(ending: e) distinct :- EligibleEnding(ending: e, priority: p), EligibleEnding(ending: other, priority: q), q > p;
NextEnding(ending: e) distinct :- EligibleEnding(ending: e), ~HigherEnding(ending: e);
