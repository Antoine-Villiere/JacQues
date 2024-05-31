import os
import joblib
import asyncio
from llama_parse import LlamaParse
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.embeddings.fastembed import FastEmbedEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_community.document_loaders import UnstructuredMarkdownLoader
from langchain.prompts import PromptTemplate
from langchain.chains import RetrievalQA
from langchain_groq import ChatGroq
import nest_asyncio
import dash
from dash import dcc, html, Input, Output, State, ALL, MATCH
import dash_bootstrap_components as dbc
import openai
import json
import os
import uuid
from dash.exceptions import PreventUpdate
from dash import callback_context
import datetime
import json
from groq import Groq
import asyncio
import base64
import shutil
import dash_loading_spinners as dls
import aiofiles
import logging