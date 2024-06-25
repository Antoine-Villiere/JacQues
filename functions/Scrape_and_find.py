from functions.IMPORT import *
from functions.web_scraper import process_query
from functions.chat_management import save_info


def scrape_and_find(query, groq_api_key, brave_id, model_dropdown, temp, max_tokens, session_id, personality):
    save_info("Initialization...")
    client = Groq(api_key=groq_api_key)
    chat_completion = client.chat.completions.create(
        messages=[
            {
                "role": "system",
                "content": """You are a Question generator who generates an array of 3 rephrased questions in JSON format.
                You MUST ONLY rely on the JSON schema. DO NOT add any other comment like "here is the json". 
                Question should be the closest as possible to the initial query.
              The JSON schema MUST include:
              {
                "original": "The original search query or context",
                "followUp": [
                  "Question 1",
                  "Question 2", 
                  "Question 3"
                ]
              }"""
            },
            {
                "role": "user",
                "content": query,
            }
        ],
        model='llama3-70b-8192',
        temperature=0,
        max_tokens=500
    )

    questions = json.loads(chat_completion.choices[0].message.content)
    retriever = asyncio.run(process_query(questions['followUp'][0], brave_id, session_id))
    if not personality:
        prompt_template = PromptTemplate(template="""Use the following pieces of information to answer the user's question. 
                                                            Context: {context} 

                                                            Question: {question}
                                                            Only return the helpful answer below and nothing else. 
                                                            Do not give any information about procedures and service features that are not mentioned in the PROVIDED CONTEXT.
                                                            You MUST ALWAYS reply in the user language.
                                                            Helpful answer:""",
                                         input_variables=['context', 'question'])
    else:
        template = """Use the following pieces of information to answer the user's question. 
                                                                    Context: {context} 

                                                                    Question: {question}
                                                                    Only return the helpful answer below and nothing else. 
                                                                    Do not give any information about procedures and service features that are not mentioned in the PROVIDED CONTEXT.
                                                                    You MUST ALWAYS reply in the user language.
                                                                    
                                                                    """
        complete = f"""Here is the personality of the assistant to provide the answer:
                                                                    {personality}
                                                                    Helpful answer:"""
        prompt_template = PromptTemplate(template=template + complete,
                                         input_variables=['context', 'question'])

    chat_model = ChatGroq(temperature=temp, model_name=model_dropdown,
                          api_key=groq_api_key, max_tokens=max_tokens)
    save_info("Almost finished... Waiting for the AI")
    qa_chain = RetrievalQA.from_chain_type(llm=chat_model, chain_type="stuff", retriever=retriever,
                                           return_source_documents=False,
                                           chain_type_kwargs={"prompt": prompt_template})
    return qa_chain.invoke({"query": query})
