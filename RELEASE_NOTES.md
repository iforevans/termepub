# Release Notes

## termepub-reader v0.5.6 — 2026-07-26

v0.5.6 is a reliability and security release focused on making long reading sessions quieter, pagination consistent, malformed EPUB handling predictable, and the test suite worthy of the word “test”.

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
