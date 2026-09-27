---
story_id: "11-4"
story_key: "11-4-documentation-i18n-market-submission"
epic_id: "epic-11"
epic_name: "End-to-End Testing & Market Preparation"
status: "ready-for-dev"
created: "2026-09-27"
analysis_completed: "2026-09-27"
---

# Story 11.4: Documentation, i18n & Market Submission

Status: done

## Story

As a plugin maintainer,
I want complete documentation and market readiness,
so that the plugin can be published and supported.

## Acceptance Criteria

1. **Given** all code complete and tested, **When** preparing for release, **Then** documentation includes a **User guide** (French): setup wizard, troubleshooting, understanding status indicators.
2. **And** an **Admin guide**: configuration, backup/restore, upgrade path.
3. **And** a **Developer guide**: code overview, API contracts, extending with new CSR presets.
4. **And** an i18n structure: all French user strings in `messages.py` (v1.0), gettext migration path documented (`# TODO v1.1: gettext`), English debug strings inline in code.
5. **And** `core/i18n/fr_FR.json` exists and is populated with the PHP-side French keys (currently **missing** — verified absent from `core/i18n/`, see Dev Notes).
6. **And** Jeedom Market submission readiness: `info.json` complete (name, description, version, icon, dependencies, min_version — verify exact required keys via `/jeedom-plugin` skill before editing, do not guess the schema).
7. **And** `packages.json` lists all Python dependencies with pinned versions (currently `jeedomdaemon` has no version pin — see Dev Notes).
8. **And** `plugin_info/*_icon.png` is the plugin's own icon (80×80 px), not the leftover `aiodemo_icon.png` template asset.
9. **And** Changelog documented (fr_FR and en_US) — no `CHANGELOG.md` exists yet in the repo root or `docs/`.
10. **And** `README.md` is rewritten from the leftover `aiodemo` plugin template (currently describes a *different, unrelated demo plugin*) into real, well-structured documentation for this project — see Dev Notes for the reference style Herve asked to follow.
11. **And** plugin submission to Jeedom Market official process is followed (manual/process step — flag as a checklist for Herve, not something the dev agent executes).
12. **And** release notes (French + English) are published on GitHub (manual/process step — flag as a checklist for Herve, not something the dev agent executes).

## Tasks / Subtasks

- [x] Task 1: Rewrite `README.md` (AC: 10)
  - [x] 1.1 Replace the current content verbatim-checked against `README.md` — it is the unrelated `aiodemo` template plugin's readme ("aiodemo plugin pour Jeedom... this small plugin aims to demo the usage of a python daemon using asyncio"), not this project's documentation. Delete it entirely, do not patch around it.
  - [x] 1.2 Follow the structure Herve pointed to as a good example: `/Users/herve.lehoux/dev-hlx/MyHargassner/README.md` — title + one-line tagline, **Features**, **Quick Links** (to guides produced in Tasks 2-4 and the changelog from Task 6), **Known Limitations**, **Disclaimer** (adapt tone — this is a protocol-compliance security plugin, not a hobby disclaimer, unless Herve wants to keep it informal), **Installation** (Jeedom Market install steps, not `git clone`/`pip install` — this is a Jeedom plugin, installed via Market or manual symlink per story 12-1, not a standalone service), **Configuration** (wizard steps 0-4, key `sia_*` config keys), **Architecture** (short overview + link to `internal-docs/design/*.md` for depth, mirroring how MyHargassner links out to `docs/TECHNICAL_ARCHITECTURE.md` instead of inlining everything).
  - [x] 1.3 Do NOT copy MyHargassner's installation steps (`git clone --recurse-submodules`, `pip install .`, systemd service) — this project installs as a Jeedom plugin via the Market/plugin manager, a fundamentally different distribution model. Take the *documentation structure and tone*, not the content.
  - [x] 1.4 Cross-link to the SIA DC-09 protocol spec (`internal-docs/SIA-DC-09-Internet-Protocol-Event-Reporting-2021.md`) and to the new guides from Tasks 2-4.
  - [x] 1.5 Credit the `aiodemo` plugin (mips2648) as the scaffolding template this project was built from, if accurate — verify with Herve if uncertain rather than guessing attribution.

- [x] Task 2: User guide, French (AC: 1)
  - [x] 2.1 Create `docs/guide-utilisateur.md` (or `docs/user-guide-fr.md` — match whatever naming convention Herve prefers; check if one already exists before creating)
  - [x] 2.2 Cover: setup wizard walkthrough (steps 0-3 CSR preset selection + zone mapping, step 4 config mode) — source from `internal-docs/design/wizard-design.md`
  - [x] 2.3 Cover: troubleshooting — common failure modes surfaced by the error handler (T1/T2/T3 notifications) and the Debug UI panel — source from `internal-docs/design/error-handler-design.md` and `internal-docs/design/debug-ui-design.md`
  - [x] 2.4 Cover: understanding status indicators — widget badge states, supervision states — source from `internal-docs/design/widget-design.md` and `internal-docs/design/supervision-design.md`
  - [x] 2.5 Written entirely in French (this is the *user-facing* guide — do not mix English)

- [x] Task 3: Admin guide (AC: 2)
  - [x] 3.1 Create `docs/guide-admin.md` (English is fine here — this repo's other design docs are English; confirm language choice matches Herve's expectation, French is also acceptable given the plugin's French-only UI — ask if unclear rather than guessing)
  - [x] 3.2 Cover: configuration (all `sia_*` config keys — enumerate from `internal-docs/design/php-core-design.md`'s Config Key Registry, ~10 keys)
  - [x] 3.3 Cover: backup/restore (standard Jeedom eqLogic export/import — verify against `/jeedom-plugin` skill, do not invent Jeedom mechanics)
  - [x] 3.4 Cover: upgrade path (Market update flow, `DAEMON_VERSION` constant discipline per `architecture.md` line ~810-812 — must be bumped alongside `info.json` before every Market publish)

- [x] Task 4: Developer guide (AC: 3)
  - [x] 4.1 Create `docs/guide-developpeur.md` or `docs/developer-guide.md`
  - [x] 4.2 Code overview: point to the existing `internal-docs/design/*.md` set rather than duplicating it — this guide is the map, not the territory
  - [x] 4.3 API contracts: the 5 IPC callback types (daemon ↔ PHP), source from `internal-docs/design/daemon-design.md` and `internal-docs/design/php-core-design.md`
  - [x] 4.4 Extending with new CSR presets: `CSRPreset` dataclass + `presets.json` / `resources/siadc09d/presets/*.json` pattern — source from `resources/siadc09d/presets.py` and the existing `ima_protect.json` preset as the worked example

- [ ] Task 5: i18n structure completion (AC: 4, 5)
  - [x] 5.1 Verify `resources/siadc09d/messages.py` header already carries `# TODO v1.1: gettext` (check before assuming missing)
  - [ ] 5.2 Confirm zero French strings exist outside `messages.py` (Python side) — grep for French text in daemon modules — **NOT confirmed (left open deliberately)**: the grep found user-facing French in `error_handler.py`, `daemon.py`, `siadc09d.py`, `sia_transport.py` (+ PHP/JS hard-coded French). Inventory documented in `docs/developer-guide.md#internationalisation`, migration deferred as D-82. AC4 is therefore partial.
  - [x] 5.3 Create the **missing** `core/i18n/fr_FR.json` — currently `core/i18n/` only has `de_DE.json`, `en_US.json`, `es_ES.json`, `it_IT.json`, `pt_PT.json`, no French file, despite `info.json` declaring `fr_FR` as a supported language and `architecture.md` listing `fr_FR.json` first in the i18n structure. Populate keys by extracting every `__('key', __FILE__)` call across `core/*.php` and `desktop/*.php` (the PHP i18n roundtrip test referenced in `architecture.md` line ~1560 expects this)
  - [x] 5.4 Run/create the i18n roundtrip check (`test_i18n_roundtrip.py` per architecture.md's testing structure — verify if it already exists under `tests/` before writing a new one) confirming all `__()` keys have entries in `fr_FR.json`

- [x] Task 6: Changelog (AC: 9)
  - [x] 6.1 Create `CHANGELOG.md` at repo root (or `docs/CHANGELOG.md` — match MyHargassner's `docs/CHANGELOG.md` location if Herve prefers consistency across his projects)
  - [x] 6.2 Populate fr_FR and en_US sections — derive version history from git log / closed epics (epics 1-10, 12, 13, 14 are `done`) rather than inventing dates; this is a retroactive first changelog, not a running log kept since day one
  - [x] 6.3 Wire `plugin_info/info.json`'s existing `"changelog": "https://hlehoux2021.github.io/my-project/#language#/changelog"` URL to actually resolve once published — flag if this requires a GitHub Pages / docs-site step outside this story's scope

- [x] Task 7: Market submission file completeness (AC: 6, 7, 8)
  - [x] 7.1 **Before editing `info.json`**, invoke `/jeedom-plugin` to get the authoritative required-keys list — do not assume the AC's parenthetical list (name/description/version/icon/dependencies/min_version) is the exact schema; verify against real Jeedom core/Market requirements
  - [x] 7.2 Current `plugin_info/info.json` has `id`, `name`, `description.fr_FR`, `licence`, `author`, `require`, `category`, `changelog`, `documentation`, `hasDependency`, `hasOwnDeamon`, `maxDependancyInstallTime`, `os.min`, `language`, `compatibility` — **no explicit `version` field is present**. Confirm with the skill whether Jeedom Market versioning is read from `info.json` or from git tags/Market metadata before adding one speculatively.
  - [x] 7.3 `plugin_info/packages.json` currently pins `cryptography` to `43.0.3` but leaves `jeedomdaemon` unpinned (`{"reinstall": true}`) — decide whether to pin it for Market submission reproducibility (check if `jeedomdaemon`'s own release history makes this safe)
  - [x] 7.4 `plugin_info/aiodemo_icon.png` is the leftover template icon — replace with a real plugin icon named per the convention `architecture.md` specifies (`siadc09_icon.png`), sized 80×80 px. Icon design is outside this story's code scope — flag as needing an actual image asset from Herve if none exists yet.

- [x] Task 8: Manual/process steps — flag, do not silently skip (AC: 11, 12)
  - [x] 8.1 Document the Jeedom Market submission process steps as a checklist in `docs/` (what to submit, where, review turnaround) — this itself is documentation, in scope; *executing* the actual submission is not something the dev agent can do and must be called out explicitly as Herve's action
  - [x] 8.2 Draft release notes (FR+EN) as markdown ready to paste into a GitHub release — publishing the GitHub release itself is a manual action for Herve, not something to fake as "done"

- [x] Task 9: Regression check (AC: all)
  - [x] 9.1 Run `python3 -m pytest tests/level1/` — compare against the known baseline (level1: 2 pre-existing failures — do not treat those as regressions introduced by this story)
  - [x] 9.2 Run `find core/ desktop/ -name "*.php" | xargs -n1 php -l` — all pass
  - [x] 9.3 If Task 5.4's i18n roundtrip test is new, confirm it passes cleanly against the newly-created `fr_FR.json`

## Dev Notes

### This story is documentation-heavy, not code-heavy

Most of epic 11-4's AC produce markdown files, one JSON i18n file, and process checklists — not daemon or PHP logic changes. Resist the urge to over-engineer; a doc that's clear and accurate beats one that's exhaustive. Per project convention: no half-finished docs, but also no scope creep into re-documenting what `internal-docs/design/*.md` already covers well — link to it instead of duplicating it.

### README.md — current state is a leftover template, not a draft

`README.md` at the repo root right now is **not** this project's documentation — it's the unmodified readme for `aiodemo`, the unrelated demo plugin this project's plugin skeleton was scaffolded from (mentions `jeedom-aiodemo`, `mips2648`, ping/pong demo commands — none of which exist in this codebase). Treat Task 1 as a full rewrite, not an edit.

**Reference style** (per Herve's explicit request): `/Users/herve.lehoux/dev-hlx/MyHargassner/README.md` — a different Herve project (Hargassner boiler ↔ MQTT gateway). Good things to take from it:
- Title + blockquote tagline, then a scannable **Features** bullet list
- A **Quick Links** section linking out to changelog/network-setup/architecture docs instead of inlining them
- **Known Limitations** stated plainly (e.g. "only tested on firmware Vx" — this project's equivalent might be "encryption is id_token-marker only in v1.0, not full AES payload encryption" per the SM3 story's Bug 7 finding, or similar honestly-scoped limitations)
- **Installation** as numbered steps with prerequisites split into Hardware/Software/Dependencies
- A short **Architecture** section that names the main components and links to a deeper doc, rather than inlining the full design

**Do not copy mechanically** — MyHargassner is a standalone Python service installed via `git clone` + `pip install` + optional systemd unit. This project is a Jeedom plugin installed via the Jeedom Market or a dev symlink (story 12-1's `ln -s /mnt/hgfs ... /plugins/siaDC09` pattern) — the Installation and Configuration sections must reflect *this* project's actual install/config story, not MyHargassner's.

### i18n gap — `fr_FR.json` is genuinely missing

Verified by directly listing `core/i18n/`: `de_DE.json`, `en_US.json`, `es_ES.json`, `it_IT.json`, `pt_PT.json` exist; `fr_FR.json` does not. `architecture.md`'s Complete Directory Structure section lists `fr_FR.json` first (`# French (from messages.py)`), and `info.json` declares `"language": ["fr_FR", "en_US", "de_DE"]`. This is a real, pre-existing gap this story should close — not a documentation nice-to-have.

### Market file gaps — verified, not assumed

- `plugin_info/info.json`: no `version` key present today. Do not add one on assumption — Jeedom plugin versioning conventions vary (info.json field vs. git tag vs. Market-side metadata); confirm via `/jeedom-plugin` skill first.
- `plugin_info/packages.json`: `jeedomdaemon` has no version pin (`{"reinstall": true}` only); `cryptography` is pinned to `43.0.3`.
- `plugin_info/aiodemo_icon.png`: still the template icon, not renamed or replaced. `architecture.md`'s adaptation table explicitly calls for `plugin_info/siadc09_icon.png`.

None of these are icon-design or Market-process work this dev agent can complete alone — flag clearly in Completion Notes rather than marking the story done with these silently unresolved.

### Previous story intelligence (11-3)

11-3 (full workflow integration testing, status: review) is Level 3 test work with no documentation deliverables — limited direct carryover. The one relevant pattern: 11-3's Dev Notes repeatedly cite exact source line ranges in `architecture.md` (e.g. `#L366-443`) — follow that citation discipline in the new guides so future readers can verify claims against the source doc.

### Language choice for Admin/Developer guides

The epics.md AC doesn't specify a language for the Admin guide or Developer guide (unlike the User guide, explicitly French). This codebase's design docs (`internal-docs/design/*.md`) are all English; the UI/wizard is French-only (`messages.py`). Default assumption: Admin + Developer guides in English (matches design-doc precedent), User guide in French (matches UI/end-user audience and the AC's explicit call-out). Confirm with Herve if this split feels wrong before writing 3 guides in the wrong language.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#L1705-1735] — Story 11.4 acceptance criteria (verbatim source)
- [Source: _bmad-output/planning-artifacts/architecture.md#L287-292] — i18n decision (messages.py, gettext TODO)
- [Source: _bmad-output/planning-artifacts/architecture.md#L810-812] — DAEMON_VERSION / info.json versioning discipline
- [Source: _bmad-output/planning-artifacts/architecture.md#L1600-1660] — Complete Directory Structure (fr_FR.json, siadc09_icon.png expected paths)
- [Source: _bmad-output/planning-artifacts/architecture.md#L1560, #L1705] — i18n roundtrip test expectation
- [Source: core/i18n/] — verified directory listing (fr_FR.json absent)
- [Source: plugin_info/info.json, plugin_info/packages.json] — verified current content (no version key, jeedomdaemon unpinned)
- [Source: README.md] — verified current content is the unrelated aiodemo template
- [Source: /Users/herve.lehoux/dev-hlx/MyHargassner/README.md] — style reference requested by Herve
- [Source: _bmad-output/implementation-artifacts/11-3-full-workflow-integration-testing.md] — previous story in epic, citation-discipline pattern

## Dev Agent Record

### Agent Model Used

eu.anthropic.claude-opus-5-5 (Claude Code, dev-story run autonomously at Herve's request — no questions asked; every judgment call is listed below)

### Debug Log References

- Regression (9.1): `python3 -m pytest tests/level1/` → 1299 passed, 2 failed (`test_connection_test.py::test_run_connection_test_preset_crc_format_used`, `test_wizard_config_key_consistency.py::test_csr_provider_key_in_python`) = the known baseline, no new failure.
- Also run: `python3 -m pytest tests/level2/` → 358 passed, 6 failed = the known baseline (5 × `test_connection_test_async.py`, 1 × `test_supervision_loop_integration.py`).
- 9.2: `find core/ desktop/ -name "*.php" | xargs -n1 php -l` → no syntax error.
- 9.3: `tests/level1/test_i18n_roundtrip.py` (new, 15 tests) passes; `test_daemon_version.py` + `tests/level2/test_daemon_version_log.py` (new) pass.
- pylint on `daemon.py`: the new version import was first written inside `on_start()` (C0415); moved to the top-level import block. The remaining 5 C0415 hits in `daemon.py` predate this story.

### Completion Notes List

- **AC10 README**: the aiodemo readme was replaced entirely. It follows the MyHargassner structure (tagline, Features, Quick Links, Known Limitations, Disclaimer, Installation via Market / dev symlink, Configuration, Architecture linking to `internal-docs/design/*.md`, Credits, License). The aiodemo/jeedomdaemon credit (1.5) was checked against the public repos `github.com/mips2648/jeedom-aiodemo` and `github.com/Mips2648/jeedom-daemon-py`, not asked.
- **AC1-3 guides — naming choices (the story left them open)**:
  - User guide: `docs/fr_FR/index.md`, not `docs/guide-utilisateur.md`, because that is the page the `info.json` `documentation` URL (`#language#/`) resolves to on GitHub Pages.
  - `docs/en_US/index.md` is a short English entry page that points to it.
  - Admin and developer guides are in English, like the other design docs: `docs/admin-guide.md` and `docs/developer-guide.md`.
- **AC9 changelog**: in `docs/fr_FR/changelog.md` + `docs/en_US/changelog.md` (the Jeedom convention the `changelog` URL points to), not a root `CHANGELOG.md`. It has a single retroactive "1.0.0 — not yet published" entry with no invented dates.
- **info.json URLs (6.3)**: the URLs pointed to `hlehoux2021.github.io/my-project/...`, but the git remote is `github.com/hlehoux2021/siadc09`. They now point to `https://hlehoux2021.github.io/siadc09/#language#/...`. They only resolve once Herve enables GitHub Pages from `/docs` (manual step, in the checklist).
- **AC6 info.json**: the version key was confirmed via `/jeedom-plugin` as `pluginVersion` (not `version`); set to `1.0.0`. The Market-required `changelog_beta` and `documentation_beta` keys were added. `DAEMON_VERSION = "1.0.0"` was added in `resources/siadc09d/__init__.py`, logged at daemon start (`Démon SIA DC-09 version …`), and kept equal to `pluginVersion` by `test_daemon_version.py`.
- **AC7 packages.json**: `jeedomdaemon` pinned to `1.2.9` (`reinstall: true` kept); `cryptography` was already pinned.
- **AC8 icon — deviation**: the Jeedom Market icon spec is **309 × 348 px** named after the plugin ID, so the file is `plugin_info/siaDC09_icon.png` (not the story's `siadc09_icon.png` 80 × 80). It is a **generated placeholder** (shield + signal arcs); the final design is a 👤 item for Herve. `aiodemo_icon.png` was removed.
- **AC4 — partial**:
  - `messages.py` carries the `TODO v1.1: gettext` note, and the gettext migration path is documented in the developer guide.
  - 5.2 failed, though: French user strings also live outside `messages.py`. Task 5 and 5.2 are left unchecked; the fix is D-82.
- **AC5**: `core/i18n/fr_FR.json` was created. It maps every `__()` and `{{…}}` key of the plugin's own files to itself, and the new round-trip test keeps it complete.
- **AC11 / AC12 — manual, not executed**:
  - `internal-docs/market-submission-checklist.md` lists every step. Items marked 👤 are Herve's: Market dev account, GitHub token, add the plugin, beta/stable branch mapping, listing, review, GitHub Pages, icon design, forum link, publishing the GitHub release.
  - A `docs/release-notes-1.0.0.md` draft was written, then **removed at Herve's request**: the project is at the early-tester stage and must not announce a 1.0.0 release. AC12's release notes are therefore not delivered; they will be written once a first release is decided (checklist § 4). **Nothing was submitted or published.**
- **Findings made while writing the docs** (not fixed here, logged as deferred):
  - **D-81 — AES encryption is not implemented on the send path.** `encryption=True` only adds the `*` to the ID token, and alarm frames are always sent in plain text. This is now the first "Known limitation" in every document. The key is also stored in plain text and passed on the command line.
  - **D-83 — aiodemo code leftovers** (PHP/JS/daemon/i18n/pre_install) still ship with the plugin. They block a Market submission and are listed in the checklist.
  - **IMA preset**: its IP is locked at `TBD`, which validation rejects. The user guide tells the user to click **Personnaliser** and enter the address given by their monitoring centre.
- Public docs carry no IP address, account number or credential. The Frigate media URL is described with placeholders only.

### File List

- README.md (rewritten)
- docs/fr_FR/index.md (new)
- docs/fr_FR/frigate.md (new — Frigate advice: exposure, recordings, tracked objects/labels)
- docs/fr_FR/images/alarme-{declenchement,desactivation,reinitialisation,activation}.png (new — Alarm-plugin wiring screenshots, taken by Herve)
- docs/fr_FR/changelog.md (new)
- docs/en_US/index.md (new)
- docs/en_US/changelog.md (created, then removed — single French changelog per Herve)
- internal-docs/ (moved from docs/: design/, SIA-DC-09 spec + page images, SIA codes PDF, experimentation.md, logging-developer-guide.md, simulator-tools.md) + path references updated repo-wide (CLAUDE.md, .claude/skills/sia-dc09-expert, resources/siadc09d/*, tests/*, _bmad-output/*)
- docs/admin-guide.md (new)
- docs/developer-guide.md (new)
- internal-docs/market-submission-checklist.md (new)
- docs/release-notes-1.0.0.md (created, then removed — no 1.0.0 release communication, per Herve)
- core/i18n/fr_FR.json (new)
- plugin_info/info.json (modified)
- plugin_info/packages.json (modified)
- plugin_info/siaDC09_icon.png (new — placeholder)
- plugin_info/aiodemo_icon.png (deleted)
- resources/siadc09d/__init__.py (modified — DAEMON_VERSION)
- resources/siadc09d/daemon.py (modified — version log line in on_start)
- resources/siadc09d/messages.py (modified — DAEMON_VERSION_INFO)
- tests/level1/test_i18n_roundtrip.py (new)
- tests/level1/test_daemon_version.py (new)
- tests/level1/test_info_json.py (modified)
- tests/level1/test_packages_json.py (modified)
- tests/level2/test_daemon_version_log.py (new)
- _bmad-output/implementation-artifacts/deferred-work.md (modified — D-81, D-82, D-83, D-84)
- _bmad-output/implementation-artifacts/sprint-status.yaml (modified)

### Review Findings

- [x] [Review][Decision] AC8 icon size 309×348 — Herve's call 2026-09-27: keep 309×348 as-is. It's a placeholder icon anyway; the exact-match test can be revisited once the real icon is designed.
- [x] [Review][Patch] i18n extractor regex missing word boundary before `__(` [tests/level1/test_i18n_roundtrip.py]
- [x] [Review][Patch] `test_fr_fr_has_no_orphan_keys` could crash with a raw `FileNotFoundError` on a malformed section instead of a clean assertion [tests/level1/test_i18n_roundtrip.py]
- [x] [Review][Patch] `_unescape_double` didn't handle `\n`/`\t`/`\r`/`\v`/`\f`/`\e` PHP escapes, so a future `__("a\nb", __FILE__)` call would silently extract the wrong key [tests/level1/test_i18n_roundtrip.py]
- [x] [Review][Patch] "Logged once by on_start()" comment is inaccurate — `on_start()` is idempotent and re-runs on every daemon restart [resources/siadc09d/messages.py:35]
- [x] [Review][Defer] `DAEMON_VERSION` duplicates `info.json`'s `pluginVersion`; kept in sync only by a test, not at runtime/import [resources/siadc09d/__init__.py] — deferred, pre-existing
- [x] [Review][Defer] Version log line isn't validated against a semver shape at runtime — a hand-edited malformed `DAEMON_VERSION` would still log and ship [resources/siadc09d/daemon.py:2314] — deferred, pre-existing
- [x] [Review][Defer] `SOURCE_FILES` in the i18n round-trip test is a hand-maintained whitelist with no reverse check for new PHP/JS files carrying `__()`/`{{}}` calls [tests/level1/test_i18n_roundtrip.py] — deferred, pre-existing
- [x] [Review][Defer] `description.fr_FR` sits exactly at the 80-char Market-minimum boundary tested by `>= 80`, zero margin [plugin_info/info.json; tests/level1/test_info_json.py] — deferred, pre-existing
- [x] [Review][Defer] Duplicate keys in `fr_FR.json` would be silently dropped by `json.loads`, invisible to all round-trip tests [core/i18n/fr_FR.json; tests/level1/test_i18n_roundtrip.py] — deferred, pre-existing
- [x] [Review][Defer] `changelog_beta`/`documentation_beta` are byte-identical to the stable keys — harmless while there's no beta channel content yet [plugin_info/info.json] — deferred, pre-existing

## Change Log

| Date | Change |
|------|--------|
| 2026-09-27 | Story created |
| 2026-09-27 | dev-story: README, FR user guide, admin and developer guides, FR/EN changelogs, fr_FR.json + round-trip test, info.json/packages.json Market fixes, DAEMON_VERSION, placeholder icon, Market checklist, release notes draft. AC4 partial (5.2 open → D-82). D-81 (encryption not implemented) and D-83 (aiodemo leftovers) logged. Status → review. |
| 2026-09-27 | Herve's decisions applied (status stays review):<br>• Single French changelog: `docs/en_US/changelog.md` removed; both `info.json` changelog URLs now point to `fr_FR/changelog`; test split accordingly.<br>• Frigate plugin authors (Sagitaz, Noodom) credited.<br>• Market install marked "future / not available yet", with manual GitHub install as the current path.<br>• All IMA Protect references removed from the public docs (the code still carries the preset).<br>• Internal docs moved from `docs/` to `internal-docs/`, so the Pages-published `docs/` holds only public docs. |
| 2026-09-27 | Herve: the docs are for **early testers**; no 1.0.0 release is to be announced.<br>• Changelog entry retitled "Version de test — premiers testeurs (non publiée)".<br>• "in 1.0" wording removed from README and the user, admin and EN guides.<br>• Early-tester status banner added to README and the user guide.<br>• `docs/release-notes-1.0.0.md` deleted; checklist § 4 made version-neutral and marked "not now".<br>• `pluginVersion` / `DAEMON_VERSION` set to `0.1.0` (Herve, same day). |
| 2026-09-27 | Herve's review, round 3.<br>• Wiring table recommends the **global** "Déclenchement" tab actions. Verified in `plugin-alarm/core/class/alarm.class.php:583,605`: `outbreak`/`outbreakImmediate` receive `#zone#`.<br>• New `docs/fr_FR/frigate.md`: exposure, recordings, tracked objects/labels, timings, checks.<br>• "for support" wording removed from the user and admin guides; Herve does not commit to support.<br>• IMA code remnants tracked as D-84 (to do).<br>• Alarm-plugin wiring screenshots (4, by Herve) added to the user guide "Exemples de câblage"; the step-3 wizard screenshot was dropped (not Alarm-related). |
| 2026-09-27 | Code review (scoped to code+tests, commit `add27af`; docs/README/changelog content out of scope): 3 layers (Blind Hunter, Edge Case Hunter, Acceptance Auditor). 1 decision resolved (AC8 icon size — keep 309×348), 4 patches applied (i18n extractor word-boundary, orphan-key crash guard, PHP escape handling, stale "logged once" comment), 6 deferred (DAEMON_VERSION dual source of truth ×2, i18n SOURCE_FILES whitelist gap, Market description length boundary, fr_FR.json duplicate-key blind spot, beta URL duplication), 3 dismissed as noise (single-FR-changelog and apt-pinning are deliberate/out-of-scope, Pages resolution already tracked in the checklist). `python3 -m pytest tests/level1/` clean after patches (1240 passed; one pre-existing flaky `sia_crypto` pad-length test, unrelated, going away with story 1-5). Status stays `review` — no story status change requested. |
