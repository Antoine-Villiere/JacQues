from functions.config import *
from functions.IMPORT import os, json, shutil, dcc, html


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

        # Move all files from the original to the new session directory
        if os.path.exists(original_session_dir):
            for filename in os.listdir(original_session_dir):
                original_file = os.path.join(original_session_dir, filename)
                new_file = os.path.join(new_session_dir, filename.replace(session_id, new_name))
                shutil.move(original_file, new_file)

            # If the old directory is now empty, remove it
            if not os.listdir(original_session_dir):
                os.rmdir(original_session_dir)
        else:
            # If original directory is missing, just initialize new session data
            with open(new_file_path, 'w') as file:
                json.dump(data, file)
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
    session_details = []  # List to store session ids and their last modified times

    # Traverse each directory in CHAT_DIR
    for session_dir in os.listdir(CHAT_DIR):
        session_path = os.path.join(CHAT_DIR, session_dir)
        if os.path.isdir(session_path):  # Make sure it's a directory
            # Look for a JSON file in this directory
            for file in os.listdir(session_path):
                if file.endswith('.json'):
                    # Get the path to the JSON file
                    file_path = os.path.join(session_path, file)
                    # Get the last modified time
                    last_modified = os.path.getmtime(file_path)
                    # Get the session id from the file name
                    session_id = os.path.splitext(file)[0]
                    # Append the session id and last modified time to the list
                    session_details.append((session_id, last_modified))

    # Sort sessions by last modified time, in descending order
    session_details.sort(key=lambda x: x[1], reverse=True)

    # Extract sorted session ids
    sessions = [session[0] for session in session_details]

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
