from functions.IMPORT import *
from functions.chat_management import save_info

async def fetch_page_content(session, url, timeout=800):
    try:
        async with session.get(url, timeout=timeout) as response:
            response.raise_for_status()
            return await response.text()
    except aiohttp.ClientResponseError:
        save_info(f"Failed to fetch {url}. Status: {response.status}")
        return None
    except asyncio.TimeoutError:
        save_info(f"Timeout while fetching {url}")
        return None


async def clean_and_extract_content(html):
    soup = BeautifulSoup(html, 'html.parser')
    for unwanted in soup(["script", "style", "head", "nav", "footer", "iframe", "img"]):
        unwanted.decompose()
    return ' '.join(soup.stripped_strings)



async def fetch_search_results(session, brave_id, query, results_count=10):
    url = f'https://api.search.brave.com/res/v1/web/search?q={query}&count={results_count}&country=fr'
    headers = {
        'Accept': 'application/json',
        'Accept-Encoding': 'gzip',
        'X-Subscription-Token': brave_id,
        'X-Loc-Country': 'fr',
        'User-Agent': 'Mozilla/5.0 (Linux; Android 13; Pixel 7 Pro) AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/108.0.0.0 Mobile Safari/537.36'}
    async with session.get(url, headers=headers) as response:
        response.raise_for_status()
        json_response = await response.json()
        return [
            {'title': r['title'], 'link': r['url'], 'snippet': r['description']}
            for r in json_response.get('web', {}).get('results', [])
        ]


async def fetch_and_process_links(session, sources):
    tasks = [fetch_page_content(session, source['link']) for source in sources]
    html_contents = await asyncio.gather(*tasks)
    contents = []
    for html, source in zip(html_contents, sources):
        if html:
            main_content = await clean_and_extract_content(html)
            contents.append({**source, 'html': main_content})
    return contents


async def create_vector_database(contents, session_id):
    os.makedirs(f"./chat_sessions/{session_id}/data_web", exist_ok=True)
    markdown_path = f'./chat_sessions/{session_id}/data_web/output.md'
    with open(markdown_path, 'w', encoding='utf8') as f:
        for content in contents:
            if content['html']:
                f.write(content['html'] + '\n')

    if not os.path.exists(markdown_path):
        return None, None

    loader = UnstructuredMarkdownLoader(markdown_path)
    save_info("Few more steps..")
    docs = loader.load()
    save_info("Few more steps...")
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=2000, chunk_overlap=100)
    save_info("Few more steps.")
    chunks = text_splitter.split_documents(docs)
    save_info("Few more steps..")
    embed_model = FastEmbedEmbeddings(model_name="BAAI/bge-base-en-v1.5")
    save_info("Few more steps...")
    vector_store = Chroma.from_documents(documents=chunks, embedding=embed_model,
                                         persist_directory=f'./chat_sessions/{session_id}/chroma/chroma_db_2',
                                         collection_name="rag")
    save_info("Few more steps.")
    return vector_store, embed_model


async def process_query(query, brave_id, session_id):
    async with aiohttp.ClientSession() as session:
        save_info("Fetch sources...")
        sources = await fetch_search_results(session, brave_id, f'${query}$')
        save_info("Get information...")
        contents = await fetch_and_process_links(session, sources)
        save_info("Check coherence...")
        save_info("Few more steps.")
        vector_store, embed_model = await create_vector_database(contents, session_id)
        vector_store = Chroma(embedding_function=embed_model,
                              persist_directory=f'./chat_sessions/{session_id}/chroma/chroma_db_2',
                              collection_name="rag")
        retriever = vector_store.as_retriever(search_kwargs={'k': 3})
        return retriever
