# BDO Gear / Garmoth — MASTER DOCUMENT

> **Source of truth for the Garmoth gear system in Silent Concierge.**
>
> Before changing `cogs/bdogear_cog.py`, read this document first.
> The user-facing behaviour described here must be preserved unless the user explicitly asks to change it.

Last updated: 2026-09-19

---

## 1. Purpose

This system reads Black Desert gear data from public Garmoth character links and connects that data to Discord members.

The complete intended flow is:

```text
Discord member
    ↓
Garmoth character / Gear Planner link
    ↓
BDO Gear parser
    ↓
AP / AAP / DP / GS
    ↓
MongoDB gear store
    ↓
Role panel checks gear
    ↓
"Страждущі" role only if AP >= 336
```

The Garmoth system is also used by mass guild gear collection.

---

## 2. Main files

### Core cog

`cogs/bdogear_cog.py`

Responsibilities today:
- `/gear_update`
- `/collect`
- `/collect_stop`
- `/gear_find`
- `/gear_list`
- parsing Garmoth
- Chromium / Selenium handling
- Discord interaction handling
- mass collection job
- writing gear to MongoDB

This is currently too much responsibility for one file and should be refactored.

### Gear storage

`data/gear_store.py`

Current collection:

`members_gear`

Current schema uses one Mongo document:

```text
_id = "main"
users = {
    "<discord_user_id>": {
        display_name,
        link,
        gs,
        ap,
        aap,
        dp,
        user_id,
        updated,
        updated_at
    }
}
```

Target architecture should use one Mongo document per Discord user.

### Role integration

`cogs/role_panel_post_cog.py`

Important constants:

```python
ROLE_SUFFERING = 1406569206815658077
MIN_SUFFERING_AP = 336
```

The role is **Страждущі**.

The role must only be given when the user's stored AP is:

```text
AP >= 336
```

If AP is 335 or lower, the role must not be given.

### Gear link channel

Guild:

```text
1323454227816906802
```

Gear channel:

```text
1358443998603120824
```

Direct Discord URL:

```text
https://discord.com/channels/1323454227816906802/1358443998603120824
```

---

## 3. Missing gear behaviour

When a member selects **Страждущі** but there is no gear entry for them:

1. Do not give the role.
2. Send the member a DM.
3. Ask them to leave their current public Garmoth Gear Planner / character link in channel `1358443998603120824`.
4. Mention that the minimum is **336+ AP**.
5. If DMs are closed, show the same information in an ephemeral response.

Current wording can be changed cosmetically, but this behaviour must remain.

---

## 4. User-facing commands

### /gear_update

Purpose:

Update one Discord user's gear from a public Garmoth character link.

Input:

```text
https://garmoth.com/character/<id>
```

Expected success result:

```text
AP/AAP: X / Y
DP: Z
GS: N
```

The result must be saved to MongoDB by Discord user ID.

### /collect

Purpose:

Mass-process Garmoth links from the gear channel.

Important desired behaviour:
- read Garmoth links from channel `1358443998603120824`;
- use only the newest relevant link per Discord user;
- process profiles one at a time;
- preserve the old visible progress style;
- save every successful player immediately, not only at the end;
- only one mass collection may run globally at a time.

### /collect_stop

Safely stops the current collection after the current profile finishes.

### /gear_find

Looks up one stored player by Discord display name.

### /gear_list

Shows stored players sorted by GS.

---

## 5. /collect visual appearance — preserve this

The user specifically wants the old display style.

Each processed profile should produce an embed similar to:

```text
✨ Garmoth Profile Updated

Дані гравця <name> оновлено.

⚔️ AP/AAP
336 / 338

🛡️ DP
430

🌟 Gearscore
767

🕒 Час
...

🔗 Посилання
Garmoth

Прогрес: 50 | Очікування: 38с
```

If a profile cannot be read, keep the old-style status:

```text
❌ Не вдалося зчитати (Private?)
```

At the end:

```text
✅ Парсинг завершено! В базі тепер гравців: <count>
```

Do not redesign this output unless explicitly requested.

---

## 6. Historical parser behaviour

### Old working Playwright version

The old working implementation used Playwright and the old selector:

```css
.grid-cols-4 .text-2xl
```

It successfully produced the old `Garmoth Profile Updated` embeds.

It later became unreliable after Garmoth frontend changes.

Observed error:

```text
Execution context was destroyed, most likely because of a navigation
```

### Selenium attempt

The cog was switched to Selenium.

Current parser version marker:

```text
selenium-v2
```

Observed Selenium error:

```text
ReadTimeoutError:
HTTPConnectionPool(host='localhost', port=...):
Read timed out. (read timeout=120)
```

This means the local Selenium → ChromeDriver communication stalled.
It is not a MongoDB error and not necessarily a Garmoth HTTP error.

---

## 7. Render constraints

Render plan currently has a **512 MB memory limit**.

Observed failure:

```text
Ran out of memory (used over 512MB)
```

Baseline bot RSS seen in logs has been around 130–145 MB before browser work.

Therefore:
- do not run several Chromium instances at once;
- do not hold large Garmoth JSON payloads in memory;
- do not keep hundreds of full Discord Message objects unnecessarily;
- block unnecessary browser resources if a browser fallback remains;
- free browser resources after every profile;
- mass collection must be sequential.

---

## 8. Discord interaction problem already observed

Observed error:

```text
404 Not Found
error code 10062
Unknown interaction
```

This happened at:

```python
await interaction.response.defer(...)
```

Important design rule:

**Defer the Discord interaction before MongoDB, browser startup, network work, or any other slow operation.**

Current code contains interaction-claim logic in MongoDB. The final architecture must not perform that DB call before the initial Discord acknowledgement.

For a long-running operation such as `/collect`:
1. immediately acknowledge/defer;
2. start a background task;
3. use a distributed MongoDB job lock after acknowledgement;
4. post progress to the channel from the background task.

---

## 9. Current interaction duplication protection

The bot has experienced overlapping Render instances during deploys.

That caused:
- duplicate welcome embeds;
- duplicate member-leave embeds;
- potentially duplicate command handling.

For gear commands there is a MongoDB interaction claim collection:

```text
gear_interaction_claims
```

This idea is valid, but the claim must happen **after immediate defer/acknowledgement**.

For `/collect`, use a separate global job lock rather than relying only on an interaction ID.

Suggested collection:

```text
gear_jobs
```

Suggested key:

```text
_id = "mass_collect"
```

The lock should include:
- owner Discord ID;
- started_at;
- heartbeat / updated_at;
- instance identifier;
- expiration / stale-lock recovery.

---

## 10. Problems in the current cog

The current `bdogear_cog.py` has accumulated too many responsibilities.

Known technical problems:

1. Selenium, Playwright installation logic and webdriver-manager are mixed.
2. Browser management and parsing are inside the Discord cog.
3. `/collect` is implemented as a long slash-command execution instead of a background job.
4. Current Mongo gear storage replaces the whole `users` dictionary.
5. One failed process can lose unsaved mass-collection progress.
6. `last_scrape_error` is shared mutable cog state.
7. Browser use can exceed Render's 512 MB limit.
8. Garmoth SPA navigation makes DOM scraping brittle.
9. Browser startup is expensive for every profile.
10. Interaction acknowledgement happens too late in some flows.
11. Old Playwright helper code remains even when Selenium is the current parser.
12. Runtime browser installation makes deployments and memory behaviour harder to predict.
13. `.render.yaml` needs cleanup and verification against the actual Python version used by the live service.

---

## 11. Target architecture

The preferred architecture is:

```text
cogs/bdogear_cog.py
    │
    ├── Discord commands only
    ├── embeds / visible responses
    └── starts jobs
          │
          ▼
services/garmoth_client.py
    │
    ├── HTTP/API parser first
    └── browser fallback only if absolutely necessary
          │
          ▼
data/gear_store.py
    │
    └── one Mongo document per Discord user
          │
          ▼
services/gear_collect_service.py
    │
    ├── background sequential collection
    ├── global Mongo lock
    ├── immediate save per successful profile
    └── old-style progress embeds
```

---

## 12. Preferred Garmoth strategy

The normal path should eventually be:

```text
Garmoth shared character URL
    ↓
determine actual Garmoth JSON/API request
    ↓
aiohttp request
    ↓
parse AP/AAP/DP/GS
```

Browser automation should be a fallback, not the default path.

Reasons:
- lower RAM;
- faster;
- no ChromeDriver localhost timeout;
- no DOM SPA navigation errors;
- better for mass collection on a 512 MB Render instance.

Do not guess undocumented endpoint URLs and hard-code them without first observing a real Garmoth character request.

---

## 13. Target MongoDB gear schema

Recommended future storage:

Collection:

```text
members_gear
```

One document per Discord member:

```json
{
  "_id": 123456789012345678,
  "display_name": "Player",
  "link": "https://garmoth.com/character/...",
  "ap": 336,
  "aap": 338,
  "dp": 430,
  "gs": 767,
  "updated_at": "...",
  "source": "garmoth"
}
```

Use:

```python
update_one(
    {"_id": user_id},
    {"$set": entry},
    upsert=True
)
```

Do not replace all players to update one user.

During migration, old `_id="main"` data must be preserved and migrated safely before removing compatibility.

---

## 14. AP rule

For the **Страждущі** role the rule is specifically:

```text
MAIN AP >= 336
```

Use stored field:

```text
ap
```

Do not substitute:
- AAP;
- average AP/AAP;
- GS;
- DP.

---

## 15. Automatic future workflow

Desired final workflow:

```text
Member selects Страждущі
        │
        ├── gear exists and AP >= 336
        │       └── give role
        │
        ├── gear exists and AP < 336
        │       └── deny role and explain current AP
        │
        └── no gear
                └── DM member with gear channel URL

Member posts Garmoth link in gear channel
        ↓
bot detects link
        ↓
bot parses it
        ↓
bot stores AP/AAP/DP/GS
        ↓
if AP >= 336 and user requested Страждущі
        ↓
role can be granted automatically
```

The automatic listener for newly posted Garmoth links is a desired feature but should only be added after the parser/storage layer is stable.

---

## 16. Required refactor order

Do work in this order.

### Phase 1 — Stabilise command flow

1. Move Discord `defer()` to the first meaningful action in `/gear_update` and `/collect`.
2. Perform Mongo interaction/job claims only after acknowledgement.
3. Make parser results local objects, not shared `last_scrape_error` state.

### Phase 2 — Fix storage

1. Add atomic per-user gear functions.
2. Preserve backward compatibility with current `main.users` document.
3. Migrate safely.
4. Save every successful `/collect` result immediately.

### Phase 3 — Separate parser

Create:

```text
services/garmoth_client.py
```

The cog should call something conceptually like:

```python
result = await garmoth_client.get_stats(url)
```

Result should contain:

```text
ok
stats
error
source
diagnostics
```

### Phase 4 — Discover stable Garmoth data source

Use one known public character URL and inspect network requests.

Find which request actually returns the shared build data.

Then implement direct HTTP first.

### Phase 5 — Rebuild mass collect as a job

1. Slash command acknowledges quickly.
2. Acquire global Mongo lock.
3. Start background task.
4. Process users sequentially.
5. Save each result immediately.
6. Preserve old embed appearance.
7. Release lock in `finally`.
8. Support `/collect_stop`.

### Phase 6 — Role automation

Once parser + storage are stable:
- watch the gear channel for new Garmoth links;
- parse automatically;
- update Mongo;
- evaluate 336 AP;
- optionally grant Страждущі automatically when appropriate.

---

## 17. Testing checklist

Do not run full `/collect` first.

### Test A — one profile

Run:

```text
/gear_update
```

Expected:
- immediate Discord acknowledgement;
- no 10062;
- parser runs;
- AP/AAP/DP/GS returned;
- Mongo updated;
- RAM remains well below 512 MB.

### Test B — storage

Run:

```text
/gear_find
```

Confirm the values match Test A.

### Test C — role

With AP < 336:
- Страждущі not granted.

With AP >= 336:
- Страждущі granted.

With no gear:
- role not granted;
- DM sent with gear-channel URL.

### Test D — small mass collect

Test 2–3 profiles before a full run.

Confirm:
- one embed per profile;
- progress display is old style;
- data is saved after each profile;
- memory does not continuously grow.

### Test E — full collect

Only after A–D pass.

---

## 18. Things that must not be accidentally changed

Unless explicitly requested:

- do not change `ROLE_SUFFERING` ID;
- do not change minimum AP from **336**;
- do not change the gear channel ID;
- do not change the guild ID;
- do not redesign old `/collect` embeds;
- do not remove MongoDB storage;
- do not use AAP/GS instead of main AP for the role check;
- do not turn missing gear into automatic role approval;
- do not run multiple browsers concurrently on Render.

---

## 19. Current important IDs

```text
Guild / Silent Cove:
1323454227816906802

Gear channel:
1358443998603120824

Страждущі role:
1406569206815658077

Minimum main AP:
336
```

---

## 20. Rule for future changes

Before modifying this system:

1. Read this file.
2. Read `cogs/bdogear_cog.py`.
3. Read `data/gear_store.py`.
4. If role behaviour is involved, read `cogs/role_panel_post_cog.py`.
5. Preserve the user-facing contract above.
6. Change one subsystem at a time.
7. Test one profile before mass collection.
