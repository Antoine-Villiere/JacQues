from IMPORT import *
from Scrape_and_find import scrape_and_find
from Parse_and_find import main

session_id_global = None
new_chat = None

CHAT_DIR = 'chat_sessions'
if not os.path.exists(CHAT_DIR):
    os.mkdir(CHAT_DIR)

# Path to the file
file_path = r'.\assets\prompt'

# Function to read file content
with open(file_path, 'r', encoding='utf-8') as file:
    prompt = file.read()

# Initialize Dash app with Bootstrap theme
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP], suppress_callback_exceptions=True)

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
    'pdf': 'fa-file-pdf',
    'docx': 'fa-file-word',
    'xlsx': 'fa-file-excel',
    'pptx': 'fa-file-powerpoint',
    'txt': 'fa-file-alt',
    'jpg': 'fa-file-image',
    'png': 'fa-file-image',
    'zip': 'fa-file-archive',
    'other': 'fa-file'
}

def save_chat(session_id, data, new_name=None):
    """ Save chat data to a JSON file. Optionally rename the session. """
    old_path = os.path.join(CHAT_DIR, f"{session_id}.json")
    new_session_id = new_name if new_name else session_id
    new_path = os.path.join(CHAT_DIR, f"{new_session_id}.json")

    if new_name and os.path.exists(old_path):
        os.rename(old_path, new_path)

    else:
        with open(new_path, 'w') as f:
            json.dump(data, f)


def delete_chat(session_id):
    """ Delete chat data file for a specific session. """
    filepath = os.path.join(CHAT_DIR, f"{session_id}.json")
    if os.path.exists(filepath):
        os.remove(filepath)
        return True
    else:
        print("The file does not exist.")
        return False


def load_chat(session_id):
    """ Load chat data from a JSON file. """
    try:
        with open(os.path.join(CHAT_DIR, f"{session_id}.json"), 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def load_all_sessions():
    sessions = []
    for filename in os.listdir(CHAT_DIR):
        if filename.endswith('.json'):
            session_id = os.path.splitext(filename)[0]
            sessions.append(session_id)
    return sessions


ai_profile_pic = "assets/Ai.png"
user_profile_pic = "assets/User.png"

# Define the layout of the app
app.layout = dbc.Container([
    dbc.Row([
        dbc.Col([
            html.Button('New Chat', id='new-chat-button', n_clicks=0, style=btn_style),
            html.Div(id='list-chats',
                     style={'marginTop': '10px', 'marginBottom': '10px', 'height': '90%', 'overflowY': 'scroll'}),

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
                          'border': f'1px solid {colors["secondary"]}', 'marginBottom': '30px'}),
                html.Div([],id='file-preview', style={'marginTop': '5px', 'marginBottom': '5px'}),

                dcc.Upload(html.Button('Upload Document', style=btn_style), id='upload-data', multiple=True,
                           style={'marginTop': '5px'}),
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
                        max=320,
                        step=1,
                        value=25,
                        marks={5: '5 sentences max', 320: '8 pages max'},
                        tooltip={"placement": "bottom", "always_visible": False}
                    ),
                ], style={'width': '100%', 'marginBottom': '15px'}),

                html.H6('GROQ API KEY', style={'marginBottom': '10px'}),

                dcc.Textarea(
                    id='groq-api-key',
                    value='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',
                    style={'width': '100%', 'height': '7%', 'overflowY': 'auto', 'padding': '10px',
                           'borderRadius': '10px', 'border': f'1px solid {colors["secondary"]}',
                           'marginBottom': '15px'},

                ),
                html.H6('LLAMAPARSE API KEY', style={'marginBottom': '10px'}),

                dcc.Textarea(
                    id='llama-parse-id',
                    value='llx-KsMowITWRhVKq1uVChXVvDIxfg8chXIakXEtEKLdKzhqhGvZ',
                    style={'width': '100%', 'height': '7%', 'overflowY': 'auto', 'padding': '10px',
                           'borderRadius': '10px', 'border': f'1px solid {colors["secondary"]}',
                           'marginBottom': '15px'},

                ),

                html.H6('BRAVE API KEY', style={'marginBottom': '10px'}),

                dcc.Textarea(
                    id='brave-id',
                    value='BSA6vLQFcC_DmOqaTk4Nm8jLF1sqTxe',
                    style={'width': '100%', 'height': '4%', 'overflowY': 'auto', 'padding': '10px',
                           'borderRadius': '10px', 'border': f'1px solid {colors["secondary"]}',
                           'marginBottom': '15px'},

                ),
                html.H6('Select Model', style={'marginBottom': '10px'}),
                dcc.Dropdown(
                    id='model-dropdown',
                    options=[
                        {'label': 'Llama3', 'value': 'Llama3'},
                        {'label': 'Mixtral 8x22b', 'value': 'Mixtral8x22b'}
                    ],
                    value='Llama3',
                    style={'marginBottom': '15px'}
                ),
                dcc.Textarea(
                    id='model-prompt',
                    value=prompt,
                    style={'marginBottom': '10px', 'width': '100%', 'height': '25%', 'overflowY': 'auto',
                           'borderRadius': '10px', 'border': f'1px solid {colors["secondary"]}'},

                ),
            ], style={
                'backgroundColor': 'white', 'padding': '30px', 'borderRadius': '10px',
                'border': f'1px solid {colors["secondary"]}', 'height': '95vh', 'boxShadow': '0 4px 8px rgba(0,0,0,0.1)'
            })
        ], width={'size': 3, 'offset': 0}),
    ], style={'marginBottom': '20px'})  # Added margin between rows for better spacing
], fluid=True, style={'backgroundColor': colors['background'], 'padding': '20px', 'height': '95vh'})


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


@app.callback(
    Output('file-preview', 'children'),
    Input('upload-data', 'contents'),
    State('upload-data', 'filename'),
    prevent_initial_call=True
)
def update_file_preview(contents, filenames):
    if contents is None:
        raise PreventUpdate

    def file_icon(ext):
        return ICON_MAP.get(ext, ICON_MAP['other'])

    children = [
        html.Div([
            html.I(className=f"fas {file_icon(filename.split('.')[-1])}", style={'fontSize': '24px'}),
            html.P(filename, style={'display': 'inline-block', 'marginLeft': '10px'}),
            html.Button('×', id={'type': 'delete-file', 'index': i}, className='close', **{'aria-label': 'Close'},
                        style={'fontSize': '16px', 'marginLeft': '10px'})
        ], className='d-flex align-items-center', style={'marginBottom': '5px', 'marginTop': '5px'})
        for i, filename in enumerate(filenames)
    ]
    return children

@app.callback(
    Output('upload-data', 'filename'),
    [Input({'type': 'delete-file', 'index': ALL}, 'n_clicks')],
    [State('upload-data', 'filename')]
)
def remove_file(delete_clicks, filenames):
    ctx = dash.callback_context
    if not ctx.triggered:
        return filenames
    button_id = ctx.triggered[0]['prop_id']
    index = json.loads(button_id)['index']
    if delete_clicks[index] is not None:
        filenames.pop(index)
    return filenames


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
    Input('session-id', 'data'),
    State('list-chats', 'children')
)
def update_chat_list(session_id, children):
    global session_id_global, new_chat
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
    print(ctx.triggered)
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

    if 'send-button' in button_id:
        if not user_input:
            raise PreventUpdate
        # If there's no active session, create a new one

        if not session_id:
            new_session_id = str(uuid.uuid4())
            save_chat(new_session_id,
                      {'messages': [{'role': 'system', 'content': 'Welcome! How can I assist you today?'}]})
            session_id = new_session_id
            new_chat = 1

        # Load chat data for the active session

        chat_data = load_chat(session_id)

        if user_input.startswith('/web'):
            print("web crawling")
            user_input = user_input.replace("/web", "")
            ai_answer = scrape_and_find(user_input, groq_api_key, brave_id, model_dropdown, temp, max_tokens)
            ai_answer = ai_answer['result']

        elif user_input.startswith('/data'):
            print("data handling")
            user_input = user_input.replace("/data", "")
            file_paths = ["./test_docs/test.pdf", "./test_docs/Hi Maria.docx"]
            ai_answer = \
            json.loads(asyncio.run(main(file_paths, user_input, model_dropdown, llama_parse_id, temp, max_tokens)))[
                'result']

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

    elif 'upload-data' in button_id:
        print(name_file, filename)
    # Fetch messages for the current or selected session
    chat_data = load_chat(session_id)
    chat_history_elements = []
    if 'messages' not in chat_data:
        return []  # Return empty list if no messages are available
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

    session_id_global = session_id
    return chat_history_elements


# Run the app
if __name__ == '__main__':
    app.run_server(debug=True)
