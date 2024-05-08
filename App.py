from functions.IMPORT import *
from functions.Scrape_and_find import scrape_and_find
from functions.Parse_and_find import parse_and_find
from functions.Autonomous_with_tools import get_auto_assitant
from functions.chat_management import *
from functions.config import *
from functions.settings import *

session_id_global = None
new_chat = None

if not os.path.exists(CHAT_DIR):
    os.mkdir(CHAT_DIR)

# Path to the file
file_path = 'assets/prompt'
ai_profile_pic = "assets/Ai.png"
user_profile_pic = "assets/User.png"

# Function to read file content
with open(file_path, 'r', encoding='utf-8') as file:
    prompt = file.read()

# Initialize Dash app with Bootstrap theme
app_settings = load_settings()
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP,
                                                "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.15.1/css/all.min.css"],
                suppress_callback_exceptions=True)

# Define the layout of the app
app.layout = dbc.Container([
    dbc.Row([
        dbc.Col([
            html.Button('New Chat', id='new-chat-button', n_clicks=0, style=btn_style),
            html.Div(id='list-chats',
                     style={'marginTop': '10px', 'marginBottom': '10px', 'height': '90%', 'overflowY': 'scroll'},
                     className='hide-scrollbar'),
            html.Div(id='file-display-area', style={'marginTop': '10px', 'overflowY': 'auto', 'maxHeight': '50px'}),
            html.Button("Hidde settings", id='toggle-button', n_clicks=0, style={
                'width': '30%',
                'right': '10px',
                'backgroundColor': colors['primary'],
                'color': 'white',
                'borderRadius': '5px',
                'border': 'none',
                'marginBottom': '10px'
            }),
            html.Div(id='toggle-state', children='show', style={'display': 'none'}),

        ], width={'size': 3, 'offset': 0}, style={'backgroundColor': 'white', 'padding': '20px', 'borderRadius': '10px',
                                                  'border': f'1px solid {colors["secondary"]}', 'height': '95vh'}),

        dbc.Col(id='chat-column', children=[
            html.Div([
                html.Div(id='chat-history', style={'marginBottom': '10px', 'height': '82%', 'overflowY': 'scroll'},
                         className='hide-scrollbar'),
                html.Div([
                    dcc.Textarea(id='user-input', placeholder='Message Jacques... Or type "/" for commands...',
                                 spellCheck=True,
                                 style={'marginBottom': '0px', 'width': '95%', 'overflowY': 'scroll',
                                        'borderRadius': '5px', 'color': '#6c757d',
                                        'background-color': 'transparent', 'border': 'none'},
                                 className='hide-scrollbar'),
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

        dbc.Col(id='settings-column', children=[
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

                html.H6('Groq api key', style={'marginBottom': '10px'}),

                dcc.Input(id='groq-api-key', value=app_settings['groq_api_key'],
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
                                 'verticalAlign': 'middle', }),
                html.H6('LlamaParse api key', style={'marginBottom': '10px'}),

                dcc.Input(id='llama-parse-id', value=app_settings['llama_parse_key'],
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
                                 'verticalAlign': 'middle', }),

                html.H6('Brave api key', style={'marginBottom': '10px'}),

                dcc.Input(id='brave-id', value=app_settings['brave_api_key'],
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
                                 'verticalAlign': 'middle', }),
                html.H6('Select Model', style={'marginBottom': '10px'}),
                dcc.Dropdown(
                    id='model-dropdown',
                    options=[
                        {'label': 'llama3', 'value': 'llama3-70b-8192'},
                        {'label': 'Mixtral 8x7b', 'value': 'mixtral-8x7b-32768'}
                    ],
                    value='llama3-70b-8192',
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
                           'verticalAlign': 'middle', 'display': 'none'}, className='hide-scrollbar'

                ),

            ])], style={
            'backgroundColor': 'white', 'padding': '30px', 'borderRadius': '10px',
            'border': f'1px solid {colors["secondary"]}', 'height': '95vh', 'boxShadow': '0 4px 8px rgba(0,0,0,0.1)'
        }, width={'size': 3, 'offset': 0}),
    ], style={'marginBottom': '20px'})  # Added margin between rows for better spacing
], fluid=True, style={'backgroundColor': colors['background'], 'padding': '20px', 'height': '95vh'})


@app.callback(
    [Output('settings-column', 'style'),
     Output('chat-column', 'width'),
     Output('toggle-button', 'children')],
    Input('toggle-button', 'n_clicks'),
    Input('toggle-state', 'children')
)
def toggle_visibility(n_clicks, toggle_state):
    # Switch the visibility state
    if n_clicks % 2 == 0:
        return {
            'backgroundColor': 'white', 'padding': '30px', 'borderRadius': '10px',
            'border': f'1px solid {colors["secondary"]}', 'height': '95vh', 'boxShadow': '0 4px 8px rgba(0,0,0,0.1)'
        }, {'size': 6, 'offset': 0}, "Hidde settings"
    else:
        return {'display': 'none'}, {'size': 9, 'offset': 0}, "Show settings"


@app.callback(
    Output('groq-api-key', 'value'),
    Input('groq-api-key', 'value')
)
def update_groq_key(new_key):
    update_setting('groq_api_key', new_key)
    return new_key


@app.callback(
    Output('llama-parse-id', 'value'),
    Input('llama-parse-id', 'value')
)
def update_llama_key(new_key):
    update_setting('llama_parse_key', new_key)
    return new_key


@app.callback(
    Output('brave-id', 'value'),
    Input('brave-id', 'value')
)
def update_brave_key(new_key):
    update_setting('brave_api_key', new_key)
    return new_key


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
        file_names = [file for file in os.listdir(session_dir)
                      if not file.endswith('.json') and os.path.isfile(os.path.join(session_dir, file))]

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
    global new_chat, session_id_global
    if n_clicks > 0 and new_chat is not None or session_id_global is None:
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
            ai_answer = scrape_and_find(user_input, groq_api_key, brave_id, model_dropdown, temp, max_tokens, session_id)
            ai_answer = ai_answer['result']

        elif user_input.startswith('/data'):
            print("data handling")
            user_input = user_input.replace("/data", "")
            directory_path = f'./chat_sessions/{session_id}'
            file_paths = [os.path.join(directory_path, file_name) for file_name in os.listdir(directory_path) if
                          not file_name.endswith('.json')]

            ai_answer = \
                json.loads(asyncio.run(
                    parse_and_find(file_paths, user_input, model_dropdown, llama_parse_id, temp, max_tokens, session_id, groq_api_key)))[
                    'result']

        elif filename:
            print("data handling")
            directory_path = f'./chat_sessions/{session_id}'
            file_paths = [os.path.join(directory_path, file_name) for file_name in filename]
            ai_answer = \
                json.loads(asyncio.run(
                    parse_and_find(file_paths, user_input, model_dropdown, llama_parse_id, temp, max_tokens, session_id, groq_api_key)))[
                    'result']
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

        else:
            directory_path = f'./chat_sessions/{session_id}'
            try:
                file_paths = [os.path.join(directory_path, file_name) for file_name in filename]
            except:
                file_paths = []
            ai_answer = get_auto_assitant(user_input, groq_api_key, brave_id, model_dropdown, temp, max_tokens,
                                          file_paths, llama_parse_id, session_id)
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
    if not session_id:
        new_session_id = str(uuid.uuid4())
        save_chat(new_session_id,
                  {'messages': [{'role': 'system', 'content': 'Welcome! How can I assist you today?'}]})
        session_id = new_session_id
        new_chat = 1
    chat_data = load_chat(session_id)
    chat_history_elements = []
    if 'messages' not in chat_data:
        return []
    for idx, msg in enumerate(chat_data['messages']):
        if msg['role'] == 'user':
            profile_pic = user_profile_pic
            style = {'textAlign': 'left',
                     'padding': '10px',
                     'borderRadius': '10px', 'marginBottom': '10px', 'maxWidth': '100%'}
        else:
            profile_pic = ai_profile_pic
            style = {'textAlign': 'left', 'backgroundColor': '#f9f7f3', 'padding': '10px',
                     'borderRadius': '10px', 'marginBottom': '10px', 'color': colors['text'], 'maxWidth': '100%'}
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
    app.run_server(debug=False)
