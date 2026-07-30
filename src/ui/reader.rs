use ratatui::layout::{Alignment, Constraint, Direction, Layout, Rect};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span, Text};
use ratatui::widgets::{Block, Borders, Clear, Paragraph, Wrap};
use ratatui::Frame;

use crate::layout::paginate as layout_paginate;

use super::app::{App, Mode};
use super::picker::draw_picker;
use super::theme::{style_for_segment, Theme};

#[allow(dead_code)]
pub fn render(frame: &mut Frame, app: &App) {
    match app.mode {
        Mode::Reader => draw_reader(frame, app),
        Mode::Toc => draw_toc(frame, app),
        Mode::Search => draw_search(frame, app),
        Mode::Picker => draw_picker(frame, app),
        Mode::Popup => draw_popup(frame, app),
        Mode::Help => draw_help(frame, app),
        Mode::Dictionary => draw_dictionary(frame, app),
    }
}

fn draw_reader(frame: &mut Frame, app: &App) {
    let area = frame.area();

    // Check if terminal is too small
    if area.height < layout_paginate::MIN_TERMINAL_ROWS as u16
        || area.width < layout_paginate::MIN_TERMINAL_COLS as u16
    {
        let msg = Paragraph::new(Span::raw("Terminal too small")).alignment(Alignment::Center);
        frame.render_widget(msg, area);
        return;
    }

    let show_header = app.show_header;
    let theme = app.theme;

    let (chunks, body_idx) = if show_header {
        let chunks = Layout::default()
            .direction(Direction::Vertical)
            .constraints(
                [
                    Constraint::Length(1), // header
                    Constraint::Length(1), // separator
                    Constraint::Min(1),    // body
                    Constraint::Length(1), // separator
                    Constraint::Length(1), // footer
                ]
                .as_ref(),
            )
            .split(area);
        (chunks, 2)
    } else {
        let chunks = Layout::default()
            .direction(Direction::Vertical)
            .constraints(
                [
                    Constraint::Min(1),    // body
                    Constraint::Length(1), // separator
                    Constraint::Length(1), // footer
                ]
                .as_ref(),
            )
            .split(area);
        (chunks, 0)
    };

    if show_header {
        draw_header(frame, app, chunks[0]);
        draw_separator(frame, &theme, chunks[1]);
    }

    draw_body(frame, app, chunks[body_idx]);

    let sep_idx = body_idx + 1;
    let footer_idx = body_idx + 2;
    draw_separator(frame, &theme, chunks[sep_idx]);
    draw_footer(frame, app, chunks[footer_idx]);
}

fn draw_separator(frame: &mut Frame, theme: &Theme, area: Rect) {
    let sep = "─".repeat(area.width as usize);
    let line = Paragraph::new(Span::raw(sep))
        .style(
            Style::default()
                .fg(theme.foreground())
                .bg(theme.background()),
        );
    frame.render_widget(line, area);
}

fn draw_body(frame: &mut Frame, app: &App, area: Rect) {
    // Clear background
    frame.render_widget(Clear, area);

    // Set background color based on theme
    let bg_color = app.theme.background();
    let bg_block = Block::default().style(Style::default().bg(bg_color));
    frame.render_widget(bg_block, area);

    if app.pages.is_empty() || app.page_index >= app.pages.len() {
        return;
    }

    let current_page = &app.pages[app.page_index];

    let mut lines: Vec<Line> = Vec::new();
    for line_segs in current_page {
        let spans: Vec<Span> = line_segs
            .iter()
            .map(|seg| {
                let style = style_for_segment(seg, &app.theme);
                Span::styled(seg.text.clone(), style)
            })
            .collect();

        // If no spans (empty line), add a single empty span
        let line = if spans.is_empty() {
            Line::from(Span::raw(""))
        } else {
            Line::from(spans)
        };
        lines.push(line);
    }

    let text = Text::from(lines);
    let paragraph = Paragraph::new(text).wrap(Wrap { trim: true });
    frame.render_widget(paragraph, area);
}

fn draw_footer(frame: &mut Frame, app: &App, area: Rect) {
    let theme = app.theme;

    let version = env!("CARGO_PKG_VERSION");
    let chapter_title = if let Some(ref book) = app.book {
        let toc = book.toc();
        if app.chapter_index < toc.len() {
            toc[app.chapter_index].title.clone()
        } else {
            format!("Chapter {}", app.chapter_index + 1)
        }
    } else {
        String::from("No book")
    };

    let page_info = format!(
        "{}/{} ({:.0}%)",
        app.page_index + 1,
        app.total_pages,
        if app.total_pages > 0 {
            (app.page_index as f64 / app.total_pages as f64) * 100.0
        } else {
            0.0
        }
    );

    let footer_text = format!(
        " termepub v{} | {} | {} | h:header ??:help q:quit ",
        version, chapter_title, page_info
    );

    let paragraph = Paragraph::new(Span::raw(footer_text))
        .style(
            Style::default()
                .fg(theme.foreground())
                .bg(theme.background())
                .add_modifier(Modifier::BOLD),
        )
        .alignment(Alignment::Center);

    frame.render_widget(paragraph, area);
}

fn draw_header(frame: &mut Frame, app: &App, area: Rect) {
    let theme = app.theme;
    let title = app
        .book
        .as_ref()
        .map(|b| b.title().to_string())
        .unwrap_or_else(|| String::from("termepub"));

    let paragraph = Paragraph::new(Span::raw(title))
        .style(
            Style::default()
                .fg(theme.foreground())
                .bg(theme.background())
                .add_modifier(Modifier::BOLD),
        )
        .alignment(Alignment::Center);

    frame.render_widget(paragraph, area);
}

fn draw_toc(frame: &mut Frame, app: &App) {
    let area = frame.area();
    let theme = app.theme;

    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Length(3), Constraint::Min(1)].as_ref())
        .split(area);

    // Title
    let title = Paragraph::new(Span::raw(" Table of Contents "))
        .style(
            Style::default()
                .fg(theme.foreground())
                .bg(theme.background())
                .add_modifier(Modifier::BOLD),
        )
        .alignment(Alignment::Center);
    frame.render_widget(title, chunks[0]);

    // TOC entries
    if let Some(ref book) = app.book {
        let toc = book.toc();
        let mut lines: Vec<Line> = Vec::new();

        for (i, entry) in toc.iter().enumerate() {
            let prefix = if i == app.toc_index { "> " } else { "  " };
            let line = Line::from(vec![Span::styled(
                format!("{}{}", prefix, entry.title),
                Style::default()
                    .fg(if i == app.toc_index {
                        Color::Yellow
                    } else {
                        theme.foreground()
                    })
                    .bg(theme.background())
                    .add_modifier(if i == app.toc_index {
                        Modifier::BOLD
                    } else {
                        Modifier::empty()
                    }),
            )]);
            lines.push(line);
        }

        let text = Text::from(lines);
        let paragraph = Paragraph::new(text).wrap(Wrap { trim: true });
        frame.render_widget(paragraph, chunks[1]);
    }
}

fn draw_search(frame: &mut Frame, app: &App) {
    let area = frame.area();
    let theme = app.theme;

    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Min(1), Constraint::Length(3)].as_ref())
        .split(area);

    // Draw underlying reader
    draw_reader(frame, app);

    // Search prompt
    let prompt = format!("/{} ", app.search_query);
    let paragraph = Paragraph::new(Span::raw(prompt))
        .style(
            Style::default()
                .fg(Color::Yellow)
                .bg(theme.background())
                .add_modifier(Modifier::BOLD),
        )
        .alignment(Alignment::Left);
    frame.render_widget(paragraph, chunks[1]);
}

fn draw_help(frame: &mut Frame, app: &App) {
    let area = frame.area();
    let theme = app.theme;

    let help_text = [
        "termepub - Terminal EPUB Reader",
        "",
        "NORMAL MODE",
        "  j/Down    Page down",
        "  k/Up      Page up",
        "  Ctrl-f    Page down",
        "  Ctrl-b    Page up",
        "  g         First page",
        "  G         Last page",
        "  t         Table of Contents",
        "  /         Search",
        "  o         File picker",
        "  T         Cycle theme",
        "  h         Toggle header",
        "  J         Toggle justification",
        "  m         Set bookmark",
        "  b         Go to bookmark",
        "  d         Dictionary",
        "  ?         This help screen",
        "  q/Ctrl-c  Quit",
        "",
        "SEARCH MODE",
        "  type      Enter query",
        "  Enter     Search",
        "  Esc/Ctrl-c Cancel",
        "",
        "TOC MODE",
        "  j/Down    Navigate down",
        "  k/Up      Navigate up",
        "  Enter     Go to chapter",
        "  Esc/Ctrl-c Close",
        "",
        "PICKER MODE",
        "  j/Down    Navigate down",
        "  k/Up      Navigate up",
        "  Enter     Open file/book",
        "  / or s    Filter entries",
        "  Esc/Ctrl-c Close",
        "",
        "Press Esc or q to close this help.",
    ];

    let lines: Vec<Line> = help_text
        .iter()
        .map(|line| {
            Line::from(Span::styled(
                line.to_string(),
                Style::default()
                    .fg(theme.foreground())
                    .bg(theme.background()),
            ))
        })
        .collect();

    let text = Text::from(lines);
    let paragraph = Paragraph::new(text)
        .block(
            Block::default()
                .borders(Borders::ALL)
                .title(" Help ")
                .style(Style::default().add_modifier(Modifier::BOLD)),
        )
        .wrap(Wrap { trim: false });

    let popup_area = centered_rect(area, 80, 24);
    frame.render_widget(Clear, popup_area);
    frame.render_widget(paragraph, popup_area);
}

fn draw_dictionary(frame: &mut Frame, app: &App) {
    let area = frame.area();
    let theme = app.theme;

    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Min(1), Constraint::Length(3)].as_ref())
        .split(area);

    // Draw underlying reader
    draw_reader(frame, app);

    // Dictionary prompt
    let prompt = format!("dict>{} ", app.dictionary_word);
    let paragraph = Paragraph::new(Span::raw(prompt))
        .style(
            Style::default()
                .fg(Color::Cyan)
                .bg(theme.background())
                .add_modifier(Modifier::BOLD),
        )
        .alignment(Alignment::Left);
    frame.render_widget(paragraph, chunks[1]);

    // Show result if available
    if let Some(ref result) = app.dictionary_result {
        let result_lines: Vec<Line> = result
            .lines()
            .map(|line| {
                Line::from(Span::styled(
                    format!("  {} ", line),
                    Style::default().fg(Color::Cyan).bg(theme.background()),
                ))
            })
            .collect();

        let result_text = Text::from(result_lines);
        let result_para = Paragraph::new(result_text);

        let result_area = Rect::new(
            area.x,
            area.y + 3,
            area.width,
            area.height.saturating_sub(3),
        );
        frame.render_widget(result_para, result_area);
    }
}

fn draw_popup(frame: &mut Frame, app: &App) {
    let area = frame.area();
    let theme = app.theme;

    if let Some(ref msg) = app.popup_message {
        let lines: Vec<Line> = vec![Line::from(Span::styled(
            msg.clone(),
            Style::default()
                .fg(Color::Yellow)
                .bg(theme.background())
                .add_modifier(Modifier::BOLD),
        ))];

        let text = Text::from(lines);
        let paragraph = Paragraph::new(text)
            .block(
                Block::default()
                    .borders(Borders::ALL)
                    .style(Style::default().add_modifier(Modifier::BOLD)),
            )
            .alignment(Alignment::Center);

        let popup_area = centered_rect(area, 30, 5);
        frame.render_widget(Clear, popup_area);
        frame.render_widget(paragraph, popup_area);
    }
}

fn centered_rect(area: Rect, width: u16, height: u16) -> Rect {
    let w = width.min(area.width);
    let h = height.min(area.height);
    let x = area.x + (area.width.saturating_sub(w)) / 2;
    let y = area.y + (area.height.saturating_sub(h)) / 2;
    Rect::new(x, y, w, h)
}
