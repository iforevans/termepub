use clap::Parser;
use std::path::PathBuf;

#[derive(Debug, Parser)]
#[command(name = "termepub", version, about = "Terminal EPUB reader")]
pub struct Cli {
    /// Path to an EPUB file to open
    pub epub_path: Option<PathBuf>,

    /// Resume at saved bookmark position
    #[arg(long)]
    pub bookmark: bool,

    /// Disable inline CSS styling (faster on slow devices)
    #[arg(long)]
    pub no_css: bool,
}

impl Cli {
    pub fn use_css(&self) -> bool {
        !self.no_css
    }
}
