from functions.config import *
from functions.IMPORT import os, json, shutil, dcc, html, datetime


def save_chat(session_id, data, new_name=None):
    """Save or update chat data in a JSON file, with optional session renaming."""
    original_session_dir = os.path.join(CHAT_DIR, session_id)
    original_file_path = os.path.join(original_session_dir, f"{session_id}.json")

    if new_name:
        new_session_dir = os.path.join(CHAT_DIR, new_name)
        new_file_path = os.path.join(new_session_dir, f"{new_name}.json")

        if not os.path.exists(new_session_dir):
            os.makedirs(new_session_dir)

        if os.path.exists(original_session_dir):
            for filename in os.listdir(original_session_dir):
                original_file = os.path.join(original_session_dir, filename)
                new_file = os.path.join(new_session_dir, filename.replace(session_id, new_name))
                shutil.move(original_file, new_file)

            if not os.listdir(original_session_dir):
                os.rmdir(original_session_dir)
        else:
            with open(new_file_path, 'w') as file:
                json.dump(data, file)
    else:
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
        print( "The directory does not exist.")
        return False


def load_chat(session_id):
    """ Load chat data from a JSON file within its specific session directory. """
    try:
        with open(os.path.join(CHAT_DIR, session_id, f"{session_id}.json"), 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def load_all_sessions():
    session_details = []

    for session_dir in os.listdir(CHAT_DIR):
        if 'chat_reminder' in session_dir:
            continue
        session_path = os.path.join(CHAT_DIR, session_dir)
        if os.path.isdir(session_path):
            for file in os.listdir(session_path):
                if file.endswith('.json'):
                    file_path = os.path.join(session_path, file)
                    last_modified = os.path.getmtime(file_path)
                    session_id = os.path.splitext(file)[0]
                    session_details.append((session_id, last_modified))

    session_details.sort(key=lambda x: x[1], reverse=True)
    sessions = [session[0] for session in session_details]

    return sessions


def create_session_div(session_id):
    """Helper function to create a chat session div with edit, delete, and save buttons (hidden initially)."""

    file_path = os.path.join(CHAT_DIR, session_id)

    last_modified_timestamp = os.path.getmtime(file_path)
    last_modified = datetime.datetime.fromtimestamp(last_modified_timestamp).strftime('%Y-%m-%d %H:%M')

    return html.Div(
        [
            dcc.Input(
                id={'type': 'edit-input', 'index': session_id},
                value=session_id,
                style={'display': 'none', 'width': '100%', 'flex': '1'}
            ),

            html.Button(
                'Save',
                id={'type': 'save-button', 'index': session_id},
                n_clicks=0,
                style={'display': 'none', 'margin-left': '10px', 'backgroundColor': '#5cb85c', 'color': '#fff',
                       'border': 'none',
                       'padding': '5px 10px', 'borderRadius': '3px', 'cursor': 'pointer'}
            ),

            html.Div(
                [
                    html.Span(
                        session_id,
                        id={'type': 'session-name', 'index': session_id},
                        style={'margin-right': '10px', 'flex': '1', 'fontWeight': 'bold', 'fontSize': '16px',
                               'color': '#333'}
                    ),

                    html.Span(
                        f"Last Modified: {last_modified}",
                        id={'type': 'last-modified', 'index': session_id},
                        style={'margin-left': '5px', 'color': 'gray', 'fontSize': '10px'}
                    ),
                ],
                style={'flex': '1', 'display': 'flex', 'flexDirection': 'column'}
            ),

            html.Div(
                [
                    html.Button(
                        'Edit',
                        id={'type': 'edit-button', 'index': session_id},
                        n_clicks=0,
                        style={'margin-left': '10px', 'backgroundColor': '#f0ad4e', 'color': '#fff', 'border': 'none',
                               'padding': '5px 10px', 'borderRadius': '3px', 'cursor': 'pointer'}
                    ),

                    html.Button(
                        'Delete',
                        id={'type': 'delete-button', 'index': session_id},
                        n_clicks=0,
                        style={'margin-left': '10px', 'backgroundColor': '#d9534f', 'color': '#fff', 'border': 'none',
                               'padding': '5px 10px', 'borderRadius': '3px', 'cursor': 'pointer'}
                    ),
                ],
                style={'display': 'flex', 'alignItems': 'center'}
            ),
        ],
        id={'type': 'chat-session', 'index': session_id},
        style={
            'padding': '15px', 'cursor': 'pointer', 'border': f'1px solid {colors["secondary"]}',
            'margin': '10px 0', 'borderRadius': '8px', 'display': 'flex', 'alignItems': 'center',
            'justifyContent': 'space-between', 'backgroundColor': '#f9f9f9', 'boxShadow': '0 2px 4px rgba(0,0,0,0.1)'
        }
    )


def file_icon_and_color(ext):
    return ICON_MAP.get(ext, ('fa-file', '#566573'))


def save_info(info):
    info = {'info': info}
    with open('./assets/info.json', 'w') as f:
        json.dump(info, f)
