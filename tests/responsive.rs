use ratatui::backend::TestBackend;
use ratatui::Terminal;

use termepub::ui::app::{App, Mode};

const WIDTHS: &[u16] = &[20, 30, 40, 50, 60, 80, 100, 120, 160];
const HEIGHTS: &[u16] = &[15, 24, 30, 40];

fn make_test_app(width: u16, height: u16, mode: Mode, show_header: bool) -> App {
    let mut app = App::new(true, (width, height));
    app.mode = mode;
    app.show_header = show_header;
    let segments = termepub::extract_html(
        "<p>Hello world from termepub. This is a test paragraph for rendering.</p>",
        true,
    );
    app.pages = termepub::paginate(
        &segments,
        width as usize,
        height as usize,
        show_header,
        app.justify,
    );
    app.total_pages = app.pages.len();
    app
}

/// Check whether a cell has any non-default style attributes set.
fn style_non_default(style: &ratatui::style::Style) -> bool {
    style.fg.is_some()
        || style.bg.is_some()
        || style.underline_color.is_some()
        || !style.add_modifier.is_empty()
        || !style.sub_modifier.is_empty()
}

fn render_app(width: u16, height: u16, app: &App) -> TestBackend {
    let backend = TestBackend::new(width, height);
    let mut terminal = Terminal::new(backend).unwrap();
    terminal
        .draw(|f| termepub::ui::reader::render(f, app))
        .unwrap();
    terminal.backend_mut().clone()
}

#[test]
fn reader_layout_sweep_widths() {
    for &width in WIDTHS {
        for &height in HEIGHTS {
            let app = make_test_app(width, height, Mode::Reader, true);
            let backend = render_app(width, height, &app);

            if width >= 10 && height >= 5 {
                let last_row = (height - 1) as usize;
                let cell = &backend.buffer()[ratatui::layout::Position::new(0, last_row as u16)];
                assert!(
                    cell.symbol() != " " || style_non_default(&cell.style()),
                    "footer should exist on last row for {width}x{height}"
                );
            }
        }
    }
}

#[test]
fn reader_too_small_no_panic() {
    let app = make_test_app(5, 5, Mode::Reader, true);
    let _backend = render_app(5, 5, &app);
}

#[test]
fn header_present_when_enabled() {
    let app = make_test_app(80, 24, Mode::Reader, true);
    let backend = render_app(80, 24, &app);
    let buf = backend.buffer();
    let has_content =
        (0..buf.area.width).any(|x| buf[ratatui::layout::Position::new(x, 0)].symbol() != " ");
    assert!(
        has_content,
        "header row should contain content when show_header=true"
    );
}

#[test]
fn header_absent_when_disabled() {
    let app = make_test_app(80, 24, Mode::Reader, false);
    let backend = render_app(80, 24, &app);
    let cell = &backend.buffer()[ratatui::layout::Position::new(0, 0)];
    assert!(
        cell.symbol() != "─",
        "first row should be body area, not separator, when show_header=false"
    );
}

#[test]
fn footer_always_last_row() {
    for &width in WIDTHS {
        for &height in HEIGHTS {
            if width < 10 || height < 5 {
                continue;
            }
            let app = make_test_app(width, height, Mode::Reader, true);
            let backend = render_app(width, height, &app);
            let last_row = (height - 1) as usize;
            let cell = &backend.buffer()[ratatui::layout::Position::new(0, last_row as u16)];
            assert!(
                cell.symbol() != " " || style_non_default(&cell.style()),
                "footer must exist on last row for {width}x{height}"
            );
        }
    }
}

#[test]
fn picker_layout_sweep() {
    for &width in WIDTHS {
        for &height in HEIGHTS {
            let app = make_test_app(width, height, Mode::Picker, false);
            let _backend = render_app(width, height, &app);
        }
    }
}

#[test]
fn toc_layout_sweep() {
    for &width in WIDTHS {
        for &height in HEIGHTS {
            let app = make_test_app(width, height, Mode::Toc, false);
            let _backend = render_app(width, height, &app);
        }
    }
}

#[test]
fn help_layout_sweep() {
    for &width in WIDTHS {
        for &height in HEIGHTS {
            let app = make_test_app(width, height, Mode::Help, false);
            let _backend = render_app(width, height, &app);
        }
    }
}
