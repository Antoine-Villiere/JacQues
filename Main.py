from IMPORT import *
from Scrape_and_find import scrape_and_find
from Parse_and_find import main
import os

session_id_global = None
new_chat = None

CHAT_DIR = 'chat_sessions'
if not os.path.exists(CHAT_DIR):
    os.mkdir(CHAT_DIR)

# Path to the file
file_path = r'./assets/prompt'
ai_profile_pic = "assets/Ai.png"
user_profile_pic = "assets/User.png"

# Function to read file content
with open(file_path, 'r', encoding='utf-8') as file:
    prompt = file.read()

# Initialize Dash app with Bootstrap theme
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP,
                                                "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.15.1/css/all.min.css"],
                suppress_callback_exceptions=True)

# Define a consistent color scheme
colors = {
    'background': '#f8f9fa',
    'text': '#343a40',
    'primary': '#005f73',
    'secondary': '#e9d8a6',
    'user': '#94d2bd',
}

# Define some styles that will be used repeatedly
btn_style = {
    'width': '100%',
    'backgroundColor': colors['primary'],
    'color': 'white',
    'borderRadius': '5px',
    'border': 'none',
    'padding': '10px',
    'marginBottom': '10px'
}

# Define a dictionary to map file extensions to icon class names (assuming use of FontAwesome or similar)
ICON_MAP = {
    'csv': ('fa-file-csv', '#cb4335'),
    'docx': ('fa-file-word', '#2e86c1'),
    'epub': ('fa-file-alt', '#f4d03f'),
    'hwp': ('fa-file', '#5dade2'),
    'ipynb': ('fa-file-code', '#a569bd'),
    'jpeg': ('fa-file-image', '#a3e4d7'),
    'jpg': ('fa-file-image', '#a3e4d7'),
    'mbox': ('fa-file-archive', '#85929e'),
    'md': ('fa-file-alt', '#5d6d7e'),
    'mp3': ('fa-file-audio', '#d35400'),
    'mp4': ('fa-file-video', '#d35400'),
    'pdf': ('fa-file-pdf', '#e74c3c'),
    'png': ('fa-file-image', '#1abc9c'),
    'ppt': ('fa-file-powerpoint', '#dc7633'),
    'pptm': ('fa-file-powerpoint', '#dc7633'),
    'pptx': ('fa-file-powerpoint', '#dc7633'),
    'doc': ('fa-file-word', '#2e86c1'),
    'docm': ('fa-file-word', '#2e86c1'),
    'dot': ('fa-file-word', '#2e86c1'),
    'dotx': ('fa-file-word', '#2e86c1'),
    'dotm': ('fa-file-word', '#2e86c1'),
    'rtf': ('fa-file-word', '#2e86c1'),
    'wps': ('fa-file-word', '#2e86c1'),
    'wpd': ('fa-file-word', '#2e86c1'),
    'sxw': ('fa-file-openoffice', '#2980b9'),
    'stw': ('fa-file-openoffice', '#2980b9'),
    'sxg': ('fa-file-openoffice', '#2980b9'),
    'pages': ('fa-file-word', '#2e86c1'),
    'mw': ('fa-file-word', '#2e86c1'),
    'mcw': ('fa-file-word', '#2e86c1'),
    'uot': ('fa-file-openoffice', '#2980b9'),
    'uof': ('fa-file-openoffice', '#2980b9'),
    'uos': ('fa-file-openoffice', '#2980b9'),
    'uop': ('fa-file-powerpoint', '#dc7633'),
    'pot': ('fa-file-powerpoint', '#dc7633'),
    'potx': ('fa-file-powerpoint', '#dc7633'),
    'potm': ('fa-file-powerpoint', '#dc7633'),
    'key': ('fa-file-powerpoint', '#dc7633'),
    'odp': ('fa-file-openoffice', '#2980b9'),
    'odg': ('fa-file-openoffice', '#2980b9'),
    'otp': ('fa-file-openoffice', '#2980b9'),
    'fopd': ('fa-file-openoffice', '#2980b9'),
    'sxi': ('fa-file-openoffice', '#2980b9'),
    'sti': ('fa-file-openoffice', '#2980b9'),
    'html': ('fa-file-code', '#27ae60'),
    'htm': ('fa-file-code', '#27ae60')
}


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


# Define the layout of the app
app.layout = dbc.Container([
    dbc.Row([
        dbc.Col([
            html.Button('New Chat', id='new-chat-button', n_clicks=0, style=btn_style),
            html.Div(id='list-chats',
                     style={'marginTop': '10px', 'marginBottom': '10px', 'height': '90%', 'overflowY': 'scroll'}),
            html.Div(id='file-display-area', style={'marginTop': '10px', 'overflowY': 'auto', 'maxHeight': '50px'}),

        ], width={'size': 3, 'offset': 0}, style={'backgroundColor': 'white', 'padding': '20px', 'borderRadius': '10px',
                                                  'border': f'1px solid {colors["secondary"]}', 'height': '95vh'}),

        dbc.Col([
            html.Div([
                html.Div(id='chat-history', style={'marginBottom': '10px', 'height': '82%', 'overflowY': 'scroll'}),
                html.Div([
                    dcc.Textarea(id='user-input', placeholder='Message Jacques... Or type "/" for commands...',
                                 spellCheck=True,
                                 style={'marginBottom': '0px', 'width': '95%', 'overflowY': 'scroll',
                                        'borderRadius': '5px', 'color': '#6c757d',
                                        'background-color': 'transparent', 'border': 'none'}),
                    html.Button('\u21E7', id='send-button', n_clicks=0, style={
                        'width': '5%',
                        'backgroundColor': colors['primary'],
                        'color': 'white',
                        'borderRadius': '5px',
                        'border': 'none',
                        'padding': '15px',
                    }),
                ], style={'display': 'flex', 'alignItems': 'center', 'backgroundColor': 'white', 'borderRadius': '10px',
                          'border': f'1px solid {colors["secondary"]}', 'marginBottom': '20px'}),
                html.Div([], id='file-preview',
                         style={'marginTop': '20px', 'marginBottom': '10px', 'overflowY': 'scroll'}),

                dcc.Upload(
                    html.Button('Upload Document', style=btn_style),
                    id='upload-data',
                    multiple=True,
                    accept='.pdf, .doc, .docx, .docm, .dot, .dotx, .dotm, .rtf, .wps, .wpd, .sxw, .stw, .sxg, .pages, '
                           '.mw, .mcw, .uot, .uof, .uos, .uop, .ppt, .pptx, .pot, .pptm, .potx, .potm, .key, .odp, '
                           '.odg, .otp, .fopd, .sxi, .sti, .epub, .html, .htm',
                    style={'marginTop': '5px'}
                ),
                dcc.Store(id='stored-filenames', data=[]),
                dcc.Store(id='session-id'),
            ], style={'backgroundColor': 'white', 'padding': '20px', 'borderRadius': '10px',
                      'border': f'1px solid {colors["secondary"]}', 'height': '95vh'})
        ], width={'size': 6, 'offset': 0}),

        dbc.Col([
            html.Div([
                html.H4('Settings', style={'marginBottom': '20px'}),
                html.H6('Degree of creativity', style={'marginBottom': '10px'}),
                html.Div([
                    dcc.Slider(
                        id='temperature-slider',
                        min=0,
                        max=100,
                        step=1,
                        value=0,
                        marks={0: 'Accurate', 50: 'Innovative', 100: 'Highly creative'},
                        tooltip={"placement": "bottom", "always_visible": False}
                    ),
                ], style={'width': '100%', 'marginBottom': '15px'}),
                html.H6('Number of sentences to generate', style={'marginBottom': '10px'}),
                html.Div([
                    dcc.Slider(
                        id='tokens-slider',
                        min=5,
                        max=31950 // 100,
                        step=1,
                        value=25,
                        marks={5: '5 sentences max', 31950 // 100: '8 pages max'},
                        tooltip={"placement": "bottom", "always_visible": False}
                    ),
                ], style={'width': '100%', 'marginBottom': '15px'}),

                html.H6('GROQ API KEY', style={'marginBottom': '10px'}),

                dcc.Textarea(
                    id='groq-api-key',
                    value='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',
                    style={'width': '100%',
                           'minHeight': '5px',
                           'overflowY': 'auto',
                           'borderRadius': '10px',
                           'border': f'1px solid {colors["secondary"]}',
                           'marginBottom': '15px',
                           'font-size': '12px',
                           'padding': '5px',
                           'boxShadow': '0 4px 6px rgba(0, 0, 0, 0.1)',
                           'outline': 'none',
                           ':focus': {
                               'borderColor': '#0056b3',
                               'boxShadow': '0 0 0 0.2rem rgba(0, 86, 179, 0.25)'
                           },
                           'verticalAlign': 'middle', },

                ),
                html.H6('LLAMAPARSE API KEY', style={'marginBottom': '10px'}),

                dcc.Textarea(
                    id='llama-parse-id',
                    value='llx-KsMowITWRhVKq1uVChXVvDIxfg8chXIakXEtEKLdKzhqhGvZ',
                    style={'width': '100%',
                           'minHeight': '5px',
                           'overflowY': 'auto',
                           'borderRadius': '10px',
                           'border': f'1px solid {colors["secondary"]}',
                           'marginBottom': '15px',
                           'font-size': '12px',
                           'padding': '5px',
                           'boxShadow': '0 4px 6px rgba(0, 0, 0, 0.1)',
                           'outline': 'none',
                           ':focus': {
                               'borderColor': '#0056b3',
                               'boxShadow': '0 0 0 0.2rem rgba(0, 86, 179, 0.25)'
                           },
                           'verticalAlign': 'middle', },

                ),

                html.H6('BRAVE API KEY', style={'marginBottom': '10px'}),

                dcc.Textarea(
                    id='brave-id',
                    value='BSA6vLQFcC_DmOqaTk4Nm8jLF1sqTxe',
                    style={'width': '100%',
                           'minHeight': '5px',
                           'overflowY': 'auto',
                           'borderRadius': '10px',
                           'border': f'1px solid {colors["secondary"]}',
                           'marginBottom': '15px',
                           'font-size': '12px',
                           'padding': '5px',
                           'boxShadow': '0 4px 6px rgba(0, 0, 0, 0.1)',
                           'outline': 'none',
                           ':focus': {
                               'borderColor': '#0056b3',
                               'boxShadow': '0 0 0 0.2rem rgba(0, 86, 179, 0.25)'
                           },
                           'verticalAlign': 'middle', },

                ),
                html.H6('Select Model', style={'marginBottom': '10px'}),
                dcc.Dropdown(
                    id='model-dropdown',
                    options=[
                        {'label': 'llama3', 'value': 'llama3-70b-8192'},
                        {'label': 'Mixtral 8x7b', 'value': 'mixtral-8x7b-32768'}
                    ],
                    value='mixtral-8x7b-32768',
                    style={'marginBottom': '15px'}
                ),
                dcc.Textarea(
                    id='model-prompt',
                    value=prompt,
                    style={'width': '100%',
                           'minHeight': '35%',
                           'overflowY': 'auto',
                           'borderRadius': '10px',
                           'border': f'1px solid {colors["secondary"]}',
                           'marginBottom': '15px',
                           'font-size': '14px',
                           'padding': '15px',
                           'outline': 'none',
                           ':focus': {
                               'borderColor': '#0056b3',
                               'boxShadow': '0 0 0 0.2rem rgba(0, 86, 179, 0.25)'
                           },
                           'verticalAlign': 'middle', },

                ),
            ], style={
                'backgroundColor': 'white', 'padding': '30px', 'borderRadius': '10px',
                'border': f'1px solid {colors["secondary"]}', 'height': '95vh', 'boxShadow': '0 4px 8px rgba(0,0,0,0.1)'
            })
        ], width={'size': 3, 'offset': 0}),
    ], style={'marginBottom': '20px'})  # Added margin between rows for better spacing
], fluid=True, style={'backgroundColor': colors['background'], 'padding': '20px', 'height': '95vh'})


@app.callback(
    Output('tokens-slider', 'max'),
    Output('tokens-slider', 'marks'),
    Input('model-dropdown', 'value')
)
def update_max_tokens(model_name):
    model_tokens = {
        'mixtral-8x7b-32768': 31950,
        'llama3-70b-8192': 8192
    }
    max_tokens = model_tokens.get(model_name, 31950)
    marks = {5: '5 sentences max', max_tokens // 100: f'{round(max_tokens * 0.00025, 0)} pages max'}
    return max_tokens // 100, marks


@app.callback(
    [Output('file-preview', 'children'),
     Output('stored-filenames', 'data')],
    [Input('upload-data', 'contents'),
     Input({'type': 'delete-file', 'index': ALL}, 'n_clicks'),
     Input('send-button', 'n_clicks')],
    [State('upload-data', 'filename'),
     State('stored-filenames', 'data'),
     State('session-id', 'data')]
)
def update_file_preview(contents, delete_clicks, send, filenames, stored_filenames, session_id):
    ctx = dash.callback_context

    if not ctx.triggered:
        return dash.no_update, stored_filenames
    trigger_id = ctx.triggered[0]['prop_id']

    if 'upload-data' in trigger_id:
        if contents is None:
            return [], []
        session_id = session_id_global
        session_dir = os.path.join(CHAT_DIR, session_id)
        if not os.path.exists(session_dir):
            os.makedirs(session_dir)
        # Assuming contents are base64 encoded files
        for content, filename in zip(contents, filenames):
            data = content.split(',')[1]
            file_path = os.path.join(session_dir, filename)
            with open(file_path, "wb") as fh:
                fh.write(base64.b64decode(data))
        # Update stored filenames with newly uploaded files
        stored_filenames = [os.path.join(session_id, fname) for fname in filenames]
        return generate_file_preview(filenames), stored_filenames

    # Handling file delete
    elif 'delete-file' in trigger_id:
        button_id = json.loads(trigger_id.split('.')[0])
        index = button_id['index']
        file_to_remove = stored_filenames[index]
        os.remove(os.path.join(CHAT_DIR, file_to_remove))
        stored_filenames.pop(index)
        return generate_file_preview(stored_filenames), stored_filenames

    # Send files to be process, delete div
    elif 'send-button' in trigger_id:
        return html.Div([], className='d-flex align-items-center', style={'overflowX': 'auto', 'whiteSpace': 'nowrap',
                                                                          'marginTop': '0px',
                                                                          'marginBottom': '0px'}), stored_filenames

@app.callback(
    Output('file-display-area', 'children'),
    [Input({'type': 'chat-session', 'index': ALL}, 'n_clicks')],
    [State({'type': 'chat-session', 'index': ALL}, 'id')]
)
def display_session_files(n_clicks, ids):
    ctx = dash.callback_context

    if not ctx.triggered:
        return dash.no_update  # No update if there's no click

    button_id = ctx.triggered[0]['prop_id']
    session_id = json.loads(button_id.split('.')[0])['index']
    session_dir = os.path.join(CHAT_DIR, session_id)
    try:
        file_names = [file for file in os.listdir(session_dir) if not file.endswith('.json')]
    except FileNotFoundError:
        return html.Div("")

    children = [
        html.Div([
            html.I(className=f"fas {file_icon_and_color(filename.split('.')[-1])[0]}",
                   style={'marginRight': '10px', 'color': file_icon_and_color(filename.split('.')[-1])[1]}),
            html.Span(f"{filename[:6]}...{filename.split('.')[-1]}" if len(filename) > 10 else filename,
                      title=f"{filename}",
                      style={'overflow': 'hidden', 'textOverflow': 'ellipsis', 'whiteSpace': 'nowrap'}),
        ], className='d-flex align-items-center', style={'marginRight': '20px'})
        for i, filename in enumerate(file_names)
    ]

    # Return a single horizontal row container
    return html.Div(children, className='d-flex align-items-center', style={'whiteSpace': 'nowrap',
                                                                            'marginTop': '0px', 'marginBottom': '0px'})

def generate_file_preview(filenames):
    # Utility function to generate HTML for file previews
    children = [
        html.Div([
            html.I(className=f"fas {file_icon_and_color(filename.split('.')[-1])[0]}",
                   style={'marginRight': '10px', 'color': file_icon_and_color(filename.split('.')[-1])[1]}),
            html.Span(f"{filename[:6]}...{filename.split('.')[-1]}" if len(filename) > 10 else filename,
                      title=f"{filename}",
                      style={'overflow': 'hidden', 'textOverflow': 'ellipsis', 'whiteSpace': 'nowrap'}),
            html.Button('×', id={'type': 'delete-file', 'index': i}, className='close', **{'aria-label': 'Close file'},
                        style={'fontSize': '16px', 'marginLeft': '10px', 'cursor': 'pointer',
                               'verticalAlign': 'middle'})
        ], className='d-flex align-items-center', style={'marginRight': '20px'})
        for i, filename in enumerate(filenames)
    ]

    # Return a single horizontal row container
    return html.Div(children, className='d-flex align-items-center', style={'overflowX': 'auto', 'whiteSpace': 'nowrap',
                                                                            'marginTop': '0px', 'marginBottom': '0px'})


@app.callback(
    Output('user-input', 'value'),
    Input('user-input', 'value')
)
def display_command_options(input_value):
    if not input_value:
        raise PreventUpdate

    if input_value.startswith('/'):
        # Assuming the user just typed "/", show the options
        if input_value == "/":
            return "/data or /web"
    return dash.no_update


# New Chat
@app.callback(
    Output('session-id', 'data'),
    Input('new-chat-button', 'n_clicks'),
    prevent_initial_call=True
)
def new_chat_session(n_clicks):
    global new_chat
    if n_clicks > 0 and new_chat is not None:
        new_session_id = str(uuid.uuid4())
        save_chat(new_session_id, {'messages': [{'role': 'system', 'content': 'Welcome! How can I assist you today?'}]})
        new_chat = None
        return new_session_id


# Update the chat list with all discussions
@app.callback(
    Output('list-chats', 'children'),
    [Input('session-id', 'data'),
     Input({'type': 'delete-button', 'index': ALL}, 'n_clicks')],
    [State({'type': 'chat-session', 'index': ALL}, 'id'),
     State('list-chats', 'children')]
)
def update_chat_list(session_id, delete_clicks, ids, children):
    global session_id_global, new_chat
    ctx = dash.callback_context
    trigger_id = ctx.triggered[0]['prop_id']

    # Handle deletion
    if 'delete-button' in trigger_id:
        button_index = json.loads(trigger_id.split('.')[0])['index']
        new_children = [child for i, child in enumerate(children) if i != button_index]
        return new_children

    if session_id_global is not None and new_chat is None:
        sessions = load_all_sessions()
        return [create_session_div(session) for session in sessions]

    if session_id_global:
        if children is None or session_id_global not in [child['props']['id']['index'] for child in
                                                         children] and new_chat is not None:
            new_child = create_session_div(session_id_global)
            new_chat = None
            return children + [new_child] if children else [new_child]
    else:
        # Load all sessions if there is no active session
        sessions = load_all_sessions()
        session_children = [create_session_div(session_id) for session_id in sessions]
        return session_children
    return children


@app.callback(
    Output({'type': 'chat-session', 'index': MATCH}, 'children'),
    [Input({'type': 'edit-button', 'index': MATCH}, 'n_clicks'),
     Input({'type': 'save-button', 'index': MATCH}, 'n_clicks'),
     Input({'type': 'delete-button', 'index': MATCH}, 'n_clicks')],
    [State({'type': 'chat-session', 'index': MATCH}, 'id'),
     State({'type': 'edit-input', 'index': MATCH}, 'value')],
    prevent_initial_call=True
)
def edit_save_delete_session(edit_clicks, save_clicks, delete_clicks, session_id, new_name):
    ctx = dash.callback_context
    if not ctx.triggered:
        return dash.no_update
    button_id = ctx.triggered[0]['prop_id'].split('.')[0]
    session_index = session_id['index']

    if 'edit-button' in button_id:
        return [
            dcc.Input(id={'type': 'edit-input', 'index': session_index}, value=session_index, style={'width': '75%'}),
            html.Button('Save', id={'type': 'save-button', 'index': session_index}, n_clicks=0),
            html.Button('Delete', id={'type': 'delete-button', 'index': session_index}, n_clicks=0),
            html.Button('Edit', id={'type': 'edit-button', 'index': session_index}, n_clicks=0,
                        style={'display': 'none'}),
        ]
    elif 'save-button' in button_id:
        save_chat(session_index, new_name, new_name=new_name)
        return create_session_div(new_name)
    elif 'delete-button' in button_id:
        delete_chat(session_index)


@app.callback(
    Output('chat-history', 'children'),
    [Input('send-button', 'n_clicks'),
     Input('new-chat-button', 'n_clicks'),
     Input('upload-data', 'contents'),
     Input({'type': 'chat-session', 'index': ALL}, 'n_clicks'),
     Input('temperature-slider', 'value'),
     Input('tokens-slider', 'value'),
     Input('groq-api-key', 'value'),
     Input('llama-parse-id', 'value'),
     Input('brave-id', 'value'),
     Input('model-dropdown', 'value'),
     Input('model-prompt', 'value'),
     ],
    [State('user-input', 'value'),
     State('session-id', 'data'),
     State('upload-data', 'filename')]
)
def update_chat(send_clicks, new_chat_clicks, upload_contents, session_clicks, temp, max_tokens, groq_api_key,
                llama_parse_id, brave_id, model_dropdown, model_prompt, user_input, session_id, filename):
    global session_id_global, new_chat
    session_id = session_id_global
    ctx = callback_context
    if not ctx.triggered:
        raise PreventUpdate
    button_id = ctx.triggered[0]['prop_id']
    ai_answer = ''
    temp = temp / 100
    max_tokens = max_tokens * 100
    file_children = []

    if 'send-button' in button_id:
        if not user_input:
            raise PreventUpdate

        if not session_id:
            new_session_id = str(uuid.uuid4())
            save_chat(new_session_id,
                      {'messages': [{'role': 'system', 'content': 'Welcome! How can I assist you today?'}]})
            session_id = new_session_id
            new_chat = 1

        chat_data = load_chat(session_id)

        if user_input.startswith('/web'):
            print("web crawling")
            user_input = user_input.replace("/web", "")
            '''ai_answer = scrape_and_find(user_input, groq_api_key, brave_id, model_dropdown, temp, max_tokens)'''
            ai_answer = '''ai_answer['result']'''

        elif user_input.startswith('/data'):
            print("data handling")
            user_input = user_input.replace("/data", "")
            directory_path = f'./chat_sessions/{session_id}'
            file_paths = [os.path.join(directory_path, file_name) for file_name in os.listdir(directory_path) if
                          not file_name.endswith('.json')]

            ai_answer = '''\
                json.loads(asyncio.run(main(file_paths, user_input, model_dropdown, llama_parse_id, temp, max_tokens)))[
                    'result']'''

        elif filename:
            print("data handling")
            directory_path = f'./chat_sessions/{session_id}'
            file_paths = [os.path.join(directory_path, file_name) for file_name in filename]
            ai_answer = '''\
                json.loads(asyncio.run(main(file_paths, user_input, model_dropdown, llama_parse_id, temp, max_tokens)))[
                    'result']'''
            filenames = filename
            file_children = [
                html.Div([
                    html.I(className=f"fas {file_icon_and_color(filename.split('.')[-1])[0]}",
                           style={'marginRight': '10px', 'color': file_icon_and_color(filename.split('.')[-1])[1]}),
                    html.Span(f"{filename[:6]}...{filename.split('.')[-1]}" if len(filename) > 10 else filename,
                              title=f"{filename}",
                              style={'overflow': 'hidden', 'textOverflow': 'ellipsis', 'whiteSpace': 'nowrap'}),
                ], className='d-flex align-items-center', style={'marginRight': '20px'})
                for i, filename in enumerate(filenames)
            ]
            file_children = html.Div(file_children, className='d-flex align-items-center',
                                     style={'overflowX': 'auto', 'whiteSpace': 'nowrap',
                                            'marginTop': '0px', 'marginBottom': '0px'})

        # Append user message to chat data
        chat_data['messages'].append({'role': 'user', 'content': user_input})
        # Append AI message to chat data
        chat_data['messages'].append({'role': 'system', 'content': ai_answer})
        # Save updated chat data
        save_chat(session_id, chat_data)

    elif 'chat-session' in button_id:
        session_id = json.loads(ctx.triggered[0]['prop_id'].split('.')[0])['index']
    elif 'new-chat-button' in button_id:
        new_session_id = str(uuid.uuid4())
        save_chat(new_session_id, {'messages': [{'role': 'system', 'content': 'Welcome! How can I assist you today?'}]})
        session_id = new_session_id
        new_chat = 1

    # Fetch messages for the current or selected session
    chat_data = load_chat(session_id)
    chat_history_elements = []
    if 'messages' not in chat_data:
        return []
    for idx, msg in enumerate(chat_data['messages']):
        if msg['role'] == 'user':
            profile_pic = user_profile_pic
            style = {'textAlign': 'left',
                     'padding': '10px',
                     'borderRadius': '10px', 'marginBottom': '10px', 'maxWidth': '70%'}
        else:
            profile_pic = ai_profile_pic
            style = {'textAlign': 'left', 'backgroundColor': '#f9f7f3', 'padding': '10px',
                     'borderRadius': '10px', 'marginBottom': '10px', 'color': colors['text'], 'maxWidth': '70%'}
        chat_bubble = html.Div([
            html.Img(src=profile_pic, style={'width': '30px', 'height': '30px', 'borderRadius': '50%'}),
            html.Span(msg['content'], style={'marginLeft': '10px'})
        ], style=style)
        chat_history_elements.append(chat_bubble)

    if filename:
        index_to_insert = len(chat_history_elements) - 1
        chat_history_elements.insert(index_to_insert, html.Div(file_children))

    session_id_global = session_id
    return chat_history_elements


# Run the app
if __name__ == '__main__':
    app.run_server(debug=True)
