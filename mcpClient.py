from __future__ import annotations
import os, shutil, subprocess
from typing import Any, Dict, List, Optional
import anyio
from contextlib import AsyncExitStack
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp import ClientSession
import re

#comandos
NPX = os.environ.get("NPX_CMD") or shutil.which("npx") or r"C:\Program Files\nodejs\npx.cmd"
FS_BIN = shutil.which("server-filesystem")
GIT_BIN = shutil.which("git-mcp-server")

def _render_content(res) -> List[Dict[str, Any]]:
    out = []
    for item in getattr(res, "content", []):
        if hasattr(item, "text"):  out.append({"type": "text", "text": item.text})
        elif hasattr(item, "value"): out.append({"type": "json", "value": item.value})
        else: out.append({"type": "repr", "value": repr(item)})
    return out

def _first_text(res) -> Optional[str]:
    for item in getattr(res, "content", []):
        if hasattr(item, "text"):
            return item.text
    return None

def _first_json(res) -> Optional[Dict[str, Any]]:
    for item in getattr(res, "content", []):
        if hasattr(item, "value"):
            return item.value
    return None

def _norm_win(p: str) -> str:
    return os.path.normpath(p)

#  Git helpers 

def run_git(repo_path: str, *args: str) -> str:
    proc = subprocess.run(["git", "-C", repo_path, *args], capture_output=True, text=True)
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        raise RuntimeError(stderr or stdout or "git failed")
    return proc.stdout.strip()

def is_git_repo(repo_path: str) -> bool:
    try:
        run_git(repo_path, "rev-parse", "--git-dir")
        return True
    except Exception:
        return False

def ensure_repo(repo_path: str):
    os.makedirs(repo_path, exist_ok=True)
    if not is_git_repo(repo_path):
        run_git(repo_path, "init")

def current_branch(repo_path: str) -> str:
    try:
        return run_git(repo_path, "rev-parse", "--abbrev-ref", "HEAD")
    except Exception:
        return ""

def ensure_branch(repo_path: str, branch: str = "main"):
    """
    Garantiza que HEAD apunte a la rama dada, incluso si no hay commits.
    """
    try:
        run_git(repo_path, "checkout", "-B", branch)
    except Exception:
        # Sin commits
        run_git(repo_path, "symbolic-ref", "HEAD", f"refs/heads/{branch}")

def add_or_update_remote(repo_path: str, name: str, url: str):
    try:
        curr = run_git(repo_path, "remote", "get-url", name)
        if curr != url:
            run_git(repo_path, "remote", "set-url", name, url)
    except Exception:
        run_git(repo_path, "remote", "add", name, url)

def has_commits(repo_path: str) -> bool:
    try:
        out = run_git(repo_path, "rev-list", "--count", "HEAD")
        return out.strip() != "0"
    except Exception:
        return False

def ensure_initial_commit(repo_path: str):
    if not has_commits(repo_path):
        run_git(repo_path, "commit", "--allow-empty", "-m", "chore: initial commit")

# crear remoto con GitHub CLI (gh)
def create_remote_if_missing(repo_path: str, remote_slug: str, branch: str = "main", visibility: str = "private"):
    """
    remote_slug: "usuario/nombre-repo" (sin .git). 
    Requiere GitHub CLI autenticado: `gh auth login`.
    """
    
    try:
        run_git(repo_path, "ls-remote", "--exit-code", f"https://github.com/{remote_slug}.git")
        return  # ya existe
    except Exception:
        pass

    # crearlo y primer push 
    cmd = [
        "gh", "repo", "create", remote_slug,
        f"--{visibility}",
        "--source", repo_path,
        "--remote", "origin",
        "--push",
        # "--confirm", # al parecer esta deprecado lol 
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"gh repo create falló:\n{proc.stderr.strip()}")
    print(proc.stdout.strip())


def create_or_push(repo_path: str, remote_slug: str, branch: str = "main", prefer_ssh: bool = False):
    """
    remote_slug: "usuario/nombre-repo"
    Si el remoto no existe, lo crea con gh; luego push a HEAD:branch.
    """
    ensure_repo(repo_path)
    ensure_branch(repo_path, branch)
    ensure_initial_commit(repo_path)

    # URL remota
    remote_url = (f"git@github.com:{remote_slug}.git" if prefer_ssh
                  else f"https://github.com/{remote_slug}.git")
    add_or_update_remote(repo_path, "origin", remote_url)

    # Crea remoto si no existe 
    try:
        run_git(repo_path, "ls-remote", "--exit-code", "origin")
    except Exception:
        create_remote_if_missing(repo_path, remote_slug, branch=branch, visibility="private")

    # push final
    print(run_git(repo_path, "push", "-u", "origin", f"HEAD:{branch}"))

def _clean_remote_url(url: str) -> str:
    return url.strip().rstrip("/")

def github_url_to_slug(remote_url: str) -> Optional[str]:
    """
    Convierte https://github.com/owner/repo(.git) o git@github.com:owner/repo(.git)
    en 'owner/repo'. Devuelve None si no es GitHub.
    """
    url = _clean_remote_url(remote_url)
    m = re.match(r'^https://github\.com/([^/]+/[^/]+?)(?:\.git)?$', url, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.match(r'^git@github\.com:([^/]+/[^/]+?)(?:\.git)?$', url, re.IGNORECASE)
    if m:
        return m.group(1)
    return None

def ensure_remote_repo_exists(remote_slug: str) -> None:
    """
    Crea el repo en GitHub si no existe. Requiere:
      - GitHub CLI instalado (gh)
      - 'gh auth login' hecho en la cuenta 'owner' del slug.
    No toca 'origin'. Solo crea el repo vacío.
    """
    # verificar si existe
    p = subprocess.run(["gh", "repo", "view", remote_slug], capture_output=True, text=True)
    if p.returncode == 0:
        return  # ya existe

    # Crearlo privado por predeterminado
    p2 = subprocess.run(["gh", "repo", "create", remote_slug, "--private", "--confirm"],
                        capture_output=True, text=True)
    if p2.returncode != 0:
        raise RuntimeError(f"gh repo create falló:\n{p2.stderr.strip()}")

def create_remote_and_push(repo_path: str, remote_url: str, branch: str = "main"):
    """
    Flujo robusto:
      1) Garantiza repo local + branch + commit inicial
      2) Configura 'origin' = remote_url
      3) Intenta push; si remoto no existe y es GitHub, lo crea y reintenta.
    """
    remote_url = _clean_remote_url(remote_url)
    ensure_repo(repo_path)
    ensure_branch(repo_path, branch)
    ensure_initial_commit(repo_path)

    # setear/actualizar origin a la URL pedida
    add_or_update_remote(repo_path, "origin", remote_url)

    try:
        print(run_git(repo_path, "push", "-u", "origin", branch))
        return
    except RuntimeError as e:
        msg = str(e)
        # Si el repo remoto NO existe y es GitHub crearlo y reintentar
        if "Repository not found" in msg or "not found" in msg:
            slug = github_url_to_slug(remote_url)
            if not slug:
                # No es GitHub o URL no reconocida
                raise RuntimeError(
                    "El remoto no existe y no es una URL de GitHub reconocible. "
                    "Crea el repo manualmente o usa un URL de GitHub válido."
                ) from e
            # crear remoto en GitHub 
            ensure_remote_repo_exists(slug)
            # reintentar push
            print(run_git(repo_path, "push", "-u", "origin", branch))
            return
        raise
    
    
# Wrapper
def push_to_github(repo_path: str, remote_url: str, branch: str = "main"):
    """
    Mantiene compatibilidad con main: agrega/actualiza origin y hace push -u origin <branch>.
    """
    ensure_repo(repo_path)
    ensure_branch(repo_path, branch)
    ensure_initial_commit(repo_path)
    add_or_update_remote(repo_path, "origin", remote_url)
    print(run_git(repo_path, "push", "-u", "origin", branch))

# Async MCP Client
class AsyncMCPClient:
    def __init__(
        self,
        allowed_dirs: List[str],
        *,
        filesystem_cmd: str = NPX,
        filesystem_args: Optional[List[str]] = None,
        git_cmd: str = NPX,
        git_args: Optional[List[str]] = None,
        logger: Any = None,
        cwd: Optional[str] = None,
    ):
        # Normalizar y filtrar dirs existentes
        normalized = [_norm_win(d) for d in allowed_dirs if isinstance(d, str)]
        existing = [d for d in normalized if os.path.isdir(d)]
        if not existing:
            raise RuntimeError(f"Ningún allowed_dir existe. Revisar: {normalized}")

        # Filesystem por npx 
        if filesystem_args is None:
            filesystem_args = ["-y", "@modelcontextprotocol/server-filesystem", *existing]
        self.fs_params = StdioServerParameters(command=filesystem_cmd, args=filesystem_args, cwd=cwd)

        # Git prefiere binario, si no, npx
        if git_args is None:
            git_args = ["-y", "@cyanheads/git-mcp-server"]
        if GIT_BIN:
            self.git_params = StdioServerParameters(command=GIT_BIN, args=[], cwd=cwd)
        else:
            self.git_params = StdioServerParameters(command=git_cmd, args=git_args, cwd=cwd)

        self.logger = logger

        # Handles de context manager y streams
        self._stack: Optional[AsyncExitStack] = None
        self._fs_streams = None
        self._git_streams = None
        self.fs: Optional[ClientSession] = None
        self.git: Optional[ClientSession] = None

        # Logs
        self._fs_errlog_fp = None
        self._git_errlog_fp = None

    async def __aenter__(self) -> "AsyncMCPClient":
        self._stack = AsyncExitStack()

        # Abrir logs
        self._fs_errlog_fp  = open("filesystem.mcp.log", "ab")
        self._git_errlog_fp = open("git.mcp.log", "ab")

        # Filesystem todo en el mismo stack/task
        fs_cm = stdio_client(self.fs_params, errlog=self._fs_errlog_fp)
        self._fs_streams = await self._stack.enter_async_context(fs_cm)
        self.fs = await self._stack.enter_async_context(ClientSession(*self._fs_streams))
        await self.fs.initialize()

        # Git: intentar params, si falla, caer a npx en el mismo stack
        try:
            git_cm = stdio_client(self.git_params, errlog=self._git_errlog_fp)
            self._git_streams = await self._stack.enter_async_context(git_cm)
        except Exception:
            npx_git_params = StdioServerParameters(
                command=NPX,
                args=["-y", "@cyanheads/git-mcp-server"],
                cwd=self.git_params.cwd
            )
            git_cm = stdio_client(npx_git_params, errlog=self._git_errlog_fp)
            self._git_streams = await self._stack.enter_async_context(git_cm)

        self.git = await self._stack.enter_async_context(ClientSession(*self._git_streams))
        await self.git.initialize()

        return self

    async def __aexit__(self, exc_type, exc, tb):
        try:
            if self._stack:
                await self._stack.aclose()
        finally:
            self._stack = None
            if self._fs_errlog_fp:
                self._fs_errlog_fp.close(); self._fs_errlog_fp = None
            if self._git_errlog_fp:
                self._git_errlog_fp.close(); self._git_errlog_fp = None

    # Wrappers FS/Git
    async def _call_fs_candidates(self, tool_names: List[str], args: Dict[str, Any]):
        last_err = None
        for name in tool_names:
            try:
                res = await self.fs.call_tool(name, args)
                return res
            except Exception as e:
                last_err = e
        raise last_err

    async def fs_create_directory(self, path: str):
        return await self._call_fs_candidates(
            ["create_directory", "filesystem:create_directory"], {"path": path}
        )

    async def fs_write_file(self, path: str, content: str):
        return await self._call_fs_candidates(
            ["write_file", "filesystem:write_file"], {"path": path, "content": content}
        )

    async def fs_read_text_file(self, path: str) -> str:
        res = await self._call_fs_candidates(
            ["read_text_file", "read_file", "filesystem:read_text_file", "filesystem:read_file"],
            {"path": path}
        )
        for item in getattr(res, "content", []):
            if hasattr(item, "text"):
                return item.text
        return ""

    async def fs_list_directory(self, path: str):
        res = await self._call_fs_candidates(
            ["list_directory", "filesystem:list_directory"], {"path": path}
        )
        for item in getattr(res, "content", []):
            if hasattr(item, "value"):
                return item.value
        return {}

    async def git_set_workdir(self, path: str):
        res = await self.git.call_tool("git_set_working_dir", {"path": path})
        for item in getattr(res, "content", []):
            if hasattr(item, "text"):
                return item.text
            if hasattr(item, "value"):
                return item.value
        return ""

    async def git_init(self):
        res = await self.git.call_tool("git_init", {})
        for item in getattr(res, "content", []):
            if hasattr(item, "text"):
                return item.text
        return ""

    async def git_add(self, paths: List[str]):
        res = await self.git.call_tool("git_add", {"paths": paths})
        for item in getattr(res, "content", []):
            if hasattr(item, "text"):
                return item.text
        return ""

    async def git_commit(self, message: str):
        res = await self.git.call_tool("git_commit", {"message": message})
        for item in getattr(res, "content", []):
            if hasattr(item, "text"):
                return item.text
        return ""

    async def git_status(self) -> str:
        res = await self.git.call_tool("git_status", {})
        for item in getattr(res, "content", []):
            if hasattr(item, "text"):
                return item.text
            if hasattr(item, "value"):
                return item.value
        return ""

    async def git_log(self, limit: int = 5):
        res = await self.git.call_tool("git_log", {"limit": limit})
        for item in getattr(res, "content", []):
            if hasattr(item, "text"):
                return item.text
            if hasattr(item, "value"):
                return item.value
        return ""

# Funciones sync que usan el cliente 
def create_repo_with_readme_and_commit(
    repo_path: str,
    readme_text: str,
    commit_msg: str,
    *,
    allowed_dirs: Optional[List[str]] = None
) -> None:
    if allowed_dirs is None:
        allowed_dirs = [
            r"C:/Users/angel/Projects",
            r"C:/Users/angel/Desktop",
            r"C:/Users/angel/OneDrive/Documentos/.universidad/.2025/s2/redes/proyecto1-redes",
            r"C:/Users/angel/OneDrive/Documentos/.universidad/.2025/s2/redes",
        ]

    async def _run():
        async with AsyncMCPClient(allowed_dirs=allowed_dirs) as mcp:
            # Crear carpeta y README mcp con fallback local
            try:
                await mcp.fs_create_directory(repo_path)
                await mcp.fs_write_file(os.path.join(repo_path, "README.md"), readme_text)
            except Exception:
                os.makedirs(repo_path, exist_ok=True)
                with open(os.path.join(repo_path, "README.md"), "w", encoding="utf-8") as f:
                    f.write(readme_text)

            # Inicializar repo/branch
            ensure_repo(repo_path)
            ensure_branch(repo_path, "main")

            # Commit del README
            try:
                await mcp.git_set_workdir(repo_path)
                readme_abs = os.path.join(repo_path, "README.md") 
                await mcp.git_add([readme_abs])
                await mcp.git_commit(commit_msg)
            except Exception:
                run_git(repo_path, "add", os.path.join(repo_path, "README.md"))
                run_git(repo_path, "commit", "-m", commit_msg)

            #  Resumen
            try:
                print(run_git(repo_path, "status", "--short"))
                print(run_git(repo_path, "log", "-1", "--oneline"))
            except Exception:
                pass

    anyio.run(_run)

def commit_readme_in_existing_repo(
    repo_path: str,
    readme_text: str,
    commit_msg: str = "docs: update README",
    *,
    allowed_dirs: Optional[List[str]] = None,
) -> None:
    """
    Actualiza/crea README.md y hace git add+commit en un repo ya inicializado.
    - Verifica respuesta de cada tool MCP; si hay "Error", da excepción.
    - Si MCP falla al escribir, escribe localmente antes del fallback git.
    - Antes de commitear en fallback, verifica si hay cambios.
    """
    import os

    if allowed_dirs is None:
        allowed_dirs = [
            r"C:/Users/angel/Projects",
            r"C:/Users/angel/Desktop",
            r"C:/Users/angel/OneDrive/Documentos/.universidad/.2025/s2/redes/proyecto1-redes",
            r"C:/Users/angel/OneDrive/Documentos/.universidad/.2025/s2/redes/",
        ]

    repo_path = os.path.normpath(repo_path)
    readme_abs = os.path.normpath(os.path.join(repo_path, "README.md"))
    git_dir = os.path.normpath(os.path.join(repo_path, ".git"))

    def _raise_if_error(label: str, out: str | None):
        s = (out or "").strip()
        if s.lower().startswith("error"):
            raise RuntimeError(f"{label} -> {s}")

    async def _run():
        wrote = False
        async with AsyncMCPClient(allowed_dirs=allowed_dirs, cwd=os.getcwd()) as mcp:
            # verificar repo
            try:
                _ = await mcp.fs_list_directory(git_dir)
            except Exception as e:
                raise RuntimeError(
                    f"'{repo_path}' no parece un repo Git inicializado (no existe {git_dir}). "
                    "Ejecuta `git init` o usa /repo para inicializar."
                ) from e

            # Working dir
            msg = await mcp.git_set_workdir(repo_path)
            if not msg or "set" not in msg.lower():
                await anyio.sleep(0.05)
                msg = await mcp.git_set_workdir(repo_path)
            _raise_if_error("git_set_workdir", msg)

            # Escribir README por FS (MCP)
            try:
                await mcp.fs_write_file(readme_abs, readme_text)
                wrote = True
            except Exception as e:
                raise e

            # git add/commit (MCP)
            msg = await mcp.git_add(["README.md"])
            _raise_if_error("git_add", msg)

            msg = await mcp.git_commit(commit_msg)
            _raise_if_error("git_commit", msg)

            try:
                print(await mcp.git_log(limit=1))
            except Exception:
                pass

    try:
        anyio.run(_run)
    except Exception as e_mcp:
        # Fallback 
        os.makedirs(repo_path, exist_ok=True)
        with open(readme_abs, "w", encoding="utf-8", newline="") as f:
            f.write(readme_text)

        # Stage del archivo
        run_git(repo_path, "add", "README.md")

        #Hay algo staged? Si no, salir
        import subprocess as _sp
        chk = _sp.run(
            ["git", "-C", repo_path, "diff", "--cached", "--name-only", "--", "README.md"],
            capture_output=True, text=True
        )
        if chk.stdout.strip() == "":
            # nada nuevo para comitear el  contenido es el mismo
            return

        # Commit
        try:
            run_git(repo_path, "commit", "-m", commit_msg)
        except Exception as ee:
            if "user.name" in str(ee) or "user.email" in str(ee):
                raise RuntimeError(
                    f"Git requiere user.name/email. Ejecuta:\n"
                    f'  git -C "{repo_path}" config user.name "Tu Nombre"\n'
                    f'  git -C "{repo_path}" config user.email "tu@correo"\n'
                    f"y vuelve a intentar."
                ) from ee
            raise