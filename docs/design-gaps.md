# Design gaps

Places where the bancoctt-design skill's DESIGN.md has no specification and the closest component was used
(technical design section 0). Each entry: where, what was used, and the question for the design-system owners.

| Where | Used | Question |
|---|---|---|
| The page's lead line (`.page > .lead`, app.css) | Paragraph 1 in `--text-title` | DESIGN.md names Paragraph 1 for lead text but no colour; `--text-secondary` fails contrast on the light page (2.80) |
| DESIGN.md rule 1 "the document-page white in Components" | - | Components does not define it (technical design A-1); the slide stage will show slides on white paper |
| Form fields on touch screens | DESIGN.md sets a field's value in Paragraph 2 (14px) | Paragraph 1 (16px) when the pointer is coarse: iOS zooms the page in when a field under 16px takes the focus. A design-system style, only the choice differs (app.css) |
