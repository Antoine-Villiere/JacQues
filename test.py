from functions.web_scraper import process_query
from functions.IMPORT import asyncio

query = "$Latest news of Donald Trump$"
brave_id = "BSA6vLQFcC_DmOqaTk4Nm8jLF1sqTxe"

retreiver = asyncio.run(process_query(query, brave_id))
print(retreiver)
