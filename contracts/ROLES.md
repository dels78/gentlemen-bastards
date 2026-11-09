# Loop bot roles — index

| Role | Purpose | Model tier | Hard prohibitions |
| --- | --- | --- | --- |
| scout | Sense email and Linear into a snapshot | cheap | Writes nothing outside artifacts; decides nothing |
| planner | Turn a snapshot into a plan and questions | strong | Holds no external tools except brain read; writes nothing |
| writer | Apply approved plans to Gmail and Linear; verify by read-back | cheap | Acts only from a plan; fetches nothing beyond plan-scoped read-back |
| herald | Digest outcomes for the human; fold in sweeps | cheap | Only external write is the approved digest channel; invents nothing |
| librarian | Tend the brain and the backlog; triage brain-proposals and mined updates | strong | Never edits the brain directly; only develops proposals into questions |
| coordinator | Scheduling nudges, retries, stuck detection, exceptions | cheap | Relays no routine traffic; only bot that escalates to Muse |

This file is an **index**, not a second source of role truth. Full definitions live in this repo under `bots/<role>/` (`profile.json` + `INSTRUCTIONS.md`). The generator renders those definitions together with `contracts/BEHAVIOR.md`.
