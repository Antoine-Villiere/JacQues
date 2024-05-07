from dash import Dash, dcc, html, Input, Output
import dash_bootstrap_components as dbc

# Initialize the Dash app
app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])

# Create the layout
app.layout = html.Div([
    # Add a button to toggle column visibility
    html.Button("Toggle Column", id='toggle-button', n_clicks=0),

    # Define a hidden div to keep track of the visibility state
    html.Div(id='toggle-state', children='show', style={'display': 'none'}),

    # Conditionally render the column
    dbc.Col(
        id='settings-column',
        children=[
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
                        max=100,
                        step=1,
                        value=25,
                        marks={5: '5 sentences max', 100: '8 pages max'},
                        tooltip={"placement": "bottom", "always_visible": False}
                    ),
                ], style={'width': '100%', 'marginBottom': '15px'}),
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
            ], style={
                'backgroundColor': 'white', 'padding': '30px', 'borderRadius': '10px',
                'border': '1px solid #ccc', 'boxShadow': '0 4px 8px rgba(0,0,0,0.1)'
            })
        ],
        width={'size': 3, 'offset': 0}
    )
])


# Define the callback to toggle column visibility
@app.callback(
    Output('settings-column', 'style'),
    Input('toggle-button', 'n_clicks'),
    Input('toggle-state', 'children')
)
def toggle_visibility(n_clicks, toggle_state):
    # Switch the visibility state
    if n_clicks % 2 == 0:
        return {'display': 'none'}
    else:
        return {'display': 'block', 'padding': '30px', 'borderRadius': '10px',
                'border': '1px solid #ccc', 'boxShadow': '0 4px 8px rgba(0,0,0,0.1)'}


if __name__ == '__main__':
    app.run_server(debug=True)
