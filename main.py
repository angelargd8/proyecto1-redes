from chat_service import ChatService

def main():
    session_id = "cli-1"
    svc = ChatService()

    print("\n\n====== ChatGPT 4o mini =============" + "=" *160)
    print("= para salir escribe SALIR o QUIT =")


    try:
        while True:
            q = input("Pregunta lo que quieras: \n > ").strip()
            print("="*80)
            if q.upper() in ("SALIR", "QUIT", "EXIT"):
                break
            try:
                ans = svc.ask(q)
                print(ans)
            except Exception as e:
                print("Error:", e)

    except KeyboardInterrupt:
        print("Interrumpido" )

main()
