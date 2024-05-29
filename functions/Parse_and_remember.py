from functions.IMPORT import *
from langchain.chains import RetrievalQA
from langchain.memory import ConversationBufferMemory

nest_asyncio.apply()


async def load_and_combine_data(base_dir):
    combined_data = []

    # Iterate through all subdirectories in base_dir
    for root, _, files in os.walk(base_dir):
        for file in files:
            file_path = os.path.join(root, file)
            if file.endswith('.json'):
                # Process JSON discussion files
                with open(file_path, 'r', encoding='utf8') as f:
                    data = json.load(f)
                    messages = data.get("messages", [])
                    parsed_text = "\n".join([f"{msg['role']}: {msg['content']}" for msg in messages])
                    combined_data.append(parsed_text)
            elif file.endswith('.md'):
                # Read existing markdown files
                with open(file_path, 'r', encoding='utf8') as f:
                    combined_data.append(f.read())

    # Combine all collected data into a single markdown file
    print(combined_data)
    print(base_dir)
    breakpoint()
    chat_reminder_dir = os.path.join(base_dir, "chat_reminder")
    os.makedirs(chat_reminder_dir, exist_ok=True)
    markdown_path = os.path.join(chat_reminder_dir, "combined_output.md")
    with open(markdown_path, 'w', encoding='utf8') as f:
        for data in combined_data:
            f.write(data + '\n')

    return markdown_path


async def create_vector_database(markdown_path, session_id):
    if not os.path.exists(markdown_path):
        return None, None

    loader = UnstructuredMarkdownLoader(markdown_path)
    docs = loader.load()
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=2000, chunk_overlap=100)
    chunks = text_splitter.split_documents(docs)
    embed_model = FastEmbedEmbeddings(model_name="BAAI/bge-base-en-v1.5")
    vector_store = Chroma.from_documents(
        documents=chunks, embedding=embed_model,
        persist_directory=f"./chat_sessions/{session_id}/chroma/chroma_db",
        collection_name="rag"
    )
    return vector_store, embed_model


async def parse_and_remember(base_dir, query, model, temp, max_tokens, groq_api_key):

    # Load and combine data from all sessions
    markdown_path = await load_and_combine_data(base_dir)

    # Initialize the vector database and vector store
    vector_store, embed_model = await create_vector_database(markdown_path, session_id)
    vector_store = Chroma(
        embedding_function=embed_model,
        persist_directory=f"./chat_sessions/{session_id}/chroma/chroma_db",
        collection_name="rag"
    )
    retrieved_context = vector_store.as_retriever(search_kwargs={'k': 3})

    chat_model = ChatGroq(
        temperature=temp, model_name=model, api_key=groq_api_key, max_tokens=max_tokens
    )
    memory = ConversationBufferMemory(memory_key='chat_history', return_messages=True, output_key='result')

    prompt_template = PromptTemplate(
        template="""Use the following pieces of information to answer the user's question.
                    Context: {context}
                    Question: {question}
                    Only return the helpful answer below and nothing else.
                    If no relevant answer, return N/A.
                    Helpful answer:""",
        input_variables=['context', 'chat_history', 'question']
    )

    qa_chain = RetrievalQA.from_chain_type(
        llm=chat_model, chain_type="stuff", retriever=retrieved_context,
        memory=memory, return_source_documents=True,
        chain_type_kwargs={"prompt": prompt_template}
    )
    return await asyncio.to_thread(qa_chain.invoke, {"query": query})

# Example usage:
# result = asyncio.run(parse_and_find("/path/to/base_dir", "What is the age of Charles Leclerc?", "gpt-3", "llama_parse_id", 0.7, 150, "groq_api_key"))
