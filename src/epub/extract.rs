//! Tolerant HTML-to-StyledSegment extraction.
//!
//! Uses an explicit tag frame stack to track style inheritance, paragraph
//! breaks, and malformed nesting recovery.

use crate::StyledSegment;
use crate::TextStyle;

/// Extracts styled text segments from HTML content.
pub fn extract(html: &str, use_css: bool) -> Vec<StyledSegment> {
    let parser = HtmlExtractor::new(html, use_css);
    parser.parse()
}

/// Tag categories for the HTML extractor.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum TagCategory {
    Block,
    Heading,
    Inline,
    Skip,
    List,
    ListItem,
    Pre,
    Break,
    Image,
    Ignore,
}

/// A frame on the tag stack, tracking style state for nested elements.
#[derive(Debug, Clone)]
struct TagFrame {
    tag: String,
    category: TagCategory,
    style: TextStyle,
    is_heading: bool,
}

/// State for the HTML extraction parser.
struct HtmlExtractor<'a> {
    input: &'a str,
    use_css: bool,
    pos: usize,
    frames: Vec<TagFrame>,
    segments: Vec<StyledSegment>,
    /// Accumulated text for the current style context.
    current_text: String,
    /// Style associated with current_text.
    accum_style: TextStyle,
    /// Heading flag associated with current_text.
    accum_heading: bool,
    /// Whether we just exited a block/heading element.
    pending_break: bool,
    /// Whether we need to emit a list bullet.
    pending_bullet: bool,
    /// When true, the next flush must NOT merge with the last segment.
    no_merge_next: bool,
}

impl<'a> HtmlExtractor<'a> {
    fn new(input: &'a str, use_css: bool) -> Self {
        Self {
            input,
            use_css,
            pos: 0,
            frames: Vec::new(),
            segments: Vec::new(),
            current_text: String::new(),
            accum_style: TextStyle::default(),
            accum_heading: false,
            pending_break: false,
            pending_bullet: false,
            no_merge_next: false,
        }
    }

    fn parse(mut self) -> Vec<StyledSegment> {
        while self.pos < self.input.len() {
            let slice = &self.input[self.pos..];
            match slice.find('<') {
                Some(offset) => {
                    let text_before = &self.input[self.pos..self.pos + offset];
                    if !text_before.is_empty() {
                        self.emit_text(sanitize_chars(text_before));
                    }
                    self.pos += offset;

                    if let Some(tag_len) = self.parse_tag() {
                        self.pos += tag_len;
                    } else {
                        self.pos += 1;
                    }
                }
                None => {
                    let remaining = &self.input[self.pos..];
                    if !remaining.is_empty() {
                        self.emit_text(sanitize_chars(remaining));
                    }
                    break;
                }
            }
        }
        self.flush_current();
        self.segments
    }

    fn parse_tag(&mut self) -> Option<usize> {
        let slice = &self.input[self.pos..];
        if !slice.starts_with('<') {
            return None;
        }

        let end = find_tag_end(slice)?;
        let tag_content = &slice[1..end];

        if tag_content.is_empty() {
            return Some(end + 1);
        }

        // Skip comments
        if tag_content.starts_with("!--") {
            if let Some(comment_end) = slice[2..].find("-->") {
                return Some(comment_end + 5);
            }
            return Some(end + 1);
        }

        // Skip DOCTYPE, processing instructions
        if tag_content.starts_with('!') || tag_content.starts_with('?') {
            return Some(end + 1);
        }

        let is_closing = tag_content.starts_with('/');
        let (tag_name, attributes, is_self_closing) =
            parse_tag_name_and_attrs(tag_content, is_closing);

        let tag_lower = tag_name.to_lowercase();

        if is_closing {
            self.handle_close_tag(&tag_lower);
        } else if is_self_closing {
            self.handle_self_closing(&tag_lower, &attributes);
        } else {
            self.handle_open_tag(&tag_lower, &attributes);
        }

        Some(end + 1)
    }

    fn get_tag_category(tag: &str) -> TagCategory {
        match tag {
            "head" | "style" | "script" => TagCategory::Skip,
            "h1" | "h2" | "h3" | "h4" | "h5" | "h6" => TagCategory::Heading,
            "p" | "div" | "section" | "article" | "aside" | "header" | "footer" | "main"
            | "figure" | "figcaption" | "blockquote" | "dl" | "hr" => TagCategory::Block,
            "pre" => TagCategory::Pre,
            "ul" | "ol" => TagCategory::List,
            "li" => TagCategory::ListItem,
            "br" => TagCategory::Break,
            "img" => TagCategory::Image,
            "b" | "strong" | "i" | "em" | "u" | "s" | "strike" | "del" | "span" | "a" | "code"
            | "abbr" | "cite" | "q" | "sub" | "sup" | "mark" | "small" | "big" | "tt" | "var"
            | "kbd" | "samp" | "ruby" | "rb" | "rt" | "rp" | "bdi" | "bdo" | "data" | "time"
            | "wbr" | "title" => TagCategory::Inline,
            _ => TagCategory::Ignore,
        }
    }

    fn handle_open_tag(&mut self, tag: &str, attrs: &[(String, String)]) {
        let category = Self::get_tag_category(tag);

        // Track nesting of skip frames
        if let Some(frame) = self.frames.last() {
            if frame.category == TagCategory::Skip {
                self.frames.push(TagFrame {
                    tag: tag.to_string(),
                    category,
                    style: TextStyle::default(),
                    is_heading: false,
                });
                return;
            }
        }

        match category {
            TagCategory::Skip => {
                self.frames.push(TagFrame {
                    tag: tag.to_string(),
                    category: TagCategory::Skip,
                    style: TextStyle::default(),
                    is_heading: false,
                });
            }
            TagCategory::Heading => {
                self.flush_current();
                if !self.segments.is_empty() {
                    self.pending_break = true;
                }

                let mut new_style = self.top_style();
                let inline_style = extract_inline_style(attrs);
                if self.use_css {
                    apply_inline_style(&mut new_style, &inline_style);
                }

                self.frames.push(TagFrame {
                    tag: tag.to_string(),
                    category: TagCategory::Heading,
                    style: new_style.clone(),
                    is_heading: true,
                });

                // Start new accumulation
                self.accum_style = new_style;
                self.accum_heading = true;
            }
            TagCategory::Block => {
                self.flush_current();
                self.pending_break = true;

                let mut new_style = self.top_style();
                let inline_style = extract_inline_style(attrs);
                if self.use_css {
                    apply_inline_style(&mut new_style, &inline_style);
                }

                self.frames.push(TagFrame {
                    tag: tag.to_string(),
                    category: TagCategory::Block,
                    style: new_style,
                    is_heading: false,
                });
            }
            TagCategory::Pre => {
                self.flush_current();
                self.pending_break = true;

                self.frames.push(TagFrame {
                    tag: tag.to_string(),
                    category: TagCategory::Pre,
                    style: self.top_style(),
                    is_heading: false,
                });
            }
            TagCategory::List => {
                self.flush_current();
                self.pending_break = true;

                self.frames.push(TagFrame {
                    tag: tag.to_string(),
                    category: TagCategory::List,
                    style: self.top_style(),
                    is_heading: false,
                });
            }
            TagCategory::ListItem => {
                self.flush_current();
                self.pending_bullet = true;

                self.frames.push(TagFrame {
                    tag: tag.to_string(),
                    category: TagCategory::ListItem,
                    style: self.top_style(),
                    is_heading: false,
                });
            }
            TagCategory::Inline => {
                let mut new_style = self.top_style();

                if self.use_css {
                    match tag {
                        "b" | "strong" => new_style.bold = true,
                        "u" => new_style.underline = true,
                        "i" | "em" => new_style.italic = true,
                        "s" | "strike" | "del" => new_style.strike = true,
                        _ => {}
                    }
                    let inline_style = extract_inline_style(attrs);
                    apply_inline_style(&mut new_style, &inline_style);
                }

                // Flush current text if style changed
                if new_style != self.accum_style {
                    self.flush_current();
                }

                self.frames.push(TagFrame {
                    tag: tag.to_string(),
                    category: TagCategory::Inline,
                    style: new_style.clone(),
                    is_heading: self.accum_heading,
                });

                self.accum_style = new_style;
            }
            TagCategory::Ignore | TagCategory::Break | TagCategory::Image => {}
        }
    }

    fn handle_close_tag(&mut self, tag: &str) {
        // If we're inside a skip frame, just track nesting
        if let Some(frame) = self.frames.last() {
            if frame.category == TagCategory::Skip {
                if let Some(idx) = self
                    .frames
                    .iter()
                    .rposition(|f| f.tag == tag && f.category == TagCategory::Skip)
                {
                    self.frames.remove(idx);
                }
                return;
            }
        }

        match self.frames.iter().rposition(|f| f.tag == tag) {
            Some(idx) => {
                // Malformed nesting recovery: pop the frames ABOVE the match,
                // then pop the matched frame itself.
                while self.frames.len() > idx + 1 {
                    self.flush_current();
                    self.frames.pop();
                    self.accum_style = self.top_style();
                    self.accum_heading = self.frames.last().map(|f| f.is_heading).unwrap_or(false);
                }
                let cat = self.frames[idx].category;
                self.flush_current();
                if cat == TagCategory::Inline {
                    self.no_merge_next = true;
                }
                self.frames.pop();
                if matches!(
                    cat,
                    TagCategory::Block | TagCategory::Heading | TagCategory::Pre
                ) {
                    self.pending_break = true;
                }
                self.accum_style = self.top_style();
                self.accum_heading = self.frames.last().map(|f| f.is_heading).unwrap_or(false);
            }
            None => {
                // Stray closing tag (no matching open frame): never destroy
                // the frame stack — flush pending text and keep the outer
                // style context intact for everything that follows.
                self.flush_current();
                let category = Self::get_tag_category(tag);
                if matches!(category, TagCategory::Block | TagCategory::Heading) {
                    self.pending_break = true;
                }
            }
        }
    }

    fn handle_self_closing(&mut self, tag: &str, attrs: &[(String, String)]) {
        let category = Self::get_tag_category(tag);

        match category {
            TagCategory::Break => {
                self.flush_current();
                self.push_break();
            }
            TagCategory::Image => {
                if let Some(alt) = attrs.iter().find(|(k, _)| k == "alt") {
                    if !alt.1.is_empty() {
                        self.flush_current();
                        let mut seg_text = String::from("[");
                        seg_text.push_str(&alt.1);
                        seg_text.push(']');
                        self.current_text = seg_text;
                        self.accum_style = self.top_style();
                        self.accum_heading =
                            self.frames.last().map(|f| f.is_heading).unwrap_or(false);
                        self.flush_current();
                    }
                }
            }
            _ => {
                // Open then close
                self.handle_open_tag(tag, attrs);
                self.handle_close_tag(tag);
            }
        }
    }

    fn emit_text(&mut self, text: String) {
        // Don't emit text inside skip frames
        if self.frames.iter().any(|f| f.category == TagCategory::Skip) {
            return;
        }

        if text.is_empty() {
            return;
        }

        // Discard whitespace-only text anywhere in the tree — it's formatting
        // indentation from the source markup and would create unwanted blank
        // lines during layout.  We only keep it if we're currently accumulating
        // real text (preserving meaningful whitespace between words).
        if text.trim().is_empty() && self.current_text.is_empty() {
            return;
        }

        if self.pending_bullet {
            self.pending_bullet = false;
            let bullet = StyledSegment {
                text: String::from("- "),
                style: self.top_style(),
                is_heading: false,
            };
            self.segments.push(bullet);
        }

        if self.current_text.is_empty() {
            // Allow merging when we're inside a non-default styled context.
            let styled_context = self
                .frames
                .iter()
                .any(|f| f.category == TagCategory::Inline && f.style != TextStyle::default());
            if styled_context {
                if let Some(last) = self.segments.last() {
                    if last.style == self.top_style()
                        && last.is_heading == self.accum_heading
                        && last.text != "\n\n"
                    {
                        self.no_merge_next = false;
                    }
                }
            }
            self.current_text = text;
        } else if self.current_text == "\n\n" {
            self.flush_current();
            self.current_text = text;
        } else if self.accum_style == self.top_style() {
            self.no_merge_next = false;
            self.current_text.push_str(&text);
        } else {
            self.flush_current();
            self.current_text = text;
        }
    }

    fn flush_current(&mut self) {
        if self.current_text.is_empty() {
            return;
        }

        // Emit pending break as a segment
        if self.pending_break {
            self.pending_break = false;
            let break_seg = StyledSegment {
                text: String::from("\n\n"),
                style: TextStyle::default(),
                is_heading: false,
            };
            self.segments.push(break_seg);
        }

        let style = self.accum_style.clone();
        let is_heading = self.accum_heading;

        // Merge with last segment if styles are compatible
        if !self.no_merge_next {
            if let Some(last) = self.segments.last_mut() {
                if last.style == style && last.is_heading == is_heading && last.text != "\n\n" {
                    last.text.push_str(&self.current_text);
                    self.current_text.clear();
                    return;
                }
            }
        }
        self.no_merge_next = false;

        let seg = StyledSegment {
            text: std::mem::take(&mut self.current_text),
            style,
            is_heading,
        };
        self.segments.push(seg);
    }

    fn push_break(&mut self) {
        self.flush_current();
        let break_seg = StyledSegment {
            text: String::from("\n\n"),
            style: TextStyle::default(),
            is_heading: false,
        };
        self.segments.push(break_seg);
        self.pending_break = false;
    }

    /// Returns the style of the top frame, or default if no frames.
    fn top_style(&self) -> TextStyle {
        self.frames
            .last()
            .map(|f| f.style.clone())
            .unwrap_or_default()
    }
}

/// Sanitizes individual characters for terminal display.
fn sanitize_chars(s: &str) -> String {
    let mut result = String::with_capacity(s.len());
    for c in s.chars() {
        let cp = c as u32;
        if cp < 0x20 && !matches!(c, '\n' | '\t') {
            continue;
        }
        if c == '\u{feff}' {
            continue;
        }
        if cp == 0x7F || (0x80..=0x9F).contains(&cp) {
            continue;
        }
        match c {
            '\u{2500}'..='\u{257F}' => result.push(' '),
            '\u{2013}' | '\u{2014}' => result.push('-'),
            '\u{2018}' | '\u{2019}' => result.push('\''),
            '\u{201C}' | '\u{201D}' => result.push('"'),
            '\u{00B7}' => result.push('.'),
            '\u{00A0}' => result.push(' '),
            '\u{2026}' => result.push_str("..."),
            _ => result.push(c),
        }
    }
    result
}

/// Finds the position of the closing '>' in an HTML tag.
/// Returns the byte index of '>' itself (not the position after it).
fn find_tag_end(slice: &str) -> Option<usize> {
    let mut in_single_quote = false;
    let mut in_double_quote = false;

    for (i, c) in slice.char_indices() {
        if i == 0 {
            continue;
        }
        match c {
            '"' if !in_single_quote => in_double_quote = !in_double_quote,
            '\'' if !in_double_quote => in_single_quote = !in_single_quote,
            '>' if !in_single_quote && !in_double_quote => return Some(i),
            _ => {}
        }
    }
    None
}

/// Parses tag name and attributes from tag content (without '<' and '>').
fn parse_tag_name_and_attrs(
    content: &str,
    is_closing: bool,
) -> (String, Vec<(String, String)>, bool) {
    let bytes = content.as_bytes();
    let mut pos = 0;

    if is_closing && pos < bytes.len() && bytes[pos] == b'/' {
        pos += 1;
    }

    while pos < bytes.len() && bytes[pos].is_ascii_whitespace() {
        pos += 1;
    }

    let name_start = pos;
    while pos < bytes.len()
        && (bytes[pos].is_ascii_alphanumeric()
            || bytes[pos] == b'-'
            || bytes[pos] == b'_'
            || bytes[pos] == b':')
    {
        pos += 1;
    }

    let name = if pos > name_start {
        String::from_utf8_lossy(&bytes[name_start..pos]).to_string()
    } else {
        return (String::new(), Vec::new(), false);
    };

    let mut attrs = Vec::new();
    let mut is_self_closing = false;

    while pos < bytes.len() {
        while pos < bytes.len() && bytes[pos].is_ascii_whitespace() {
            pos += 1;
        }
        if pos >= bytes.len() {
            break;
        }

        if bytes[pos] == b'/' {
            is_self_closing = true;
            pos += 1;
            continue;
        }

        let attr_start = pos;
        while pos < bytes.len()
            && (bytes[pos].is_ascii_alphanumeric()
                || matches!(bytes[pos], b'-' | b'_' | b':' | b'.'))
        {
            pos += 1;
        }

        if pos == attr_start {
            break;
        }

        let attr_name = String::from_utf8_lossy(&bytes[attr_start..pos]).to_string();

        while pos < bytes.len() && bytes[pos].is_ascii_whitespace() {
            pos += 1;
        }

        if pos < bytes.len() && bytes[pos] == b'=' {
            pos += 1;
            while pos < bytes.len() && bytes[pos].is_ascii_whitespace() {
                pos += 1;
            }

            if pos < bytes.len() {
                let quote = bytes[pos];
                if quote == b'"' || quote == b'\'' {
                    pos += 1;
                    let val_start = pos;
                    while pos < bytes.len() && bytes[pos] != quote {
                        pos += 1;
                    }
                    let value = String::from_utf8_lossy(&bytes[val_start..pos]).to_string();
                    if pos < bytes.len() {
                        pos += 1;
                    }
                    attrs.push((attr_name, value));
                } else {
                    let val_start = pos;
                    while pos < bytes.len() && !bytes[pos].is_ascii_whitespace() {
                        pos += 1;
                    }
                    let value = String::from_utf8_lossy(&bytes[val_start..pos]).to_string();
                    attrs.push((attr_name, value));
                }
            }
        } else {
            attrs.push((attr_name, String::new()));
        }
    }

    (name, attrs, is_self_closing)
}

/// Extracts the inline style attribute value from attributes.
fn extract_inline_style(attrs: &[(String, String)]) -> String {
    for (name, value) in attrs {
        if name.eq_ignore_ascii_case("style") {
            return value.clone();
        }
    }
    String::new()
}

/// Applies inline CSS style properties to a TextStyle.
fn apply_inline_style(style: &mut TextStyle, css: &str) {
    if css.is_empty() {
        return;
    }

    for part in css.split(';') {
        let part = part.trim();
        if part.is_empty() {
            continue;
        }

        let colon_pos = match part.find(':') {
            Some(pos) => pos,
            None => continue,
        };
        let prop = part[..colon_pos].trim().to_lowercase();
        let value = part[colon_pos + 1..].trim();

        match prop.as_str() {
            "color" => {
                style.foreground = parse_color(value);
            }
            "font-weight" => {
                if matches!(value, "bold" | "700" | "800" | "900") {
                    style.bold = true;
                }
            }
            "text-decoration" => {
                if value.contains("underline") {
                    style.underline = true;
                }
                if value.contains("line-through") || value.contains("strike") {
                    style.strike = true;
                }
            }
            "font-style" => {
                if matches!(value, "italic" | "oblique") {
                    style.italic = true;
                }
            }
            _ => {}
        }
    }
}

/// Parses a CSS color value into RGB.
fn parse_color(value: &str) -> Option<[u8; 3]> {
    let value = value.trim();

    let named_colors: &[(&str, [u8; 3])] = &[
        ("red", [255, 0, 0]),
        ("green", [0, 128, 0]),
        ("blue", [0, 0, 255]),
        ("yellow", [255, 255, 0]),
        ("cyan", [0, 255, 255]),
        ("magenta", [255, 0, 255]),
        ("white", [255, 255, 255]),
        ("black", [0, 0, 0]),
        ("gray", [128, 128, 128]),
        ("grey", [128, 128, 128]),
        ("silver", [192, 192, 192]),
        ("maroon", [128, 0, 0]),
        ("navy", [0, 0, 128]),
        ("purple", [128, 0, 128]),
        ("orange", [255, 165, 0]),
        ("pink", [255, 192, 203]),
        ("brown", [165, 42, 42]),
        ("teal", [0, 128, 128]),
        ("olive", [128, 128, 0]),
        ("lime", [0, 255, 0]),
        ("aqua", [0, 255, 255]),
        ("fuchsia", [255, 0, 255]),
    ];

    if let Some((_, rgb)) = named_colors.iter().find(|(name, _)| *name == value) {
        return Some(*rgb);
    }

    if let Some(hex) = value.strip_prefix('#') {
        if hex.len() == 6 {
            if let (Ok(r), Ok(g), Ok(b)) = (
                u8::from_str_radix(&hex[0..2], 16),
                u8::from_str_radix(&hex[2..4], 16),
                u8::from_str_radix(&hex[4..6], 16),
            ) {
                return Some([r, g, b]);
            }
        } else if hex.len() == 3 {
            let bytes = hex.as_bytes();
            if let (Ok(r), Ok(g), Ok(b)) = (
                u8::from_str_radix(&format!("{}{}", bytes[0] as char, bytes[0] as char), 16),
                u8::from_str_radix(&format!("{}{}", bytes[1] as char, bytes[1] as char), 16),
                u8::from_str_radix(&format!("{}{}", bytes[2] as char, bytes[2] as char), 16),
            ) {
                return Some([r, g, b]);
            }
        }
    }

    if value.starts_with("rgb(") && value.ends_with(')') {
        let inner = &value[4..value.len() - 1];
        let parts: Vec<&str> = inner.split(',').collect();
        if parts.len() == 3 {
            if let (Ok(r), Ok(g), Ok(b)) = (
                parts[0].trim().parse::<u8>(),
                parts[1].trim().parse::<u8>(),
                parts[2].trim().parse::<u8>(),
            ) {
                return Some([r, g, b]);
            }
        }
    }

    None
}
