from IMPORT import *
from web_scraper import process_query
from langchain.chains import RetrievalQA


def scrape_and_find(query, groq_api_key, brave_id, model_dropdown, temp, max_tokens):
    print("Initialization...")
    client = Groq(api_key=groq_api_key)
    chat_completion = client.chat.completions.create(
        messages=[
            {
                "role": "system",
                "content": """You are a Question generator who generates an array of 3 rephrased questions in JSON format.
                You MUST ONLY rely on the JSON schema. Question should be the closest as possible to the initial query.
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
        model=model_dropdown,
        temperature=temp,
        max_tokens=max_tokens
    )

    questions = json.loads(chat_completion.choices[0].message.content)
    retriever = asyncio.run(process_query(questions['followUp'][0], brave_id))
    prompt_template = PromptTemplate(template="""Use the following pieces of information to answer the user's question. 
                                                            Context: {context} 

                                                            Question: {question}
                                                            Only return the helpful answer below and nothing else. 
                                                            If, based on the provided context, you cannot explicitly give the answer, you MUST reply "N/A".
                                                            Helpful answer:""",
                                     input_variables=['context', 'question'])

    chat_model = ChatGroq(temperature=temp, model_name=model_dropdown,
                          api_key=groq_api_key, max_tokens=max_tokens)
    print("Almost finished...")
    qa_chain = RetrievalQA.from_chain_type(llm=chat_model, chain_type="stuff", retriever=retriever,
                                           return_source_documents=True,
                                           chain_type_kwargs={"prompt": prompt_template})
    return qa_chain.invoke({"query": query})
