#ss
from client import *
from server import *


def main():
    session_id = "cli-1"
    svc = ChatService()
    svc.start_session(session_id)

    print("\n\n====== ChatGPT 4o mini =============" + "=" *160)
    print("= para salir escribe SALIR o QUIT =")
    print("="*196)
    
    try:
        while True:
            question = input("Pregunta lo que quieras: ").strip()
            if question.upper() == "SALIR" or question == "QUIT":
                svc.end_session(session_id)
                break;
            else:
                response = svc.ask(session_id, question, max_output_tokens=100)
                print(response)

    except KeyboardInterrupt:
        svc.end_session(session_id)
        print("Interrumpido" )
main()