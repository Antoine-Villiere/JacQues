from functions.IMPORT import *
from functions.chat_management import save_info


nest_asyncio.apply()

async def load_and_combine_data(base_dir):
    combined_data = []

    for root, _, files in os.walk(f"./{base_dir}"):
        for file in files:
            file_path = os.path.join(root, file)
            if "chat_reminder" in file_path:
                continue
            if file.endswith('.json'):
                try:
                    with open(file_path, 'r', encoding='utf8') as f:
                        data = json.load(f)
                        messages = data.get("messages", [])
                        if messages:
                            parsed_text = "\n".join(f"{msg['role']}: {msg['content']}" for msg in messages)
                            combined_data.append(f"## Discussion from {file}\n\n{parsed_text}\n")
                except (json.JSONDecodeError, KeyError, IOError) as e:
                    save_info(f"Error processing JSON file {file_path}: {e}")
            elif file.endswith('.md'):
                try:
                    with open(file_path, 'r', encoding='utf8') as f:
                        combined_data.append(f"## Discussion from {file}\n\n{f.read()}\n")
                except IOError as e:
                    save_info(f"Error reading markdown file {file_path}: {e}")

    chat_reminder_dir = os.path.join(f"./{base_dir}", "chat_reminder")
    os.makedirs(chat_reminder_dir, exist_ok=True)
    markdown_path = os.path.join(chat_reminder_dir, "combined_output.md")
    with open(markdown_path, 'w', encoding='utf8') as f:
        f.write("\n\n".join(combined_data))

    return markdown_path

async def create_vector_database(markdown_path, base_dir):
    if not os.path.exists(markdown_path):
        return None, None

    loader = UnstructuredMarkdownLoader(markdown_path)
    docs = loader.load()
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=2000, chunk_overlap=100)
    chunks = text_splitter.split_documents(docs)
    embed_model = FastEmbedEmbeddings(model_name="BAAI/bge-base-en-v1.5")
    vector_store = Chroma.from_documents(
        documents=chunks, embedding=embed_model,
        persist_directory=os.path.join(f"./{base_dir}", "chat_reminder", "chroma","chroma_db"),
        collection_name="rag"
    )
    return vector_store, embed_model

async def parse_and_remember(base_dir, query, groq_api_key, global_check):

    markdown_path = await load_and_combine_data(base_dir)
    vector_store_dir = os.path.join(f"./{base_dir}", "chat_reminder", "chroma", "chroma_db")

    if global_check or not os.path.exists(vector_store_dir):
        vector_store, embed_model = await create_vector_database(markdown_path, base_dir)
    else:
        embed_model = FastEmbedEmbeddings(model_name="BAAI/bge-base-en-v1.5")
        vector_store = Chroma(
            embedding_function=embed_model,
            persist_directory=vector_store_dir,
            collection_name="rag"
        )
    retrieved_context = vector_store.as_retriever(search_kwargs={'k': 8})

    chat_model = ChatGroq(
        temperature=0, model_name='mixtral-8x7b-32768', api_key=groq_api_key, max_tokens=32768
    )
    memory = ConversationBufferMemory(memory_key='chat_history', return_messages=True, output_key='result')

    prompt_template = PromptTemplate(
        template="""Use the following pieces of information to answer the user's question.
                    Context: {context}
                    Question: {question}
                    Only return the helpful answer below and nothing else.
                    If no relevant answer, please inform the user you cannot find any relevant information, do not try to reply alternatively.
                    YOU MUST NOT ANSWER ANY QUESTION THAT ARE NOT DIRECTLY RELATED TO THE CONTEXT. 
                    You MUST ALWAYS reply in the user language.
                    Helpful answer:""",
        input_variables=['context', 'chat_history', 'question']
    )

    qa_chain = RetrievalQA.from_chain_type(
        llm=chat_model, chain_type="stuff", retriever=retrieved_context,
        memory=memory, return_source_documents=True,
        chain_type_kwargs={"prompt": prompt_template}
    )
    return await asyncio.to_thread(qa_chain.invoke, {"query": query})

