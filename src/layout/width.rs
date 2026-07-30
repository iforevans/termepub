//! Grapheme-safe width helpers for terminal cell measurement.

use unicode_segmentation::UnicodeSegmentation;
use unicode_width::UnicodeWidthStr;

/// Returns the terminal cell width of a string, using `unicode_width`.
pub fn text_width(s: &str) -> usize {
    s.width()
}

/// Splits a string into grapheme clusters, returning them as `&str` slices.
pub fn graphemes(s: &str) -> Vec<&str> {
    s.graphemes(true).collect()
}

/// Returns the grapheme cluster at a given grapheme index, or `None`.
pub fn grapheme_at(s: &str, idx: usize) -> Option<&str> {
    s.graphemes(true).nth(idx)
}

/// Returns the byte offset after `n` grapheme clusters.
pub fn grapheme_byte_offset(s: &str, n: usize) -> usize {
    s.grapheme_indices(true)
        .nth(n)
        .map(|(i, _)| i)
        .unwrap_or(s.len())
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

/// Splits a string into words at grapheme-safe whitespace boundaries.
/// Each word is returned as a `(String, style_index)` where style_index
/// is unused here (caller handles style per segment).
pub fn split_into_words(s: &str) -> Vec<String> {
    let mut words = Vec::new();
    let mut current = String::new();

    for g in s.graphemes(true) {
        if g.trim().is_empty() {
            if !current.is_empty() {
                words.push(current);
                current = String::new();
            }
            // Separate words with a space marker
            words.push(String::new());
        } else {
            current.push_str(g);
        }
    }

    if !current.is_empty() {
        words.push(current);
    }

    words
}
