# Servidor: es la herramienta que ejecuta las acciones. Puede ejecutarse de forma local o remoto. 
import asyncio
from openai import OpenAI
from dotenv import load_dotenv
import os
from client import *
from typing import Dict, Optional
import time
from log import JsonlLogger

#load env variables
load_dotenv()


class SessionState:
    def __init__(self, model: str): 
        self.model = model
        self.prev_id: Optional[str] = None
        self.created_at = time.time()
        self.turns = 0


class ChatService:
    def __init__(self, default_model: str = "gpt-4o-mini", logger: JsonlLogger | None = None):
        self.sessions: Dict[str, SessionState] = {}
        self.logger = logger or JsonlLogger()
        #el unico cliente del llm para todo el servicio
        self.llm = OpeniaGPT4ominiClient(model = default_model)

    #ciclo de vida de las sessions
    def start_session(self, session_id: str, *, model: Optional[str] = None):
        if session_id not in self.sessions:
            self.sessions[session_id] = SessionState(model or self.llm.model)
            self.logger.event("system","info", session_id=session_id, info={"msg":"session_started"})

    def reset_session(self, session_id):
        s = self._require(session_id)
        s.prev_id = None
        s.turns = 0
        self.logger.event("system","info", session_id=session_id, info={"msg":"session_reset"})


    def end_session(self, session_id: str):
        if session_id in self.sessions:
            del self.sessions[session_id]
            self.logger.event("system","info", session_id=session_id, info={"msg":"session_ended"})
            

    #interaction
    def ask(self, session_id: str, user_msg: str, max_output_tokens: int = 100) -> str:
        s = self._require(session_id)
        turn = s.turns + 1

        if s.prev_id is None:
            text, rid = self.llm.first_turn(session_id = session_id, user_msg=user_msg, max_output_tokens=max_output_tokens)
        else:
            text, rid = self.llm.next_turn(session_id = session_id, prev_response_id=s.prev_id, user_msg=user_msg, max_output_tokens=max_output_tokens, turn=turn)
        s.prev_id = rid
        s.turns = turn
        return text
    
    #utils
    def _require(self, session_id: str) -> SessionState:
        if session_id not in self.sessions:
            # si no existe, se crea con defaults
            self.start_session(session_id)
        return self.sessions[session_id]
    
    
