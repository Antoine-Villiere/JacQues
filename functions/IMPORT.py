# Standard library imports
import os
import json
import uuid
import base64
import shutil
import logging
import asyncio
import datetime
import pickle

# Third-party imports
import aiofiles
import aiohttp
import urllib
import nest_asyncio
import joblib
import openai
from bs4 import BeautifulSoup
from groq import Groq
from llama_parse import LlamaParse

# Dash-related imports
import dash
import dash_bootstrap_components as dbc
import dash_loading_spinners as dls
from dash import dcc, html, Input, Output, State, ALL, MATCH, callback_context
from dash.exceptions import PreventUpdate

# Langchain-related imports
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.prompts import PromptTemplate
from langchain.chains import RetrievalQA
from langchain.memory import ConversationBufferMemory
from langchain_groq import ChatGroq
from langchain_community.embeddings.fastembed import FastEmbedEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_community.document_loaders import UnstructuredMarkdownLoader