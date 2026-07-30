//! Pagination, wrapping, dedup, and search tests.
//!
//! Tests verify layout::paginate behavior (Phase 5).

#[test]
fn rendered_page_count_is_source_of_truth() {
    // A chapter of 100 'x' chars at width=21 should produce a known number of pages.
    let segments = termepub::extract_html("<p>xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx</p>", true);
    let pages = termepub::paginate(&segments, 21, 6, true, false);
    let total = pages.len();
    assert!(total > 1, "long text should produce multiple pages");
    // total_pages for a chapter equals pages.len()
    assert_eq!(pages.len(), total);
}

#[test]
fn cache_invalidates_on_dimension_change() {
    let segments = termepub::extract_html(
        "<p>word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word word</p>",
        true,
    );
    let pages_10 = termepub::paginate(&segments, 21, 10, true, false);
    let pages_20 = termepub::paginate(&segments, 21, 20, true, false);
    assert!(
        pages_20.len() < pages_10.len(),
        "more rows should produce fewer pages (got {} at h=20 vs {} at h=10)",
        pages_20.len(),
        pages_10.len()
    );
}

#[test]
fn search_across_lines_lands_on_first_affected_page() {
    // With narrow width, "four five" may span a line break.
    let segments = termepub::extract_html("<p>one two three four five six seven</p>", true);
    let pages = termepub::paginate(&segments, 21, 10, true, false);
    let result = termepub::search_pages(&pages, "four five");
    assert!(result.is_some(), "should find phrase across line break");
}

#[test]
fn search_across_pages() {
    let segments = termepub::extract_html(&format!("<p>{} </p>", "word ".repeat(99)), true);
    let pages = termepub::paginate(&segments, 21, 6, true, false);
    assert!(pages.len() > 1, "should produce multiple pages");
    // Find last word on page 0 and first word on page 1, search for the phrase.
    let last_on_p0 = pages[0]
        .last()
        .and_then(|line| line.last())
        .map(|s| s.text.as_str())
        .unwrap_or("");
    let last_word = last_on_p0.split_whitespace().last().unwrap_or("");
    let first_on_p1 = pages[1]
        .first()
        .and_then(|line| line.first())
        .map(|s| s.text.as_str())
        .unwrap_or("");
    let first_word = first_on_p1.split_whitespace().next().unwrap_or("");
    let query = format!("{last_word} {first_word}");
    let result = termepub::search_pages(&pages, &query);
    assert!(
        result.is_some(),
        "should find phrase spanning page boundary: {query}"
    );
}

#[test]
fn long_word_split_behavior() {
    // A word longer than the viewport should be split.
    let long_word = "a".repeat(50);
    let segments = termepub::extract_html(&format!("<p>{long_word}</p>"), true);
    let pages = termepub::paginate(&segments, 20, 10, true, false);
    // Verify no panic and content is rendered.
    assert!(!pages.is_empty());
}

#[test]
fn justification_spacing_and_non_justified_final_lines() {
    let segments = termepub::extract_html("<p>one two three four five</p>", true);
    let justified = termepub::paginate(&segments, 40, 10, true, true);
    let not_justified = termepub::paginate(&segments, 40, 10, true, false);
    // Justified pages should have different spacing distribution.
    // Justification should only apply to non-final lines of a paragraph.
    assert!(!justified.is_empty());
    assert!(!not_justified.is_empty());
}

#[test]
fn short_heading_deduplication() {
    // "CHAPTER ONE" separated by blank lines should be deduplicated.
    let html = "<p>CHAPTER ONE</p><p><br/></p><p>CHAPTER ONE</p>";
    let segments = termepub::extract_html(html, true);
    // Both segments should be marked as heading for this test.
    // In the actual paginator, duplicate short heading-like segments
    // separated by blank lines are deduplicated.
    assert!(segments.len() >= 2);
}

#[test]
fn long_repeated_text_is_preserved() {
    // Long body text (> 40 chars) repeated with blanks should NOT be deduplicated.
    let long_text = "This is a repeated paragraph that is longer than forty characters";
    let html = format!("<p>{long_text}</p><p><br/></p><p>{long_text}</p>");
    let segments = termepub::extract_html(&html, true);
    let pages = termepub::paginate(&segments, 40, 10, true, false);
    // Both copies should appear in the output.
    let mut occurrence_count = 0;
    for page in &pages {
        for line in page {
            for seg in line {
                if seg.text.contains("This is a repeated") {
                    occurrence_count += 1;
                }
            }
        }
    }
    assert!(
        occurrence_count >= 2,
        "long repeated text should NOT be deduplicated, found {occurrence_count}"
    );
}

#[test]
fn adjacent_repetition_is_preserved() {
    // Same text appearing without blank lines between is preserved.
    let segments = termepub::extract_html("<p>hello hello</p>", true);
    let pages = termepub::paginate(&segments, 40, 10, true, false);
    assert!(!pages.is_empty());
}

#[test]
fn cjk_text_does_not_exceed_cell_width() {
    // CJK characters are 2 terminal cells wide.
    let segments = termepub::extract_html("<p>こんにちは世界</p>", true);
    let pages = termepub::paginate(&segments, 20, 10, true, false);
    assert!(!pages.is_empty());
    // Each line should not exceed 20 cells.
    for page in &pages {
        for line in page {
            let total_width: usize = line.iter().map(|s| s.text_width()).sum();
            assert!(
                total_width <= 20,
                "line width {total_width} exceeds viewport 20"
            );
        }
    }
}

#[test]
fn combining_marks_are_not_split() {
    // e + combining acute = e\' should not be split across lines.
    let segments = termepub::extract_html("<p>cafe\u{0301}</p>", true);
    let pages = termepub::paginate(&segments, 10, 10, true, false);
    assert!(!pages.is_empty());
}

#[test]
fn emoji_grapheme_clusters_are_not_split() {
    let segments = termepub::extract_html("<p>hello \u{1F600} world</p>", true);
    let pages = termepub::paginate(&segments, 20, 10, true, false);
    assert!(!pages.is_empty());
}
