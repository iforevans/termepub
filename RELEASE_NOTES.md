# Release Notes

## termepub v2.0.0 — 2026-07-30

Complete rewrite in Rust. Faster startup, zero runtime dependencies, self-contained binary with embedded dictionary.

### What Changed

- **Rewritten in Rust** — the entire codebase is now a compiled binary with no Python runtime requirement
- **Executable renamed** — `termepub.py` → `termepub`
- **Self-contained** — the ~24 MB binary includes the ECDICT dictionary; no installation step on first run
- **Faster startup and rendering** — no interpreter overhead, lazy dictionary loading
- **Grapheme-safe layout** — CJK characters, emoji, and combining marks are handled correctly without splitting across lines
- **Four themes** — added Solarized Dark and Solarized Light alongside the existing Dark and Light
- **Same keyboard controls** — all key bindings from v1.x are preserved
- **Same state file format** — `~/.config/termepub/state.json` is read and written in the Python-compatible format; bookmarks, reading positions, and theme preferences are preserved
- **EPUB safety limits** — bounded archive reads, encryption detection, compression ratio checks

### Technical Details

- **Dependencies:** clap, crossterm, ratatui, tokio, zip, quick-xml, unicode-width, unicode-segmentation, serde_json, sha1, thiserror
- **Test coverage:** 73 passing tests (unit, CLI, EPUB parsing, HTML extraction, pagination, state persistence, dictionary lookup, responsive layout) plus 6 PTY integration tests (ignored by default)
- **Minimum terminal size:** 10 columns × 5 rows; below this a "terminal too small" message is shown
- **Offline-only:** no network access, no cloud synchronization, no external data files

### Migration Notes

- If you were using `termepub.py`, update your shell alias or symlink to `termepub`
- Your existing `~/.config/termepub/state.json` will work without modification
- The dictionary no longer needs to be downloaded or installed — it is built into the binary
- The `--no-css`, `--bookmark`, and `--version` flags work exactly as before

### Known Limitations

- DRM-protected EPUBs with encrypted text resources are rejected (same as v1.x)
- Italic and line-through are parsed but may not render visibly in all terminal emulators
- PTY resize tests are provided but must be run manually with `--ignored --test-threads=1`

---

## termepub v1.0.4 — 2026-07-29

Post-1.0 code hardening: UTF-8 rendering, 256-color support, deterministic dictionary suggestions, and miscellaneous correctness fixes.

### Changes

- `ascii_sanitize` now preserves all printable Unicode characters (accented Latin, CJK, etc.) instead of stripping everything above ASCII
- Color rendering uses the 256-color cube on capable terminals, falling back to the 16-color ANSI palette on error
- Dictionary "did you mean" suggestions are now deterministic
- Duplicate-segment detection requires blank-line separation and text ≤ 40 chars, preventing loss of legitimate repeated body text
- Color pair wraparound at 256 pairs now clears the cache before reuse
- `_get_plain_pages` removed — dead code after the v1.0.1 styled-pages optimization
- `show_help` collapsed from three sequential popups into a single scrollable popup
- Test count increased from 22 to 30
