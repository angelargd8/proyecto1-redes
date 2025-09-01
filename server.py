# Servidor: es la herramienta que ejecuta las acciones. Puede ejecutarse de forma local o remoto. 
import asyncio
from openai import OpenAI
from dotenv import load_dotenv
import os
from client import *
from typing import Dict, Optional
import time

#load env variables
load_dotenv()


class SessionState:
    def __init__(self, model: str): 
        self.model = model
        self.prev_id: Optional[str] = None
        self.created_at = time.time()
        self.turns = 0


class ChatService:
    def __init__(self, default_model: str = "gpt-4o-mini"):
        self.sessions: Dict[str, SessionState] = {}
        #el unico cliente del llm para todo el servicio
        self.llm = OpeniaGPT4ominiClient(model = default_model)

    #ciclo de vida de las sessions
    def start_session(self, session_id: str, *, model: Optional[str] = None):
        if session_id not in self.sessions:
            self.sessions[session_id] = SessionState(model or self.llm.model)

    def reset_session(self, session_id):
        s = self._require(session_id)
        s.prev_id = None
        s.turns = 0

    def end_session(self, session_id: str):
        if session_id in self.sessions:
            del self.sessions[session_id]
            

    #interaction
    def ask(self, session_id: str, user_msg: str, max_output_tokens: int = 100) -> str:
        s = self._require(session_id)
        if s.prev_id is None:
            text, rid = self.llm.first_turn(user_msg=user_msg, max_output_tokens=max_output_tokens)
        else:
            text, rid = self.llm.next_turn(prev_response_id=s.prev_id, user_msg=user_msg, max_output_tokens=max_output_tokens)
        s.prev_id = rid
        s.turns += 1
        return text
    
    #utils
    def _require(self, session_id: str) -> SessionState:
        if session_id not in self.sessions:
            # si no existe, se crea con defaultss
            self.start_session(session_id)
        return self.sessions[session_id]
    
        