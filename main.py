
from client import *
from server import *

while True:
    chatgpt4mini = OpeniaGPT4ominiClient()
    print("\n\n====== ChatGPT 4o mini =============" + "=" *160)
    print("= para salir escribe SALIR o QUIT =")
    print("="*196)

    question = input("Pregunta lo que quieras: ")
    if question.upper() == "SALIR" or question == "QUIT":
        break;
    else:
        response = chatgpt4mini.send_message(question )
        print(response)
