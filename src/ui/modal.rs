use ratatui::layout::Rect;
use ratatui::style::{Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, Paragraph};
use ratatui::Frame;

use super::app::App;

#[allow(dead_code)]
pub fn draw_centered_block(frame: &mut Frame, _app: &App, title: &str, content: &str) -> Rect {
    let area = frame.area();
    let block_width = (area.width as f64 * 0.8) as u16;
    let block_height = (area.height as f64 * 0.6) as u16;

    let popup_area = center_rect(area, block_width, block_height);

    let block = Block::default()
        .borders(Borders::ALL)
        .title(Span::raw(title))
        .style(Style::default().add_modifier(Modifier::BOLD));

    let lines: Vec<Line> = content
        .lines()
        .map(|line| Line::from(Span::raw(format!("{} ", line))))
        .collect();

    let paragraph = Paragraph::new(lines).block(block);
    frame.render_widget(paragraph, popup_area);

    popup_area
}

fn center_rect(area: Rect, width: u16, height: u16) -> Rect {
    let x = area.x + (area.width.saturating_sub(width)) / 2;
    let y = area.y + (area.height.saturating_sub(height)) / 2;
    Rect::new(x, y, width, height)
}
