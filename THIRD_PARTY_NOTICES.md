# Third-Party Notices

termepub v2.0.0 includes the following third-party components:

## ECDICT (English-Chinese Dictionary with English definitions)

- **Source:** https://github.com/skywind3000/ECDICT
- **License:** MIT
- **Usage:** `ecdict_index.json` (~21 MB) is embedded in the termepub binary via `include_bytes!` and lazily parsed on first dictionary lookup.
- **Contents:** 160,000+ word entries with modern English definitions, sourced from contemporary English-language references.
- **Redistribution:** The dictionary data is redistributed as part of the compiled binary. Users who object to the dictionary data may compile termepub without it by removing the `ecdict_index.json` file before building.

### MIT License (ECDICT)

```
Copyright (c) 2015-2023 skywind3000 <skywind88888888@gmail.com>

Permission is hereby granted, free of charge, to any person obtaining
a copy of this software and associated documentation files (the
"Software"), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so, subject to
the following conditions:

The above copyright notice and this permission notice shall be
included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

## Rust Dependencies

All Rust dependencies used by termepub are available under their respective
licenses (MIT, Apache-2.0, or dual-licensed). Run `cargo license` for the
complete dependency license list. Key dependencies include:

- **crossterm** — MIT/Apache-2.0
- **ratatui** — MIT
- **tokio** — MIT
- **clap** — MIT/Apache-2.0
- **zip** — MIT/Apache-2.0
- **quick-xml** — MIT/Apache-2.0
- **serde** / **serde_json** — MIT/Apache-2.0
- **unicode-width** — MIT/Apache-2.0
- **unicode-segmentation** — MIT/Apache-2.0
- **sha1** — MIT/Apache-2.0
- **thiserror** — MIT/Apache-2.0
