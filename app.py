from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import json

from ink_generator import generate_next_ink_chunk, load_ontology, generate_spine, DEFAULT_SPINE

app = FastAPI(title="Saya's Ontology Adventure")
app.mount("/static", StaticFiles(directory="static"), name="static")

SPINE_PATH = Path("data/memory/spine.json")
MAX_BEAT_TURNS = 5          # force the story forward if a beat stalls

# --- Game state --------------------------------------------------------
current_story = ""
spine = []
beat_index = 0
beat_turns = 0
finished = False


def _seed_story():
    p = Path("initial.ink")
    if p.exists():
        return p.read_text(encoding="utf-8")
    return "=== start\nSaya greets you in the dark, all teeth and attitude.\n+ [Begin] -> start"


current_story = _seed_story()

def _save_spine():
    try:
        SPINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        SPINE_PATH.write_text(json.dumps(spine, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"Could not save spine: {e}")


def _is_fallback(s):
    return [b.get("title") for b in (s or [])] == [b.get("title") for b in DEFAULT_SPINE]


def _ensure_spine():
    """Use the in-memory spine, else load from disk, else generate one. A
    persisted fallback arc is auto-upgraded once real generation succeeds."""
    global spine
    if spine and not _is_fallback(spine):
        return
    if not spine and SPINE_PATH.exists():
        try:
            loaded = json.loads(SPINE_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, list) and loaded:
                spine = loaded
        except Exception as e:
            print(f"Could not read spine: {e}")
    if spine and not _is_fallback(spine):
        return
    generated, ok = generate_spine()
    spine = generated
    if ok:
        _save_spine()


def _new_spine():
    """Generate a fresh arc (new playthrough). Only persisted if real."""
    global spine
    generated, ok = generate_spine()
    spine = generated
    if ok:
        _save_spine()


def _progress():
    total = len(spine)
    i = max(0, min(beat_index, total - 1)) if total else 0
    beat = spine[i] if total else {}
    return {
        "act": beat.get("act", i + 1) if total else 0,
        "title": beat.get("title", "") if total else "",
        "total": total,
        "beat_index": i,
        "finished": finished,
    }

@app.get("/", response_class=HTMLResponse)
async def home():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()


@app.post("/choice")
async def make_choice(request: Request):
    global current_story, beat_index, beat_turns, finished
    data = await request.json()
    choice_text = data.get("choice_text", "")

    _ensure_spine()
    if finished:
        return {"success": True, "new_ink": "", "progress": _progress()}

    result = generate_next_ink_chunk(current_story, choice_text, spine, beat_index)
    current_story += "\n\n" + result["ink"]

    # Advance the spine: on the model's signal, or force it if a beat stalls.
    beat_turns += 1
    on_final = beat_index >= len(spine) - 1
    if on_final:
        if result["end"] or beat_turns >= MAX_BEAT_TURNS:
            finished = True
    elif result["advance"] or beat_turns >= MAX_BEAT_TURNS:
        beat_index += 1
        beat_turns = 0

    return {"success": True, "new_ink": result["ink"], "progress": _progress()}

@app.post("/reset")
async def reset_story():
    """Reset the run to the seed and the first beat. Keeps the same arc (fast)."""
    global current_story, beat_index, beat_turns, finished
    current_story = _seed_story()
    beat_index = 0
    beat_turns = 0
    finished = False
    _ensure_spine()
    return {"success": True, "progress": _progress()}


@app.post("/new_adventure")
async def new_adventure():
    """Roll a fresh arc and restart (slower \u2014 regenerates the spine)."""
    global current_story, beat_index, beat_turns, finished
    _new_spine()
    current_story = _seed_story()
    beat_index = 0
    beat_turns = 0
    finished = False
    return {"success": True, "progress": _progress()}


@app.get("/spine")
async def get_spine():
    _ensure_spine()
    return {"spine": spine, "progress": _progress()}


@app.get("/initial.ink", response_class=HTMLResponse)
async def get_initial_ink():
    with open("initial.ink", "r", encoding="utf-8") as f:
        return f.read()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)