import re
import json
from pathlib import Path

import ollama

# --- Ontology loading --------------------------------------------------

# Prefer the compact canonical view; fall back to the full graph.
_ONTOLOGY_FILES = [
    "saya_graph_canonical_small.json",
    "saya_graph_canonical_big.json",
]
_SEARCH_DIRS = [
    Path("data"),
    Path("../data"),
    Path(__file__).resolve().parent / "data",
]


def load_ontology():
    """Load the canonical ontology graph as a dict. Prefers the small view."""
    for fname in _ONTOLOGY_FILES:
        for directory in _SEARCH_DIRS:
            path = directory / fname
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception as e:
                    print(f"Warning: Failed to load {path}: {e}")
    print("\u26a0\ufe0f Ontology not found. Running without world knowledge.")
    return {}

# --- World brief (the part that actually grounds the narrator) ---------

# Entity types that represent in-world canon, mapped to brief section labels,
# in display order. Note/Document types are workspace/graph-maintenance
# artifacts (confidence scores, name reconciliation) and are excluded.
_BRIEF_SECTIONS = [
    ("Project", "PREMISE"),
    ("Person", "CHARACTERS"),
    ("Relationship", "RELATIONSHIPS"),
    ("Organization", "FACTIONS & ORGANIZATIONS"),
    ("Location", "PLACES"),
]


def _entity_brief_line(props, max_note_chars):
    name = props.get("name") or props.get("title") or "?"
    descriptor = props.get("role") or props.get("kind")
    body = props.get("notes") or props.get("summary") or props.get("content") or ""
    body = " ".join(body.split())  # collapse newlines/whitespace
    if len(body) > max_note_chars:
        body = body[:max_note_chars].rsplit(" ", 1)[0].rstrip(",.;") + "\u2026"
    head = name if not descriptor else f"{name} \u2014 {descriptor}"
    return f"- {head}: {body}" if body else f"- {head}"


def build_world_brief(ontology, max_chars=22000, max_note_chars=600):
    """Render ontology entities into a compact, readable canon block."""
    entities = (ontology or {}).get("entities", {})
    if not entities:
        return ""

    by_type = {}
    for ent in entities.values():
        by_type.setdefault(ent.get("type"), []).append(ent.get("properties") or {})

    blocks = []
    for type_name, label in _BRIEF_SECTIONS:
        group = by_type.get(type_name)
        if not group:
            continue
        lines = [_entity_brief_line(p, max_note_chars) for p in group]
        blocks.append(label + ":\n" + "\n".join(lines))

    brief = "\n\n".join(blocks).strip()
    if len(brief) > max_chars:
        brief = brief[:max_chars].rsplit("\n", 1)[0] + "\n\u2026(canon truncated)"
    return brief


# Build once and reuse across turns (the file doesn't change at runtime).
_WORLD_BRIEF = None


def get_world_brief():
    global _WORLD_BRIEF
    if _WORLD_BRIEF is None:
        _WORLD_BRIEF = build_world_brief(load_ontology())
    return _WORLD_BRIEF

# --- Generation --------------------------------------------------------

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"^```[\w-]*\s*$", re.MULTILINE)


def _clean_ink_output(text):
    """Strip qwen3 reasoning blocks and markdown fences before the Ink is
    appended to the running story (otherwise that noise re-enters the prompt
    on the next turn)."""
    text = _THINK_RE.sub("", text)
    text = _FENCE_RE.sub("", text)
    return text.strip()


def generate_next_ink_chunk(current_story: str, player_choice: str = ""):
    world_brief = get_world_brief()

    system_prompt = (
        "You are Saya, a sassy, bratty, teasing narrator of an interactive "
        "fiction set in the world of \"Saya and the Dragon\".\n"
        "Voice: sarcastic, playful, theatrical, a little mean.\n\n"
        "OUTPUT RULES:\n"
        "- Respond in valid Ink syntax ONLY. No preamble, no explanations, "
        "no markdown code fences.\n"
        "- Each turn: 1-2 short narrative paragraphs, then 2-4 choices.\n"
        "- Write choices as:  + [Choice text] -> knot_name\n"
        "- Stay consistent with the established canon below. Do not rename or "
        "contradict known characters, places, or relationships. You may invent "
        "new minor detail, but never overwrite canon."
    )

    if world_brief:
        system_prompt += (
            "\n\n=== ESTABLISHED CANON ===\n" + world_brief + "\n=== END CANON ==="
        )

    user_prompt = (
        f"Current story so far:\n{current_story[-1500:]}\n\n"
        f"Player just chose: {player_choice}\n\n"
        "Continue the story, consistent with the canon. Output ONLY valid Ink code."
    )

    try:
        response = ollama.chat(
            model="qwen3:14b",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            options={"num_ctx": 16384, "temperature": 0.8},
        )
        return _clean_ink_output(response["message"]["content"])
    except Exception as e:
        return f"=== error\nSaya: Ugh, something broke. Error: {str(e)}\n+ [Try again] -> start"