from typing import Optional, List
from intents import Intent, CreateRepoIntent, UpdateReadmeIntent, PushIntent, SetWorkingDirIntent
from mcpClient import create_repo_with_readme_and_commit, commit_readme_in_existing_repo, create_or_push, create_remote_and_push


ALLOWED_DIRS_DEFAULT = [
    r"C:/Users/angel/Projects",
    r"C:/Users/angel/Desktop",
    r"C:/Users/angel/OneDrive/Documentos/.universidad/.2025/s2/redes/proyecto1-redes",
    r"C:/Users/angel/OneDrive/Documentos/.universidad/.2025/s2/redes",
]

def _allowed(path: str, allowed_dirs: List[str]) -> bool:
    import os
    p = os.path.normpath(path)
    for root in allowed_dirs:
        rootn = os.path.normpath(root)
        try:
            if os.path.commonpath([p, rootn]) == rootn:
                return True
        except Exception:
            pass
    return False

def execute_intent(intent: Intent, *, allowed_dirs: Optional[List[str]] = None) -> str:
    allowed_dirs = allowed_dirs or ALLOWED_DIRS_DEFAULT

    if isinstance(intent, CreateRepoIntent):
        if not _allowed(intent.repo_path, allowed_dirs):
            return f"No permitido: {intent.repo_path} está fuera de las direcciones permitidas"
        create_repo_with_readme_and_commit(
            repo_path=intent.repo_path,
            readme_text=intent.readme_text,
            commit_msg=intent.commit_msg,
            allowed_dirs=allowed_dirs,
        )
        return f"Repo creado en {intent.repo_path}, README escrito y commit '{intent.commit_msg}' realizado."

    if isinstance(intent, UpdateReadmeIntent):
        if not _allowed(intent.repo_path, allowed_dirs):
            return f"No permitido: {intent.repo_path} está fuera de allowed_dirs."
        commit_readme_in_existing_repo(
            repo_path=intent.repo_path,
            readme_text=intent.readme_text,
            commit_msg=intent.commit_msg,
            allowed_dirs=allowed_dirs,
        )
        return f"README actualizado en {intent.repo_path} y commit '{intent.commit_msg}' realizado."

    if isinstance(intent, PushIntent):
        if not _allowed(intent.repo_path, allowed_dirs):
            return f"No permitido: {intent.repo_path} está fuera de las direcciones permitidas"
        try:
            create_remote_and_push(
                repo_path=intent.repo_path,
                remote_url= intent.remote_url,   # URL completa https o ssh
                branch= intent.branch,
            )
            
            return f"push realizado a {intent.remote_url} (branch {intent.branch})."
        except Exception as e:
            return (
                "Push falló: " + str(e)
                + "\nSugerencias:"
                + "\n- Si usas HTTPS, ten un PAT (token) listo; Credential Manager lo guardará."
                + "\n- Si prefieres SSH, usa git@github.com:owner/repo.git y agrega tu clave a GitHub."
                + "\n- Asegúrate de que 'gh auth login' está hecho con la cuenta del OWNER del repo."
            )
        

    if isinstance(intent, SetWorkingDirIntent):
        return f"Working dir preferido establecido a: {intent.repo_path}"
    

    return "No pude ejecutar la intención."
