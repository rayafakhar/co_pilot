# Pre-refactor baseline

Captured on 2026-07-19 before application code was changed.

The original generator created 20 independent random rows and always deleted all
existing data. A representative run used eight aircraft and produced:

- 8 overlapping adjacent aircraft operations;
- 11 airport-continuity breaks;
- a forced 5/5/5/5 split of `Done`, `In Route`, `30 minutes till take off`, and
  `Scheduled`, regardless of operational feasibility;
- no deterministic seed or route-range, turnaround, maintenance, cancellation,
  diversion, actual-time, or estimated-time handling.

The untouched board returned HTTP 200 with 20 rows. It rendered a browser-derived
clock labelled only `Local Time`, provided no authoritative server timestamp, showed
flight timestamps in the Django `UTC` display timezone without labelling them as UTC,
and used a 60-second full-page meta refresh.

The first attempted verification also found that the host Python environment did not
have Django installed. Verification continued in the repository-ignored `env_tmp`
virtual environment using the dependency declared by the project.
