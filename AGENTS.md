# Balboa RS485 engineering rules

Read `docs/architecture.md`, `docs/implementation_plan.md`, and
`docs/protocol_sources.md` before protocol or transport work.
Review each phase before proceeding. On 2026-09-06 the user authorized autonomous
completion of Phases 6–11 after Phase 5 installation/hardware tests pass, and
bounded real-spa commands while BWALink is stopped. Verify that condition before
connecting. Production HA must remain protected: no deliberate outages, HA/OS
upgrades or security weakening. Confirm a required production HA restart with the
user unless covered by an unambiguously unused explicit authorization. Record each
restart against its current allowance; do not reuse historical phase allowances.
Publication work authorizes no HA restart. Historical restart/acceptance evidence
lives in `docs/phase4b_review.md`, `docs/phase6_review.md` and earlier reviews;
it does not prove current production state. Another agent may restart HA independently.

## Public distribution authorization

On 2026-09-08 the user explicitly authorized public HACS distribution and updates
to these instructions. Preserve the original repository/history privately as
`raunosr/ha-balboa-rs485-private-archive`; publish a sanitized, parentless source
snapshot as `raunosr/ha-balboa-rs485`. Never push private history or personal commit
email to the public remote. Use the owner's GitHub noreply address for new commits.
After bootstrap, use pull requests and required tests on protected `main`; no
force pushes, deletion or automatic merging. Protect published version tags.
Keep repository credentials read-only in CI, require approval for external fork
workflows, and do not run untrusted code with production access. Review publication
text for secrets and home-network information. Publish experimental limitations
honestly; HACS download success is not hardware acceptance. No new write
collaborators, license changes or unrelated public releases without user direction.
The owner explicitly selected MIT on 2026-09-08. Preserve LICENSE in the repository
and HACS-distributed component; the package test enforces matching notices.

Public HACS publication and scoped installation cleanup are complete. The previous
fixed-address direct-mode compatibility trial passed on v0.0.16; see
`docs/direct_tcp_live_review.md` for its bounded evidence and remaining gates.
The user explicitly deferred
all automation migration/cleanup until the integration is complete. Do not resume
historical HA startup diagnosis. The current priority is the v0.0.16 reliability
regression: routine reminders block controls, historical priming looks active,
clock Activity noise, and failed unload retains the bus connection. Energy work
is explicitly deferred and retained privately. See `docs/reliability_0_0_17.md`.
The user's NEW 2026-09-09 bug-fix allowance is TWO HA Core restarts, 1/2 used
for v0.0.17 activation. This replaces, and must not be added to, old
trial allowances. Reconcile against the private deployment ledger before acting.
Use the normal restart tool only; record actual accepted dispatches privately.
This does not authorize spa power cycling, failure injection on production or
automation changes. The panel remains a bus participant; low client count is not
collision-proof arbitration. Verify BWALink stopped immediately before the trial.
Run failure injection in the lab.
Read `docs/bwalink_transport_review.md` before further recovery work. The rolling
allocation-window draft was rejected before deployment: pacing does not prevent
finite controller channel-pool exhaustion. Do not silently add repeated allocations
or unacknowledged direct writes. Filter acceptance passed on v0.0.15; native
High/Low restoration and two automatic recoveries passed in the explicit v0.0.16
direct trial. First-attempt reliability, that mode's bathing-session restoration,
other advanced controls and long soak remain unaccepted. Do not migrate automations.
Keep the Python core independent of Home Assistant. Never send unknown messages
to hardware, treat an open socket as availability, or replay raw toggles.
Use observed state, not optimistic updates. Run tests and lint before delivery.
Do not check in `.research/`, virtual environments, or hardware captures.

## Agent skills

### Issue tracker

GitHub Issues in public `raunosr/ha-balboa-rs485`. See `docs/agents/issue-tracker.md`.

### Triage labels

Standard five-role vocabulary. See `docs/agents/triage-labels.md`.

### Domain docs

Single backend context. See `docs/agents/domain.md`.
