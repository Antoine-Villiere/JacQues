from functions.IMPORT import *
from functions.Scrape_and_find import scrape_and_find
from functions.Parse_and_find import parse_and_find
from functions.Autonomous_with_tools import get_auto_assistant
from functions.chat_management import *
from functions.config import *
from functions.settings import *
from functions.Personalities import load_personalities, save_personalities
from functions.Parse_and_remember import parse_and_remember
from functions.chat_management import save_info

session_id_global = None
new_chat = None
open_ = False
global_check = True
global_info = ""
save_info("N/A")

if not os.path.exists(CHAT_DIR):
    os.mkdir(CHAT_DIR)
os.environ["TOKENIZERS_PARALLELISM"] = "true"
supported_extensions = [
    '.pdf', '.doc', '.docx', '.docm', '.dot', '.dotx', '.dotm', '.rtf',
    '.wps', '.wpd', '.sxw', '.stw', '.sxg', '.pages', '.mw', '.mcw',
    '.uot', '.uof', '.uos', '.uop', '.ppt', '.pptx', '.pot', '.pptm',
    '.potx', '.potm', '.key', '.odp', '.odg', '.otp', '.fopd', '.sxi',
    '.sti', '.epub', '.html', '.htm'
]

# Path to the file
ai_profile_pic = "assets/Ai.png"
user_profile_pic = "assets/User.png"


def read_info():
    with open('assets/info.json', 'r') as f:
        info = json.load(f)['info']

    return info


app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP,
                                                "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.15.1/css/all.min.css"],
                suppress_callback_exceptions=True)

app.layout = dbc.Container([
    dbc.Row([
        dbc.Col([
            html.Button('New Chat', id='new-chat-button', n_clicks=0, style=btn_style),
            html.Div(id='list-chats',
                     style={'marginTop': '10px', 'marginBottom': '10px', 'height': '80vh', 'overflowY': 'scroll'},
                     className='hide-scrollbar'),
            html.Div(id='file-display-area', style={'marginTop': '10px', 'overflowY': 'auto', 'Maxheight': '50px'}),
            dbc.Row([
                html.Button(["Hide settings", html.I(className='fa fa-eye-slash')], id='toggle-button', n_clicks=0,
                            style={
                                'width': '40%',
                                'right': '10px',
                                'backgroundColor': colors['primary'],
                                'color': 'white',
                                'borderRadius': '5px',
                                'border': 'none',
                                'marginBottom': '10px',
                                'marginRight': '80px'
                            }),
                html.Button(["Remind me ", html.I(className='fa fa-clock')], id='toggle-button-reminder', n_clicks=0,
                            style={
                                'width': '40%',
                                'right': '10px',
                                'backgroundColor': "#ca6702",
                                'color': 'white',
                                'borderRadius': '5px',
                                'border': 'none',
                                'marginBottom': '10px'
                            }),
                dbc.Modal(
                    [
                        dbc.ModalHeader(close_button=True),
                        dbc.ModalBody(
                            [
                                dls.Hash(html.Div(
                                    id='chat-history-reminder',
                                    style={
                                        'marginBottom': '10px',
                                        'height': '86%',
                                        'overflowY': 'scroll'
                                    },
                                    className='hide-scrollbar'
                                ), color="#435278",
                                    speed_multiplier=2,
                                    size=100,
                                )

                            ]
                        ),
                        dbc.ModalFooter(
                            html.Div([
                                dcc.Textarea(id='reminder-user-input',
                                             placeholder='Ask Jacques what you would like to remind...',
                                             spellCheck=True,
                                             style={'marginBottom': '0px', 'width': '95%', 'overflowY': 'scroll',
                                                    'borderRadius': '5px', 'color': '#6c757d',
                                                    'background-color': 'transparent', 'border': 'none'},
                                             className='hide-scrollbar'),
                                html.Button('\u21E7', id='reminder-send-button', n_clicks=0, style={
                                    'width': '5%',
                                    'backgroundColor': colors['primary'],
                                    'color': 'white',
                                    'borderRadius': '5px',
                                    'border': 'none',
                                    'padding': '15px',
                                }),
                            ], style={'display': 'flex', 'alignItems': 'center', 'backgroundColor': 'white',
                                      'borderRadius': '10px', 'width': '100%',
                                      'border': f'1px solid {colors["secondary"]}', 'marginBottom': '20px'})
                        ),
                    ],
                    id="modal",
                    size="xl",
                    is_open=False,
                    backdrop='static',
                    keyboard=False,
                    centered=True,
                    scrollable=True
                )
                ,
            ]),
            html.Div(id='toggle-state', children='show', style={'display': 'none'}),

        ], width={'size': 3, 'offset': 0}, style={'backgroundColor': 'white', 'padding': '20px', 'borderRadius': '10px',
                                                  'border': f'1px solid {colors["secondary"]}', 'height': '95vh'}),

        dbc.Col(id='chat-column', children=[
            html.Div([
                dbc.Modal(
                    [
                        dbc.ModalHeader(id="modal-header"),
                        dbc.ModalBody(id="modal-body"),
                    ],
                    id="modal-sm",
                    size="sm",
                    is_open=False,
                    backdrop='static',
                    keyboard=False,
                    centered=True,
                ),
                dcc.Interval(
                    id='interval-component',
                    interval=1 * 1000,
                    n_intervals=0
                ),
                html.Div(id='chat-history', style={'marginBottom': '10px', 'height': '86%', 'overflowY': 'scroll'},
                         className='hide-scrollbar'),
                html.Div([
                    dcc.Textarea(id='user-input', placeholder='Message Jacques... Or type "/" for commands...',
                                 spellCheck=True,
                                 style={'marginBottom': '0px', 'width': '95%', 'overflowY': 'scroll',
                                        'borderRadius': '5px', 'color': '#6c757d',
                                        'background-color': 'transparent', 'border': 'none'},
                                 className='hide-scrollbar',
                                 persistence=False),
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

                dcc.Input(id='groq_api_key', value=load_settings()['groq_api_key'],
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

                dcc.Input(id='llama_parse_key', value=load_settings()['llama_parse_key'],
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

                dbc.Row([
                    dcc.Input(id='brave_api_key', value=load_settings()['brave_api_key'],
                              style={'width': '50%',
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
                    html.Div([dcc.Slider(0, 1,
                                         id='internet-slider',
                                         step=None,
                                         marks={
                                             0: 'OFF',
                                             1: 'ON',
                                         },
                                         value=1)],
                             style={'width': '50%'}
                             )
                ]),
                html.Button('Save', id='save-button-api', n_clicks=0, style={
                    'width': '40%',
                    'right': '10px',
                    'backgroundColor': colors['primary'],
                    'color': 'white',
                    'borderRadius': '5px',
                    'border': 'none',
                    'marginBottom': '10px',
                }),

                html.H6('Select Model', style={'marginBottom': '10px'}),
                dcc.Dropdown(
                    id='model-dropdown',
                    options=[
                        {'label': 'llama3.1 405B', 'value': 'llama3-groq-70b-8192-tool-use-preview'},
                        {'label': 'Mixtral 8x7b', 'value': 'mixtral-8x7b-32768'},
                        {'label': 'llama3 8B', 'value': 'llama3-8b-8192'},
                        {'label': 'gemma 7B', 'value': 'gemma-7b-it'},
                    ],
                    value='llama3-70b-8192',
                    style={'marginBottom': '15px'}
                ),

                html.H6('Select Personality', style={'marginBottom': '10px'}),
                html.Div([
                    dcc.Dropdown(id='personality-dropdown', options=[], placeholder="Select a personality", value=None),
                    dcc.Input(id='title-input', type='text', placeholder='Enter title', style={'display': 'none'}),
                    dcc.Textarea(
                        id='description-input',
                        placeholder='Enter description',
                        style={'display': 'none'}),
                    html.Button("Update Personality", id='update-personality-btn', n_clicks=0,
                                style={'display': 'none'}),
                    html.Button("Delete Personality", id='delete-personality-btn', n_clicks=0,
                                style={'display': 'none'}),
                ])

            ])], style={
            'backgroundColor': 'white', 'padding': '30px', 'borderRadius': '10px',
            'border': f'1px solid {colors["secondary"]}', 'height': '95vh'}, width={'size': 3, 'offset': 0}),
    ], style={'marginBottom': '20px'})
], fluid=True, style={'backgroundColor': colors['background'], 'padding': '20px', 'height': '95vh'})


@app.callback(
    [Output("modal-sm", "is_open"),
     Output("modal-header", "children"),
     Output("modal-body", "children")],
    [Input('interval-component', 'n_intervals')],
    [State("modal-sm", "is_open")]
)
def toggle_modal(n_intervals, is_open):
    modal_text = read_info()

    if n_intervals and modal_text != "N/A":
        if modal_text == "DONE":
            return False, "Info", dbc.ModalBody()
        return True, "Info", dbc.ModalBody(modal_text)
    else:
        return dash.no_update, dash.no_update, dash.no_update


@app.callback(
    [Output('personality-dropdown', 'options'),
     Output('personality-dropdown', 'value'),

     Output('title-input', 'value'),
     Output('title-input', 'style'),

     Output('description-input', 'value'),
     Output('description-input', 'style'),

     Output('update-personality-btn', 'style'),
     Output('delete-personality-btn', 'style')],

    [Input('update-personality-btn', 'n_clicks'),
     Input('delete-personality-btn', 'n_clicks'),
     Input('personality-dropdown', 'value')],

    [
        State('title-input', 'value'),
        State('description-input', 'value')]
)
def modify_personalities(save_clicks, delete_clicks, selected_personality, title_, description_):
    ctx = dash.callback_context
    if not ctx.triggered:
        button_id = 'No clicks yet'
    else:
        button_id = ctx.triggered[0]['prop_id'].split('.')[0]

    personalities = load_personalities()
    personalities['*New Personality*'] = """Describe as precise as possible the personnality. 
    
    1. Define the Purpose and Role
Identify the primary role: Determine what specific functions the AI will perform.
Set objectives: What problems is the AI designed to solve? What are the goals of the AI's interactions?

2. Establish Core Competencies
List skills and knowledge areas: Identify the key areas of expertise the AI needs to excel in.
Determine depth of knowledge: Decide on the level of expertise (e.g., basic, intermediate, advanced).

3. Create a Personality Profile
Traits: Define personality traits such as friendly, professional, empathetic, etc.
Communication style: Decide on the tone and style of interaction (formal, casual, technical, etc.).

4. Develop Interaction Scenarios
Common interactions: List typical questions or tasks the AI will handle.
Responses: Craft sample responses for these scenarios to ensure consistency in personality and competency.

"""
    try:
        title = selected_personality
        description = personalities[selected_personality]
    except:
        title = ''
        description = ''
    if button_id == 'update-personality-btn' and title_ and description_:
        if selected_personality in personalities:
            del personalities[selected_personality]
        personalities[title_] = description_
        save_personalities(personalities)
        selected_personality = title_
    elif button_id == 'delete-personality-btn' and selected_personality:
        if selected_personality in personalities:
            del personalities[selected_personality]
            save_personalities(personalities)
            selected_personality = None

    options = [{'label': key, 'value': key} for key in personalities.keys()]
    display_btn_update = {
        'width': '40%',
        'right': '10px',
        'backgroundColor': colors['primary'],
        'color': 'white',
        'borderRadius': '5px',
        'border': 'none',
        'marginBottom': '10px',
        'marginRight': '80px'
    } if selected_personality else {'display': 'none'}

    display_btn_delete = {
        'width': '40%',
        'right': '10px',
        'backgroundColor': "#ca6702",
        'color': 'white',
        'borderRadius': '5px',
        'border': 'none',
        'marginBottom': '10px'
    } if selected_personality else {'display': 'none'}
    title_style = {'width': '100%',
                   'minHeight': '5px',
                   'overflowY': 'auto',
                   'borderRadius': '10px',
                   'border': f'1px solid {colors["secondary"]}',
                   'marginBottom': '15px',
                   'marginTop': '15px',
                   'font-size': '15px',
                   'padding': '5px',
                   'boxShadow': '0 4px 6px rgba(0, 0, 0, 0.1)',
                   'outline': 'none',
                   ':focus': {
                       'borderColor': '#0056b3',
                       'boxShadow': '0 0 0 0.2rem rgba(0, 86, 179, 0.25)'
                   },
                   'verticalAlign': 'middle', } if selected_personality else {'display': 'none'}
    description_style = {
        'width': '100%',
        'height': '20vh',
        'borderRadius': '10px',
        'border': f'1px solid {colors["secondary"]}',
        'marginBottom': '15px',
        'font-size': '15px',
        'padding': '5px',
        'boxShadow': '0 4px 6px rgba(0, 0, 0, 0.1)',
        'outline': 'none',
        ':focus': {
            'borderColor': '#0056b3',
            'boxShadow': '0 0 0 0.2rem rgba(0, 86, 179, 0.25)'
        },
        'whiteSpace': 'pre-wrap',
        'overflowY': 'auto',
        'wordWrap': 'break-word'
    } if selected_personality else {'display': 'none'}
    return (options,
            selected_personality,
            title if selected_personality else '',
            title_style,
            description if selected_personality else '',
            description_style,
            display_btn_update,
            display_btn_delete)


@app.callback(
    [Output('settings-column', 'style'),
     Output('chat-column', 'width'),
     Output('toggle-button', 'children')],
    Input('toggle-button', 'n_clicks'),
    Input('toggle-state', 'children')
)
def toggle_visibility(n_clicks, toggle_state):
    if n_clicks % 2 == 0:
        return {
            'backgroundColor': 'white', 'padding': '30px', 'borderRadius': '10px',
            'border': f'1px solid {colors["secondary"]}', 'height': '95vh',
        }, {'size': 6, 'offset': 0}, ["Hide settings ", html.I(className='fa fa-eye-slash')]
    else:
        return {'display': 'none'}, {'size': 9, 'offset': 0}, ["Show settings ", html.I(className='fa fa-eye')]


@app.callback(
    [Output('groq_api_key', 'value'),
     Output('llama_parse_key', 'value'),
     Output('brave_api_key', 'value')],
    Input('save-button-api', 'n_clicks'),
    [State('groq_api_key', 'value'),
     State('llama_parse_key', 'value'),
     State('brave_api_key', 'value')]
)
def update_groq_key(button, groq, llama, brave):
    ctx = dash.callback_context

    if not ctx.triggered:
        return dash.no_update, dash.no_update, dash.no_update

    trigger_id = ctx.triggered[0]['prop_id'].split(".")[0]
    if trigger_id == "save-button-api":
        update_setting('groq_api_key', groq)
        update_setting('llama_parse_key', llama)
        update_setting('brave_api_key', brave)
        data = load_settings()
        return data['groq_api_key'], data['llama_parse_key'], data['brave_api_key']
    else:
        return dash.no_update, dash.no_update, dash.no_update


@app.callback(
    Output('tokens-slider', 'max'),
    Output('tokens-slider', 'marks'),
    Input('model-dropdown', 'value')
)
def update_max_tokens(model_name):
    model_tokens = {
        'mixtral-8x7b-32768': 31950,
        'llama3-70b-8192': 8192,
        'llama3-8b-8192': 8192,
        'gemma-7b-it': 8192

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
        for content, filename in zip(contents, filenames):
            data = content.split(',')[1]
            file_path = os.path.join(session_dir, filename)
            with open(file_path, "wb") as fh:
                fh.write(base64.b64decode(data))
        stored_filenames = [os.path.join(session_id, fname) for fname in filenames]
        return generate_file_preview(filenames), stored_filenames

    elif 'delete-file' in trigger_id:
        button_id = json.loads(trigger_id.split('.')[0])
        index = button_id['index']
        file_to_remove = stored_filenames[index]
        os.remove(os.path.join(CHAT_DIR, file_to_remove))
        stored_filenames.pop(index)
        return generate_file_preview(stored_filenames), stored_filenames

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
        return dash.no_update

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

    return html.Div(children, className='d-flex align-items-center', style={'whiteSpace': 'nowrap',
                                                                            'marginTop': '0px', 'marginBottom': '0px'})


def generate_file_preview(filenames):
    children = [
        html.Div([
            html.I(className=f"fas {file_icon_and_color(filename.split('.')[-1])[0]}",
                   style={'marginRight': '10px', 'color': file_icon_and_color(filename.split('.')[-1])[1]}),
            html.Span(f"{filename[:6]}...{filename.split('.')[-1]}" if len(filename) > 10 else filename,
                      title=f"{filename}",
                      style={'overflow': 'hidden', 'textOverflow': 'ellipsis', 'whiteSpace': 'nowrap'}),
            html.Button('×', id={'type': 'delete-file', 'index': i}, className='close',
                        style={'fontSize': '16px', 'marginLeft': '10px', 'cursor': 'pointer',
                               'verticalAlign': 'middle'})
        ], className='d-flex align-items-center', style={'marginRight': '20px'})
        for i, filename in enumerate(filenames)
    ]

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
        if input_value == "/":
            return "/data or /web"
    return dash.no_update


@app.callback(
    Output('session-id', 'data'),
    Input('new-chat-button', 'n_clicks'),
    prevent_initial_call=True
)
def new_chat_session(n_clicks):
    global new_chat, session_id_global
    if session_id_global is None or (n_clicks > 0 and new_chat is not None):
        new_session_id = str(uuid.uuid4())
        save_chat(new_session_id, {'messages': [{'role': 'system', 'content': 'Welcome! How can I assist you today?'}]})
        new_chat = None
        return new_session_id


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
            html.Button('Save', id={'type': 'save-button', 'index': session_index},
                        style={'margin-left': '10px', 'backgroundColor': '#5cb85c', 'color': '#fff',
                               'border': 'none',
                               'padding': '5px 10px', 'borderRadius': '3px', 'cursor': 'pointer'}, n_clicks=0),
            html.Button('Delete', id={'type': 'delete-button', 'index': session_index},
                        style={'margin-left': '10px', 'backgroundColor': '#d9534f', 'color': '#fff', 'border': 'none',
                               'padding': '5px 10px', 'borderRadius': '3px', 'cursor': 'pointer'}, n_clicks=0),
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

     ],
    [State('user-input', 'value'),
     State('session-id', 'data'),
     State('upload-data', 'filename'),
     State('temperature-slider', 'value'),
     State('tokens-slider', 'value'),
     State('groq_api_key', 'value'),
     State('llama_parse_key', 'value'),
     State('brave_api_key', 'value'),
     State('internet-slider', 'value'),
     State('model-dropdown', 'value'),
     State('title-input', 'value'),
     State('description-input', 'value')
     ]
)
def update_chat(send_clicks, new_chat_clicks, upload_contents, session_clicks,
                user_input, session_id, filename,
                temp, max_tokens,
                groq_api_key,
                llama_parse_id,
                brave_id, internet_on_off,
                model_dropdown, personality_title, personality_description):
    global session_id_global, new_chat, global_check
    session_id = session_id_global
    ctx = callback_context
    if not ctx.triggered:
        raise PreventUpdate
    button_id = ctx.triggered[0]['prop_id']
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
        personality_description = personality_description
        if not personality_description or personality_title == "*New Personality*":
            personality_description = False

        if user_input.startswith('/web'):
            save_info("Web scraping...")
            user_input = user_input.replace("/web", "")

            ai_answer = scrape_and_find(user_input, groq_api_key, brave_id, model_dropdown, temp, max_tokens,
                                        session_id, personality_description)
            ai_answer = ai_answer['result']
            save_info("DONE")


        elif user_input.startswith('/data'):
            save_info("data handling")
            user_input = user_input.replace("/data", "")
            directory_path = f'{CHAT_DIR}/{session_id}'
            file_paths = [os.path.join(directory_path, file_name) for file_name in os.listdir(directory_path)
                          if any(file_name.endswith(ext) for ext in supported_extensions)]

            ai_answer = \
                asyncio.run(
                    parse_and_find(file_paths, user_input, model_dropdown, llama_parse_id, temp, max_tokens,
                                   groq_api_key, session_id, personality_description, 3))['result']
            save_info("DONE")

            if ai_answer == "N/A":
                    ai_answer = get_auto_assistant(user_input, groq_api_key, brave_id, model_dropdown, temp, max_tokens,
                                                   file_paths, llama_parse_id, session_id, personality_description,
                                                   internet_on_off=0)

        elif filename:
            save_info("Looking over the files...")
            directory_path = f'{CHAT_DIR}/{session_id}'
            file_paths = [os.path.join(directory_path, file_name) for file_name in filename]
            ai_answer = \
                asyncio.run(
                    parse_and_find(file_paths, user_input, model_dropdown, llama_parse_id, temp, max_tokens,
                                   groq_api_key, session_id, personality_description, 3))[
                    'result']
            if ai_answer == "N/A":
                    ai_answer = get_auto_assistant(user_input, groq_api_key, brave_id, model_dropdown, temp, max_tokens,
                                                   file_paths, llama_parse_id, session_id, personality_description,
                                                   internet_on_off=0)
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
                file_paths = [os.path.join(directory_path, file_name) for file_name in os.listdir(directory_path)
                              if any(file_name.endswith(ext) for ext in supported_extensions)]
            except:
                file_paths = []
            ai_answer = get_auto_assistant(user_input, groq_api_key, brave_id, model_dropdown, temp, max_tokens,
                                           file_paths, llama_parse_id, session_id, personality_description,
                                           internet_on_off)
            save_info("DONE")

        chat_data['messages'].append({'role': 'user', 'content': user_input})
        chat_data['messages'].append({'role': 'assistant', 'content': ai_answer})
        save_info("DONE")
        save_chat(session_id, chat_data)

    elif 'chat-session' in button_id:
        session_id = json.loads(ctx.triggered[0]['prop_id'].split('.')[0])['index']
    elif 'new-chat-button' in button_id:
        new_session_id = str(uuid.uuid4())
        save_chat(new_session_id,
                  {'messages': [{'role': 'assistant', 'content': 'Welcome! How can I assist you today?'}]})
        session_id = new_session_id
        new_chat = 1

    if not session_id:
        new_session_id = str(uuid.uuid4())
        save_chat(new_session_id,
                  {'messages': [{'role': 'assistant', 'content': 'Welcome! How can I assist you today?'}]})
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
            html.Span(
                [html.P(line, style={'margin': '0', 'line-height': '1.2'}) if line.strip() else html.Br() for line in
                 msg['content'].split('\n')], style={'marginLeft': '10px'})
        ], style=style)

        chat_history_elements.append(chat_bubble)

    if filename:
        index_to_insert = len(chat_history_elements) - 1
        chat_history_elements.insert(index_to_insert, html.Div(file_children))

    session_id_global = session_id
    global_check = True

    return chat_history_elements


@app.callback(
    [Output('chat-history-reminder', 'children'),
     Output("modal", "is_open")],
    [Input("toggle-button-reminder", "n_clicks"),
     Input('reminder-send-button', 'n_clicks')],
    [State('reminder-user-input', 'value'),
     State('groq_api_key', 'value'), ]
)
def update_chat_reminder(reminder_open_button, send_button, message, groq_api_key):
    directory_path = 'chat_reminder'
    ctx = dash.callback_context
    global global_check

    if not ctx.triggered:
        return dash.no_update, dash.no_update

    trigger = ctx.triggered[0]['prop_id'].split('.')[0]

    if not os.path.exists(os.path.join(CHAT_DIR, directory_path)):
        save_chat(directory_path, {'messages': [{'role': 'system', 'content': 'Welcome! How can I assist you today?'}]})

    chat_data = load_chat(directory_path)
    chat_history_elements = []
    for msg in chat_data['messages']:
        if msg['role'] == 'user':
            profile_pic = user_profile_pic
            style = {'textAlign': 'left', 'padding': '10px', 'borderRadius': '10px', 'marginBottom': '10px',
                     'maxWidth': '100%'}
        else:
            profile_pic = ai_profile_pic
            style = {'textAlign': 'left', 'backgroundColor': '#f9f7f3', 'padding': '10px', 'borderRadius': '10px',
                     'marginBottom': '10px', 'color': colors['text'], 'maxWidth': '100%'}

        chat_bubble = html.Div([
            html.Img(src=profile_pic, style={'width': '30px', 'height': '30px', 'borderRadius': '50%'}),
            html.Span(msg['content'], style={'marginLeft': '10px'})
        ], style=style)
        chat_history_elements.append(chat_bubble)

    if trigger == "toggle-button-reminder":
        return chat_history_elements, True

    if trigger == "reminder-send-button" and message:
        chat_data['messages'].append({'role': 'user', 'content': message})

        ai_answer = asyncio.run(parse_and_remember('chat_sessions', message, groq_api_key, global_check))['result']
        chat_data['messages'].append({'role': 'assistant', 'content': ai_answer})

        save_chat(directory_path, chat_data)

        chat_history_elements.append(html.Div([
            html.Img(src=user_profile_pic, style={'width': '30px', 'height': '30px', 'borderRadius': '50%'}),
            html.Span(
                [html.P(line, style={'margin': '0', 'line-height': '1.2'}) if line.strip() else html.Br() for line in
                 message.split('\n')], style={'marginLeft': '10px'})
        ], style={'textAlign': 'left', 'padding': '10px', 'borderRadius': '10px', 'marginBottom': '10px',
                  'maxWidth': '100%'}))

        chat_history_elements.append(html.Div([
            html.Img(src=ai_profile_pic, style={'width': '30px', 'height': '30px', 'borderRadius': '50%'}),
            html.Span(
                [html.P(line, style={'margin': '0', 'line-height': '1.2'}) if line.strip() else html.Br() for line in
                 ai_answer.split('\n')], style={'marginLeft': '10px'})
        ], style={'textAlign': 'left', 'backgroundColor': '#f9f7f3', 'padding': '10px', 'borderRadius': '10px',
                  'marginBottom': '10px', 'color': colors['text'], 'maxWidth': '100%'}))
        global_check = False
        return chat_history_elements, True

    return dash.no_update, dash.no_update


if __name__ == '__main__':
    app.run_server(debug=False)

