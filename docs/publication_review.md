# HACS publication review

On 2026-09-08 the user requested public HACS distribution with basic repository
protections and selected a private archive plus a sanitized public source snapshot.
The user subsequently confirmed the publication exception and explicitly authorized
updating AGENTS.md and the remaining release documentation. No publication approval
is pending. No HA restart is part of this operation.

## Checks completed

- Public repository ID 1361003309 now has a clean root commit
  `ff912c0f9f125b088a6520d2412c686def039915` with no parents and GitHub noreply
  authorship. Only this branch was pushed to the new public origin. Gitleaks
  rechecked that single public commit and reported no leaks.
- The original repository ID 1358036928 is private and archived (read-only) as
  `raunosr/ha-balboa-rs485-private-archive`; a local ignored Git bundle also preserves
  all earlier refs. No private history was force-rewritten or deleted.
- GitHub confirmed administrator-enforced main protection: PRs, resolved review
  conversations, strict up-to-date `core`/`home-assistant`/`hacs` checks from GitHub
  Actions app 15368; force pushes/deletion off. Active tag ruleset 22513878 blocks
  updates/deletion of `v*` tags with no bypass actors. Only @raunosr is a collaborator.
- Fork workflow approval is `all_external_contributors`; workflow defaults are
  read-only and cannot approve PRs. Secret scanning and push protection are enabled,
  as are vulnerability alerts and private vulnerability reporting. Auto-merge is off.
- Initial public HACS run 34194347390 passed brand, manifest, HACS manifest and
  repository metadata checks; its sole failure was a missing license. The owner
  then explicitly chose MIT. Both repository and HACS package now carry matching
  notices, covered by the packaging regression test. No check is skipped to pass.
- Public root CI run 34194347414 passed core/tools and actual HA tests, lint,
  bundle and types. The licensed package is separately rechecked through a PR.
- The new license-preservation assertion first failed because the manual ZIP
  builder only included files with selected extensions. It now explicitly includes
  the component LICENSE; all six packaging tests and lint pass. The public ZIP
  contains 51 files; its hash is `a4ac41393a29d0a8424d7b3c00e10ed0f9817d71042311ffd1783a5f37177a9d`.

- Gitleaks 8.30.1 checked all 91 existing commits (~1.02 MB of changed text) and
  reported no leaks. The scanner download matched its official release checksum.
  This does not prove the absence of every possible secret.
- Known private LAN examples were removed from current documentation and replaced
  by a documentation-range address in the non-loopback refusal test. The original
  history and personal commit email will stay in the private archive, not be
  force-rewritten or pushed to the public repository.
- All **527** core/tools tests passed, with **96.99%** coverage. An initial Windows
  temp-directory permission error affected five packaging fixtures, not the code;
  the complete rerun in a fresh workspace-local base temp directory passed.
- Ruff, formatting, strict core typing and canonical/bundled-core equality passed.
- The rebuilt 50-file manual-install ZIP is unchanged from the reviewed 0.0.14
  archive: SHA-256 `de5e7d28067a2068b31c2ebcc9b968941110117b976358d1bde399ae820802e5`.
- HACS is reachable through the HA connector; the new repository is not yet listed.
  No integration file was copied to HA and no restart or spa command was issued.

## Protection rationale and remaining gates

The sole writer is the owner, @raunosr. Main requires a PR, resolved review
conversations and `core`, `home-assistant`, `hacs` checks from GitHub Actions, with
administrator enforcement and no force push/deletion. Require no second reviewer
while only one maintainer exists, avoiding an unapprovable self-authored PR.
Version tags reject updates/deletion. Fork workflows require maintainer
approval; workflow credentials stay read-only and cannot approve PRs. No automatic
merge/deployment is configured. The live settings were read back after applying them.

The fresh public snapshot needs its own core/actual-HA/HACS CI acceptance, release
tag, HACS registration/download test and settings readback. Do not call these
complete based only on local files. Runtime hardware acceptance stays as described
in `phase4b_review.md`. The user has restored HA and reports Balboa absent; no
historical startup investigation or automation cleanup is part of this publication.
