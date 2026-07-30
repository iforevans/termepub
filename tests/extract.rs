//! HTML extraction behavior tests.
//!
//! Tests verify that the text extractor (Phase 4: `epub::extract`) correctly
//! handles inline styles, semantic tags, malformed nesting, and paragraph
//! boundary preservation.

#[test]
fn parent_style_survives_unstyled_nested_tags() {
    // <b>A<span>B</span>C</b> -> merged segment "ABC" with bold
    let segments = termepub::extract_html("<b>A<span>B</span>C</b>", true);
    let seg = segments
        .iter()
        .find(|s| s.text.contains("ABC"))
        .expect("should have ABC segment");
    assert!(
        seg.style.bold,
        "bold style should survive through unstyled span"
    );
}

#[test]
fn style_does_not_leak_after_styled_section_ends() {
    // <section style="color:red">A</section><p>B</p> -> "B" has no color
    let segments = termepub::extract_html("<section style=\"color:red\">A</section><p>B</p>", true);
    let seg = segments
        .iter()
        .find(|s| s.text == "B")
        .expect("should have B segment");
    assert!(
        seg.style.foreground.is_none(),
        "color should not leak after section ends: {:?}",
        seg.style.foreground
    );
}

#[test]
fn heading_metadata_survives_adjacent_segment_merging() {
    // <h1>Hello <span>world</span></h1> -> "Hello world" with is_heading=true
    let segments = termepub::extract_html("<h1>Hello <span>world</span></h1>", true);
    let seg = segments
        .iter()
        .find(|s| s.text.contains("Hello world"))
        .expect("should have merged heading segment");
    assert!(seg.is_heading, "heading metadata should survive merge");
}

#[test]
fn malformed_nested_heading_does_not_leak_heading_state() {
    // <h1><h2>nested heading</h1>body</h2>
    // The "body" text should NOT be a heading.
    let segments = termepub::extract_html("<h1><h2>nested heading</h1>body</h2>", true);
    let text_segments: Vec<_> = segments
        .iter()
        .filter(|s| !s.text.trim().is_empty())
        .collect();
    assert!(
        text_segments[0].is_heading,
        "nested heading should be marked as heading"
    );
    let last = text_segments.last().expect("should have last segment");
    assert_eq!(last.text, "body");
    assert!(
        !last.is_heading,
        "body text after malformed heading should not be heading"
    );
}

#[test]
fn css_off_disables_semantic_and_inline_styles() {
    let segments_on =
        termepub::extract_html("<b>bold</b><span style=\"color:red\">red</span>", true);
    let segments_off =
        termepub::extract_html("<b>bold</b><span style=\"color:red\">red</span>", false);
    // With CSS off, no bold or color should be applied.
    let bold_off = segments_off
        .iter()
        .find(|s| s.text == "bold")
        .expect("bold text segment");
    assert!(
        !bold_off.style.bold,
        "bold should be disabled when CSS is off"
    );
    let red_off = segments_off
        .iter()
        .find(|s| s.text == "red")
        .expect("red text segment");
    assert!(
        red_off.style.foreground.is_none(),
        "color should be disabled when CSS is off"
    );
    // With CSS on, bold should be applied.
    let bold_on = segments_on
        .iter()
        .find(|s| s.text == "bold")
        .expect("bold text segment");
    assert!(bold_on.style.bold, "bold should be enabled when CSS is on");
}

#[test]
fn block_tags_produce_paragraph_breaks() {
    let segments = termepub::extract_html("<p>para1</p><p>para2</p>", true);
    // Should have paragraph break whitespace between paragraphs.
    let texts: Vec<_> = segments.iter().map(|s| &s.text).collect();
    // There should be a break segment between the two paragraphs.
    let has_break = texts.iter().any(|t| t.contains('\n'));
    assert!(
        has_break,
        "block tags should produce paragraph breaks: {texts:?}"
    );
}

#[test]
fn list_items_produce_bullet_segments() {
    let segments = termepub::extract_html("<ul><li>item1</li><li>item2</li></ul>", true);
    let has_bullet = segments.iter().any(|s| s.text.contains("-"));
    assert!(has_bullet, "list items should produce bullets");
}

#[test]
fn preformatted_text_preserves_newlines() {
    let segments = termepub::extract_html("<pre>line1\nline2</pre>", true);
    let has_newline = segments.iter().any(|s| s.text.contains("\n"));
    assert!(has_newline, "preformatted text should preserve newlines");
}

#[test]
fn skipped_head_content() {
    let segments = termepub::extract_html(
        "<html><head><title>Title</title><style>.x{}</style><script>alert(1)</script></head><body><p>visible</p></body></html>",
        true,
    );
    let texts: Vec<_> = segments.iter().map(|s| s.text.as_str()).collect();
    assert!(
        !texts.iter().any(|t| t.contains("Title")),
        "head content should be skipped"
    );
    assert!(
        !texts.iter().any(|t| t.contains("alert")),
        "script content should be skipped"
    );
    assert!(
        texts.iter().any(|t| t.contains("visible")),
        "body content should be present"
    );
}

#[test]
fn image_alt_text_is_included() {
    let segments = termepub::extract_html("<p><img alt=\"diagram\" src=\"img.png\"/></p>", true);
    let has_alt = segments.iter().any(|s| s.text.contains("diagram"));
    assert!(has_alt, "image alt text should be included");
}

#[test]
fn merge_does_not_cross_whitespace_only_breaks() {
    // Two paragraphs separated by whitespace-only segment should NOT merge.
    let segments = termepub::extract_html("<p>A</p><p>B</p>", true);
    // "A" and "B" should be in separate segments.
    let has_merged = segments
        .iter()
        .any(|s| s.text.contains("AB") || s.text.contains("A B"));
    assert!(
        !has_merged,
        "adjacent paragraphs should not merge across paragraph break"
    );
}

#[test]
fn unicode_sanitization_preserves_printable_unicode() {
    let segments = termepub::extract_html("<p>café señor 中文</p>", true);
    let texts: Vec<_> = segments.iter().map(|s| s.text.as_str()).collect();
    let combined = texts.join("");
    assert!(
        combined.contains("café"),
        "should preserve Latin accented: {combined}"
    );
    assert!(
        combined.contains("señor"),
        "should preserve Latin tilde: {combined}"
    );
    assert!(combined.contains("中文"), "should preserve CJK: {combined}");
}
