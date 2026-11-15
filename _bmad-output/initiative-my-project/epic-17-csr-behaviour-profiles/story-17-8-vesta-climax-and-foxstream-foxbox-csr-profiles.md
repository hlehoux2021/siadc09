---
id: 8
type: story
title: "17.8 — Vesta (Climax) and FoxStream (FoxBox) CSR Profiles"
parent: epic-17-csr-behaviour-profiles
covers: [FR11, NFR7]
after: [1, 2, 3, 7]
hitl: false
risk: low
---

# 17.8 — Vesta (Climax) and FoxStream (FoxBox) CSR Profiles

## Description

Two new profiles in the wizard profile list: Vesta (Climax) sends snapshot and clip, format U, one tag with a single space between the URLs; FoxStream (FoxBox) sends snapshot and clip, format V, one tag with a single space between the URLs. Both also set the supervision frame to sia-dcs every 30 s and the RP cyclic test on every 120 s. These two timings are test values.

## Acceptance Criteria

Verify: Choosing each profile in the wizard sets the media options and the two timings as described and nothing else changes in the equipment. The level 1 test on the preset file accepts both profiles.

## Amendment 2026-11-15 (user): described profiles, Maday and Cors Online replace Vesta and FoxStream

Every profile carries a `description` shown under the selector when it is chosen; « Personnalisé » shows « « Personnalisé » = mode expert : vous réglez tout. ». The text « Le profil règle pour vous les options de votre centrale. » sits above the selector, the description on its own line below it. The selector lists, in this order:

| Profile (key) | Description | Supervision / RP | Media |
|---|---|---|---|
| Maday Sécurité (www.maday.fr) (`maday`) | Profil Maday Sécurité, protocole type FoxStream, avec alarme intrusion SIA et levée de doute par envoi d'une rafale de photos sur serveur FTP. | `null` every 300 s, RP every 86400 s | photo burst on, clip off, transport `ftps`, plain FTP (no TLS) ticked by default |
| Cors Online (www.cors-online.com) (`cors`) | Profil Cors Online, protocole SIA-DC09 avec alarme intrusion SIA et levée de doute par envoi de l'URL d'un clip vidéo pris par vos caméras. | `null` every 300 s, RP every 7200 s | clip on, format V, photo off, one tag, transport `url` |
| Ajax Hub simulé (`ajax`, key unchanged) | Profil simulation Ajax Hub, avec alarme intrusion, sans levée de doute photo/vidéo. | `null` every 300 s, RP every 3600 s | none |

Vesta and FoxStream are removed from `core/config/csr_presets.json`. An equipment saved with `csr_profile` `vesta` or `foxstream` keeps its values and shows « Personnalisé » (unknown key, nothing locked).

## References

- parent — _bmad-output/initiative-my-project/epic-17-csr-behaviour-profiles/epic-17-csr-behaviour-profiles.md
- media options and their configuration keys — story 17.7

## Notes

- Decision: the Vesta and FoxStream profiles set sia-dcs supervision every 30 s and RP every 120 s; these are test values (user, 2026-11-05).
- Decision: the media URL template is never part of a profile (user, 2026-11-05).
- Decision: Vesta uses format U and FoxStream format V, both with one tag and a single space between the URLs (user, 2026-11-05). U is `[U<url>]`, see 17.7.
- Decision (user, 2026-11-15): Maday supervises with `null` every 300 s and RP every 24 h; Cors Online `null` every 300 s, RP every 2 h, clip V; the descriptions are the user's wording. Maday uses plain FTP (`ftps_plain` 1): a profile default, filled but never locked, like `media_enabled`. Ajax Hub simulé sends a NULL ping every 300 s and RP every 3600 s (user, 2026-11-15, after being told `internal-docs/ajax.md` shows the real hub sends NULL only in permanent mode, not implemented, D-115; on demand it sends none and the RP carries the supervision).
- Decision (reversed by 17.10, user 2026-11-06): the profile media keys are filled and locked by the profile; Scutum also declares video only, format V, box off (to test).
