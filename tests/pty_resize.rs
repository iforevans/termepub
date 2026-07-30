/// PTY integration tests for termepub.
///
/// These tests spawn the compiled binary inside a pseudo-terminal and
/// verify responsive resize behavior.  Run with `--test-threads=1`:
///
/// ```bash
/// cargo test --test pty_resize -- --ignored --test-threads=1
/// ```
use portable_pty::{native_pty_system, CommandBuilder, PtySize};

fn fixture_epub() -> std::path::PathBuf {
    std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("test_colors.epub")
}

fn binary_path() -> std::path::PathBuf {
    std::path::PathBuf::from(env!("CARGO_BIN_EXE_termepub"))
}

#[ignore = "requires PTY and compiled binary"]
#[test]
fn pty_basic_startup() {
    let pty_system = native_pty_system();
    let pair = pty_system
        .openpty(PtySize {
            rows: 24,
            cols: 80,
            pixel_width: 0,
            pixel_height: 0,
        })
        .expect("openpty");

    let mut cmd = CommandBuilder::new(binary_path());
    cmd.arg(fixture_epub());

    let mut child = pair.slave.spawn_command(cmd).expect("spawn");

    std::thread::sleep(std::time::Duration::from_millis(800));

    let mut reader = pair.master.try_clone_reader().expect("clone reader");
    let mut buf = [0u8; 8192];
    let n = reader.read(&mut buf).expect("read");

    let output = std::str::from_utf8(&buf[..n]).expect("utf8");
    assert!(
        !output.trim().is_empty(),
        "should have non-blank output on startup"
    );

    let _ = child.kill();
    let _ = child.wait();
}

#[ignore = "requires PTY and compiled binary"]
#[test]
fn pty_resize_120x40_to_60x28() {
    pty_resize_test(120, 40, 60, 28);
}

#[ignore = "requires PTY and compiled binary"]
#[test]
fn pty_resize_120x40_to_40x26() {
    pty_resize_test(120, 40, 40, 26);
}

#[ignore = "requires PTY and compiled binary"]
#[test]
fn pty_resize_100x34_to_30x22() {
    pty_resize_test(100, 34, 30, 22);
}

#[ignore = "requires PTY and compiled binary"]
#[test]
fn pty_resize_80x30_to_45x24() {
    pty_resize_test(80, 30, 45, 24);
}

#[ignore = "requires PTY and compiled binary"]
#[test]
fn pty_resize_60x28_to_110x36() {
    pty_resize_test(60, 28, 110, 36);
}

fn pty_resize_test(init_cols: u16, init_rows: u16, new_cols: u16, new_rows: u16) {
    let pty_system = native_pty_system();
    let pair = pty_system
        .openpty(PtySize {
            rows: init_rows,
            cols: init_cols,
            pixel_width: 0,
            pixel_height: 0,
        })
        .expect("openpty");

    let mut cmd = CommandBuilder::new(binary_path());
    cmd.arg(fixture_epub());

    let mut child = pair.slave.spawn_command(cmd).expect("spawn");

    std::thread::sleep(std::time::Duration::from_millis(800));

    let mut reader = pair.master.try_clone_reader().expect("clone reader");
    let mut buf = [0u8; 8192];
    let n = reader.read(&mut buf).expect("read");
    let _initial_output = std::str::from_utf8(&buf[..n]).expect("utf8");

    pair.master
        .resize(PtySize {
            rows: new_rows,
            cols: new_cols,
            pixel_width: 0,
            pixel_height: 0,
        })
        .expect("resize");

    std::thread::sleep(std::time::Duration::from_millis(800));

    let n2 = reader.read(&mut buf).expect("read after resize");
    let _after_resize = std::str::from_utf8(&buf[..n2]).expect("utf8");

    assert!(
        n2 > 0,
        "should produce output after resize from {}x{} to {}x{}",
        init_cols,
        init_rows,
        new_cols,
        new_rows
    );

    let _ = child.kill();
    let _ = child.wait();
}
