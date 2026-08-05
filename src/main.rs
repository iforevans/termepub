use clap::Parser;
use termepub::cli::Cli;
use termepub::error::Error;
use termepub::ui;

#[tokio::main(flavor = "current_thread")]
async fn main() {
    match run().await {
        Ok(()) => std::process::exit(0),
        Err(err) => {
            eprintln!("Error: {err}");
            std::process::exit(1);
        }
    }
}

async fn run() -> Result<(), Error> {
    let cli = Cli::parse();

    // Check if we have a TTY — if not, fall back to non-interactive mode
    let has_tty = atty::is(atty::Stream::Stdout);

    if !has_tty {
        return run_non_interactive(&cli);
    }

    let (cols, rows) = crossterm::terminal::size().map_err(|e| Error::io_path("terminal", e))?;
    let mut app = ui::app::App::new(cli.use_css(), (cols, rows));

    // Start the dictionary load in the background so the first lookup
    // doesn't block the UI on the ~21 MB parse.
    termepub::preload_dictionary();

    // Try state store
    if let Ok(store) = termepub::StateStore::open_default() {
        app.state_store = Some(store);
        app.load_global_settings();
    }

    // Startup: explicit path -> prior book -> picker
    if let Some(ref path) = cli.epub_path {
        app.open_book(path.clone())?;
        app.mode = ui::app::Mode::Reader;
    } else if let Some(last_path) = app.get_last_book_path() {
        if let Ok(absolute) = std::path::absolute(&last_path) {
            let _ = app.open_book(absolute);
            app.mode = ui::app::Mode::Reader;
        }
    }

    if cli.bookmark {
        app.go_to_bookmark();
    }

    if app.book.is_none() {
        app.mode = ui::app::Mode::Picker;
        app.refresh_picker();
    }

    let result = ui::terminal::run_app(app).await;
    result
}

fn run_non_interactive(cli: &Cli) -> Result<(), Error> {
    // Non-TTY fallback: print info and exit successfully
    if let Some(ref path) = cli.epub_path {
        eprintln!("Opening: {}", path.display());
    } else {
        eprintln!("No EPUB path provided");
    }

    if cli.bookmark {
        eprintln!("Bookmark mode requested");
    }

    if !cli.use_css() {
        eprintln!("CSS disabled");
    }

    Ok(())
}
