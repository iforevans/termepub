//! Shared helpers for integration tests: build EPUB fixtures from the
//! tracked `tests/fixtures/` tree at runtime.
//!
//! This module is included via `mod support;` in several test binaries,
//! each of which uses only some helpers — so the others are "dead" per
//! compilation unit. Allow dead code rather than warning per test crate.
#![allow(dead_code)]

use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::LazyLock;

/// Path to the `tests/fixtures/` directory in the project root.
static FIXTURES_DIR: LazyLock<PathBuf> =
    LazyLock::new(|| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures"));

/// Builds a minimal EPUB ZIP from a fixture directory and writes it to `tmp_dir`.
pub fn build_epub(tmp_dir: &Path, name: &str, fixture_dir: &str) -> PathBuf {
    let src = FIXTURES_DIR.join(fixture_dir);
    let dst = tmp_dir.join(format!("{name}.epub"));
    pack_directory_into_zip(&src, &dst);
    dst
}

/// Packs all files under `src_dir` into a ZIP archive at `dst`.
fn pack_directory_into_zip(src_dir: &Path, dst: &Path) {
    let mut archive = zip::ZipWriter::new(fs::File::create(dst).expect("cannot create temp epub"));
    let src = src_dir.canonicalize().expect("fixture dir not found");

    let mut entries: Vec<PathBuf> = Vec::new();
    walk_dir(&src, &mut entries);

    for entry in &entries {
        let relative = entry.strip_prefix(&src).expect("invalid strip");
        let path_str = relative.to_string_lossy().to_string().replace('\\', "/");

        if entry.is_dir() {
            archive
                .add_directory::<&str, ()>(&path_str, zip::write::FileOptions::default())
                .expect("add directory");
        } else {
            archive
                .start_file::<&str, ()>(&path_str, zip::write::FileOptions::default())
                .expect("start file");
            let data = fs::read(entry).expect("read fixture");
            archive.write_all(&data).expect("write to zip");
        }
    }

    archive.finish().expect("finish zip");
}

fn walk_dir(dir: &Path, entries: &mut Vec<PathBuf>) {
    let mut children: Vec<_> = fs::read_dir(dir)
        .expect("read dir")
        .map(|e| e.expect("read entry").path())
        .collect();
    children.sort();

    for path in children {
        entries.push(path.clone());
        if path.is_dir() {
            walk_dir(&path, entries);
        }
    }
}

/// Writes the minimal container.xml into a ZIP writer.
fn write_container(writer: &mut zip::ZipWriter<fs::File>) {
    writer
        .start_file::<&str, ()>("META-INF/container.xml", zip::write::FileOptions::default())
        .expect("start file");
    writer.write_all(
        b"<?xml version=\"1.0\"?><container xmlns=\"urn:oasis:names:tc:opendocument:xmlns:container\"><rootfiles><rootfile full-path=\"content.opf\"/></rootfiles></container>",
    ).expect("write container");
}

/// Builds a ZIP file with `n` members, each containing `payload_len` bytes of data.
pub fn build_many_members_epub(tmp_dir: &Path, name: &str, n: u32, payload_len: usize) -> PathBuf {
    let dst = tmp_dir.join(format!("{name}.epub"));
    let mut archive = zip::ZipWriter::new(fs::File::create(&dst).expect("cannot create temp epub"));

    write_container(&mut archive);

    for i in 0..n {
        let member_name = format!("member_{i}.xhtml");
        archive
            .start_file::<String, ()>(member_name, zip::write::FileOptions::default())
            .expect("start file");
        let payload = vec![b'a'; payload_len];
        archive.write_all(&payload).expect("write");
    }

    archive.finish().expect("finish");
    dst
}

/// Builds a ZIP with a single oversized member.
pub fn build_oversized_member_epub(tmp_dir: &Path, name: &str, size: usize) -> PathBuf {
    let dst = tmp_dir.join(format!("{name}.epub"));
    let mut archive = zip::ZipWriter::new(fs::File::create(&dst).expect("cannot create temp epub"));

    write_container(&mut archive);

    archive
        .start_file::<&str, ()>("big.xhtml", zip::write::FileOptions::default())
        .expect("start file");
    archive.write_all(&vec![b'x'; size]).expect("write");

    archive.finish().expect("finish");
    dst
}

/// Builds a ZIP with a highly compressed member (compression ratio test).
pub fn build_high_compression_epub(
    tmp_dir: &Path,
    name: &str,
    uncompressed_size: usize,
) -> PathBuf {
    let dst = tmp_dir.join(format!("{name}.epub"));
    let mut archive = zip::ZipWriter::new(fs::File::create(&dst).expect("cannot create temp epub"));

    write_container(&mut archive);

    let options =
        zip::write::FileOptions::default().compression_method(zip::CompressionMethod::Deflated);
    archive
        .start_file::<&str, ()>("bomb.xhtml", options)
        .expect("start file");
    archive
        .write_all(&vec![b'x'; uncompressed_size])
        .expect("write");

    archive.finish().expect("finish");
    dst
}
