<p align="center">
  <img src="https://raw.githubusercontent.com/Backroads4Me/librecoach-site/main/public/og-default-opt.png" alt="LibreCoach — open RV control with Home Assistant" width="720">
</p>

# LibreCoach

**Bring your RV's lights, climate, tanks, power systems, and more into Home
Assistant—without replacing the factory controls you already rely on.**

[Website](https://librecoach.com/) ·
[How it works](https://librecoach.com/start-here/what-is-librecoach/) ·
[Build guide](https://librecoach.com/build/overview/) ·
[Community and support](https://librecoach.com/community/connect/) ·
[Contributing](./librecoach/CONTRIBUTING.md)

LibreCoach connects an RV-C network to Home Assistant using standard hardware
and open-source software. It automatically discovers compatible devices, runs
locally without a required cloud service, and gives you a system you can
customize and maintain yourself.

![LibreCoach dashboards showing lighting, tanks, climate, and power](https://raw.githubusercontent.com/Backroads4Me/librecoach-site/main/src/assets/dashboards/dash_light.webp)

## Why LibreCoach?

- **One interface for the whole RV.** Control and monitor lights, shades,
  locks, pumps, tanks, climate, batteries, and other supported systems from a
  phone, tablet, or browser.
- **Automatic RV-C discovery.** Compatible devices appear in Home Assistant
  without hand-written entity templates.
- **Local and extensible.** Build dashboards, alerts, and automations on the
  Home Assistant ecosystem instead of a vendor-locked touchscreen.
- **Factory controls stay in place.** LibreCoach adds monitoring and
  convenience control; it does not replace existing switches, panels, or
  safety-critical controls.

LibreCoach is intended for RVs with an RV-C based CAN network. Fully analog RVs
and RVs using an unsupported proprietary network are not compatible. See
[What is LibreCoach?](https://librecoach.com/start-here/what-is-librecoach/)
for the full compatibility and system overview.

## Install

Add the stable LibreCoach repository to Home Assistant:

[![Add repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FBackroads4Me%2Fha-addons)

Then find **LibreCoach** under **Settings → Apps → Install Apps**. On first
start, LibreCoach installs and configures Mosquitto, Node-RED, and the
LibreCoach automation flows.

Building a complete system also requires a Home Assistant host, CAN interface,
and connection to the RV-C network. Follow the
[step-by-step build guide](https://librecoach.com/build/overview/) for hardware,
assembly, software, and connection instructions.

## Documentation and support

- [Installation guide](https://librecoach.com/build/software/)
- [Configuration guides](https://librecoach.com/configuration/identify-devices/)
- [Frequently asked questions](https://librecoach.com/community/faq/)
- [Discord, Facebook, and GitHub support](https://librecoach.com/community/connect/)
- [Add-on overview and first-start notes](./librecoach/README.md)

## Contributing

Bug reports, feature ideas, documentation improvements, and code contributions
are welcome. Start with the
[contribution guide](./librecoach/CONTRIBUTING.md); contributions to the
LibreCoach add-on require signing the CLA.

## Support LibreCoach

If LibreCoach has been useful to you, and you'd like to help keep it going:

[![Buy Me a Coffee](https://img.shields.io/badge/Support-Buy%20Me%20a%20Coffee-FFDD00?logo=buy-me-a-coffee&logoColor=000000)](https://buymeacoffee.com/Backroads4Me)
[![Star on GitHub](https://img.shields.io/badge/%E2%AD%90%20Star%20ha--addons-GitHub-lightgrey?logo=github&logoColor=black)](https://github.com/Backroads4Me/ha-addons)
