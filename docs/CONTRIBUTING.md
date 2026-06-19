# Contributing to Profiler Machine

Thanks for your interest in contributing to PROFM. It's a hobby project, so the
process here is light — but a few notes will make your contribution easier to
review and merge.

---

## Before you start

PROFM is a deliberate aesthetic homage to the Machine from *Person of Interest*
and the Profiler from *Watch_Dogs*. That theme isn't decoration — it's the point
of the project. Two things follow from that:

- **The maintainer makes the final call on design, naming, lore, and UI.** If a
  change alters the look, the designation system, the console voice, or anything
  cosmetic, open an issue to discuss it first rather than sending a surprise PR.
  Functional changes don't need this.
- **Keep the aesthetic consistent.** Overlay colors, designation names, infocard
  layout, and console phrasing are intentional. If you're unsure whether a change
  fits the theme, ask in an issue.

---

## Development setup

PROFM requires **Python 3.12.x** specifically. 3.13+ breaks `onnxruntime` and
`lapx`; 3.11 and below are untested.

**Supported platforms:** Windows and Linux (Linux verified on Arch). macOS is
untested — contributions to validate or fix it are welcome.

Clone and install:

```bash
git clone https://github.com/anthrxc/profiler-machine
cd profiler-machine
```

- **Windows:** run `install.bat`
- **Linux / macOS / cross-platform:** run `python install.py`
  (on distros that ship Python 3.13+, install `uv` first — the installer uses it
  to fetch a standalone 3.12 automatically)

See [docs/INSTALL.md](docs/INSTALL.md) for the full setup walkthrough, including
GPU/CUDA notes and the Linux audio-player requirement.

An NVIDIA GPU with CUDA is strongly recommended for development — CPU-only mode
works but is roughly 10x slower, which makes testing recognition tedious.

---

## Project structure

| Path | Contents |
|---|---|
| `modules/core/` | Core logic — startup, recognition, tracking, alerts |
| `modules/io/` | Input/output — audio, feeds, etc. |
| `web/` | Flask web interface and static assets |
| `config/` | Runtime config (feeds, session, web settings) |
| `docs/` | Documentation and screenshots |
| `assets/` | Bundled assets |

---

## Reporting bugs

Bugs are tracked on [GitHub Issues](https://github.com/anthrxc/profiler-machine/issues).
A good bug report includes:

- What you did, what you expected, and what actually happened
- Your OS and GPU (or CPU-only)
- Relevant output from `logs/profiler_machine.log`
- A screenshot if it's a UI issue

---

## Submitting changes

1. Fork the repo and create a branch off `main`.
2. Make your change. Keep PRs focused — one logical change per PR is easier to
   review than a grab-bag.
3. **Test it before opening the PR.** At minimum, confirm the app still starts,
   warms up, recognizes a face, and that the web UI loads. If your change touches
   a platform-specific path (audio, CUDA, install), note which platform you
   tested on — the maintainer develops on Windows and can't always verify Linux/Mac.
4. Open the PR with a clear description of *what* changed and *why*. The cleaner
   the description, the faster it gets reviewed.

If your change is large or affects the aesthetic, open an issue to discuss it
before writing the code.

---

## Good first contributions

Look for issues tagged **good first issue** if any are open. Beyond that,
cross-platform validation (especially macOS) and the open items in the README's
"Known issues" section are approachable starting points.

---

## Code of conduct

Be decent to each other. This is a small, friendly project — keep discussions
civil and on-topic. The maintainer reserves the right to close or decline
contributions that don't fit the project's direction, and that's not personal.

---

## License

PROFM is licensed under [AGPL-3.0](LICENSE.md). By contributing, you agree that
your contributions will be licensed under the same terms.
