import asyncio
import base64
import datetime
import json
import logging
import os
import pickle
import shutil
import uuid
import aiofiles
import dash
import dash_bootstrap_components as dbc
import dash_loading_spinners as dls
import joblib
import nest_asyncio
import openai
from dash import MATCH, ALL, Input, Output, State, callback_context, dcc, html
from dash.exceptions import PreventUpdate
from groq import Groq
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import UnstructuredMarkdownLoader
from langchain_community.embeddings.fastembed import FastEmbedEmbeddings
from langchain_community.vectorstores import Chroma
from llama_parse import LlamaParse
