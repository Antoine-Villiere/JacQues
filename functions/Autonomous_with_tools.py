from functions.IMPORT import *
from functions.Scrape_and_find import scrape_and_find
from functions.Parse_and_find import parse_and_find


def get_auto_assitant(user_query, groq_api_key, brave_id, model_dropdown, temp, max_tokens, file_paths, api_key,session_id):
    print(user_query)
    print(file_paths)

    if len(file_paths) > 0:
        vector_store = parse_and_find(file_paths, user_query, model_dropdown, api_key, temp, max_tokens, ai=False)
        print(vector_store.count())
        breakpoint()
    # Step 1: send the conversation and available functions to the model
    messages = [
        {
            "role": "system",
            "content": ("You are an Assistant called 'JacQues' that answers questions by calling functions."
                        "First get additional information about the users question."
                        "You can either use the `parse_and_find` tool to search your knowledge base or the "
                        "`scrape_and_find` tool to search the internet."
                        "If the user asks about current events, use the `scrape_and_find` tool to search the "
                        "internet."
                        "If the user asks to summarize the conversation, use the `get_chat_history` tool to get your "
                        "chat history with the user."
                        "Carefully process the information you have gathered and provide a clear and concise answer "
                        "to the user."
                        "Respond directly to the user with your answer, do not say 'here is the answer' or 'this is "
                        "the answer' or 'According to the information provided'"
                        "NEVER mention your knowledge base or say 'According to the search_knowledge_base tool' or "
                        "'According to {some_tool} tool'.")

        },
        {
            "role": "user",
            "content": user_query,
        }
    ]
    tools = [
        {
            "type": "function",
            "function": {
                "name": "parse_and_find",
                "description": "This function leverages a sophisticated document retrieval system to access a comprehensive knowledge base. It aims to efficiently parse the user's query and locate relevant information within internal documents, enabling the assistant to deliver accurate and well-informed responses.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The user's question or inquiry, formatted as a detailed and contextual string. This query should be crafted carefully to include all necessary details and context to enhance the accuracy and relevance of the search results within the knowledge base.",
                        }
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "scrape_and_find",
                "description": "This function initiates a real-time internet search to gather and synthesize information relevant to the user's query. It is designed to fetch the most up-to-date data from a wide array of online sources, ensuring the assistant provides current and comprehensive answers.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "A precise and context-rich question provided by the user, intended to be used for an exhaustive internet search. The query should include specific details and phrasing that aid in pinpointing accurate and relevant online information.",
                        }
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_chat_history",
                "description": "This function retrieves the entire interaction history between the user and the assistant. It is crucial for understanding the context of ongoing conversations and ensuring continuity in the dialogue. The function supports the assistant in delivering more personalized and context-aware responses.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "Boolean",
                            "description": "A Boolean flag indicating whether the chat history should be retrieved. Setting this to True enables the assistant to review past interactions, which is particularly useful for maintaining context over extended conversations.",
                        }
                    },
                    "required": ["query"],
                },
            },
        }
    ]
    client = Groq(api_key=groq_api_key)
    response = client.chat.completions.create(
        model=model_dropdown,
        messages=messages,
        tools=tools,
        tool_choice="auto",
        max_tokens=max_tokens
    )
    response_message = response.choices[0].message
    print(response_message)
    if response_message.content is None:
        tool_calls = response_message.tool_calls[0].function.name
        query = json.loads(response_message.tool_calls[0].function.arguments)["query"]
        print(tool_calls, query)
        # Step 2: check if the model wanted to call a function
        if tool_calls:
            ai_answer = ''
            if tool_calls == "scrape_and_find":
                print("scrape_and_find")
                ai_answer = scrape_and_find(query, groq_api_key, brave_id, model_dropdown, temp, max_tokens,session_id)
            return ai_answer
    return response_message.content
