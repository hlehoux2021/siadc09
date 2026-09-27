# Jeedom Market submission checklist — siaDC09

Steps to publish siaDC09 on the Jeedom Market. The **files** are prepared in the repository. **Every step marked 👤 is a manual action for the maintainer**: it needs a Market account, GitHub access or a design decision, so it cannot be done from the code.

## 1. Repository content (prepared — re-check before each publish)

- [x] `plugin_info/info.json`: `id`, `name`, `description.fr_FR` (≥ 80 characters), `licence`, `author`, `require`, `category`, `pluginVersion`, `changelog`, `changelog_beta`, `documentation`, `documentation_beta` (with `#language#`), `hasDependency`, `hasOwnDeamon`, `maxDependancyInstallTime`, `os`, `language`, `compatibility` — guarded by `tests/level1/test_info_json.py`
- [x] `pluginVersion` = `DAEMON_VERSION` (`tests/level1/test_daemon_version.py`)
- [x] `plugin_info/packages.json`: every pip3 dependency pinned (`jeedomdaemon==1.2.9`, `cryptography==43.0.3`)
- [x] `plugin_info/siaDC09_icon.png`, 309 × 348 PNG
- [x] `core/i18n/fr_FR.json` complete (`tests/level1/test_i18n_roundtrip.py`)
- [x] `docs/fr_FR/index.md`, `docs/fr_FR/changelog.md` (single changelog, French only — `info.json` points both `changelog` URLs to `fr_FR/changelog`), `docs/en_US/index.md`
- [x] Internal documents (design docs, protocol spec, simulator/logging guides) live in `internal-docs/`, outside the `/docs` folder that GitHub Pages publishes
- [ ] 👤 **Icon design**: the current icon is a generated placeholder (shield + signal arcs + "SIA DC-09"). Replace it with a final design if you want one: 309 × 348 PNG, rounded corners, coloured background, transparency, avoid the official Jeedom palette.
- [ ] **Remove the aiodemo template leftovers** before the first publish, otherwise the Market package ships a second, unrelated plugin's files: `core/ajax/aiodemo.ajax.php`, `core/class/aiodemo.class.php`, `core/php/jeeaiodemo.php`, `desktop/js/aiodemo.js`, `desktop/php/aiodemo.php`, `resources/aiodemod/`, the `plugins/aiodemo/...` sections of `core/i18n/{de_DE,en_US,es_ES,it_IT,pt_PT}.json`, and `aiodemo_pre_update()` in `plugin_info/pre_install.php` (delete the file or rename it to `siaDC09_pre_update()`).
- [ ] **Non-French translations**: `info.json` declares `en_US` and `de_DE`. Let `.github/workflows/translations.yml` generate the siaDC09 sections (or reduce `language` to what is really translated).
- [ ] 👤 **Forum link** (optional but recommended): once a topic exists on community.jeedom.com, add `"link": {"forum": "<topic URL>"}` to `info.json`.
- [ ] Run the full regression: `python3 -m pytest tests/level1/ tests/level2/ tests/level2_5/`, `find core/ desktop/ -name "*.php" | xargs -n1 php -l`, `python3 -m pylint resources/siadc09d/`.

## 2. Documentation site (👤)

`info.json` points to `https://hlehoux2021.github.io/siadc09/#language#/` and `…/#language#/changelog`.

- [ ] 👤 Enable **GitHub Pages** for `hlehoux2021/siadc09` (Settings → Pages → deploy from branch, folder `/docs`).
- [ ] 👤 Open `https://hlehoux2021.github.io/siadc09/fr_FR/` and `…/fr_FR/changelog` in a browser and check that both render. If Pages needs `.md`-less URLs, keep the default Jekyll build (it serves `index.md` → `/fr_FR/`, `changelog.md` → `/fr_FR/changelog`).
- [ ] 👤 `de_DE` has no documentation page yet. Either add `docs/de_DE/` or accept the 404 for German users.

## 3. Market account and publication (👤)

1. [ ] 👤 Have a **developer account** on the Jeedom Market (market.jeedom.com, profile → request developer status if not already granted).
2. [ ] 👤 Create a **GitHub token** for the Market: classic token with `repo` scope, or a fine-grained token with read-only access to *Contents* and *Metadata* of `hlehoux2021/siadc09`. Paste it in the Market profile (GitHub section).
3. [ ] 👤 On the Market, **add a plugin**: source GitHub, repository `hlehoux2021/siadc09`, plugin ID `siaDC09`.
4. [ ] 👤 **Branch mapping**: choose which branch feeds **beta** and which feeds **stable** (for example `beta` → beta, `master` → stable). Push the release to the beta branch first.
5. [ ] 👤 Fill in the Market listing: category *Sécurité*, price (free), screenshots (wizard, widget, diagnostic tab), short description. Mention the known limitations (encryption, UDP) in the description.
6. [ ] 👤 Submit for **review**. The Jeedom team checks the plugin before it becomes public; expect several days and possibly change requests (commonly: leftover template files, missing translations, icon).
7. [ ] 👤 Install the **beta** from the Market on a test box (for example test-jeedom) and validate against a real receiver before promoting to stable.

## 4. GitHub release (👤)

> Not now: the plugin is at the **early-tester** stage and no release is planned yet. Do these steps only once a first release is decided.

1. [ ] 👤 Decide the version number of the first release and write its release notes (French + English).
2. [ ] Tag the release commit: `git tag -a v<x.y.z> -m "siaDC09 <x.y.z>"` then `git push origin v<x.y.z>`.
3. [ ] 👤 Create the GitHub release from the tag and paste the release notes.
4. [ ] Update the changelog: replace the "Version de test — premiers testeurs (non publiée)" heading with the publication date and version, using the `# dd/mm/yyyy Beta & Stable x.y.z` heading format.

## 5. Every next version

- [ ] Bump `pluginVersion` and `DAEMON_VERSION` together.
- [ ] Add an entry to `docs/fr_FR/changelog.md`.
- [ ] Run the regression, push to the beta branch, validate, then merge to the stable branch.
