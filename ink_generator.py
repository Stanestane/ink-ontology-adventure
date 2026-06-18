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

# --- World brief (grounds the narrator in canon) -----------------------

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
    body = " ".join(body.split())
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


_WORLD_BRIEF = None


def get_world_brief():
    global _WORLD_BRIEF
    if _WORLD_BRIEF is None:
        _WORLD_BRIEF = build_world_brief(load_ontology())
    return _WORLD_BRIEF

# --- Story spine (the overarching arc) ---------------------------------

# Generic fallback arc, used if the model can't produce valid JSON. Still
# shaped like a real story so the game always has a beginning, middle, end.
DEFAULT_SPINE = [
    {"act": 1, "title": "The Hook",
     "summary": "Saya and the Dragon are pulled into a scheme or threat they can't walk away from."},
    {"act": 2, "title": "On the Road",
     "summary": "They set out; the stakes and the road ahead take shape amid friction and banter."},
    {"act": 3, "title": "Complications",
     "summary": "A rival, betrayal, or nasty surprise knocks the plan sideways."},
    {"act": 4, "title": "The Low Point",
     "summary": "Things fall apart; trust is tested and the goal looks lost."},
    {"act": 5, "title": "The Gambit",
     "summary": "Saya improvises a desperate, clever play that risks everything."},
    {"act": 6, "title": "Resolution",
     "summary": "The scheme pays off or fails spectacularly, and the bond between Saya and the Dragon is redefined."},
]


def _parse_spine(text, num_beats):
    """Extract a JSON array of beats from model output; return None on failure."""
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except Exception:
        return None
    if not isinstance(data, list) or not data:
        return None
    beats = []
    for i, b in enumerate(data[:num_beats]):
        if not isinstance(b, dict):
            continue
        beats.append({
            "act": i + 1,
            "title": str(b.get("title") or f"Act {i + 1}").strip(),
            "summary": str(b.get("summary") or b.get("goal") or "").strip(),
        })
    return beats or None

def generate_spine(num_beats=6):
    """Ask the model to design a fresh adventure arc grounded in the ontology.
    Falls back to DEFAULT_SPINE if generation or parsing fails."""
    world_brief = get_world_brief()
    system_prompt = (
        "You are a story architect for an interactive fiction set in the world of "
        "\"Saya and the Dragon\". Design the SPINE of ONE playable adventure: a "
        f"sequence of exactly {num_beats} dramatic beats running from inciting "
        "incident through rising complications and a low point to a climax and "
        "resolution. Ground it in the established canon \u2014 use real characters, "
        "places, and relationships, and give it a concrete throughline.\n\n"
        "Output ONLY a JSON array. Each element must be an object: "
        "{\"act\": <int>, \"title\": <short title>, \"summary\": <1-2 sentence "
        "situation/goal for that beat>}. No prose, no markdown, no code fences."
    )
    if world_brief:
        system_prompt += "\n\n=== ESTABLISHED CANON ===\n" + world_brief + "\n=== END CANON ==="
    user_prompt = (
        f"Design a fresh {num_beats}-beat adventure spine for Saya and the Dragon, "
        "specific to this world. Output ONLY the JSON array."
    )
    try:
        response = ollama.chat(
            model="qwen3:4b",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            options={"num_ctx": 16384, "temperature": 0.9},
        )
        text = _clean_ink_output(response["message"]["content"])
        parsed = _parse_spine(text, num_beats)
        if parsed:
            return parsed, True
        return list(DEFAULT_SPINE), False
    except Exception as e:
        print(f"Spine generation failed, using default: {e}")
        return list(DEFAULT_SPINE), False

# --- Generation --------------------------------------------------------

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"^```[\w-]*\s*$", re.MULTILINE)
_ADVANCE_RE = re.compile(r"#\s*ADVANCE\b", re.IGNORECASE)
_END_RE = re.compile(r"#\s*END\b", re.IGNORECASE)


def _clean_ink_output(text):
    """Strip qwen3 reasoning blocks and markdown fences."""
    text = _THINK_RE.sub("", text)
    text = _FENCE_RE.sub("", text)
    return text.strip()


def _steering_block(spine, beat_index):
    """Build the soft-steering instruction for the current beat."""
    if not spine:
        return ""
    n = len(spine)
    i = max(0, min(beat_index, n - 1))
    beat = spine[i]
    is_final = i == n - 1
    block = (
        "\n\nSTORY SPINE (internal direction \u2014 never show act numbers or these "
        "notes to the player):\n"
        f"You are in Act {beat.get('act', i + 1)} of {n}: {beat.get('title', '')} "
        f"\u2014 {beat.get('summary', '')}\n"
        "Steer events toward fulfilling THIS beat. Don't rush \u2014 let it breathe "
        "over a few turns \u2014 but keep nudging the story this way instead of wandering.\n"
    )
    if is_final:
        block += (
            "This is the FINAL beat. When it resolves, bring the whole adventure to a "
            "satisfying close, give the player a final reflective choice or two, and put "
            "#END on its own last line."
        )
    else:
        nxt = spine[i + 1]
        block += (
            "When this beat has clearly played out, put #ADVANCE on its own last line to "
            f"move the story toward the next beat: {nxt.get('title', '')}."
        )
    return block

def generate_next_ink_chunk(current_story, player_choice="", spine=None, beat_index=0):
    """Generate the next Ink chunk, steered by the current spine beat.
    Returns {"ink": str, "advance": bool, "end": bool}."""
    world_brief = get_world_brief()

    system_prompt = (
        "You are Saya, a sassy, bratty, teasing narrator of an interactive fiction "
        "set in the world of \"Saya and the Dragon\".\n"
        "Voice: sarcastic, playful, theatrical, a little mean.\n\n"
        "OUTPUT RULES:\n"
        "- Respond in valid Ink syntax ONLY. No preamble, no explanations, no "
        "markdown code fences.\n"
        "- Each turn: 1-2 short narrative paragraphs, then 2-4 choices.\n"
        "- Write choices as:  + [Choice text] -> knot_name\n"
        "- Stay consistent with the established canon. Do not rename or contradict "
        "known characters, places, or relationships. Invent only minor new detail."
    )
    if world_brief:
        system_prompt += (
            "\n\n=== ESTABLISHED CANON ===\n" + world_brief + "\n=== END CANON ==="
        )
    system_prompt += _steering_block(spine, beat_index)

    user_prompt = (
        f"Current story so far:\n{current_story[-1500:]}\n\n"
        f"Player just chose: {player_choice}\n\n"
        "Continue the story, consistent with the canon and steered toward the current "
        "beat. Output ONLY valid Ink code."
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
        raw = response["message"]["content"]
        advance = bool(_ADVANCE_RE.search(raw))
        end = bool(_END_RE.search(raw))
        ink = _clean_ink_output(raw)
        ink = _END_RE.sub("", _ADVANCE_RE.sub("", ink)).strip()
        return {"ink": ink, "advance": advance, "end": end}
    except Exception as e:
        return {
            "ink": f"=== error\nSaya: Ugh, something broke. Error: {str(e)}\n+ [Try again] -> start",
            "advance": False,
            "end": False,
        }