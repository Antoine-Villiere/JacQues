# jacQues: Your Intelligent AI Assistant

jacQues is a cutting-edge AI agent designed to revolutionize the way you interact with information and complete tasks. 
Developed as a solo project, jacQues aims to offers a seamless and intuitive experience for users across various domains.

![jacQues AI Assistant](assets/Ai.png)

## Features

### 1. Multi-Modal Information Processing
- **Web Scraping**: jacQues can search the web for up-to-date information on any topic.
- **Document Analysis**: Efficiently process and extract insights from various file formats including PDFs, Word documents, presentations, and more.
- **Autonomous Agent**: jacQues adapts its approach based on the user's request, combining these sources as needed to deliver the most accurate and helpful response possible.

### 2. Adaptive Personality
- Customize jacQues' personality to suit your preferences or specific use cases.
- Choose from pre-defined personalities or create your own for a tailored experience.

### 3. Intelligent Conversation Management
- Maintain context across multiple chat sessions.
- Access a pop-up window that helps you recall information from different discussions without manually searching through chat history.

### 4. Advanced Language Model Integration
- Utilizes open-source language models available through GROQ's servers, including:
  - LLaMA 3
  - Mixtral
  - Gemma
- Balances performance and efficiency with state-of-the-art open-source models.

### 5. File Management
- Upload and manage documents directly within the chat interface.
- Seamlessly reference and analyze uploaded files during conversations.

### 6. Customizable Settings
- Adjust creativity levels and response lengths to fine-tune jacQues' outputs.
- Toggle internet access for real-time information retrieval.

### 7. Reminder System
- Set and manage reminders within conversations.
- jacQues can recall important information from previous chats.

### 8. API Integration
- Seamlessly integrates with Groq, LlamaParse, and Brave APIs for enhanced functionality.

## Technical Stack

- **Frontend**: Dash (Python-based web application framework)
- **Backend**: Python
- **APIs**: Groq, LlamaParse, Brave
- **File Processing**: Support for various document formats

## Getting Started

1. Clone the repository:
   ```
   git clone https://github.com/your-username/jacQues-ai-assistant.git
   ```

2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

3. Set up your API keys in the settings panel:
   - Groq API Key : [Groq API](https://console.groq.com/keys)
   - LlamaParse API Key : [LlamaParse API](https://cloud.llamaindex.ai/login)
   - Brave API Key : [Brave API](https://brave.com/search/api/)

4. Run the application:
   ```
   python app.py
   ```

5. Open your browser and navigate to `http://localhost:8050` to start chatting with jacQues!

## Usage Examples

1. **Web Research**: 
   ```
   /web What are the latest developments in quantum computing?
   ```

2. **Document Analysis**:
   ```
   /data Summarize the key points from the uploaded financial report.
   ```

3. **Customizing Personality**:
   Use the settings panel to create or select a personality that suits your needs.

4. **Setting Reminders**:
   Click the reminder button and ask jacQues to remember important information.

## Contributing

Contributions to improve jacQues are welcome! While we don't have a formal CONTRIBUTING.md file yet, feel free to submit pull requests, report issues, or suggest enhancements through the GitHub repository.

## License

This project is open source and available under the [MIT License](https://opensource.org/licenses/MIT).

## Acknowledgments

- Thanks to the teams behind Groq, LlamaParse, and Brave for their excellent APIs.
- Appreciation to the open-source community for developing powerful language models like LLaMA, Mixtral, and Gemma.
- Special thanks to the various AI assistants that provided guidance during the development process.
