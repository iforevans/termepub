//! Terminal setup, event loop, and cleanup.

use std::io;
use std::time::Duration;

use crossterm::event::{self, Event, KeyEventKind};
use crossterm::execute;
use crossterm::terminal::{disable_raw_mode, enable_raw_mode};
use crossterm::terminal::{EnterAlternateScreen, LeaveAlternateScreen};
use ratatui::backend::CrosstermBackend;
use ratatui::Terminal;

use crate::error::Error;

use super::app::App;
use super::reader;

/// Restores terminal state when dropped, so every exit path — including
/// errors and panics — leaves the terminal usable instead of stuck in raw
/// mode / alternate screen.
struct TerminalGuard;

impl Drop for TerminalGuard {
    fn drop(&mut self) {
        let _ = execute!(io::stdout(), LeaveAlternateScreen);
        let _ = disable_raw_mode();
    }
}

pub async fn run_app(mut app: App) -> Result<(), Error> {
    execute!(io::stdout(), EnterAlternateScreen).map_err(|e| Error::io_path("stdout", e))?;
    let _guard = TerminalGuard;
    enable_raw_mode().map_err(|e| Error::io_path("raw mode", e))?;

    let backend = CrosstermBackend::new(io::stdout());
    let mut terminal = Terminal::new(backend).map_err(|e| Error::io_path("terminal", e))?;

    loop {
        if event::poll(Duration::from_millis(100)).map_err(|e| Error::io_path("event poll", e))? {
            match event::read().map_err(|e| Error::io_path("event read", e))? {
                Event::Key(key) => {
                    // Handle presses and — for navigation/typing keys —
                    // auto-repeat, so holding an arrow key flips pages.
                    if key.kind == KeyEventKind::Press
                        || (key.kind == KeyEventKind::Repeat && app.is_repeat_safe(key))
                    {
                        app.handle_key(key);
                    }
                }
                Event::Resize(cols, rows) => {
                    app.resize(cols, rows);
                }
                _ => {}
            }
        }

        if app.should_quit {
            break;
        }

        terminal
            .draw(|frame| reader::render(frame, &app))
            .map_err(|e| Error::io_path("terminal draw", e))?;
    }

    app.save_state();

    Ok(())
}
