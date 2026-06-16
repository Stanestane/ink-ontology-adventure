from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import ollama
from ink_generator import generate_ink_chunk, load_ontology

app = FastAPI()

story_ink = open('initial.ink', 'r').read() if Path('initial.ink').exists() else '-> start\n=== start\nSaya: "Hey there..."\n* Choice 1 -> next\n-> END'

@app.get("/", response_class=HTMLResponse)
def root():
    with open("static/index.html") as f:
        return f.read()

@app.post("/choice")
def make_choice(data: dict):
    global story_ink
    new = generate_ink_chunk(story_ink, data.get('choice', ''), load_ontology(), '')
    story_ink += '\n\n' + new
    return {'ink': story_ink}

app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8000)