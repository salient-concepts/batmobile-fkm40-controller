# Contributing

Thanks for considering a contribution. This project exists because a
manufacturer abandoned a product — keeping it alive is a community effort.

## Most-wanted contributions

- **Sensor-response decoding.** The Batmobile sends back a 14-byte packet
  containing seven 10-bit values (`Result1`-`Result7`). One is almost
  certainly battery level. Documenting which value corresponds to what
  would let us bring the BAT indicator back to the WebUI.
- **Sound-effect catalog.** 256 sound indices (`01_00` through `01_FF`)
  exist on the unit; almost none are labeled. Run `sound_sweep.py` to
  walk through them, label what each one is (engine rev, gunfire,
  Batman line, etc.), and submit the labels as JSON in `sounds.json`.
- **Camera firmware investigation.** The RTSP camera advertises a stream
  but emits no frames. The network surface is fully enumerated and the
  symptom is reproducible across all known-good clients. The remaining
  paths (UART debug header, OpenIPC reflash, U-Boot recovery) require
  opening the case. See [docs/camera-investigation.md](docs/camera-investigation.md).
- **Localization.** UI strings are English-only. The HTML/JS uses static
  strings; pulling them into a small i18n dict and adding translations
  would be welcome.
- **Hardware variants.** This project targets the Mattel **FKM40** only.
  Other RC vehicles using similar Anyka/Hisilicon-class WiFi modules may
  use the same protocol or a close variant. Documenting compatible models
  (or known-incompatible ones) is useful.

## Submitting changes

1. Fork the repo on GitHub.
2. Create a topic branch: `git checkout -b my-thing`.
3. Make your changes. Keep diffs focused — one feature/fix per PR.
4. Test on real hardware if your change touches the controller. Bench
   testing is fine; full vehicle testing is better.
5. Open a PR. Describe what changed and how you tested it.

## Code style

- **Python:** follow PEP 8 generally. We don't enforce a formatter — the
  code is small enough that consistency-by-eye is fine. If you want to
  run `ruff` or `black` on the file you touched, that's welcome.
- **JavaScript:** plain ES2020+, no build step, no framework. Keep it that
  way unless there's a strong reason. Two-space indent, single quotes.
- **CSS:** custom properties for colors and sizes. Avoid hardcoded hex
  values in selectors — add them to `:root` first.
- **HTML:** semantic where possible, ARIA labels on every interactive
  element.

## Testing

There is no automated test suite yet. The project is small enough that
manual smoke testing on the Pi + Batmobile is currently sufficient. If
you add a meaningful test harness for the controller's packet logic
(without needing the physical unit), it would be welcome.

## What's out of scope

- **Tracking, analytics, telemetry to remote servers.** This project is
  owner-first. Nothing phones home.
- **Cloud account requirements.** Same.
- **Mobile app wrappers.** The WebUI works on phones; a native wrapper
  doesn't add value and creates app-store maintenance burden.
- **Re-implementing camera streaming.** The camera firmware is fragile
  across the entire product line. Software fixes from the network side
  are exhausted. If you want camera, the path is hardware-level
  (UART, replacement module). Network-level "let me try one more RTSP
  variant" PRs will be politely declined.

## Code of conduct

Be respectful. If something on the project bothers you, open an issue.
If interaction with another contributor bothers you, contact a maintainer
privately first.

## Maintainer

[Salient Concepts LLC](https://salient-concepts.github.io/) — owner of
the GitHub org. Reach out via GitHub issues for project questions.
