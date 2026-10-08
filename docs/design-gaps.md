# Design gaps

Places where the bancoctt-design skill's DESIGN.md has no specification and the closest component was used
(technical design section 0). Each entry: where, what was used, and the question for the design-system owners.

| Where | Used | Question |
|---|---|---|
| The page's lead line (`.page > .lead`, app.css) | Paragraph 1 in `--text-title` | DESIGN.md names Paragraph 1 for lead text but no colour; `--text-secondary` fails contrast on the light page (2.80) |
| DESIGN.md rule 1 "the document-page white in Components" | - | Components does not define it (technical design A-1); the slide stage will show slides on white paper |
| Form fields on touch screens | DESIGN.md sets a field's value in Paragraph 2 (14px) | Paragraph 1 (16px) when the pointer is coarse: iOS zooms the page in when a field under 16px takes the focus. A design-system style, only the choice differs (app.css) |
| Text the copied shell writes in `--text-section` / `--text-secondary` that must be read: product name, menu sections, status line, inactive tab titles, table headings, captions (app.css, layout.css) | `--text-weak` (5.74:1) | Colors › Contrast lists those roles as failing on the light theme (2.80-2.85:1), "never for text that must be read"; found by tests/ui/a11y.mjs (axe-core). Should Banco CTT replace the source tokens? |
| A primary button's hover (app.css) | `--primary-active` (6.24:1), the replacement Colors › Contrast lists | White on `--primary-hover` is 3.09:1 on the light theme ("Light fails"): awaiting the brand team's decision on the token |
| A data table with more than three columns in a narrow page that is not a phone (the administration's usage and audit log beside the side panel on a tablet) (app.css) | One card per row, each cell a label-and-value row, by the page's own width (under 640 px) | Data table (ours) says this for a phone only; a page beside the side panel is as narrow (368 px measured at 834 px), and scrolling a 4-7 column table sideways there hid most of it |
| The editor's Slide, Insert and Format menus (menu.json) | The menu bar copied from Cortex (noted's MenuBar), as the Project and Assistant menus | DESIGN.md has no menu or dropdown component; is a desktop menu bar acceptable for an editing tool, or should the actions be a toolbar? |
| The selected shape's actions under the slide (`.shape-actions`, app.css) | Text buttons (Components › Buttons), a row centred under the slide | No contextual action bar is specified |
| A form's multi-line field (`modalForm`'s `multiline`: a slide's points, notes, a chart's or a table's data) | The filled text input with its underline (Components › Text input), as a textarea | Text input specifies one line only |
