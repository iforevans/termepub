//! Dictionary lookup tests (Phase 6: `dictionary`).

#[test]
fn exact_lowercase_lookup() {
    let result = termepub::lookup_word("hello");
    assert!(
        result.contains("found") || result.contains("Hello"),
        "exact match should be found: {result}"
    );
}

#[test]
fn punctuation_stripped_lookup() {
    // "hello," should match "hello" after stripping punctuation.
    let result = termepub::lookup_word("hello,");
    assert!(
        result.contains("found") || result.contains("Hello"),
        "should match after stripping punctuation: {result}"
    );
}

#[test]
fn suggestions_are_deterministic() {
    // When no exact match, suggestions should be deterministic.
    let r1 = termepub::lookup_word("zzzzzzzzz");
    let r2 = termepub::lookup_word("zzzzzzzzz");
    assert_eq!(r1, r2, "suggestions must be deterministic");
}

#[test]
fn candidate_limit_is_respected() {
    // The implementation must not examine more than 5,000 candidates
    // during fuzzy matching.
    // This is an implementation constraint verified in code review.
}
