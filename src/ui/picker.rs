use ratatui::layout::{Alignment, Constraint, Direction, Layout};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Paragraph, Wrap};
use ratatui::Frame;

use super::app::App;

pub fn draw_picker(frame: &mut Frame, app: &App) {
    let area = frame.area();
    let theme = app.theme;

    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints(
            [
                Constraint::Length(3),
                Constraint::Min(1),
                Constraint::Length(3),
            ]
            .as_ref(),
        )
        .split(area);

    // Title
    let title = Paragraph::new(Span::raw(format!(" {} ", app.picker_dir.display())))
        .style(
            Style::default()
                .fg(theme.foreground())
                .bg(theme.background())
                .add_modifier(Modifier::BOLD),
        )
        .alignment(Alignment::Center);
    frame.render_widget(title, chunks[0]);

    // Entries
    let filtered = app.filtered_picker_entries();
    let mut lines: Vec<Line> = Vec::new();

    for (i, &entry_idx) in filtered.iter().enumerate() {
        let entry = &app.picker_entries[entry_idx];
        let is_selected = i == app.picker_selected;

        let prefix = if is_selected { "> " } else { "  " };

        let icon = if entry.is_dir || entry.name == ".." {
            "[DIR] "
        } else if entry.is_epub {
            "[EPUB] "
        } else {
            "      "
        };

        let color = if is_selected {
            Color::Yellow
        } else {
            theme.foreground()
        };

        let line = Line::from(Span::styled(
            format!("{}{}{}", prefix, icon, entry.name),
            Style::default()
                .fg(color)
                .bg(theme.background())
                .add_modifier(if is_selected {
                    Modifier::BOLD
                } else {
                    Modifier::empty()
                }),
        ));
        lines.push(line);
    }

    let paragraph = Paragraph::new(lines).wrap(Wrap { trim: true });
    frame.render_widget(paragraph, chunks[1]);

    // Footer hints
    let hints = if app.picker_filtering {
        format!(
            "Filtering: '{}' | type to filter, Enter done, Esc clear",
            app.picker_filter
        )
    } else if !app.picker_filter.is_empty() {
        format!(
            "Filter: '{}' | j/k:navigate Enter:open Esc:back /:edit",
            app.picker_filter
        )
    } else {
        "j/k:navigate Enter:open Esc:back /:filter".to_string()
    };
    let hint_para = Paragraph::new(Span::raw(hints))
        .style(
            Style::default()
                .fg(theme.foreground())
                .bg(theme.background())
                .add_modifier(Modifier::BOLD),
        )
        .alignment(Alignment::Center);
    frame.render_widget(hint_para, chunks[2]);
}
