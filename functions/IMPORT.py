import os
import json
import uuid
import base64
import shutil
import logging
import asyncio
import datetime
import pickle
import aiofiles
from dash.exceptions import PreventUpdate
from dash import dcc, html, Input, Output, State, ALL, MATCH, callback_context
import dash_bootstrap_components as dbc
import dash_loading_spinners as dls
import dash
import nest_asyncio
import joblib
import openai
from groq import Groq
from llama_parse import LlamaParse
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.embeddings.fastembed import FastEmbedEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_community.document_loaders import UnstructuredMarkdownLoader
from langchain.prompts import PromptTemplate
from langchain.chains import RetrievalQA
from langchain_groq import ChatGroq
