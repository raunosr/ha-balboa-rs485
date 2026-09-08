# Security

This is experimental software controlling physical equipment. Protect the spa's
gateway on the local network; do not expose its TCP or management ports publicly.
The integration cannot replace the controller's physical safety protections.

Use GitHub's **Security → Report a vulnerability** for sensitive reports when
available. Do not put credentials, network captures or private home information
in public issues. Ordinary reproducible bugs can be filed in Issues with redacted
diagnostics and simulator steps.

Only the latest reviewed experimental release is a candidate for fixes; no
long-term support or fully unattended hardware acceptance is promised. Keep a
known-good HA backup before installing any custom integration. See the current
acceptance review before enabling physical controls.

CI uses read-only repository permissions and unprivileged pull-request events;
it does not deploy to HA, hold home-network credentials, or automatically merge
or publish changes. GitHub Actions references are pinned; upstream container or
package dependencies still require review. Never run untrusted PR code using
`pull_request_target`, a self-hosted production runner or write credentials.
