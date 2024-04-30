from IMPORT import *
from langchain.chains import RetrievalQA
from langchain.memory import ConversationBufferMemory

nest_asyncio.apply()

# Load environment variables
LLAMAPARSE_API_KEY = os.getenv('LLAMAPARSE_API_KEY', 'llx-KsMowITWRhVKq1uVChXVvDIxfg8chXIakXEtEKLdKzhqhGvZ')
GROQ_API_KEY = os.getenv('GROQ_API_KEY', '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')


# Helper Functions
async def load_or_parse_data(file_paths):
    parsed_data = []
    for file_path in file_paths:
        data_file = f"./data/data_parse/parsed_data_{os.path.basename(file_path)}.pkl"
        os.makedirs("./data/data_parse", exist_ok=True)

        if os.path.exists(data_file):
            parsed_data.append(joblib.load(data_file))
        else:
            parsing_instruction = ("The provided document contains many tables. extract all the documnet, including "
                                   "table and best keep the same format as the original document.")
            parser = LlamaParse(api_key=LLAMAPARSE_API_KEY, result_type="markdown",
                                parsing_instruction=parsing_instruction, max_timeout=5000)
            data = await asyncio.to_thread(parser.load_data, file_path)
            joblib.dump(data, data_file)
            parsed_data.append(data)
    return parsed_data


async def create_vector_database(file_paths):
    documents = await load_or_parse_data(file_paths)
    markdown_path = './data/data_parse/output.md'
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
    vector_store = Chroma.from_documents(documents=chunks, embedding=embed_model, persist_directory="./chroma/chroma_db",
                                         collection_name="rag")
    return vector_store, embed_model


# Main Function to Run Everything
async def main(file_paths, model="mixtral-8x7b-32768", api_key=GROQ_API_KEY):
    chat_model = ChatGroq(temperature=0, model_name=model, api_key=api_key)
    memory = ConversationBufferMemory(memory_key='chat_history', return_messages=True, output_key='result')
    vector_store, embed_model = await create_vector_database(file_paths)
    vector_store = Chroma(embedding_function=embed_model, persist_directory="./chroma/chroma_db", collection_name="rag")
    retriever = vector_store.as_retriever(search_kwargs={'k': 3})
    prompt_template = PromptTemplate(template="""Use the following pieces of information to answer the user's question. 
                                                Context: {context} 

                                                Question: {question}
                                                Only return the helpful answer below and nothing else.
                                                Helpful answer:""",
                                     input_variables=['context', 'chat_history', 'question'])
    qa_chain = RetrievalQA.from_chain_type(llm=chat_model, chain_type="stuff", retriever=retriever, memory=memory,
                                           return_source_documents=True, chain_type_kwargs={"prompt": prompt_template})
    response = await asyncio.to_thread(qa_chain.invoke, {"query": "what was Reims Campaign and Black Monday?"})