from JacQues.functions.config import *
from JacQues.functions.IMPORT import os, json, shutil, dcc, html


def save_chat(session_id, data, new_name=None):
    """Save or update chat data in a JSON file, with optional session renaming."""
    # Define original and new session directory paths
    original_session_dir = os.path.join(CHAT_DIR, session_id)
    original_file_path = os.path.join(original_session_dir, f"{session_id}.json")

    if new_name:
        new_session_dir = os.path.join(CHAT_DIR, new_name)
        new_file_path = os.path.join(new_session_dir, f"{new_name}.json")

        # Ensure the new directory exists
        if not os.path.exists(new_session_dir):
            os.makedirs(new_session_dir)

        # Handle renaming the file
        if os.path.exists(original_file_path):
            with open(original_file_path, 'r') as file:
                content = json.load(file)
            with open(new_file_path, 'w') as file:
                json.dump(content, file)
            os.remove(original_file_path)
        else:
            # If original file is missing, just initialize new session data
            with open(new_file_path, 'w') as file:
                json.dump(data, file)

        # If the old directory is now empty, remove it
        if not os.listdir(original_session_dir):
            os.rmdir(original_session_dir)
        elif original_session_dir != new_session_dir:
            # If directories are different and the old is not empty, use shutil.move
            shutil.move(original_session_dir, new_session_dir)
    else:
        # No renaming, just save the data
        if not os.path.exists(original_session_dir):
            os.makedirs(original_session_dir)
        with open(original_file_path, 'w') as file:
            json.dump(data, file)


def delete_chat(session_id):
    """ Delete chat data directory for a specific session. """
    session_dir = os.path.join(CHAT_DIR, session_id)
    if os.path.exists(session_dir):
        shutil.rmtree(session_dir)
        return True
    else:
        print("The directory does not exist.")
        return False


def load_chat(session_id):
    """ Load chat data from a JSON file within its specific session directory. """
    try:
        with open(os.path.join(CHAT_DIR, session_id, f"{session_id}.json"), 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def load_all_sessions():
    sessions = []
    # Traverse each directory in CHAT_DIR
    for session_dir in os.listdir(CHAT_DIR):
        session_path = os.path.join(CHAT_DIR, session_dir)
        if os.path.isdir(session_path):  # Make sure it's a directory
            # Look for a JSON file in this directory
            for file in os.listdir(session_path):
                if file.endswith('.json'):
                    session_id = os.path.splitext(file)[0]
                    sessions.append(session_id)
    return sessions


def create_session_div(session_id):
    """ Helper function to create a chat session div with edit, delete, and save buttons (hidden initially). """
    return html.Div([
        dcc.Input(id={'type': 'edit-input', 'index': session_id}, value=session_id,
                  style={'display': 'none', 'width': '100%', 'flex': '1'}),
        html.Button('Save', id={'type': 'save-button', 'index': session_id}, n_clicks=0,
                    style={'display': 'none', 'margin-left': '10px'}),
        html.Span(session_id, id={'type': 'session-name', 'index': session_id},
                  style={'margin-right': '10px', 'flex': '1'}),
        html.Button('Edit', id={'type': 'edit-button', 'index': session_id}, n_clicks=0,
                    style={'margin-left': '10px'}),
        html.Button('Delete', id={'type': 'delete-button', 'index': session_id}, n_clicks=0,
                    style={'margin-left': '10px'}),
    ], id={'type': 'chat-session', 'index': session_id},
        style={
            'padding': '10px', 'cursor': 'pointer', 'border': f'1px solid {colors["secondary"]}',
            'margin': '5px', 'borderRadius': '5px', 'display': 'flex', 'alignItems': 'center',
            'justifyContent': 'space-between', 'backgroundColor': '#FFF', 'boxShadow': '0 2px 4px rgba(0,0,0,0.1)'
        })


def file_icon_and_color(ext):
    # Get the icon and color based on file extension
    return ICON_MAP.get(ext, ('fa-file', '#566573'))
