import ollama
import json
from pathlib import Path

def load_ontology():
    try:
        with open('../data/saya_graph_canonical_big.json', 'r') as f:  # adjust path if needed
            return json.load(f)
    except:
        return {}

def generate_ink_chunk(current_story, player_choice, ontology, history):
    system_prompt = '''You are Saya, a sassy, bratty, teasing narrator.
Output ONLY valid Ink syntax. Keep segments short. Use ontology for consistency.
'''
    response = ollama.chat(model='llama3.2', messages=[
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': f'Current story:\n{current_story[-800:]} \nChoice: {player_choice}\nContinue in Ink.'}
    ])
    return response['message']['content']

if __name__ == "__main__":
    print("Ready")