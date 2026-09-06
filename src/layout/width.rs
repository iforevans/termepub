//! Grapheme-safe width helpers for terminal cell measurement.

use unicode_segmentation::UnicodeSegmentation;
use unicode_width::UnicodeWidthStr;

/// Returns the terminal cell width of a string, using `unicode_width`.
pub fn text_width(s: &str) -> usize {
    s.width()
}

/// Splits a string at grapheme boundaries, returning at most `max_width`
/// cells worth of graphemes in the first element and the remainder in the
/// second.  Returns `None` if the string fits within `max_width`.
pub fn split_at_width(s: &str, max_width: usize) -> Option<(String, String)> {
    let mut width = 0;
    let mut last_grapheme_end = 0;

    for (byte_offset, g) in s.grapheme_indices(true) {
        let g_width = g.width();
        if width + g_width > max_width && last_grapheme_end > 0 {
            let before = s[..last_grapheme_end].to_string();
            let after = s[byte_offset..].to_string();
            return Some((before, after));
        }
        width += g_width;
        last_grapheme_end = byte_offset + g.len();
    }

    None
}

/// Splits a long word (exceeding `max_width`) into chunks of at most
/// `max_width` terminal cells, breaking at grapheme boundaries.
/// Returns `None` if the word fits within `max_width`.
pub fn split_long_word(word: &str, max_width: usize) -> Option<Vec<String>> {
    if text_width(word) <= max_width {
        return None;
    }

    let mut chunks = Vec::new();
    let mut remaining = word.to_string();

    while !remaining.is_empty() {
        if let Some((chunk, rest)) = split_at_width(&remaining, max_width) {
            chunks.push(chunk);
            remaining = rest;
        } else {
            if !remaining.is_empty() {
                chunks.push(remaining.to_string());
            }
            break;
        }
    }

    if chunks.is_empty() {
        None
    } else {
        Some(chunks)
    }
}
