# Cliente: es el componente que mantiene la conexión con el servidor, y obtiene la información sobre como utilizarlo. 
import asyncio
from openai import OpenAI
from dotenv import load_dotenv
import os

#load env variabless
load_dotenv()

class OpeniaGPT4ominiClient:
    def __init__(self, model: str = "gpt-4o-mini"):
        self.api_key = os.getenv('OPENIA_API_KEY')
        if not self.api_key:
            raise RuntimeError("Falta OPENAI_API_KEY en el entorno")
        self.client = OpenAI(
        api_key=self.api_key
        )
        
        self.model = model

    def send_message(self, message,  max_output_tokens = 500, store=True):
        try:
            response = self.client.responses.create(
            model=self.model,
            input=message,
            max_output_tokens=max_output_tokens,
            store=store,
            )
            return response.output_text
        
        except Exception as e: 
            print("error: ", str(e))
    


chatgpt4mini = OpeniaGPT4ominiClient()
print("====== ChatGPT 4o mini =============")
question = input("Pregunta lo que quieras: ")
response = chatgpt4mini.send_message(question )
print(response)
