# HACS installation

Requires an existing HACS installation and Home Assistant **2026.8.3+**. This
repository is a custom integration source, not a HACS default-catalog entry.
The first public release is experimental; installation success is not complete
hardware or weak-network acceptance. Read [current limitations](phase4b_review.md).

## Install

1. In HACS, open the three-dot menu → **Custom repositories**.
2. Add `https://github.com/raunosr/ha-balboa-rs485` with type **Integration**.
3. Find **Balboa RS485** and download the reviewed release. If only a prerelease
   is offered, enable HACS's beta/prerelease option and select its explicit tag.
4. Restart HA once, at a safe time. HACS downloading alone does not load Python
   code. Do not upgrade HA or its OS just to install this integration.
5. Open **Settings → Devices & services → Add integration → Balboa RS485**.
   If an existing Balboa RS485 entry remains, reuse it instead of adding another.
6. Before connecting, verify BWALink and any competing RS485 client are stopped.
   Enter the EW11 address and port. Start with physical controls disabled. The
   experimentally verified channel bus uses `channel-rs485`; `auto` is passive.
   Do not pick `classic-rs485` just because the TCP connection opens.
7. Verify fresh status, controller metadata and discovered capabilities before
   enabling physical controls. Run bounded reversible tests, then restore the
   original spa settings. Do not migrate old automations in the same step.

The package is self-contained under `custom_components/balboa_rs485/`, including
the core and local icon. No pip package, MQTT bridge or public gateway access is
needed. Only one entry should own each physical spa.

## Updates and rollback

Keep a known-good HA backup and note the installed version before updating.
Stop this integration, download an explicitly reviewed HACS version and restart
at a safe time. Preserve its entry and entity IDs. If a release misbehaves, disable
this integration and use HACS **Redownload** to select a known-good version, then
restart. Do not remove the whole `custom_components` directory or restore all of
HA merely to roll back this component.

HACS reads the integration directory from tagged repository source. `hacs.json`
does not enable `zip_release`: the separately supplied manual-install ZIP has a
different root layout and is not used by the HACS download path.

## References

- [HACS custom repositories](https://www.hacs.xyz/docs/faq/custom_repositories/)
- [HACS integration structure](https://www.hacs.xyz/docs/publish/integration/)
- [EW11 recommended settings](ew11_settings.md)
- [Native controls and bathing sessions](native_controls_0_0_13.md)
