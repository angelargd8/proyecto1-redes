from ChatTool import ToolCallingChatService

def main():
    session_id = "cli-1"
    svc = ToolCallingChatService(model="gpt-4o-mini")

    print("\n\n====== ChatGPT 4o mini =============" + "=" *160)
    print("= para salir escribe SALIR o QUIT =")


    try:
        while True:
            q = input("Pregunta lo que quieras: ").strip()
            print("="*80)
            if q.upper() in ("SALIR", "QUIT", "EXIT"):
                break
            try:
                ans = svc.ask(session_id, q, max_output_tokens=900)
                print(ans)
            except Exception as e:
                print("Error:", e)

    except KeyboardInterrupt:
        svc.end_session(session_id)
        print("Interrumpido" )

main()
