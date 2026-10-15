@Engine("sqlite");

Candidate(user:, resource:) distinct :-
  Member(user:, role:), RoleAccess(role:, resource:);
Candidate(user:, resource:) distinct :- Sponsored(user:, resource:);

CanAccess(user:, resource:) distinct :-
  Candidate(user:, resource:), ~Revoked(user:, resource:);
