# termepub-reader

A terminal-based (NCurses) ePUB reader with a clean, keyboard-driven interface. Built for offline reading in terminal environments.

**Version:** 1.0.3 (2026-07-28)

## Features

- **File Picker:** Browse and open EPUB files with advanced navigation
- **Navigation:** Page/chapter forward/back (arrow keys)
- **Table of Contents:** Interactive TOC with visual selection indicator (=>) - *v0.4.4*
- **Search:** Full-text search with chapter highlighting
- **Bookmarks:** Save and restore reading position
- **Themes:** Dark/light mode toggle
- **Progress Tracking:** Overall book pagination with percentage
- **CSS Styling:** Inline CSS support (bold, underline, italic, colors) - *v0.4.2*
- **Justified Text:** Toggle justified text alignment (j key) - *v0.4.11*
- **Proper Word Wrapping:** No mid-word breaks - *v0.4.10*
- **Dictionary Lookup:** Built-in dictionary with 160K words (d key) - *v0.4.12*
- **Word Selection Mode:** Visual word selection with arrow keys - *v0.4.13*
- **Direct Dictionary Prompt:** Type any word to lookup (? key) - *v0.4.15*
- **Help Dialog:** Press h to see all key bindings - *v0.5.1*
- **Clean Status Bar:** Simplified footer with just position info - *v0.5.1*
- **Colored Headings:** Chapter headings in yellow+bold, toggle with g key - *v0.5.3*
- **Debug Mode:** Set TERM_EPUB_DEBUG=1 for curses error logging - *v0.5.4*
- **Responsive Layout:** Terminal resize support — adapts to any window size, no wrap-around overflow - *v0.5.5*
- **Robust EPUB Handling:** Safe bounded archive reads, reliable pagination, and hardened malformed-book handling - *v0.5.6*

## Controls

| Key | Action |
|-----|--------|
| `←/→` | Page navigation |
| `↑/↓` | Chapter navigation |
| `t` | Table of contents |
| `/` | Search |
| `b` | Bookmark |
| `o` | Open book (file picker) |
| `s` | In picker - start live search/filter |
| `j` | In picker - jump to letter |
| `j` | In reader - toggle justified text - *v0.4.11* |
| `d` | Dictionary selection mode (visual word selection) - *v0.4.13* |
| `?` | Dictionary lookup prompt (type any word) - *v0.4.15* |
| `m` | Toggle theme |
| `h` | Show help dialog - *v0.5.1* |
| `H` | Toggle header - *v0.5.1* |
| `g` | Toggle heading style (bold/reverse) |
| `q` | Quit |

**Dictionary Selection Mode (v0.4.13):**
1. Press `d` to enter selection mode (first word highlighted in reverse video)
2. Use arrow keys (←/→/↑/↓) to navigate between words
3. Press `Enter` to look up the highlighted word
4. Press `Esc` to cancel selection

## Usage

```bash
termepub.py [book.epub] [--bookmark] [--no-css] [--version]
```

**Options:**
- `--bookmark`: Open book at saved bookmark position
- `--no-css`: Disable inline CSS styling (faster on slow devices)
- `--version`: Show version number and exit

## Installation

1. Clone this repository
2. Make the script executable:
   ```bash
   chmod +x termepub.py
   ```
3. Run it:
   ```bash
   ./termepub.py
   ```

## CSS Styling Support (v0.4.2+)

The reader now supports inline CSS styling from EPUB files:

**Currently rendered:**
- **Bold text:** `<b>`, `<strong>`, `font-weight: bold`
- **Underline:** `<u>`, `text-decoration: underline`
- **Italic:** `<i>`, `<em>`, `font-style: italic` (terminal-dependent)
- **Line-through:** `<s>`, `<strike>`, `<del>` (terminal-dependent)
- **Colors (v0.4.9):** 
  - Hex: `color: #rrggbb` or `color: #rgb`
  - RGB: `color: rgb(r,g,b)`
  - Named: `color: red`, `blue`, `green`, `yellow`, `purple`, `cyan`, `magenta`, `orange`, `pink`, `brown`, `navy`, `teal`, `olive`, `maroon`, `lime`, `aqua`, `fuchsia`, `black`, `white`
  - Colors adapt to current theme (dark/light mode)

## Requirements

- Python 3.9+
- No external dependencies (uses only stdlib: `zipfile`, `xml.etree`, `html.parser`, `curses`)
- Dictionary file (`ecdict_index.json`) auto-installed to `~/.config/termepub/` on first run (21MB)

## State

User state (bookmarks, reading position) is stored in `~/.config/termepub/state.json`.

## License

MIT

## Author

Ifor Evans - [@iforevans](https://github.com/iforevans)

---

## Recent Changes

### v1.0.3 (2026-07-28) - Code Quality

- Fixed misleading comment in `ascii_sanitize`
- Added clarifying comment in `_navigate_selection` for stale index handling
- Minor indentation consistency fix

### v1.0.2 (2026-07-28) - Performance & Correctness

- `next_page`/`prev_page` now call `_get_styled_pages` directly, matching the v1.0.1 fix for `_ensure_page_in_range`
- `hex_to_16_color` is memoized with `@functools.lru_cache(maxsize=256)` to avoid repeated color-distance computation during rendering
- Word-selection navigation caches the current index instead of scanning `all_word_positions` on every arrow key press
- Removed redundant `_ensure_page_in_range` call from `_handle_resize` (the main loop already handles it via `needs_draw`)
- `EpubBook.__del__` wrapped in try/except to prevent interpreter-shutdown crashes
- Consolidated duplicate `j` key binding in `usage()` output

### v1.0.1 (2026-07-27) - Performance Fix

- `_ensure_page_in_range` now calls `_get_styled_pages` directly, skipping an unnecessary fragment-to-plain-text conversion on every page navigation and resize event
- Aligned docstring version with `__version__`

### v1.0.0 (2026-07-26) - First Stable Release

termepub-reader is now considered stable for daily use. The 1.0 release promotes the hardened v0.5.6 codebase after comprehensive parser, pagination, terminal, malformed-input, and real-PTY testing. It introduces no incompatible command-line or state-file changes.

**Stability baseline:**
- Reliable EPUB parsing, navigation, pagination, progress, search, bookmarks, themes, CSS styling, dictionary lookup, and file switching
- Bounded handling of untrusted EPUB archive content
- Responsive curses layout with verified live terminal resizing
- Zero-redraw idle loop and blocking modal input
- No runtime dependencies beyond Python's standard library
- 22 focused regression tests plus 1,269 responsive layout checks and 14 real-PTY scenarios

### v0.5.6 (2026-07-26) - Reliability, Security & Test Coverage

**Correctness:**
- Fixed HTML style-stack corruption so nested and malformed tags no longer drop or leak styles
- Preserved heading metadata when adjacent text segments are merged
- Unified page counting, progress, navigation, and search around rendered styled pages
- Search now finds phrases spanning rendered lines and page boundaries
- File-picker filtering and letter jumping now use the visible result set safely
- Switching books preserves `--no-css` and keeps the current book open if the replacement fails
- Malformed state entries are discarded safely, and EPUBs with no readable spine chapters are rejected cleanly

**Security & Resource Safety:**
- Added limits for EPUB member count, individual decompressed text size, total decompressed text, and suspicious compression ratios
- Added bounded ZIP-member reads to prevent malformed or hostile books from consuming unbounded memory

**Terminal UX & Performance:**
- Stopped idle redraws; the main loop now sleeps without repainting when no key is pressed
- Prevented resize-event feedback loops and kept curses calls out of the SIGWINCH handler
- TOC input blocks while idle and handles terminal resize events
- Long information and dictionary popups are now scrollable

**Tests:**
- Added 22 focused pytest regressions covering parsing, pagination, search, state, EPUB limits, picker behavior, popup scrolling, and idle-loop behavior
- Strengthened the real-PTY suite to require post-resize output with the title and footer at the new geometry
- Responsive suite covers 705 reader layouts and 564 file-picker layouts; PTY suite covers 9 static sizes and 5 live resizes

### v0.5.5 (2026-07-26) - Responsive Terminal Layout

**Features:**
- Full terminal resize support — app adapts to any window size
- Real-time resize detection via a flag-only SIGWINCH handler with main-loop ioctl reconciliation
- Proper styled-page cache invalidation on resize, with height and width in cache keys
- Total pages recomputed on resize for accurate pagination
- Dictionary prompt input survives terminal resize (bounds-safe addnstr with try/except)
- Info popup with terminal-too-small guard and clamped dimensions

**Tests:**
- MockStdscr sweep: 1,269 render configurations (widths 20-160, multiple heights)
- Real PTY + pyte: 9 static sizes + 5 live SIGWINCH resizes

### v0.5.4 (2026-07-20) - Performance & Code Quality

**Performance:**
- **ascii_sanitize: 3x faster:** Uses `str.translate` table for 23 single-character replacements instead of 34 sequential `str.replace()` calls. Remaining 9 multi-char replacements (em dash, ellipsis, arrows) still use replace.

**Code Quality:**
- **Named constants:** All magic numbers replaced with named constants (`KEY_ESCAPE`, `KEY_ENTER`, `COLOR_PAIR_TITLE`, etc.) for readability and maintainability.
- **Debug mode:** Set `TERM_EPUB_DEBUG=1` to log curses rendering errors to stderr with coordinates.

### v0.5.3 (2026-07-20) - Headings, Colors & Bug Fixes

**New Features:**
- **Colored chapter headings:** h1-h6 headings render in yellow+bold for easy scanning
- **Heading style toggle (`g` key):** Switch between yellow+bold and reverse video

**Bug Fixes:**
- **Duplicate chapter headings:** `<head>` content (including `<title>`) is now skipped during parsing, eliminating duplicate plain-text headings that appeared alongside styled `<h1>` headings
- **All text colors broken after initial popup:** `setup_colors()` now guards against re-initialization, preventing `curses.start_color()` from failing on second call and disabling all color rendering
- **Search jumps to wrong page:** `search()` now operates against styled pages (same data used for rendering) instead of raw chapter text, ensuring search results land on the correct page
- **Fuzzy dictionary suggestions freeze UI:** Length-filtered word matching is now capped at 5000 candidates to prevent freezing on misspelled lookups

**Performance:**
- **Color lookup tables moved to module level:** `_NAMED_COLORS` and `_ANSI_COLORS` are now module-level constants, eliminating per-character dict/list allocation during rendering

**Cleanup:**
- Removed dead code: `_guess_title`, `_get_page_text`, `ensure_dictionary`

### v0.5.2 (2026-07-12) - Bug Fixes & Performance

**Bug Fixes:**
- **ZipFile resource leak:** `EpubBook` now properly closes its underlying ZipFile handle. Added `close()` method and `__del__` for cleanup. Switching books via the file picker no longer leaks file handles.
- **`paragraphs.index(para)` O(n) bug in popup renderer:** Replaced with enumerate-based index tracking. Fixes incorrect behavior with duplicate paragraph text and eliminates quadratic cost.
- **Duplicate `import os` inside `main()`:** Removed redundant local import (already at module level).
- **Shebang portability:** Changed from `#!/usr/local/bin/python3.9` to `#!/usr/bin/env python3`.

**Performance:**
- **Dictionary fallback uses `set` instead of linear file scan:** `words.txt` is loaded once into a `set` on first lookup (~466K words, O(1) membership). Previously did a sequential line-by-line scan on the main thread that froze the UI.
- **Cache key now includes `justify_text` and `theme`:** Eliminates fragile manual cache clearing on toggle. The styled pages cache now invalidates naturally when these settings change.

**Cleanup:**
- Removed `*.epub` from `.gitignore` — test EPUBs were never tracked in git.

### v0.5.1 (2026-04-06) - Help Dialog & Clean Status Bar

**Summary:** Cleaned up the UI by moving key hints to a help dialog and simplifying the status bar.

**Changes:**
- **Help dialog (`h` key):** Shows all key bindings in a nicely formatted popup
- **Clean status bar:** Footer now shows `Chapter X/Y | Page A/B | Z% | h=help`
- **Header toggle:** Moved to `H` (uppercase) to free up `h` for help
- **Fixed Unicode rendering:** Help dialog uses ASCII instead of arrow symbols
- All key bindings documented in one place

**Rationale:** The status bar was getting crowded with too many key hints. Moving them to a help dialog keeps the UI clean while making it easy to look up controls.

### v0.5.0 (2026-04-06) - Major Milestone Release

**Summary:** A stable, feature-complete terminal EPUB reader ready for daily use.

**New in this release:**
- **Direct dictionary prompt:** Press `?` to type any word to look up
- **Visual word selection:** Press `d` to highlight and select words on screen
- **Enter key confirmation:** More intuitive selection mode (Enter to lookup)
- **Full CSS support:** Inline styling with colors, bold, italic, underline
- **Polished UX:** Proper word wrapping, justified text toggle, progress tracking

**This release represents:**
- 9 days of active development (v0.4.7 → v0.5.0)
- 8 versions of iterative improvement
- Extensive testing on Gemini PDA
- A stable foundation for future enhancements

### v0.4.15 (2026-04-06) - Direct Dictionary Prompt

**New Feature:**
- **Direct word lookup:** Press `?` to prompt for any word to look up (not just words on screen)
- **Separate from selection mode:** `d` is for visual selection, `?` is for typing any word
- **Full input support:** Type word, use Backspace, Enter to lookup, Escape to cancel

### v0.4.14 (2026-04-06) - Enter Key to Confirm Selection

**Improvement:**
- **More intuitive confirmation:** Press `Enter` to look up selected word (instead of double-pressing `d`)
- **Updated footer:** Selection mode now shows "Enter to lookup" instead of "'d' to lookup"
- **Standard UI pattern:** `Enter` to confirm is more familiar and expected by users

### v0.4.13 (2026-04-05) - Word Selection Mode

**Features:**
- **Visual word selection:** Press `d` enters selection mode with reverse-video highlight
- **Arrow key navigation:** ←/→ move between words, ↑/↓ move to words on adjacent lines
- **Precise highlighting:** Character-by-character rendering ensures only selected word is highlighted
- **Instant lookup:** Press `Enter` to look up the highlighted word (changed from `d` in v0.4.14)
- **Escape to cancel:** Press `Esc` to exit selection mode without lookup

**Technical:**
- Word positions extracted from styled pages (same source as rendering)
- Positions stored as `(line_num, start_col, end_col)` for accurate mapping
- Selection state: `in_selection_mode`, `selected_line`, `selected_word_start`, `selected_word_end`
- Character-by-character rendering in selection mode for precise highlight boundaries

### v0.4.12 (2026-04-04) - Dictionary Lookup

**Features:**
- **Built-in dictionary:** Press `d` on highlighted word to look up definitions
- **ECDICT dictionary:** 160,000+ words with modern English definitions
- **Smart popup:** Definitions display with proper newlines and formatting
- **Auto-sizing:** Popup adapts to content width (50-90% of screen)
- **Offline-first:** Dictionary file included in repository (21MB)

**Dictionary Source:**
- Uses ECDICT (English-Chinese Dictionary with English definitions)
- Modern definitions from contemporary sources
- Dictionary stored alongside reader code (`ecdict_index.json`)

**Technical:**
- JSON index loaded once, cached in memory
- Preserves paragraph breaks and formatting from definitions
- Popup handles long words by wrapping at word boundaries

### v0.4.11 (2026-04-04) - Justified Text

**Bug Fixes:**
- Fixed word wrapping to respect word boundaries (no more mid-word breaks)
- `_wrap_segments_with_styles` now finds last space before split point
- Falls back to force-break only for extremely long words with no spaces

**Technical:**
- Uses `rfind(' ')` to locate word boundaries before line breaks
- Strips trailing/leading whitespace at split points for clean wrapping

### v0.4.11 (2026-04-04) - Justified Text

**Features:**
- Toggle justified text alignment with `j` key (shows "j ON" / "j OFF" in footer)
- Justification distributes extra space evenly between words
- Last line of paragraphs remains left-aligned (standard typesetting)
- Justification preference persists across sessions
- Removed redundant `j/k` and `n/p` navigation shortcuts (cursor keys only)

### v0.4.10 (2026-04-04) - Word Wrap Fix

**Bug Fixes:**
- Fixed word wrapping to respect word boundaries (no mid-word breaks)
- Properly splits at last space before line width limit
- Handles extremely long words with forced breaks

### v0.4.9 (2026-04-03) - CSS Colors

**Features:**
- **Inline color rendering:** EPUBs can now display colored text
- **Named CSS colors:** 19 common colors (`red`, `blue`, `green`, etc.)
- **Hex colors:** `#rrggbb` and `#rgb` formats
- **RGB colors:** `rgb(r,g,b)` format
- **Theme-aware:** Colors automatically adapt to dark/light mode
- **Dynamic color pairs:** Efficient curses color pair allocation with caching

**Bug Fixes:**
- Fixed cache invalidation on theme toggle (colors now re-render correctly)
- Fixed cache invalidation on initial load (colors render correctly from start)

**Technical:**
- Added `hex_to_16_color()` function to map CSS colors to curses color indices
- Color pair cache cleared on theme toggle and initial setup
- Background color matches current theme (black for dark, white for light)

### v0.4.8 (2026-03-30) - Style Boundary Fix

**Bug Fixes:**
- Fixed CSS style mapping for wrapped text (styles now preserved across line breaks)
- Deduplicates consecutive identical segments (e.g., duplicate chapter headings)
- Limits consecutive blank lines to avoid excessive whitespace

**Technical:**
- Rewrote text wrapping to use segment-aware algorithm
- Each line can now have multiple style fragments (e.g., "Title: Pride and Prejudice" with "Title" bold)
- Style boundaries are preserved even when text wraps

### v0.4.7 (2026-03-29) - Code Quality & Safety

**Cleanup:**
- Removed dead code: `_get_pages_with_attrs()` (was defined but never called)
- Renamed `_get_pages()` → `_get_plain_pages()` for clarity
- Extracted footer format string to `FOOTER_FORMAT` constant
- Added clarifying comments to status message clears

**Documentation:**
- Added comments to all 13 bare `pass` statements explaining error handling
- Improved docstring for `_get_current_styles()`

**Safety:**
- Added runtime validation for style stack underflow (catches HTML parsing bugs)

**Net change:** -4 lines of dead code, +15 lines of documentation/safety

### v0.4.6 (2026-03-29) - Code Cleanup

**Cleanup:**
- Converted remaining `%` formatting to f-strings (18 instances)
- Improved consistency with modern Python 3.9+ style

### v0.4.5 (2026-03-28) - TOC Improvements

**Features:**
- Added `=>` visual indicator for selected TOC entries
- Removed redundant chapter numbers (cleaner display)
- Added navigation hint in TOC footer

### v0.4.4 (2026-03-28) - Code Quality

**Cleanup:**
- Removed 44 lines of dead code (duplicate methods, unused CSS extraction)
- Added cache invalidation for theme/heading style toggles
- Added `--version` flag
- Added Sparky co-author credit

### v0.4.3 (2026-03-27) - CSS Rendering

**Features:**
- Full inline CSS styling support (bold, underline, italic, line-through)
- StyledSegment dataclass with style stack for CSS inheritance
- Handles semantic tags: `<b>`, `<strong>`, `<i>`, `<em>`, `<u>`, `<s>`

### v0.4.2 (2026-03-25) - Unicode & Popups

**Improvements:**
- Comprehensive Unicode sanitization (34 character replacements)
- Styled popup system with bordered styling
- Better terminal compatibility for complex Unicode content
