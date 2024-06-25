from functions.IMPORT import *

def load_personalities():
    try:
        with open('./assets/personalities.json', 'r') as f:
            personalities = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        personalities = {}
    return personalities

def save_personalities(personalities):
    with open('./assets/personalities.json', 'w') as f:
        json.dump(personalities, f)

