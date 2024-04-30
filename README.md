# JacQues

JacQues is a Dash-based interactive web application designed to facilitate real-time chat and document management. It leverages AI-driven responses and file handling to provide a sophisticated user interaction platform. Ideal for businesses looking to integrate chat functionalities with document processing and settings management through a web interface.

## Features

- **Real-Time Chat**: Users can start new chat sessions, send messages, and receive AI-generated responses.
- **Session Management**: Save, load, edit, or delete chat sessions with ease.
- **Document Upload**: Supports uploading documents that can be processed by integrated AI functionalities.
- **Dynamic Settings**: Customize AI settings and API keys through a user-friendly web interface.

## Installation

To run JacQues on your local machine, you'll need Python and several dependencies:

### Prerequisites

- Python 3.6 or newer
- pip for installing Python packages

### Dependencies

Install the required Python packages using pip:

```bash
pip install dash dash-bootstrap-components dash-core-components dash-html-components
```

### Clone the Repository

Clone this repository to your local machine:

```bash
git clone https://github.com/yourusername/JacQues.git
cd JacQues
```

## Usage

To start the server and use the application, run:

```bash
python app.py
```

Navigate to `http://127.0.0.1:8050/` in your web browser to access the application.

## Configuration

### API Keys

Before running the application, ensure you configure the necessary API keys:

1. **GROQ API KEY**: Used for AI functionalities.
2. **LLAMAPARSE API KEY**: Necessary for Parsing processes.
3. **BRAVE API KEY**: Necessary for Web Scraping processes.

You can set these keys through the application's settings panel.

### Models

Select from various AI models for different functionalities:

- Llama3
- Mixtral 8x22b

Adjust the model settings and prompts as needed for optimal performance.

## Contributing

Contributions are welcome! Feel free to fork this repository and submit pull requests, or open issues for bugs, feature requests, or other concerns.

## License

This project is licensed under the MIT License - see the [LICENSE.md](LICENSE) file for details.
