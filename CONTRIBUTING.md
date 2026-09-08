# Contributing

Changes go through pull requests and the required `core`, `home-assistant` and
`hacs` checks. The repository has one maintainer, @raunosr. Public visibility does
not grant write or merge permission. Do not request access simply to submit a PR;
use a fork. No automatic merging or publishing is configured.

The main branch disallows force pushes and deletion. A second approving reviewer
is not required while there is only one maintainer: an author cannot approve their
own PR. Reassess required code-owner approval before adding any write collaborator.

Run `python -m tools.dev test`, `python -m tools.dev lint` and
`python -m tools.package --check`. Adapter tests use the pinned HA test requirements
and Python 3.14 in CI. Edit the independent `balboa_rs485/` core and regenerate
`custom_components/balboa_rs485/_core/` with `python -m tools.package`.

Keep credentials, device identifiers, captures, personal addresses and local
development files out of commits and issue attachments. Use documentation IP
addresses in examples. Use simulators for outages and failure injection. Changes
must preserve observed-state verification, bounded retries and session restoration;
never replay ambiguous raw toggles or send unknown commands to a real spa.

Before a release, review the hardware acceptance limitations, verify all required
checks, match the tag to the manifest version, and publish a release explicitly.
HACS downloads the integration directory from that tagged source; the separate
installation ZIP is for manual installation, not a HACS `zip_release` artifact.
