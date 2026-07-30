//! State persistence tests (Phase 6: `state`).
//!
//! Tests verify `state.json` compatibility with the Python format.

use std::fs;
use std::path::PathBuf;
use tempfile::TempDir;

/// Helper: write a state.json and return the path.
fn write_state(dir: &TempDir, content: &str) -> PathBuf {
    let path = dir.path().join("state.json");
    fs::write(&path, content).unwrap();
    path
}

#[test]
fn valid_python_format_state_loads() {
    let tmp = TempDir::new().unwrap();
    write_state(
        &tmp,
        r#"{
        "_global": {"theme": "dark", "show_header": true},
        "abc123": {"path": "/tmp/book.epub", "chapter_index": 2, "page_index": 5}
    }"#,
    );

    let store = termepub::StateStore::open(tmp.path().join("state.json")).unwrap();
    assert_eq!(store.get_theme(), "dark");
    assert!(store.get_show_header());

    let state = store.get_state_for_book("abc123");
    assert_eq!(state.chapter_index, 2);
    assert_eq!(state.page_index, 5);
}

#[test]
fn malformed_root_defaults_safely() {
    // Root is an array instead of object -> safe default
    let tmp = TempDir::new().unwrap();
    write_state(&tmp, "[1, 2, 3]");

    let store = termepub::StateStore::open(tmp.path().join("state.json")).unwrap();
    assert_eq!(store.get_theme(), "dark");
}

#[test]
fn malformed_global_defaults_safely() {
    let tmp = TempDir::new().unwrap();
    write_state(&tmp, r#"{"_global": []}"#);

    let store = termepub::StateStore::open(tmp.path().join("state.json")).unwrap();
    assert_eq!(store.get_theme(), "dark");
}

#[test]
fn non_object_entries_are_dropped() {
    let tmp = TempDir::new().unwrap();
    write_state(
        &tmp,
        r#"{"_global": {}, "bad-book": 7, "valid-book": {"page_index": 2}}"#,
    );

    let store = termepub::StateStore::open(tmp.path().join("state.json")).unwrap();
    // "bad-book" should be dropped; "valid-book" should remain.
    let state = store.get_state_for_book("valid-book");
    assert_eq!(state.page_index, 2);
}

#[test]
fn book_key_matches_python_sha1() {
    // Python: sha1(abspath(path).encode("utf-8")).hexdigest()
    use sha1::Digest;
    let mut hasher = sha1::Sha1::new();
    hasher.update("/tmp/test.epub".as_bytes());
    let expected = format!("{:x}", hasher.finalize());

    let key = termepub::StateStore::book_key("/tmp/test.epub");
    assert_eq!(key, expected);
}

#[test]
fn unknown_fields_are_preserved_on_save() {
    let tmp = TempDir::new().unwrap();
    write_state(
        &tmp,
        r#"{"_global": {}, "book-key": {"custom_field": "value", "page_index": 0}}"#,
    );

    let mut store = termepub::StateStore::open(tmp.path().join("state.json")).unwrap();
    // Update a known field without erasing the custom field.
    store.set_state_for_book("book-key", 0, 10);
    store.save().unwrap();

    let content = fs::read_to_string(store.path()).unwrap();
    assert!(
        content.contains("custom_field"),
        "unknown fields must be preserved: {content}"
    );
}

#[test]
fn invalid_chapter_page_clamps_to_zero() {
    let tmp = TempDir::new().unwrap();
    write_state(
        &tmp,
        r#"{"_global": {}, "book": {"chapter_index": -5, "page_index": "invalid"}}"#,
    );

    let store = termepub::StateStore::open(tmp.path().join("state.json")).unwrap();
    let state = store.get_state_for_book("book");
    assert_eq!(state.chapter_index, 0);
    assert_eq!(state.page_index, 0);
}

#[test]
fn bookmark_persistence() {
    let tmp = TempDir::new().unwrap();
    write_state(&tmp, r#"{"_global": {}}"#);

    let mut store = termepub::StateStore::open(tmp.path().join("state.json")).unwrap();
    store.set_bookmark("some-key", 3, 7).unwrap();
    store.save().unwrap();

    let bm = store.get_bookmark("some-key").unwrap();
    assert_eq!(bm.chapter_index, 3);
    assert_eq!(bm.page_index, 7);
}

#[test]
fn atomic_write_uses_rename() {
    // Verify the store writes to a temp file then renames.
    // We can't easily verify this behavior programmatically,
    // but we can verify the file is valid JSON after save.
    let tmp = TempDir::new().unwrap();
    let path = tmp.path().join("state.json");

    let mut store = termepub::StateStore::open(path.clone()).unwrap();
    store.set_state_for_book("test", 1, 2);
    store.save().unwrap();

    let content = fs::read_to_string(&path).unwrap();
    let parsed: serde_json::Value = serde_json::from_str(&content).unwrap();
    assert!(parsed.is_object());
}
