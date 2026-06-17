from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import ollama
from ink_generator import generate_next_ink_chunk, load_ontology

app = FastAPI(title="Saya's Ontology Adventure")

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Load initial story
initial_path = Path("initial.ink")
if initial_path.exists():
    current_story = initial_path.read_text(encoding="utf-8")
else:
    current_story = """=== start
Saya's voice cuts through the darkness like a knife wrapped in velvet and sarcasm.

*Well, well, well...* Look who finally decided to show up. 

I’m Saya. Yeah, *that* Saya. The one who’s going to narrate your little adventure whether you like it or not. 

Don’t get too comfortable, mortal. I bite.

+ [Tell me more about you, Saya.]
    -> saya_intro

+ [Skip the chit-chat. Let’s dive straight into the story.]
    -> begin_adventure

=== saya_intro
*rolls eyes* Oh great, another curious one.

Fine. I'm ancient, bratty, and I know this world better than you ever will.

-> start

=== begin_adventure
*smirks* Finally. Let's get this show on the road...

-> first_scene
"""

@app.get("/", response_class=HTMLResponse)
async def home():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.post("/choice")
async def make_choice(request: Request):
    global current_story
    data = await request.json()
    choice_text = data.get("choice_text", "")

    next_chunk = generate_next_ink_chunk(current_story, choice_text)
    current_story += "\n\n" + next_chunk

    return {"success": True, "new_ink": next_chunk, "full_story": current_story}

@app.post("/reset")
async def reset_story():
    """Reset the running story back to the initial seed (called on page load)."""
    global current_story
    if Path("initial.ink").exists():
        current_story = Path("initial.ink").read_text(encoding="utf-8")
    return {"success": True}

@app.get("/initial.ink", response_class=HTMLResponse)
async def get_initial_ink():
    with open("initial.ink", "r", encoding="utf-8") as f:
        return f.read()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)