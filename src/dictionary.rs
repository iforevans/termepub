//! External dictionary with lazy loading and fuzzy suggestions.
//!
//! Loads `ecdict_index.json` from disk on first lookup via `OnceLock`.
//! Search order:
//! 1. `~/.config/termepub/ecdict_index.json`
//! 2. Next to the binary (resolved from `argv[0]`)
//!
//! Performs exact lowercase lookup, then retries with punctuation stripped.
//! Falls back to deterministic fuzzy suggestions limited to 5,000 candidates.

use std::collections::BTreeMap;
use std::env;
use std::path::PathBuf;
use std::sync::OnceLock;

/// Maximum fuzzy-matching candidates to examine.
const MAX_CANDIDATES: usize = 5_000;

/// Lazy-loaded dictionary data.
static DICTIONARY: OnceLock<Option<BTreeMap<String, Definition>>> = OnceLock::new();

/// A dictionary entry.
#[derive(Debug, Clone)]
struct Definition {
    headword: String,
    definition: String,
}

/// Resolves the path to the dictionary file.
fn find_dictionary_path() -> Option<PathBuf> {
    // 1. Config directory.
    if let Some(config_dir) = dirs_config_path() {
        let p = config_dir.join("ecdict_index.json");
        if p.exists() {
            return Some(p);
        }
    }

    // 2. Next to the binary.
    if let Ok(argv0) = env::current_exe() {
        if let Some(parent) = argv0.parent() {
            let p = parent.join("ecdict_index.json");
            if p.exists() {
                return Some(p);
            }
        }
    }

    None
}

fn dirs_config_path() -> Option<PathBuf> {
    if let Some(config) = std::env::var_os("XDG_CONFIG_HOME") {
        let mut p = PathBuf::from(config);
        p.push("termepub");
        return Some(p);
    }
    if let Some(home) = std::env::var_os("HOME") {
        let mut p = PathBuf::from(home);
        p.push(".config");
        p.push("termepub");
        return Some(p);
    }
    None
}

fn load_dictionary() -> Option<BTreeMap<String, Definition>> {
    let path = find_dictionary_path()?;
    let data = std::fs::read(&path).ok()?;
    let parsed: serde_json::Map<String, serde_json::Value> = serde_json::from_slice(&data).ok()?;

    let mut map = BTreeMap::new();
    for (word, val) in parsed {
        let obj = val.as_object()?;
        let headword = obj
            .get("headword")
            .and_then(|v| v.as_str())
            .unwrap_or(&word)
            .to_string();
        let definition = obj
            .get("def")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        map.insert(
            word,
            Definition {
                headword,
                definition,
            },
        );
    }
    Some(map)
}

/// Returns the dictionary, loading it lazily on first access.
fn get_dictionary() -> Option<&'static BTreeMap<String, Definition>> {
    DICTIONARY.get_or_init(load_dictionary).as_ref()
}

/// Looks up a word in the dictionary.
///
/// First tries exact lowercase match, then retries with punctuation
/// stripped.  If no exact match is found, returns deterministic
/// suggestions limited to `MAX_CANDIDATES` candidates.
pub fn lookup_word(word: &str) -> String {
    let word_lower = word.to_lowercase();
    let stripped = word_lower
        .chars()
        .filter(|c| c.is_alphanumeric() || *c == '-')
        .collect::<String>();

    if let Some(dict) = get_dictionary() {
        // Exact match on lowercased word.
        if let Some(def) = dict.get(&word_lower) {
            return format!(
                "{}\n\nfound: {}\n{}",
                def.headword, def.headword, def.definition
            );
        }

        // Retry with punctuation stripped.
        if stripped != word_lower {
            if let Some(def) = dict.get(&stripped) {
                return format!(
                    "{}\n\nfound: {}\n{}",
                    def.headword, def.headword, def.definition
                );
            }
        }

        // No exact match — provide suggestions.
        return suggest_word(&word_lower, dict);
    }

    format!("Dictionary not available: {word_lower}")
}

/// Generates deterministic suggestions for a misspelled word.
///
/// Sorts candidate words, examines up to `MAX_CANDIDATES` length-compatible
/// entries, and returns the best matches.
fn suggest_word(word: &str, dict: &BTreeMap<String, Definition>) -> String {
    let target_len = word.len();

    // Filter to length-compatible candidates (within ±2 of target length).
    let min_len = target_len.saturating_sub(2);
    let max_len = target_len + 2;

    // BTreeMap is already sorted, so iteration is deterministic.
    let candidates: Vec<&str> = dict
        .iter()
        .filter(|(k, _)| k.len() >= min_len && k.len() <= max_len)
        .map(|(k, _)| k.as_str())
        .take(MAX_CANDIDATES)
        .collect();

    // Score candidates by similarity.
    let mut scored: Vec<(usize, &str)> = Vec::new();
    for cand in &candidates {
        let score = similarity_score(word, cand);
        if score > 0 {
            scored.push((score, cand));
        }
    }

    // Sort by score descending, then alphabetically for determinism.
    scored.sort_by(|a, b| b.0.cmp(&a.0).then_with(|| a.1.cmp(b.1)));

    let top: Vec<String> = scored
        .iter()
        .take(5)
        .map(|(_, cand)| {
            let cand = *cand;
            dict.get(cand)
                .map(|d| d.headword.clone())
                .unwrap_or_else(|| cand.to_string())
        })
        .collect();

    if top.is_empty() {
        format!("Not found: {word}\n\nNo suggestions available.")
    } else {
        let suggestions = top.join(", ");
        format!("Not found: {word}\n\nDid you mean: {suggestions}?")
    }
}

/// Computes a simple similarity score between two strings.
///
/// Uses character overlap and edit-distance heuristics.
fn similarity_score(a: &str, b: &str) -> usize {
    let a_bytes = a.as_bytes();
    let b_bytes = b.as_bytes();

    if a_bytes.len().abs_diff(b_bytes.len()) > 3 {
        return 0;
    }

    // Count common characters (simple overlap).
    let common = a_bytes.iter().filter(|c| b_bytes.contains(c)).count();

    if common < a_bytes.len() / 2 {
        return 0;
    }

    // Prefer exact prefix matches.
    let prefix = a
        .chars()
        .zip(b.chars())
        .take_while(|(ca, cb)| ca == cb)
        .count();

    common + prefix * 2
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn lookup_is_deterministic() {
        let r1 = lookup_word("zzzzzzzzz");
        let r2 = lookup_word("zzzzzzzzz");
        assert_eq!(r1, r2, "suggestions must be deterministic");
    }
}
