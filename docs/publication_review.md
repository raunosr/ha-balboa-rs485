# HACS publication review

This records the publication-only checkpoint. Subsequent activation and native
tests are recorded in [Phase 4B](phase4b_review.md) and the
[filter confirmation review](filter_confirmation_review.md); the disabled-entry
state below is historical, not a current production-state assertion.

On 2026-09-08 the user requested public HACS distribution with basic repository
protections and selected a private archive plus a sanitized public source snapshot.
The user subsequently confirmed the publication exception and explicitly authorized
updating AGENTS.md and the remaining release documentation. No publication approval
is pending. No HA restart is part of this operation.

## Outcome — 2026-09-08

Public HACS distribution is complete for the experimental
[v0.0.14 prerelease](https://github.com/raunosr/ha-balboa-rs485/releases/tag/v0.0.14),
tagged at `3e547658986a8292822b4d67b61e8bf8e52ad705`. The private archive remains
private and read-only. This is distribution acceptance, not production hardware
acceptance or a completed BWALink replacement.

- Release [software CI](https://github.com/raunosr/ha-balboa-rs485/actions/runs/34195286735)
  passed **610 tests**: 527 core/tools, 82 actual HA 2026.8.3 tests and one isolated
  ZIP-installation test, plus lint, formatting, bundle equality and strict types.
- Release [HACS validation](https://github.com/raunosr/ha-balboa-rs485/actions/runs/34195286748)
  passed all **nine checks**, with no ignored check.
- The public custom repository was registered in the user's HACS and explicitly
  downloaded as `v0.0.14`. A separate HACS readback confirmed `installed=true` and
  `installed_version=v0.0.14`. This checks the HACS source-download path, not just
  the separately attached manual ZIP.
- The existing HA entry remains disabled and `not_loaded`, with physical controls
  disabled. Its identifiers and old automations were preserved. No HA restart,
  integration enable/reload, spa connection or spa command was performed.
- Required `core`, `home-assistant` and `hacs` checks, administrator enforcement,
  and force-push/deletion prohibitions were read back after publication.

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
  bundle and types. The licensed package was separately checked in PR #3 and on
  the resulting main commit before publication.
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
- The public manual-install ZIP includes the MIT notice and has **51 files**,
  **1,262,657 bytes**. GitHub's uploaded asset digest matches the SHA-256 above.
  It supersedes the historical 50-file pre-license archive.

## One-time license bootstrap

HACS's license check used repository metadata from the default branch, so adding
the first LICENSE in PR #3 could not make that required check pass before merging.
After the owner's MIT approval and successful core/HA checks on the exact PR head,
only `hacs` was temporarily removed from the required check list for that one
normal squash merge. PR requirements, administrator enforcement, writer access
and force-push/deletion protection were retained; no administrator merge bypass
or auto-merge was used. The full three-check protection was restored immediately
in a cleanup step and read back. All nine HACS checks then passed on main before
the release tag was published. No ongoing protection exception remains.

## Protection rationale and remaining gates

The sole writer is the owner, @raunosr. Main requires a PR, resolved review
conversations and `core`, `home-assistant`, `hacs` checks from GitHub Actions, with
administrator enforcement and no force push/deletion. Require no second reviewer
while only one maintainer exists, avoiding an unapprovable self-authored PR.
Version tags reject updates/deletion. Fork workflows require maintainer
approval; workflow credentials stay read-only and cannot approve PRs. No automatic
merge/deployment is configured. The live settings were read back after applying them.

Public CI, release publication, HACS registration/download and settings readback
are complete. Runtime activation is still pending: arrange an explicitly authorized
safe HA restart, verify competing RS485 clients are stopped, then reuse the existing
entry and verify fresh controller state with controls disabled. Hardware acceptance
stays as described in `phase4b_review.md`; do not infer it from a HACS download.
No historical startup investigation or automation cleanup is part of this
publication. Historical CI links point into the private archive and require owner
access; the public release CI links above are independently accessible.
