# Release Notes

## termepub-reader v1.0.4 — 2026-07-29

Post-1.0 code hardening: UTF-8 rendering, 256-color support, deterministic dictionary suggestions, and miscellaneous correctness fixes.

### Changes

- `ascii_sanitize` now preserves all printable Unicode characters (accented Latin, CJK, etc.) instead of stripping everything above ASCII
- Color rendering uses the 256-color cube (`_rgb_to_256_color`) on capable terminals, falling back to the 16-color ANSI palette on error
- `_parse_color_to_rgb` extracted as a shared color-parsing helper, reused by both 16-color and 256-color paths
- Dictionary "did you mean" suggestions are now deterministic — `_word_list` is sorted on load
- Duplicate-segment detection in `_wrap_segments_with_styles` requires blank-line separation and text ≤ 40 chars, preventing loss of legitimate repeated body text
- Color pair wraparound at 256 pairs now clears the cache before reuse, avoiding stale pair-to-color mappings
- `_get_plain_pages` removed — dead code after the v1.0.1 styled-pages optimization
- `show_help` collapsed from three sequential popups into a single scrollable popup
- Added `-> None` return type hints to 30+ `ReaderUI` and `FilePicker` methods
- Backspace handling consolidated to `KEY_BACKSPACE_ALL` tuple
- Removed redundant `import sys` inside `_log_curses_error`
- Test count increased from 22 to 30, covering Unicode preservation, 256-color mapping, color parsing, deterministic suggestions, and conservative dedup

## termepub-reader v1.0.3 — 2026-07-28

Follow-up to v1.0.2 with minor code quality improvements from review.

### Changes

- Fixed misleading comment in `ascii_sanitize` that claimed `.isspace()` was avoided
- Added clarifying comment in `_navigate_selection` explaining why the cached `_selection_index` can become stale after page changes
- Minor indentation consistency fix for `_selection_index` initialization

## termepub-reader v1.0.2 — 2026-07-28

Follow-up to v1.0.1 with performance improvements and correctness fixes.

### Changes

- `next_page` and `prev_page` now call `_get_styled_pages` directly, completing the v1.0.1 optimization that eliminated the `_get_plain_pages` indirection across all navigation paths
- `hex_to_16_color` is memoized with `@functools.lru_cache(maxsize=256)`, avoiding repeated regex parsing and Euclidean distance computation for repeated inline CSS colors during rendering
- Word-selection navigation (`_navigate_selection`) caches the current index in `_selection_index`, replacing an O(n) linear scan on every arrow key press
- Removed redundant `_ensure_page_in_range` call from `_handle_resize` — the main loop already handles page clamping via the `needs_draw` flag after resize
- `EpubBook.__del__` wrapped in try/except to prevent potential crashes during Python interpreter shutdown when module state is partially torn down
- Consolidated duplicate `j` key binding in `usage()` into a single context-aware line

## termepub-reader v1.0.1 — 2026-07-27

Performance fix: `_ensure_page_in_range` now calls `_get_styled_pages` directly instead of going through `_get_plain_pages`, eliminating an unnecessary fragment-to-plain-text conversion on every page navigation and resize event.

## termepub-reader v1.0.0 — 2026-07-26

v1.0.0 is the first stable termepub-reader release. It promotes the hardened v0.5.6 codebase after comprehensive parser, pagination, terminal, malformed-input, and real-PTY testing. The command line and state-file format remain compatible.

The 1.0 baseline is suitable for daily reading: core navigation, search, bookmarks, themes, CSS rendering, dictionary lookup, file switching, terminal resizing, and hostile-input limits are implemented and covered by automated tests.

### Highlights

- Correct tag-aware HTML style inheritance, including malformed nested markup
- Reliable heading metadata through segment merging and pagination
- One rendered-page model for page counts, navigation, progress, and search
- Phrase search across rendered line and page boundaries
- Scrollable information and dictionary popups
- Idle UI no longer redraws continuously
- Safer terminal-resize handling without signal-handler curses calls or resize feedback loops

### EPUB safety

Untrusted or malformed EPUB archives now have explicit limits for:

- Archive member count
- Individual decompressed text-member size
- Total decompressed text size
- Suspicious compression ratios

All relevant ZIP reads are bounded. Books without readable spine chapters are rejected before the reader UI starts.

### State and file handling

- Invalid state-file shapes and malformed entries fall back safely
- File-picker navigation remains valid when filtering produces an empty list
- Letter jumps operate on the visible filtered result set
- Opening another book preserves `--no-css`
- A failed replacement book leaves the current book open

### Terminal behavior

- The main loop sleeps without repainting when `getch()` reports no input
- TOC input blocks while idle and responds correctly to terminal resizing
- Resize events are reconciled in the main loop
- Long popups support Up/Down and Page Up/Page Down scrolling

### Verification

- 22 focused pytest regression tests
- 705 responsive reader-layout configurations
- 564 responsive file-picker configurations
- 9 real-PTY static terminal sizes
- 5 live real-PTY resize transitions
- Python compilation and whitespace checks pass
- No new runtime dependencies
