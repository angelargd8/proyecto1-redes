# Cliente: es el componente que mantiene la conexión con el servidor, y obtiene la información sobre como utilizarlo. 
from openai import OpenAI
from dotenv import load_dotenv
import os, time
from log import JsonlLogger
import anyio
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp import ClientSession

#load env variables
load_dotenv()

class OpeniaGPT4ominiClient:
    def __init__(self, model: str = "gpt-4o-mini", logger: JsonlLogger = None):
        self.api_key = os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            raise RuntimeError("Falta OPENAI_API_KEY en el entorno")
        self.client = OpenAI(
        api_key=self.api_key
        )
        
        self.model = model
        self.prev_id = None
        self.logger = logger or JsonlLogger()

    def first_turn(self, session_id: str, user_msg: str, max_output_tokens: int = 500 ) ->str:
        t0 = time.perf_counter()
        self.logger.event("llm","request", session_id=session_id, turn=1,
                          request={"model": self.model, "op": "first_turn", "max_tokens": max_output_tokens,
                                   "text": user_msg})

        response = self.client.responses.create(
            model=self.model,
            input=user_msg,
            max_output_tokens=max_output_tokens,
            store=True,
            )
        
        dt_ms = int((time.perf_counter()-t0)*1000)
        usage = getattr(response, "usage", None)
        self.logger.event("llm","response", session_id=session_id, turn=1,
                          response={"id": response.id, "duration_ms": dt_ms,
                                    "text": response.output_text, "usage": usage})

        return response.output_text, response.id

    def next_turn(self, session_id: str, prev_response_id: str, user_msg: str, max_output_tokens : int = 100, turn: int = 2) ->str:
        t0 = time.perf_counter()
        self.logger.event("llm","request", session_id=session_id, turn=turn,
                          request={"model": self.model, "op": "next_turn",
                                   "previous_response_id": prev_response_id,
                                   "max_tokens": max_output_tokens, "text": user_msg})

        response = self.client.responses.create(
            model=self.model,
            input=user_msg,
            previous_response_id = prev_response_id,
            max_output_tokens=max_output_tokens,
            store=True,
            )
        
        dt_ms = int((time.perf_counter()-t0)*1000)
        usage = getattr(response, "usage", None)
        self.logger.event("llm","response", session_id=session_id, turn=turn,
                          response={"id": response.id, "duration_ms": dt_ms,
                                    "text": response.output_text, "usage": usage})

        return response.output_text, response.id
    
    async def list_mcp_tools(self):
        fs_params = StdioServerParameters(
            command="npx",
            args=[
                "-y", "@modelcontextprotocol/server-filesystem",
                r"C:\Users\angel\Projects",
                r"C:\Users\angel\Desktop",
                r"C:\Users\angel\OneDrive\Documentos\.universidad\.2025\s2\redes\proyecto1-redes",
            ],
        )
        git_params = StdioServerParameters(
            command="npx",
            args=["-y", "@cyanheads/git-mcp-server"],
        )

        lines = []
        async with stdio_client(fs_params) as (r, w):
            async with ClientSession(r, w) as sess:
                await sess.initialize()
                res = await sess.list_tools()
                lines += [f"- {t.name}: {t.description}" for t in res.tools]

        async with stdio_client(git_params) as (r, w):
            async with ClientSession(r, w) as sess:
                await sess.initialize()
                res = await sess.list_tools()
                lines += [f"- {t.name}: {t.description}" for t in res.tools]

        return "\n".join(lines)

    def list_mcp_tools_sync(self):
        return anyio.run(self.list_mcp_tools)
