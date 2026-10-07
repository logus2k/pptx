"""The assistant's tools in groups, as the tool-group router (router/slides_tools.yaml) chooses them, and the
groups an evaluation request needs, from its expectation (the oracle: the router's test labels)."""

from __future__ import annotations

# tool groups (an experiment for a router, labs/jev): what a request needs, from its expectation (the oracle)
GROUPS = {
    "core": ["ask_user", "propose_plan", "get_slide", "get_deck_outline"],
    "text": ["update_text", "edit_paragraphs", "format_text"],
    "table": ["edit_table"],
    "notes": ["set_notes"],
    "images": ["insert_image", "replace_image", "set_alt_text", "render_slide", "kb_list_images"],
    "structure": ["add_slide", "duplicate_slide", "delete_slide", "move_slide", "change_layout", "add_shape",
                  "move_resize_shape", "delete_shape"],
    "decks": ["create_deck", "duplicate_deck", "copy_slides", "change_template", "list_templates"],
    "knowledge": ["kb_search", "kb_read_document", "search_project"],
    "memory": ["remember", "search_conversations", "update_instructions"],
    "history": ["undo", "redo", "decide_changes"],
}  # fmt: skip
ROLE_GROUP = {"table": "table", "notes": "notes", "picture": "images"}


def oracle_groups(item: dict) -> set[str]:
    exp, need = item["expect"], {"core"}
    for roles in (exp.get("edit") or {}).values():
        need |= {ROLE_GROUP.get(r, "text") for r in roles}
        if "any" in roles:
            need |= {"structure", "text"}
    if exp.get("add"):
        need |= {"structure", "text"}  # a new slide, and the text written into it
    if exp.get("delete") or exp.get("move"):
        need |= {"structure"}
    if item["id"].startswith("kb-"):
        need |= {"knowledge"}  # and the groups its expectation names (a new slide, an edit, a question)
        if exp.get("edit") or exp.get("add"):
            need |= {"notes"}  # the source cited in the notes
    return need
