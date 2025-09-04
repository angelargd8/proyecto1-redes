#sssssa
from client import *
from server import *
from mcpClient import commit_readme_in_existing_repo, create_repo_with_readme_and_commit
import traceback

def main():
    #s
    session_id = "cli-1"
    svc = ChatService()
    svc.start_session(session_id)

    print("\n\n====== ChatGPT 4o mini =============" + "=" *160)
    print("= para salir escribe SALIR o QUIT =")
    print("Comandos:")
    print("  /repo <ruta> | <texto readme> | <mensaje commit>      # crea repo nuevo + README + commit")
    print("  /readme <ruta_repo> | <texto readme> | <mensaje>      # SOLO actualiza/crea README y commit en repo EXISTENTE\n")

    print("="*196)

    try:
        while True:
            question = input("Pregunta lo que quieras: ").strip()
            if question.upper() == "SALIR" or question == "QUIT":
                svc.end_session(session_id)
                break;
            
            elif question.startswith("/readme "):
                try:
                    _, rest = question.split("/readme ", 1)
                    parts = [p.strip() for p in rest.split("|")]
                    repo_path  = parts[0]
                    readme_txt = parts[1] if len(parts) > 1 else "# README\n"
                    commit_msg = parts[2] if len(parts) > 2 else "docs: update README"

                    commit_readme_in_existing_repo(
                        repo_path=repo_path,
                        readme_text=readme_txt,
                        commit_msg=commit_msg,
                        allowed_dirs=[r"C:/Users/angel/Projects",
                                    r"C:/Users/angel/Desktop",
                                    r"C:/Users/angel/OneDrive/Documentos/.universidad/.2025/s2/redes/proyecto1-redes",
                                    r"C:/Users/angel/OneDrive/Documentos/.universidad/.2025/s2/redes/proyecto1-redes/mcp-demo",

        
                                ],
                    )

                    print(f"README actualizado y commit hecho en {repo_path}")
                    
                except Exception as e:
                    print(f"Error al crear el repositorio: {e}")
                    print("error en el /readme", traceback.format_exc()) #
                continue

            elif question.startswith("/repo "):
                try:
                    _, rest = question.split("/repo ", 1)
                    parts = [p.strip() for p in rest.split("|")]
                    repo_path  = parts[0]
                    readme_txt = parts[1] if len(parts) > 1 else "# README\n"
                    commit_msg = parts[2] if len(parts) > 2 else "chore: init"

                    create_repo_with_readme_and_commit(
                        repo_path=repo_path,
                        readme_text=readme_txt,
                        commit_msg=commit_msg,
                        allowed_dirs=[
                            r"C:/Users/angel/Projects",
                            r"C:/Users/angel/Desktop",
                            r"C:/Users/angel/OneDrive/Documentos/.universidad/.2025/s2/redes/proyecto1-redes",
                            r"C:/Users/angel/OneDrive/Documentos/.universidad/.2025/s2/redes",

                        ],
                    )
                    print(f"Repositorio creado en {repo_path} con README y commit.")
                except Exception as e:
                    print(f"Error en /repo: {e}")
                continue

            else:
                response = svc.ask(session_id, question, max_output_tokens=100)
                print(response)

    except KeyboardInterrupt:
        svc.end_session(session_id)
        print("Interrumpido" )
main()