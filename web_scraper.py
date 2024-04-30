from IMPORT import *
import aiohttp
from bs4 import BeautifulSoup

async def fetch_page_content(session, url, timeout=800):
    try:
        async with session.get(url, timeout=timeout) as response:
            response.raise_for_status()
            return await response.text()
    except aiohttp.ClientResponseError:
        print(f"Failed to fetch {url}. Status: {response.status}")
        return None
    except asyncio.TimeoutError:
        print(f"Timeout while fetching {url}")
        return None


async def clean_and_extract_content(html):
    soup = BeautifulSoup(html, 'html.parser')
    for unwanted in soup(["script", "style", "head", "nav", "footer", "iframe", "img"]):
        unwanted.decompose()
    return ' '.join(soup.stripped_strings)


async def fetch_search_results(session, brave_id,query, results_count=3):
    url = f'https://api.search.brave.com/res/v1/web/search?q={query}&count={results_count}'
    headers = {
        'Accept': 'application/json',
        'Accept-Encoding': 'gzip',
        'X-Subscription-Token': brave_id}
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


async def create_vector_database(contents):
    os.makedirs("./data/data_web", exist_ok=True)
    markdown_path = './data/data_web/output.md'
    with open(markdown_path, 'w', encoding='utf8') as f:
        for content in contents:
            if content['html']:
                f.write(content['html'] + '\n')

    if not os.path.exists(markdown_path):
        return None, None

    loader = UnstructuredMarkdownLoader(markdown_path)
    docs = loader.load()
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=2000, chunk_overlap=100)
    chunks = text_splitter.split_documents(docs)
    embed_model = FastEmbedEmbeddings(model_name="BAAI/bge-base-en-v1.5")
    vector_store = Chroma.from_documents(documents=chunks, embedding=embed_model, persist_directory="./chroma/chroma_db_2",
                                         collection_name="rag")
    return vector_store, embed_model


async def process_query(query,brave_id):
    async with aiohttp.ClientSession() as session:
        print("Fetch sources...")
        sources = await fetch_search_results(session,brave_id, query)
        print("Get information...")
        contents = await fetch_and_process_links(session, sources)
        print("Check coherence...")
        vector_store, embed_model = await create_vector_database(contents)
        vector_store = Chroma(embedding_function=embed_model, persist_directory="./chroma/chroma_db_2", collection_name="rag")
        retriever = vector_store.as_retriever(search_kwargs={'k': 3})
        return retriever
