use crate::StyledSegment;
use ratatui::style::{Color, Modifier, Style};

#[allow(dead_code)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Theme {
    Dark,
    Light,
    SolarizedDark,
    SolarizedLight,
}

impl Theme {
    #[allow(dead_code)]
    pub fn name(&self) -> &str {
        match self {
            Theme::Dark => "dark",
            Theme::Light => "light",
            Theme::SolarizedDark => "solarized-dark",
            Theme::SolarizedLight => "solarized-light",
        }
    }

    #[allow(dead_code)]
    pub fn from_name(s: &str) -> Option<Theme> {
        match s {
            "dark" => Some(Theme::Dark),
            "light" => Some(Theme::Light),
            "solarized-dark" => Some(Theme::SolarizedDark),
            "solarized-light" => Some(Theme::SolarizedLight),
            _ => None,
        }
    }

    #[allow(dead_code)]
    pub fn iter() -> impl Iterator<Item = Theme> {
        [
            Theme::Dark,
            Theme::Light,
            Theme::SolarizedDark,
            Theme::SolarizedLight,
        ]
        .into_iter()
    }

    #[allow(dead_code)]
    pub fn next_theme(&self) -> Theme {
        match self {
            Theme::Dark => Theme::Light,
            Theme::Light => Theme::SolarizedDark,
            Theme::SolarizedDark => Theme::SolarizedLight,
            Theme::SolarizedLight => Theme::Dark,
        }
    }

    #[allow(dead_code)]
    pub fn background(&self) -> Color {
        match self {
            Theme::Dark => Color::Rgb(0, 0, 0),
            Theme::Light => Color::Rgb(253, 246, 227),
            Theme::SolarizedDark => Color::Rgb(7, 54, 66),
            Theme::SolarizedLight => Color::Rgb(238, 232, 213),
        }
    }

    #[allow(dead_code)]
    pub fn foreground(&self) -> Color {
        match self {
            Theme::Dark => Color::Rgb(204, 204, 204),
            Theme::Light => Color::Rgb(0, 0, 0),
            Theme::SolarizedDark => Color::Rgb(131, 148, 150),
            Theme::SolarizedLight => Color::Rgb(101, 123, 131),
        }
    }
}

#[allow(dead_code)]
pub fn style_for_segment(seg: &StyledSegment, theme: &Theme) -> Style {
    let mut mods = Modifier::empty();
    if seg.is_heading {
        mods |= Modifier::BOLD;
    }
    if seg.style.bold {
        mods |= Modifier::BOLD;
    }
    if seg.style.underline {
        mods |= Modifier::UNDERLINED;
    }

    let fg = if seg.is_heading {
        Color::Yellow
    } else if let Some(rgb) = seg.style.foreground {
        map_rgb_to_terminal(rgb[0], rgb[1], rgb[2], theme)
    } else {
        theme.foreground()
    };

    Style::default()
        .fg(fg)
        .bg(theme.background())
        .add_modifier(mods)
}

#[allow(dead_code)]
pub fn map_rgb_to_terminal(r: u8, g: u8, b: u8, _theme: &Theme) -> Color {
    Color::Rgb(r, g, b)
}
