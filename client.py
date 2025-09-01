# Cliente: es el componente que mantiene la conexión con el servidor, y obtiene la información sobre como utilizarlo. 
import asyncio
from openai import OpenAI
from dotenv import load_dotenv
import os

#load env variables
load_dotenv()

class OpeniaGPT4ominiClient:
    def __init__(self, model: str = "gpt-4o-mini"):
        self.api_key = os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            raise RuntimeError("Falta OPENAI_API_KEY en el entorno")
        self.client = OpenAI(
        api_key=self.api_key
        )
        
        self.model = model
        self.prev_id = None

    def first_turn(self, user_msg: str, max_output_tokens: int = 100 ) ->str:

        response = self.client.responses.create(
            model=self.model,
            input=user_msg,
            max_output_tokens=max_output_tokens,
            store=True,
            )
        # self.prev_id = response.id
        return response.output_text, response.id
    
    def next_turn(self, prev_response_id: str, user_msg: str, max_output_tokens : int = 100) ->str:
        response = self.client.responses.create(
            model=self.model,
            input=user_msg,
            previous_response_id = prev_response_id,
            max_output_tokens=max_output_tokens,
            store=True,
            )
        # self.prev_id = response.id
        return response.output_text, response.id
    


