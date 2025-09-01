# Servidor: es la herramienta que ejecuta las acciones. Puede ejecutarse de forma local o remoto. 
import asyncio
from openai import OpenAI
from dotenv import load_dotenv
import os
from client import *
from typing import Dict, Optional
import time

#load env variabless
load_dotenv()


class SessionState:
    def __init__(self, model: str, system_prop: Optional[str] = None):
        self.model = model
        self.system_prop= system_prop
        self.prev_id: Optional[str] = None
        self.created_at = time.time()
        self.turns = 0


class ChatService:
    def __init__(self, default_model: str = "gpt-4o-mini"):
        self.sessions: Dict[str, SessionState] = {}
        #el unico cliente del llm para todo el servicio
        self.llm = OpeniaGPT4ominiClient(model = default_model)

    #ciclo de vida de las sessions
    def start_session(self, session_id: str, *, model: Optional[str] = None, system_prompt: Optional[str] = None):
        if session_id in self.sessions:
            return
        self.sessions[session_id] = SessionState(model or self.llm.model, system_prompt)

    def reset_session(self, session_id):
        s = self._require(session_id)
        s.prev_id = None
        s.turns = 0

    def end_session(self, session_id: str):
        if session_id in self.sessions:
            del self.sessions[session_id]
            
        