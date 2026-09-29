# Weekly Team Pulse Check – Scope

2026-09-29

## Purpose & audience

The tool gives a project lead a weekly, anonymous read on how the team is doing, using a rating that takes under a minute.

Team members rate a few fixed dimensions once a week. The lead sees only aggregates and their trend over time. The tool is open source and self-hosted only; there is no central instance.

## In scope (v1)

Version 1 covers a fixed weekly rating, a login-free respondent flow, and a trend dashboard for leads.

**Rating input**

- Four fixed dimensions per week: workload/stress, clarity of goals and priorities, collaboration/team atmosphere, progress/confidence in delivery
- Ratings only, no free text; the whole submission takes under one minute

**Respondents**

- Submit via a shared project link, with no login
- One submission per week, enforced by a browser cookie (easy to bypass; accepted for v1)

**Leads**

- Log in with an account and password
- Dashboard lists all of the lead's projects
- Per project: a line chart of the trend over weeks, one line per dimension, aggregates only

**Anonymity**

- The lead never sees individual ratings
- When too few people have responded, results are still shown, with a warning that anonymity is limited
- Respondents see the same warning before they submit

**Data retention**

- Data is kept until the lead deletes the project
- Deleting a project must purge all of its data

## Out of scope (v1)

Everything that needs identity, notifications, or central operation stays out of the first version.

- Reminders (the lead shares the link manually each week)
- Alerts when a dimension drops, and emailed weekly summaries
- Free-text comments
- A central hosted instance (self-host only)
- Single sign-on

## Deployment & access model

Each instance runs as a single Docker container with an embedded SQLite database, so self-hosters need no separate database setup.

- The first user to register becomes the instance admin
- Further lead accounts are created by invitation only
- Respondents never need an account; they use the project's shared link
- Team sizes vary widely, so the tool must handle groups from a handful of people up to larger teams

## Known limitations & risks

The design trades strong guarantees for simplicity, and these trade-offs were accepted knowingly.

- **Duplicate and fake submissions:** the cookie limit is trivial to bypass, and anyone with the link can submit.
- **Anonymity in small teams:** with very few respondents, aggregates can identify individuals. The tool warns instead of hiding results.
- **Anonymity towards the host:** whoever runs an instance has database access, so "anonymous" means anonymous to the lead, not to the host.
- **Indefinite retention:** raw ratings stay until a project is deleted, which is the least privacy-friendly option.
- **Password accounts:** login, reset and hashing must be handled correctly; using an established auth library is safer than building it.
- **Data protection:** each host is responsible for legal obligations (e.g. nDSG/GDPR) on their own instance.

## Open questions

Four details still need a decision before implementation starts.

- [ ] Rating scale: 1 to 5, or something else?
- [ ] Minimum number of responses below which the anonymity warning appears
- [ ] Definition of a "week": calendar week, or rolling seven days from the link being shared?
- [ ] Can lead accounts be deleted, and what happens to their projects?
