from functions.IMPORT import *
from langchain.chains import RetrievalQA
from langchain.memory import ConversationBufferMemory
from functions.chat_management import save_info

nest_asyncio.apply()


async def load_or_parse_data(file_paths, llama_parse_id, session_id):
    parsed_data = []
    for file_path in file_paths:
        data_file = f"./chat_sessions/{session_id}/data_parse/parsed_data_{os.path.basename(file_path)}.pkl"
        os.makedirs(f"./chat_sessions/{session_id}/data_parse", exist_ok=True)

        if os.path.exists(data_file):
            parsed_data.append(joblib.load(data_file))
        else:
            parsing_instruction = ("The provided document contains many tables. extract all the document, including "
                                   "table and best keep the same format as the original document.")
            parser = LlamaParse(api_key=llama_parse_id, result_type="markdown",
                                parsing_instruction=parsing_instruction, max_timeout=5000)
            data = await asyncio.to_thread(parser.load_data, file_path)
            joblib.dump(data, data_file)
            parsed_data.append(data)
    return parsed_data



async def create_vector_database(file_paths, llama_parse_id, session_id):
    documents = await load_or_parse_data(file_paths, llama_parse_id, session_id)
    markdown_path = f"./chat_sessions/{session_id}/data_parse/output.md"
    with open(markdown_path, 'w', encoding='utf8') as f:
        for data in documents:
            for doc in data:
                f.write(doc.text + '\n')

    if not os.path.exists(markdown_path):
        return None, None

    loader = UnstructuredMarkdownLoader(markdown_path)
    docs = loader.load()
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=2000, chunk_overlap=100)
    chunks = text_splitter.split_documents(docs)
    embed_model = FastEmbedEmbeddings(model_name="BAAI/bge-base-en-v1.5")
    vector_store = Chroma.from_documents(documents=chunks, embedding=embed_model,
                                         persist_directory=f"./chat_sessions/{session_id}/chroma/chroma_db",
                                         collection_name="rag")
    return vector_store, embed_model


async def parse_and_find(file_paths, query, model, llama_parse_id, temp, max_tokens, groq_api_key, session_id,
                         personality,number):
    client = Groq(api_key=groq_api_key)
    chat_completion = client.chat.completions.create(
        messages=[
            {
                "role": "system",
                "content": """You are a Question generator who generates an array of 3 rephrased questions in JSON format IN ENGLISH.
                    You MUST ONLY rely on the JSON schema. DO NOT add any other comment like "here is the json". 
                    Question should be the closest as possible to the initial query AND IN ENGLISH.
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

    vector_store, embed_model = await create_vector_database(file_paths, llama_parse_id, session_id)
    vector_store = Chroma(embedding_function=embed_model,
                          persist_directory=f"./chat_sessions/{session_id}/chroma/chroma_db", collection_name="rag")
    retrieved_context = vector_store.as_retriever(search_kwargs={'k': number})

    chat_model = ChatGroq(temperature=temp, model_name=model, api_key=groq_api_key, max_tokens=max_tokens)
    memory = ConversationBufferMemory(memory_key='chat_history', return_messages=True, output_key='result')

    if not personality:
        prompt_template = PromptTemplate(template="""Use the following pieces of information to answer the user's question.
                                                    Context: {context}
                                                    Question: {question}
                                                    Only return the helpful answer below and nothing else.
                                                    You MUST ALWAYS reply in the user language.
                                                    If no relevant answer, YOU MUST ONLY REPLY N/A.
                                                    If you cannot successfully reply, YOU MUST ONLY REPLY N/A.
                                                    Helpful answer:""",
                                         input_variables=['context', 'chat_history', 'question'])
    else:
        save_info(f"Jacques will reply with the selected personality: {personality}")
        template = """Use the following pieces of information to answer the user's question.
                                                        Context: {context}
                                                        Question: {question}
                                                        Only return the helpful answer below and nothing else.
                                                        You MUST ALWAYS reply in the user language.
                                                        If no relevant answer, YOU MUST ONLY REPLY N/A.
                                                        If you cannot successfully reply, YOU MUST ONLY REPLY N/A."""
        complete = f"""Here is the personality of the assistant to provide the answer:
                                                                            {personality}
                                                                            Helpful answer:"""
        prompt_template = PromptTemplate(template=template + complete,
                                         input_variables=['context', 'chat_history', 'question'])

    qa_chain = RetrievalQA.from_chain_type(llm=chat_model, chain_type="stuff", retriever=retrieved_context,
                                           memory=memory,
                                           return_source_documents=True, chain_type_kwargs={"prompt": prompt_template})
    return await asyncio.to_thread(qa_chain.invoke, {"query": questions['followUp'][0]})
