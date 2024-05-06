CHAT_DIR = 'chat_sessions'

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