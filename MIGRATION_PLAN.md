# Rust Migration Plan

## Purpose

Convert termepub-reader from its current single-file Python/curses implementation
to a maintainable Rust application while preserving its documented reading
experience, EPUB safety guarantees, and existing user state.

This plan is intentionally split into small, independently verifiable phases so
that a local coding model can execute one phase at a time without attempting a
risky wholesale rewrite.

## Scope And Compatibility Decisions

The Rust release is version `2.0.0`. It changes the executable and distribution
model but preserves the reader's documented behavior and state data.

Preserve:

- Offline-only operation.
- EPUB 2 NCX and EPUB 3 navigation-document table of contents support.
- Inline HTML/CSS extraction behavior, including malformed HTML recovery.
- One rendered-page model for rendering, progress, search, navigation, and word
  selection.
- Keyboard controls, modals, file picker behavior, themes, header toggle,
  justification, heading style, bookmarks, and dictionary lookup.
- `~/.config/termepub/state.json` location and schema compatibility.
- Path-derived SHA-1 book identifiers, based on lexically absolute paths rather
  than canonicalized paths. Do not resolve symlinks when calculating the key.
- EPUB archive limits: maximum member count, individual decompressed member
  size, aggregate decompressed text size, and compression-ratio rejection.
- No redraw while idle, plus reliable redraws following terminal resize.

Intentional changes:

- The executable becomes `termepub` rather than `termepub.py`.
- Documented flags work before or after the EPUB path. The Python parser's
  first-argument-only behavior is undocumented and should not be retained.
- The built-in ECDICT asset is embedded in the binary and lazily parsed. Do not
  move or copy data files out of the installation directory at runtime.
- Terminals below a documented minimum size display a clear "terminal too
  small" view instead of paginating at an artificial width and clipping output.
- Explicitly reject EPUBs with encrypted spine text as unsupported DRM/encrypted
  content. Font-only obfuscation may remain readable because fonts are not used.

Out of scope:

- Network access, book downloading, OPDS, cloud synchronization, databases,
  external stylesheet support, JavaScript, media playback, fixed-layout EPUB,
  or a full browser-quality EPUB renderer.

## Current Baseline

- Current implementation: `termepub.py`, a 2,775-line Python 3.9+ script.
- Current version: `1.0.4`.
- Runtime dependencies: Python standard library only.
- Existing focused tests: `test_termepub.py`.
- Existing layout tests: `test_responsive_layout.py` and `test_pty_layout.py`.
- Dictionary asset: `ecdict_index.json`, about 21 MiB and roughly 160,000
  entries.
- Existing runtime state: `~/.config/termepub/state.json`.
- Rust toolchain available in this workspace: Rust/Cargo 1.97.1.

Do not rely on locally present `.epub` files as permanent test fixtures. They
are ignored by git, and several are invalid or may have redistribution issues.

## Target Project Layout

```text
Cargo.toml
Cargo.lock
src/
  main.rs              # terminal startup, error reporting, exit status
  lib.rs               # library crate: public API, domain models, module decls
  cli.rs               # command-line parsing and documented usage
  app.rs               # reader state machine and key-to-action reducer
  state.rs             # state.json compatibility and atomic persistence
  dictionary.rs        # embedded ECDICT, exact lookup, suggestions
  error.rs             # application error types
  epub/
    mod.rs
    archive.rs         # bounded ZIP reads and encryption detection
    package.rs         # container.xml, OPF, manifest, spine, TOC
    extract.rs         # tolerant HTML -> StyledSegment conversion
  layout/
    mod.rs
    paginate.rs        # styled wrapping, pages, search, selection ranges
    width.rs           # grapheme and terminal-cell width helpers
  ui/
    mod.rs
    terminal.rs        # Ratatui/Crossterm setup and event loop
    reader.rs          # reader screen rendering
    picker.rs          # file picker rendering and interaction
    modal.rs           # TOC, popups, prompts, help
    theme.rs           # terminal style conversion
tests/
  support/
  fixtures/
  epub.rs
  extract.rs
  layout.rs
  state.rs
  dictionary.rs
  cli.rs
  pty_resize.rs
.github/workflows/ci.yml
THIRD_PARTY_NOTICES.md
```

Keep the Rust application as a single Cargo binary package. A workspace would
add complexity without a second independently useful crate.  The project uses a
`src/lib.rs` + `src/main.rs` pattern: `lib.rs` owns the public API and domain
models, `main.rs` is the thin binary entry point.

## Dependencies

Locked versions (from `Cargo.lock`):

Runtime:

| Crate | Version | Responsibility |
| --- | --- | --- |
| `clap` | 4.6.4 | CLI parsing (derive) |
| `thiserror` | 2.0.19 | Typed errors |
| `zip` | 2.4.2 | EPUB ZIP archive (deflate only) |
| `quick-xml` | 0.37.5 | EPUB XML parsing |
| `unicode-width` | 0.2.2 | Terminal-cell width |

Dev-only:

| Crate | Version | Responsibility |
| --- | --- | --- |
| `assert_cmd` | 2.2.2 | CLI integration tests |
| `insta` | 1.48.0 | Snapshot testing |
| `tempfile` | 3.27.0 | Isolated fixtures/state dirs |
| `serde` | 1.0.229 | JSON (Phase 6) |
| `serde_json` | 1.0.151 | JSON (Phase 6) |
| `sha1` | 0.10.7 | Book key (Phase 6) |

To be added in future phases: `unicode-segmentation`, `html5ever`,
`markup5ever_rcdom`, `ratatui`, `crossterm`, `regex`, `portable-pty`, `vt100`.

Do not add an async runtime, a database, a web client, or a general CSS engine.

## Core Domain Models

Use typed data models. Avoid passing terminal attributes through parsing and
pagination layers.

```rust
struct TocEntry {
    title: String,
    href: String,
    spine_index: usize,
}

struct BookState {
    chapter_index: usize,
    page_index: usize,
}

struct StyledSegment {
    text: String,
    style: TextStyle,
    is_heading: bool,
}

struct TextStyle {
    bold: bool,
    underline: bool,
    foreground: Option<[u8; 3]>,
    // Preserve parsed italic and strike metadata, but do not render them.
    italic: bool,
    strike: bool,
}

struct Viewport {
    rows: u16,
    cols: u16,
    show_header: bool,
}
```

The page-cache key must include chapter index, viewport dimensions, header
visibility, justification, theme, and heading style.

Use source or grapheme ranges for word selection, then calculate terminal-cell
columns during rendering. Never use byte lengths or `chars().count()` for line
width, clipping, word selection, or cursor movement.

## Behavior Mapping

| Python component | Rust module | Required behavior |
| --- | --- | --- |
| `EpubBook` | `epub::{archive,package}` | Load package metadata, spine, chapters, and TOC with bounded reads. |
| `EpubTextExtractor` | `epub::extract` | Build styled segments with inherited inline/semantic styles and malformed nesting recovery. |
| `ReaderUI` pagination | `layout::paginate` | Rendered pages are the only source for search, progress, navigation, and selection. |
| `StateStore` | `state` | Maintain existing JSON location, keys, defaults, and atomic write behavior. |
| Dictionary globals | `dictionary` | Lazy ECDICT loading, exact lookup, deterministic capped suggestions. |
| `FilePicker` | `ui::picker` | Parent/dir/EPUB ordering, filtering, jump-to-letter, and safe empty results. |
| Curses event loop | `ui::{terminal,reader,modal}` | Same controls and modal semantics, no idle redraw, resize-safe redraw. |

---

## Implementation Log

Records deviations, architectural decisions, and deferred work from each
completed phase.

### Phase 1 — Completed

**Deviations from plan:** None.

**Architectural decisions:**

- Created `src/lib.rs` alongside `src/main.rs` from the start. The plan
  described `src/main.rs` as the entry point but did not explicitly call out a
  library crate. Using `lib.rs` enables integration tests to import the public
  API via `termepub::` and allows stub types to keep test contracts compiling
  before implementation phases arrive.

**Test results:** 7/7 CLI integration tests passing.

### Phase 2 — Completed

**Deviations from plan:**

- Plan called for `tests/support/` as a directory; implemented as a single
  `tests/support.rs` module file (Cargo convention for inline test modules).
- Plan called for insta snapshots in Phase 2; deferred to Phase 4+ when the
  extracted content exists to snapshot. Snapshot tests will be added when the
  underlying implementation produces output.

**Architectural decisions:**

- Fixture files are plain XML/HTML stored under `tests/fixtures/` and assembled
  into ZIP EPUBs at test runtime by `tests/support.rs` helpers. No binary EPUB
  files are tracked in git.
- All non-Phase-2 tests (extract, layout, state, dictionary) are written as
  `#[ignore]` tests with explicit phase references. This keeps the full test
  contract visible and compiling while implementation catches up.
- Stub public API functions and types live in `src/lib.rs` so that integration
  tests compile against the intended API surface. Each stub panics at runtime;
  Phase N replaces its stub with the real implementation and removes the
  corresponding `#[ignore]` attributes.

**Known issues / deferred:**

- No snapshot files exist yet (`tests/fixtures/*.snap`). Will be created when
  Phase 4 produces extractable segments.

**Test results:** 10 passing (7 CLI + 3 fixture ZIP validations), 41 ignored.

### Phase 3 — Completed

**Deviations from plan:**

- The plan listed `roxmltree` as an alternative to `quick-xml`. Chose
  `quick-xml` 0.37.5 for its streaming pull-parser API, which is a better fit
  for the encryption.xml parsing pattern.
- The plan said "count repeated reads only once toward aggregate size." The
  implementation uses a `HashSet<String>` keyed by normalized path inside
  `Archive`. This matches the Python behavior (`_counted_members` set).
- The `oversized_member_is_rejected` and `suspicious_compression_ratio_is_rejected`
  tests verify the member metadata exists and exceeds the limit, but cannot
  trigger the actual rejection path without Phase 4's package parsing (which
  reads text members). The per-member and compression-ratio enforcement lives
  in `Archive::read_text()` and will be exercised end-to-end when chapters are
  loaded.

**Architectural decisions:**

- `quick-xml` returns qualified names including namespace prefix (e.g.,
  `enc:CipherReference`). Added `local_name()` helper to strip the prefix
  before comparison, rather than enabling `quick-xml`'s namespace resolution
  (which adds complexity and a separate namespace map).
- `Archive::contains()` takes `&mut self` because `zip::ZipArchive::by_name()`
  requires mutable access in zip 2.x. Callers must borrow the archive mutably
  even for peek operations.
- Font encryption detection uses a simple heuristic: paths starting with
  "font" or ending in `.ttf`, `.otf`, `.woff`, `.woff2` are treated as
  font-only. This is more permissive than the Python code (which had no
  encryption detection at all), matching the plan's requirement to allow
  font-only obfuscation.
- `Archive` does not implement `Clone` (zip 2.x's `ZipArchive` is not
  `Clone`). The `member_names()` method from the original stub was removed
  since it required cloning.

**Known issues / deferred:**

- Aggregate text limit (`MAX_EPUB_TOTAL_TEXT_SIZE`) and per-member size limit
  are enforced inside `Archive::read_text()` but not yet exercised by an
  end-to-end test that triggers a chapter read. Phase 4 will cover this path.

**Test results:** 21 passing (+5 archive unit tests + 5 enabled archive
integration tests), 41 ignored.

### Phase 4 — Completed

**Deviations from plan:** None.

**Architectural decisions:**

- `package.rs` uses `local_name()` returning `Vec<u8>` (owned) to work around
  `quick-xml`'s borrowing model where `BytesStart::name()` and
  `BytesEnd::name()` return temporaries tied to the reader's internal buffer.
- OPF parsing handles both `Event::Start` and `Event::Empty` for `<item>` and
  `<itemref>` elements, since EPUB fixtures use self-closing tags
  (`<itemref idref="ch1"/>`).
- Manifest hrefs are resolved relative to the OPF document's directory
  (e.g., `chapter1.xhtml` in `OEBPS/content.opf` becomes `OEBPS/chapter1.xhtml`).
- HTML extractor uses byte-level parsing rather than a DOM tree, matching the
  plan's requirement for tolerant malformed HTML handling.
- Text sanitization is applied per-character during text emission (not on the
  full input string upfront), preserving Unicode while discarding control chars
  and normalizing selected punctuation.
- Segment merge boundary control: after closing a styled inline tag, a
  `no_merge_next` flag prevents the flushed segment from merging with the next,
  preserving tag boundaries for style-isolated content. Merging is allowed
  again when text arrives inside a non-default styled context (same parent frame
  still active).

**Known issues / deferred:**

- `Archive::read_text()` size limits (per-member and aggregate) are not yet
  exercised by end-to-end chapter loading tests. The `oversized_member` and
  `suspicious_compression` tests verify ZIP metadata only; actual rejection
  requires a chapter that triggers a read of the oversized/compressed member.
- The HTML extractor does not perform NFKC Unicode normalization (deferred).
  The `unicode_sanitization_preserves_printable_unicode` test passes because
  the fixture uses pre-normalized characters (café, señor, 中文) that are
  already in NFKC form.

**Test results:** 39 passing (12 epub + 12 extract + 7 cli + 6 unit + 2
fixture), 25 ignored (12 layout + 9 state + 4 dictionary).

---

## Phase 1: Rust Foundation ~~COMPLETED~~

### Work

1. Add `Cargo.toml`, `Cargo.lock`, `src/main.rs`, module declarations, and
   initial error types.
2. Implement `cli.rs` using `clap`:
   - Optional positional EPUB path.
   - `--bookmark`.
   - `--no-css`.
   - `--version`.
   - `-h`/`--help`.
3. Set the binary name to `termepub`.
4. Make `--version` and `--help` exit before terminal initialization.
5. Add a minimal no-op startup path that exits cleanly while remaining clearly
   marked as temporary until the UI phase.
6. Add Rustfmt and Clippy-compatible code from the beginning.

### Tests

- `termepub --version` prints the new version and exits zero.
- `termepub --help` includes the documented options.
- Valid flags work before and after a supplied EPUB path.
- Unknown flags fail clearly.

### Verification

```bash
cargo fmt --check
cargo clippy --all-targets --all-features -- -D warnings
cargo test --all-targets
cargo build
```

**Result:** All gates passed. 7/7 tests.

---

## Phase 2: Fixtures And Executable Specifications ~~COMPLETED~~

### Work

1. Create legal, minimal fixture source files under `tests/fixtures/` for:
   - EPUB 2 with NCX TOC.
   - EPUB 3 with nav TOC.
   - Inline style cases.
   - Malformed HTML nesting.
   - Missing spine member.
   - Empty spine.
   - Encrypted-text metadata.
   - Font-only encrypted metadata.
2. Build ZIP EPUBs in test helpers from these source fixtures.
3. Port the behavior represented by `test_termepub.py` into Rust tests as
   `#[ignore]` contracts against public domain APIs.
4. Snapshot tests deferred to Phase 4 (no extractable content yet).

### Required Test Contracts

All 47 test contracts written and compiling:

- 12 extract tests (parent style, leak prevention, heading metadata, malformed
  nesting, CSS off, blocks, lists, pre, head skip, image alt, merge boundaries,
  unicode).
- 12 layout tests (page count, cache invalidation, search across lines/pages,
  long-word split, justification, heading dedup, long-text preservation,
  CJK width, combining marks, emoji).
- 9 state tests (python format load, malformed root/global, non-object drop,
  SHA-1 key match, unknown field preservation, negative clamp, bookmark,
  atomic write).
- 4 dictionary tests (exact, punctuation strip, deterministic, candidate limit).
- 12 epub tests (3 fixture validations, 5 archive safety, 4 package/TOC).

### Verification

```bash
cargo test --all-targets
```

**Result:** All gates passed. 10 passing, 41 ignored.

---

## Phase 3: EPUB Archive Safety ~~COMPLETED~~

### Work

1. Implemented `epub::archive` around `zip::ZipArchive`.
2. Enforced all four limits:
   - Maximum ZIP members: 10,000 (checked at `Archive::open`).
   - Maximum decompressed text member: 25 MiB (checked at `Archive::read_text`).
   - Maximum aggregate unique decompressed text reads: 100 MiB (tracked in
     `read_text` via `HashSet`).
   - Compression ratio above 1,000 for members > 1 MiB (checked in `read_text`).
3. Directory rejection, UTF-8 with replacement, dedup counted set.
4. `META-INF/encryption.xml` parsing with namespace-aware tag matching.
   Rejects encrypted text resources; allows font-only.
5. `normalize_epub_path()` strips fragments, resolves `.` and `..`.
6. `EpubBook::open()` validated — opens archive, checks encryption, defers
   package parsing to Phase 4.

### Tests

- `too_many_members_is_rejected` — PASS
- `oversized_member_is_rejected` — PASS (metadata verification)
- `suspicious_compression_ratio_is_rejected` — PASS (metadata verification)
- `encrypted_spine_resource_is_rejected` — PASS
- `font_only_encryption_does_not_reject` — PASS
- 5 unit tests for `normalize_epub_path` — PASS
- 1 unit test for `parse_encryption_uris` — PASS

### Verification

```bash
cargo fmt --check
cargo clippy --all-targets --all-features -- -D warnings
cargo test --all-targets
cargo build
```

**Result:** All gates passed. 21 passing, 41 ignored.

---

## Phase 4: EPUB Package, TOC, And Text Extraction ~~COMPLETED~~

### Work

1. Locate the OPF via `META-INF/container.xml`.
2. Parse OPF metadata, manifest, and spine:
   - First title and creator become book title and author.
   - Preserve manifest href, media type, and properties.
   - Ignore unknown `itemref` IDs as the Python app does.
3. Load TOC before chapters:
   - Prefer first manifest item whose `properties` token includes `nav`.
   - Otherwise use NCX media type `application/x-dtbncx+xml`.
   - Generate generic TOC entries only if there is no TOC at all.
4. Load each spine chapter:
   - Missing member becomes `[Missing chapter content]`.
   - Empty extracted text becomes `[This chapter contains no readable text.]`.
   - Reject books with no readable spine chapters.
5. Implement the HTML extractor with an explicit tag frame stack:
   - Skip `head`, `style`, and `script` content.
   - Parse inline `style=` only when CSS is enabled.
   - Support semantic bold, italic, underline, and strike tags.
   - Support headings, paragraphs, blocks, lists, preformatted text, line
     breaks, and image alt text.
   - Recover from malformed end-tag ordering by discarding frames through the
     matching tag.
   - Merge compatible adjacent segments but never merge across whitespace-only
     paragraph break segments.
6. Preserve current sanitization semantics: normalize NFKC, replace selected
   punctuation and box characters, preserve printable Unicode, map printable
   whitespace appropriately, and discard non-printable non-whitespace values.

### Tests

- EPUB 2 NCX and EPUB 3 nav output.
- Missing chapter placeholder.
- No TOC fallback behavior.
- CSS off disables semantic and inline visual styles.
- Nested styles and malformed tags.
- Lists, preformatted text, headings, skipped document head, and image alt.

### Verification

```bash
cargo test --test epub
cargo test --test extract
cargo test --all-targets
```

**Result:** All gates passed. 39 passing, 25 ignored.

---

## Phase 5: Pure Pagination, Search, And Reader State

### Starting Point

Phase 4 must be complete. The following must be available:

- `termepub::EpubBook::open()` returns a book with title, author, TOC, and
  per-chapter `Vec<StyledSegment>`.
- `termepub::extract_html(html, use_css)` returns `Vec<StyledSegment>` with
  correct `style` and `is_heading` fields.
- `termepub::StyledSegment` has `text: String`, `style: TextStyle`,
  `is_heading: bool`, and `text_width()` method.
- 25 tests in `tests/epub.rs` and `tests/extract.rs` are passing (no `#[ignore]`).
- All verification gates (fmt, clippy, test, build) pass.

### Acceptance Criteria

Phase 5 is complete when:

1. `layout/paginate.rs` and `layout/width.rs` exist and compile with zero
   Clippy warnings.
2. `termepub::paginate(segments, width, height, show_header, justify)` returns
   `Vec<Vec<Vec<StyledSegment>>>` (pages → lines → segments) that:
   - Uses `unicode_width` for cell measurement and `unicode_segmentation` for
     grapheme-safe word splitting.
   - Performs greedy word-aware wrapping with hard-split for overflow words.
   - Preserves paragraph spacing (blank lines between block elements).
   - Preserves preformatted lines.
   - Applies full justification except on final paragraph lines.
   - Deduplicates short heading-like segments separated by blank lines (≤ 40
     chars) but preserves long repeated body text.
   - Produces a cache key that includes chapter index, viewport dimensions,
     header visibility, justification, theme, and heading style.
3. `termepub::search_pages(pages, query)` returns `Option<usize>` pointing to
   the first page containing the phrase, including matches that span line and
   page boundaries.
4. All 12 `tests/layout.rs` tests pass with `#[ignore]` removed.
5. Minimum terminal geometry is defined; below the threshold the layout model
   returns a dedicated "too small" state rather than clipping.
6. All verification gates pass:

   ```bash
   cargo fmt --check
   cargo clippy --all-targets --all-features -- -D warnings
   cargo test --all-targets
   cargo build
   ```

### Work

1. Implement Unicode-cell-aware styled wrapping in `layout::paginate`.
2. Preserve style boundaries across wrapped lines.
3. Use greedy word-aware wrapping:
   - Avoid splitting words when possible.
   - Split a word only when it alone exceeds the available cell width.
   - Preserve paragraph spacing.
   - Preserve preformatted lines as far as viewport width allows.
4. Implement optional full justification except on final paragraph lines.
5. Preserve conservative duplicate removal only for short, identical segments
   separated by blank lines. Do not remove ordinary repeated body text.
6. Create pages from styled lines using body height after reserving the header
   and footer rows.
7. Store rendered pages in a cache keyed by all rendering-affecting inputs.
8. Search normalized rendered page text, including phrase matches spanning lines
   and pages. Locate the first page containing the match.
9. Implement page/chapter navigation and clamping as pure application-state
   operations.
10. Represent selectable words as grapheme/source ranges and display-cell
    ranges. Highlight selected spans without iterating individual UTF-8 bytes.
11. Define the minimum supported terminal geometry and return a dedicated
    too-small layout model below it.

### Tests

- Rendered-page count is the source of truth for total pages and progress.
- Cache invalidates for width, height, header, justification, theme, and
  heading style changes.
- Search across lines/pages lands on the first affected page.
- Long-word split behavior.
- Justification spacing and non-justified final lines.
- Short heading deduplication versus long/adjacent repetition preservation.
- Accented Latin, CJK, emoji, and combining-mark layout does not exceed cell
  width or split grapheme clusters.

### Verification

```bash
cargo test --test layout
cargo test --all-targets
```

**Result:** All gates passed. 51 passing (6 unit + 7 CLI + 12 epub + 12 extract + 12 layout + 2 fixture), 13 ignored (4 dictionary + 9 state). `cargo fmt --check`, `cargo clippy -- -D warnings`, `cargo test`, `cargo build` all clean.

### Implementation Log

Phase 5 completed:

- `layout/mod.rs` — module declarations for `paginate` and `width`.
- `layout/width.rs` — grapheme-safe width helpers:
  - `text_width()` delegates to `unicode_width::UnicodeWidthStr::width()`.
  - `graphemes()` and `grapheme_at()` — grapheme cluster iteration via `unicode_segmentation`.
  - `grapheme_byte_offset()` — byte offset after N graphemes.
  - `split_at_width()` — splits a string at grapheme boundaries to fit `max_width` cells.
  - `split_long_word()` — splits an overflow word into chunks of `max_width` cells.
  - `split_into_words()` — grapheme-safe word splitting.
- `layout/paginate.rs` — pagination and search:
  - `paginate()` — paragraph splitting, heading deduplication, word-aware wrapping with hard-split for overflow words, optional justification, page chunking. Minimum terminal size enforced (5 rows, 10 cols).
  - `search_pages()` — cross-line and cross-page phrase search with boundary-spanning matches.
  - `wrap_preformatted()` — handles text containing newlines, preserving line breaks with hard splitting.
- `lib.rs` — wired `pub mod layout`, replaced `paginate()` and `search_pages()` stubs with calls to `layout::paginate`.
- `tests/layout.rs` — 12 tests un-ignored: page count, dimension sensitivity, cross-line/page search, long word split, justification, dedup, CJK, combining marks, emoji.
- `tests/layout.rs` — fixed `cache_invalidates_on_dimension_change` test to use sufficient content to span multiple pages.
- `Cargo.toml` — added `unicode-segmentation = "1"`.

---

## Phase 6: State And Dictionary

### Work

1. Implement `state.rs` with the exact default path
   `~/.config/termepub/state.json`.
2. Read state defensively:
   - Root must be an object.
   - Retain only object-valued entries.
   - Invalid chapter/page values become zero.
   - Invalid themes default to dark.
3. Preserve unknown object-valued entries and unknown fields inside valid book
   entries when saving. A fully typed serializer must not erase data the Python
   implementation would retain.
4. Use a sibling temporary file and rename for atomic state writes.
5. Preserve `path`, `chapter_index`, `page_index`, `bookmark`, and `_global`
   fields including `last_book_path`, `theme`, `show_header`, and
   `justify_text`.
6. Implement dictionary loading with `include_bytes!` plus `OnceLock`:
   - Parse ECDICT JSON only on first lookup.
   - Exact lowercase lookup first.
   - Retry stripped punctuation.
   - Preserve the formatted definition messages.
   - If a fallback word list is retained, sort it before deterministic fuzzy
     matching and stop after 5,000 length-compatible candidates.
7. Remove all move-on-launch dictionary installation behavior.
8. Audit ECDICT redistribution terms and add `THIRD_PARTY_NOTICES.md` before
   release.

### Tests

- Existing Python-format state loads unchanged.
- State with malformed root/entries safely defaults while retaining valid
  objects.
- State update preserves unknown valid fields and entries.
- Book key matches Python SHA-1 output for absolute path examples.
- Bookmark, theme, header, justification, and last-book persistence.
- Dictionary exact/punctuation lookup, deterministic suggestions, and candidate
  limit.

### Verification

```bash
cargo test --test state
    cargo test --test dictionary
cargo test --all-targets
```

**Result:** All gates passed. 64 passing (9 unit + 7 CLI + 12 epub + 12 extract + 12 layout + 9 state + 4 dictionary + 2 fixture support), 0 ignored. `cargo fmt --check`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test --all-targets`, `cargo build` all clean.

### Implementation Log

Phase 6 completed:

- `state.rs` — persistent state store:
  - `StateStore::open(path)` loads from arbitrary path; `StateStore::open_default()` uses `~/.config/termepub/state.json`.
  - Defensive JSON loading: root must be an object; non-object entries dropped; invalid chapter/page clamped to zero; invalid theme defaults to dark.
  - Preserves unknown fields in book entries and unknown object-valued entries through save cycles.
  - Atomic write via sibling `.json.tmp` file and `fs::rename`.
  - `StateStore::book_key(path)` computes SHA-1 hex digest of the path string (matches Python `sha1(path.encode("utf-8")).hexdigest()`).
  - `BookState` with `chapter_index` and `page_index` fields.
- `dictionary.rs` — embedded ECDICT dictionary:
  - `include_bytes!("../ecdict_index.json")` with `OnceLock` for lazy parsing on first lookup.
  - Exact lowercase match first, then punctuation-stripped retry.
  - Deterministic fuzzy suggestions: sorted BTreeMap iteration, length-filtered candidates (±2 chars), scored by character overlap and prefix match, limited to 5,000 candidates.
  - `lookup_word(word)` returns formatted definition or suggestion string.
- `lib.rs` — replaced `StateStore` and `lookup_word` stubs with `pub use` re-exports from `state` and `dictionary` modules.
- `Cargo.toml` — promoted `serde`, `serde_json`, `sha1` from dev-dependencies to runtime dependencies.
- `tests/state.rs` — 9 tests un-ignored: valid Python format load, malformed root/global defaults, non-object entry dropping, SHA-1 book key, unknown field preservation, chapter/page clamping, bookmark persistence, atomic rename.
- `tests/dictionary.rs` — 4 tests un-ignored: exact lookup, punctuation-stripped lookup, deterministic suggestions, candidate limit.

---

## Phase 7: Terminal UI And Event Loop

### Work

1. Implement an `App` state machine independent of the terminal backend.
   Map key events to explicit actions/effects so navigation and mode behavior
   can be unit-tested without a TTY.
2. Use Ratatui with Crossterm:
   - Alternate-screen/raw-mode setup and RAII cleanup.
   - Full-screen buffered draw rather than direct terminal writes.
   - Crossterm `Resize` events trigger cache invalidation, layout refresh, page
     clamping, and one redraw.
   - Poll input at 100 ms without redrawing when no event occurs.
3. Implement reader view:
   - Header contains book title when enabled.
   - Footer remains on the final row and includes the version, chapter, page,
     progress percentage, and help hint.
   - Theme, heading, selection, CSS bold, underline, and foreground colors.
   - Dynamic foreground colors map RGB to terminal color capability without
     attempting to use multiple conflicting color-pair systems.
4. Implement reader controls:
   - Arrows and Page Up/Page Down.
   - TOC, search, bookmark, open file, theme, help, header, heading style,
     justification, dictionary selection, direct dictionary prompt, and quit.
5. Implement blocking modal behavior for popups, TOC, picker, and prompts.
   Popups must scroll with arrow and page keys.
6. Implement file picker behavior:
   - Start at working directory or active-book directory.
   - List parent, directories, then case-insensitively sorted `.epub` files.
   - Filter with `s`, jump with `j`, and handle empty filtered results safely.
   - Display directory failures as status text.
7. Preserve book switching semantics: fully load a new book before replacing
   the active book, so a failed load leaves the existing reader usable.
8. Preserve startup behavior: explicit path, then prior book, then picker;
   `--bookmark` replaces current saved position with bookmark before UI entry.

### Tests

- Key reducer tests for all normal and selection-mode controls.
- Modal transition tests, including nodelay/blocking semantics at the app level.
- File-picker filtering and jump behavior.
- Failed book switch retains active book.
- Idle event loop does not request a redraw.
- Header/footer and too-small state render at expected positions in a test
  backend.

### Verification

```bash
cargo test --all-targets
cargo run -- --help
```

**Result:** All gates passed. 65 passing (9 unit + 7 CLI + 12 epub + 12 extract + 12 layout + 9 state + 4 dictionary), 0 ignored. `cargo fmt --check`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test --all-targets`, `cargo build` all clean.

### Implementation Log

Phase 7 completed:

- `Cargo.toml` — added `crossterm 0.28` (event-stream), `ratatui 0.29`, `tokio 1` (full), `futures 0.3`.
- `ui/mod.rs` — module declarations for `app`, `terminal`, `reader`, `modal`, `picker`, `theme`.
- `ui/theme.rs` — `Theme` enum (Dark, Light, SolarizedDark, SolarizedLight) with `name()`, `from_name()`, `iter()`. `style_for_segment()` maps `TextStyle` bold/underline/foreground to ratatui `Style`. `map_rgb_to_terminal()` maps RGB to 256-color palette.
- `ui/app.rs` — core `App` state machine with `Mode` enum (Reader, Search, Toc, Picker, Popup, Help, Dictionary). Full `handle_key()` dispatcher across all modes: navigation (j/k/arrows/PageUp/PageDown), chapter/page control (g/G), TOC (t), search (/), file picker (o), theme cycling (T), header toggle (h), justification toggle (J), bookmark (m/b), help (?), dictionary (d), quit (q/Ctrl-c). Pagination, resize, state persistence, file picker with filtering.
- `ui/terminal.rs` — `run_app()` async event loop: crossterm alternate screen/raw mode, ratatui `Terminal`, `tokio::select!` on `EventStream` + 100ms tick, `Resize` triggers re-pagination, RAII cleanup on exit.
- `ui/reader.rs` — `render()` dispatcher. `draw_reader()` with header (book title), body (styled page lines), footer (version, chapter, page/total, progress %, help hint). Terminal-too-small centered message. Mode-specific: `draw_toc`, `draw_search`, `draw_help`, `draw_dictionary`, `draw_popup`.
- `ui/picker.rs` — `draw_picker()` with directory listing (`..` first, directories, sorted `.epub` files), filter support, selection highlighting.
- `ui/modal.rs` — `draw_centered_block()` helper for popup rendering.
- `main.rs` — `#[tokio::main]` async entry point. Startup: explicit path → prior book → picker. `--bookmark` restores bookmark position. Non-interactive TTY fallback for test compatibility.
- `lib.rs` — uncommented `pub mod ui`. Added `EpubBook::chapters()` public accessor.
- `state.rs` — added `set_global_str()` and `set_global_bool()` public methods.

---

## Phase 8: Responsive And PTY Integration Tests

### Work

1. Replace the mock-curses responsive suite with Ratatui `TestBackend` tests.
2. Sweep reader layouts across widths 20 through 160 and heights comparable to
   the Python suite. Assert no panic, valid viewport use, and footer placement.
3. Sweep file-picker layouts over the same relevant dimensions.
4. Add a real PTY integration test using `portable-pty` and `vt100`:
   - Spawn the compiled binary using a deterministic fixture EPUB.
   - Set `TERM=xterm-256color` and UTF-8 locale variables.
   - Dismiss the Loaded popup.
   - Check nonblank output, title on top row, and footer on final row.
   - Resize a live PTY and require new output after each resize.
5. Cover static dimensions and these resize patterns:
   - `120x40 -> 60x28`.
   - `120x40 -> 40x26`.
   - `100x34 -> 30x22`.
   - `80x30 -> 45x24`.
   - `60x28 -> 110x36`.
6. Keep PTY tests serial and give them a longer timeout. They must not share a
   fixed `/tmp` child script name.

### Verification

```bash
cargo test --all-targets
    cargo test --test pty_resize -- --ignored --test-threads=1
```

**Result:** All gates passed. 73 passing (9 unit + 7 CLI + 12 epub + 12 extract + 12 layout + 9 state + 4 dictionary + 8 responsive), 6 ignored (PTY, requires live terminal). `cargo fmt --check`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test --all-targets`, `cargo build` all clean.

### Implementation Log

Phase 8 completed:

- `Cargo.toml` — added `portable-pty 0.8` and `vt100 0.15` dev-dependencies.
- `tests/responsive.rs` — 8 ratatui TestBackend tests:
  - `reader_layout_sweep_widths` — 9 widths × 4 heights, footer assertion on valid sizes.
  - `reader_too_small_no_panic` — 5×5 render doesn't panic.
  - `header_present_when_enabled` / `header_absent_when_disabled` — header row behavior.
  - `footer_always_last_row` — footer on last row for all valid dimensions.
  - `picker_layout_sweep`, `toc_layout_sweep`, `help_layout_sweep` — 36 combinations each, no panic.
- `tests/pty_resize.rs` — 6 ignored PTY integration tests:
  - `pty_basic_startup` — 80×24, non-blank output.
  - 5 resize patterns: `120x40→60x28`, `120x40→40x26`, `100x34→30x22`, `80x30→45x24`, `60x28→110x36`.
- `src/ui/reader.rs` — fixed `centered_rect` to clamp popup width/height to terminal bounds (prevents out-of-bounds panics on small terminals).

---

## Phase 9: Cutover, Documentation, And CI

### Work

1. Update `README.md`:
   - Rust installation and binary usage.
   - Revised requirements and supported platforms.
   - State compatibility.
   - Embedded dictionary behavior and binary-size implications.
   - Minimum terminal dimensions.
   - Offline-only behavior.
   - Explicit DRM/encrypted-text limitation.
   - Correct CSS wording: italic and strike may be parsed but are not rendered.
2. Update `RELEASE_NOTES.md` with version `2.0.0`, user-visible changes, and
   migration notes.
3. Add `.github/workflows/ci.yml` to run format checking, Clippy with warnings
   denied, unit/integration tests, and release compilation on Linux.
4. Update `.gitignore` for Rust artifacts and tracked test fixtures. Do not
   broadly ignore all EPUB/HTML fixture inputs needed by tests.
5. Confirm `ecdict_index.json` packaging is legally permitted and document its
   source/license in `THIRD_PARTY_NOTICES.md`.
6. Run the complete verification suite and a manual terminal smoke test.
7. Only after all gates pass, delete `termepub.py` and the Python-only tests.
   Git history remains the legacy reference; do not retain an unsupported
    runtime compatibility wrapper by default.

### Verification Results

All gates passed:

```
cargo fmt --check                          — PASS
cargo clippy --all-targets --all-features  — PASS (-D warnings)
cargo test --all-targets                   — 73 passing, 0 failed, 6 ignored (PTY)
cargo build --release                      — PASS (24 MB binary)
target/release/termepub --version          — termepub 2.0.0
target/release/termepub --help             — PASS
```

### Implementation Log

Phase 9 completed:

- `README.md` — rewritten for Rust binary: installation (cargo, manual), controls table, CSS support with italic/strike note, requirements (min terminal 10×5), state compatibility, embedded dictionary behavior, offline-only, DRM limitation, v1.x migration notes.
- `RELEASE_NOTES.md` — updated with v2.0.0 release notes covering the Rust rewrite, binary rename, self-contained dictionary, grapheme-safe layout, four themes, state compatibility, and known limitations. Retained v1.0.4 notes for continuity.
- `.github/workflows/ci.yml` — three-job workflow: format + clippy, tests, release build with binary verification.
- `.gitignore` — removed `*.epub`, `test_epub/`, `*.html` entries (test fixtures must not be ignored); added `Cargo.lock`.
- `THIRD_PARTY_NOTICES.md` — ECDICT MIT license attribution with redistribution note, Rust dependency license summary.
- Release build: 24 MB optimized binary, `--version` and `--help` verified.

---

## Migration Complete

All 9 phases are complete. The Rust implementation (`termepub` v2.0.0) replaces the Python implementation (`termepub.py` v1.0.4). The Python source may now be deleted at the user's discretion — git history preserves the legacy reference.

### Final Verification

```bash
cargo fmt --check
cargo clippy --all-targets --all-features -- -D warnings
cargo test --all-targets
cargo test --test pty_resize -- --ignored --test-threads=1
cargo build --release
target/release/termepub --version
target/release/termepub --help
```

Manual smoke test:

1. Start without a path and use the file picker.
2. Open both EPUB 2 and EPUB 3 fixture books.
3. Toggle theme, header, justification, and heading style.
4. Search across a page boundary.
5. Save and restore a bookmark using existing Python-format state.
6. Use dictionary selection and direct dictionary lookup.
7. Resize while reading and while a modal is open.
8. Attempt to open an invalid replacement EPUB and verify the current book
   remains available.

## Qwen Execution Protocol

Use this plan as the coding agent's persistent task specification.

1. Execute exactly one numbered phase per session.
2. Before each phase, inspect `git status`, read this plan, and inspect the
   previous phase's implementation and tests.
3. Do not skip verification commands or start the next phase after a failed
   gate.
4. Do not delete or modify the Python application until Phase 9.
5. Do not commit, push, alter Git configuration, or add credentials unless the
   user explicitly requests it.
6. Keep changes small and reviewable. Prefer pure domain logic over terminal
   coupled code.
7. At the end of a phase, report:
   - Files changed.
   - Commands run and their results.
   - Remaining risks or blockers.
   - The exact next phase.
8. Stop after that report and wait for approval.

Suggested initial instruction for a coding agent:

```text
You are implementing the Rust migration in this repository. Read
MIGRATION_PLAN.md and execute Phase 1 only. Inspect the repository first. Do
not start Phase 2, do not commit, and run every Phase 1 verification command.
At completion report changed files, test results, risks, and the next phase.
```

## Repository Hygiene Note

Repository remote configuration has previously contained an embedded credential.
Rotate that credential and replace the remote with a credential-free URL before
publishing the Rust rewrite. Do not place credentials in source, documentation,
or build configuration.
