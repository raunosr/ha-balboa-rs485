# HACS publication review — preparation

On 2026-09-08 the user requested public HACS distribution with basic repository
protections and selected a private archive plus a sanitized public source snapshot.
The user subsequently confirmed the publication exception and explicitly authorized
updating AGENTS.md and the remaining release documentation. No publication approval
is pending. No HA restart is part of this operation.

## Checks completed

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

## Intended protections and remaining gates

The sole writer is the owner, @raunosr. Main is to require a PR, resolved review
conversations and `core`, `home-assistant`, `hacs` checks from GitHub Actions, with
administrator enforcement and no force push/deletion. Require no second reviewer
while only one maintainer exists, avoiding an unapprovable self-authored PR.
Version tags are to reject updates/deletion. Fork workflows require maintainer
approval; workflow credentials stay read-only and cannot approve PRs. No automatic
merge/deployment is configured. Recheck live settings after applying them.

The fresh public snapshot needs its own core/actual-HA/HACS CI acceptance, release
tag, HACS registration/download test and settings readback. Do not call these
complete based only on local files. Runtime hardware acceptance stays as described
in `phase4b_review.md`. The user has restored HA and reports Balboa absent; no
historical startup investigation or automation cleanup is part of this publication.
