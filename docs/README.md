# Documentation

## Installing and using the experimental release

- [HACS installation, updates and rollback](hacs_installation.md)
- [Native controls, Low/High bathing sessions, filters and diagnostics](native_controls_0_0_13.md)
- [EW11 recommended settings](ew11_settings.md)
- [Connection modes and installation safety](home_assistant.md)
- [Heating prediction and learning](heating_prediction.md)
- [Supported native entities versus BWALink](entity_parity.md)
- [Current hardware acceptance and known limitations](phase4b_review.md)
- [Public HACS release and repository safeguards](publication_review.md)

0.0.14 is experimental, not an accepted unattended BWALink replacement. A successful
HACS download does not validate physical controls or long-duration network recovery.
Do not migrate automations until the appropriate hardware acceptance is complete.

## Development and historical evidence

[Architecture](architecture.md), [protocol sources](protocol_sources.md),
[implementation plan](implementation_plan.md), [local testing](local_testing.md)
and [contribution rules](../CONTRIBUTING.md) describe the engineering workflow.

Numbered phase design/review documents retain evidence from earlier private
development. Statements about then-installed versions, private visibility, pending
features and restart allowances are historical, not current installation claims
or fresh authorization. Their old commit and CI references belong to the private
archive, not the new public Git history. Start with the current guides above.
