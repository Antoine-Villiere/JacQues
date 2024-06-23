from functions.IMPORT import *
from functions.Scrape_and_find import scrape_and_find
from functions.Parse_and_find import parse_and_find
from functions.chat_management import load_chat, save_info


def get_auto_assistant(user_query, groq_api_key, brave_id, model_dropdown, temp, max_tokens, file_paths, api_key,
                       session_id, personality, internet_on_off):
    chat_history = load_chat(session_id)

    messages = [
        {
            "role": "system",
            "content": """You are an AI Assistant named 'Jacques' specialized in responding to user inquiries.
        Your primary objective is to respond directly and accurately using your built-in knowledge.
        Only use internet searches if the query specifically requires the most recent information or pertains to current events.

        When responding, be concise and straightforward. Do not preface your answers with phrases like 'here is the answer' or 'according to...'.
        Avoid mentioning any underlying tools, processes, or specific names of resources used in your responses."""
        }
    ]

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
                "description": "This function initiates a real-time internet search to gather and synthesize information relevant to the user's query. "
                               "It is designed to fetch the most up-to-date data from a wide array of online sources, ensuring the assistant provides current and comprehensive answers."
                               "Only use internet searches if the query specifically requires the most recent information or pertains to current events.",
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
            if len(file_paths) < 2:
                save_info("Parsing the document...")
            else:
                save_info("Parsing documents...")
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
            save_info("DONE")
            return response_message.content

        if internet_on_off == 1 and response_message.tool_calls:
            tool_calls = response_message.tool_calls[0].function.name
            query = json.loads(response_message.tool_calls[0].function.arguments)["query"]
            if tool_calls == "scrape_and_find":
                save_info("Scraping the web...")
                ai_answer = scrape_and_find(query, groq_api_key, brave_id, model_dropdown, temp, max_tokens, session_id,
                                            personality)
                save_info("DONE")
                return ai_answer['result']

    return asyncio.run(handle_files_and_respond())
