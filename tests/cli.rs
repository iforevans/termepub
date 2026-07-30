use assert_cmd::Command;

#[test]
fn version_prints_and_exits_zero() {
    Command::cargo_bin("termepub")
        .unwrap()
        .arg("--version")
        .assert()
        .success();
}

#[test]
fn help_includes_documented_options() {
    let assert = Command::cargo_bin("termepub")
        .unwrap()
        .arg("--help")
        .assert()
        .success();

    let output = assert.get_output();
    let stdout = String::from_utf8_lossy(&output.stdout);

    assert!(
        stdout.contains("--bookmark"),
        "help should mention --bookmark"
    );
    assert!(stdout.contains("--no-css"), "help should mention --no-css");
}

#[test]
fn short_help_works() {
    Command::cargo_bin("termepub")
        .unwrap()
        .arg("-h")
        .assert()
        .success();
}

#[test]
fn flags_before_epub_path() {
    Command::cargo_bin("termepub")
        .unwrap()
        .args(["--bookmark", "--no-css", "dummy.epub"])
        .assert()
        .success();
}

#[test]
fn flags_after_epub_path() {
    Command::cargo_bin("termepub")
        .unwrap()
        .args(["dummy.epub", "--bookmark", "--no-css"])
        .assert()
        .success();
}

#[test]
fn flags_mixed_with_epub_path() {
    Command::cargo_bin("termepub")
        .unwrap()
        .args(["--bookmark", "dummy.epub", "--no-css"])
        .assert()
        .success();
}

#[test]
fn unknown_flag_fails() {
    Command::cargo_bin("termepub")
        .unwrap()
        .arg("--unknown-flag")
        .assert()
        .failure();
}
