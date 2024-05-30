from functions.IMPORT import *
from functions.Scrape_and_find import scrape_and_find
from functions.Parse_and_find import parse_and_find
from functions.chat_management import load_chat


def get_auto_assistant(user_query, groq_api_key, brave_id, model_dropdown, temp, max_tokens, file_paths, api_key,
                       session_id, personality, internet_on_off):
    chat_history = load_chat(session_id)

    messages = [{
        "role": "system",
        "content": """You are an AI Assistant named 'Jacques' specialized in responding to user inquiries. 
Your initial step is to gather detailed information relevant to the user's question. For general queries, utilize your built-in knowledge. 
However, if the question pertains to current events or requires the most recent information, deploy the scrape_and_find tool to conduct an internet search. After collecting the necessary data, analyze it to ensure your response is accurate, clear, and directly addresses the query. 

Always provide answers in a straightforward manner without prefacing them with phrases like 'here is the answer' or 'according to...'. 
Avoid mentioning your underlying tools or processes, such as 'knowledge base' or any specific tool names, in your responses."""
    }]

    if 'messages' in chat_history:
        messages.extend(chat_history['messages'])

    messages.append({
        "role": "user",
        "content": user_query,
    })

    client = Groq(api_key=groq_api_key)

    if internet_on_off == 1:
        tools = [{
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
        }]

    async def handle_files_and_respond():
        if len(file_paths) > 0:
            retrieved_contexts = await parse_and_find(file_paths, user_query, model_dropdown, api_key, temp, max_tokens,
                                                      groq_api_key, session_id, personality)
            if retrieved_contexts['result'] != "N/A":
                return retrieved_contexts['result']

        response = client.chat.completions.create(
            model=model_dropdown,
            messages=messages,
            tools=tools if internet_on_off == 1 else None,
            tool_choice="auto" if internet_on_off == 1 else 'none',
            max_tokens=max_tokens,
            temperature=temp
        )
        response_message = response.choices[0].message

        if response_message.content:
            return response_message.content

        if internet_on_off == 1 and response_message.tool_calls:
            tool_calls = response_message.tool_calls[0].function.name
            query = json.loads(response_message.tool_calls[0].function.arguments)["query"]
            if tool_calls == "scrape_and_find":
                ai_answer = scrape_and_find(query, groq_api_key, brave_id, model_dropdown, temp, max_tokens, session_id,
                                            personality)
                return ai_answer['result']

    return asyncio.run(handle_files_and_respond())

