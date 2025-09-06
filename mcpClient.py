from __future__ import annotations
import os, shutil
from typing import Any, Dict, List, Optional
import anyio
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp import ClientSession
import subprocess
#sss
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
        if hasattr(item, "text"): return item.text
    return None

def _first_json(res) -> Optional[Dict[str, Any]]:
    for item in getattr(res, "content", []):
        if hasattr(item, "value"): return item.value
    return None

def _norm_win(p: str) -> str:
    return os.path.normpath(p)

#para validar si es un repo git

def run_git(repo_path: str, *args: str) -> str:
    proc = subprocess.run(["git", "-C", repo_path, *args],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "git failed")
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
    # Si no hay commit inicial crea el branch directamente
    try:
        run_git(repo_path, "checkout", "-B", branch)
    except Exception:
        # Crea el head apuntando a branch
        run_git(repo_path, "symbolic-ref", "HEAD", f"refs/heads/{branch}")

def add_or_update_remote(repo_path: str, name: str, url: str):
    try:
        curr = run_git(repo_path, "remote", "get-url", name)
        if curr != url:
            run_git(repo_path, "remote", "set-url", name, url)
    except Exception:
        run_git(repo_path, "remote", "add", name, url)


# def push_to_github(repo_path: str, remote_url: str, branch: str = "main"):
#     ensure_repo(repo_path)
#     ensure_branch(repo_path, branch)
#     ensure_initial_commit(repo_path)
#     add_or_update_remote(repo_path, "origin", remote_url)
#     print(run_git(repo_path, "push", "-u", "origin", f"HEAD:{branch}"))
#s

def create_remote_if_missing(repo_path: str, remote_slug: str, branch: str = "main", visibility: str = "private"):
    """
    remote_slug: "usuario/nombre-repo" (sin .git)
    Requiere GitHub CLI autenticado: gh auth login
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
        # "--confirm",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"gh repo create falló:\n{proc.stderr.strip()}")
    print(proc.stdout.strip())


def create_or_push(repo_path: str, remote_slug: str, branch: str = "main", prefer_ssh: bool = False):
    """
    remote_slug: "usuario/nombre-repo"
    Si el repo remoto no existe, lo crea con gh. Luego hace push HEAD:branch.
    """
    ensure_repo(repo_path)
    ensure_branch(repo_path, branch)
    ensure_initial_commit(repo_path)

    # URL remota 
    remote_url = (
        f"git@github.com:{remote_slug}.git" if prefer_ssh
        else f"https://github.com/{remote_slug}.git"
    )
    add_or_update_remote(repo_path, "origin", remote_url)

    # Crea remoto si no existe 
    try:
        run_git(repo_path, "ls-remote", "--exit-code", "origin")
    except Exception:
        create_remote_if_missing(repo_path, remote_slug, branch=branch, visibility="private")

    # push final
    print(run_git(repo_path, "push", "-u", "origin", f"HEAD:{branch}"))

def has_commits(repo_path: str) -> bool:
    try:
        out = run_git(repo_path, "rev-list", "--count", "HEAD")
        return out.strip() != "0"
    except Exception:
        return False

def ensure_initial_commit(repo_path: str):
    if not has_commits(repo_path):
        # commit vacío si no hay nada que agregar
        run_git(repo_path, "commit", "--allow-empty", "-m", "chore: initial commit")


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
        existing   = [d for d in normalized if os.path.isdir(d)]
        if not existing:
            raise RuntimeError(f"Ningún allowed_dir existe. Revisar: {normalized}")

        # Filesystem por npx 
        if filesystem_args is None:
            filesystem_args = ["-y", "@modelcontextprotocol/server-filesystem", *existing]
        self.fs_params = StdioServerParameters(command=filesystem_cmd, args=filesystem_args, cwd=cwd)

        # Git: primero global, si no, npx
        if git_args is None:
            git_args = ["-y", "@cyanheads/git-mcp-server"]
        if GIT_BIN:
            self.git_params = StdioServerParameters(command=GIT_BIN, args=[], cwd=cwd)
        else:
            self.git_params = StdioServerParameters(command=git_cmd, args=git_args, cwd=cwd)

        # Handles de context manager y streams
        self._fs_cm = None
        self._git_cm = None
        self._fs_streams = None  # tuple(read, write)
        self._git_streams = None  # tuple(read, write)

        self.fs: Optional[ClientSession] = None
        self.git: Optional[ClientSession] = None
        self.logger = logger

        # Logs
        self._fs_errlog_fp = None
        self._git_errlog_fp = None

    async def __aenter__(self) -> "AsyncMCPClient":
        # Abrir logs
        self._fs_errlog_fp  = open("filesystem.mcp.log", "ab")
        self._git_errlog_fp = open("git.mcp.log", "ab")

        # --- Filesystem ---
        try:
            # guardar el context manager para poder llamar __aexit__ después
            self._fs_cm = stdio_client(self.fs_params, errlog=self._fs_errlog_fp)
            self._fs_streams = await self._fs_cm.__aenter__()  # (read, write)
            self.fs = await ClientSession(*self._fs_streams).__aenter__()
            await self.fs.initialize()
            
        # esto es mucho texto, pero por alguna razon no me estaba funcionando, entonces por eso mucha validacion
        except Exception as e:
            try:
                if self.fs:
                    await self.fs.__aexit__(type(e), e, e.__traceback__)
            finally:
                self.fs = None
            try:
                if self._fs_cm:
                    await self._fs_cm.__aexit__(type(e), e, e.__traceback__)
            finally:
                self._fs_cm = None
            if self._fs_errlog_fp: self._fs_errlog_fp.close(); self._fs_errlog_fp = None
            if self._git_errlog_fp: self._git_errlog_fp.close(); self._git_errlog_fp = None
            raise RuntimeError(
                "No se pudo iniciar el servidor MCP de Filesystem. "
                "Revisa filesystem.mcp.log y prueba en consola: "
                "`npx -y @modelcontextprotocol/server-filesystem <allowed_dirs>`"
            ) from e

        # Git 
        try:
            if GIT_BIN:
                self._git_cm = stdio_client(
                    StdioServerParameters(command=GIT_BIN, args=[], cwd=self.git_params.cwd),
                    errlog=self._git_errlog_fp
                )
                self._git_streams = await self._git_cm.__aenter__()
            else:
                raise RuntimeError("skip to npx")
        except Exception:
            try:
                self._git_cm = stdio_client(
                    StdioServerParameters(command=NPX, args=["-y", "@cyanheads/git-mcp-server"], cwd=self.git_params.cwd),
                    errlog=self._git_errlog_fp
                )
                self._git_streams = await self._git_cm.__aenter__()
            except Exception as e:
                try:
                    if self.fs:
                        await self.fs.__aexit__(type(e), e, e.__traceback__)
                finally:
                    self.fs = None
                try:
                    if self._fs_cm:
                        await self._fs_cm.__aexit__(type(e), e, e.__traceback__)
                finally:
                    self._fs_cm = None
                if self._fs_errlog_fp: self._fs_errlog_fp.close(); self._fs_errlog_fp = None
                if self._git_errlog_fp: self._git_errlog_fp.close(); self._git_errlog_fp = None
                raise RuntimeError(
                    "No se pudo iniciar el servidor MCP de Git (no abrió proceso). "
                    "Revisa git.mcp.log y prueba `npx -y @cyanheads/git-mcp-server`."
                ) from e

        
        try:
            self.git = await ClientSession(*self._git_streams).__aenter__()
            await self.git.initialize()
        except Exception as e:
            # Cerrar Git 
            try:
                if self.git:
                    await self.git.__aexit__(type(e), e, e.__traceback__)
            finally:
                self.git = None
            try:
                if self._git_cm:
                    await self._git_cm.__aexit__(type(e), e, e.__traceback__)
            finally:
                self._git_cm = None
            # Cerrar FS limpio
            try:
                if self.fs:
                    await self.fs.__aexit__(type(e), e, e.__traceback__)
            finally:
                self.fs = None
            try:
                if self._fs_cm:
                    await self._fs_cm.__aexit__(type(e), e, e.__traceback__)
            finally:
                self._fs_cm = None
            if self._fs_errlog_fp: self._fs_errlog_fp.close(); self._fs_errlog_fp = None
            if self._git_errlog_fp: self._git_errlog_fp.close(); self._git_errlog_fp = None
            raise RuntimeError(
                "No se pudo inicializar la sesión MCP de Git. Revisa git.mcp.log "
                "y confirma `git --version` y `npx -y @cyanheads/git-mcp-server`."
            ) from e

        return self

    async def __aexit__(self, exc_type, exc, tb):
        # Git primero
        try:
            if self.git:
                await self.git.__aexit__(exc_type, exc, tb)
        finally:
            self.git = None
            if self._git_cm:
                await self._git_cm.__aexit__(exc_type, exc, tb)
                self._git_cm = None

        # FS después
        try:
            if self.fs:
                await self.fs.__aexit__(exc_type, exc, tb)
        finally:
            self.fs = None
            if self._fs_cm:
                await self._fs_cm.__aexit__(exc_type, exc, tb)
                self._fs_cm = None

        # Cerrar logs
        if self._fs_errlog_fp: self._fs_errlog_fp.close(); self._fs_errlog_fp = None
        if self._git_errlog_fp: self._git_errlog_fp.close(); self._git_errlog_fp = None

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
        return await self._call_fs_candidates(["create_directory", "filesystem:create_directory"], {"path": path})

    async def fs_write_file(self, path: str, content: str):
        return await self._call_fs_candidates(["write_file", "filesystem:write_file"], {"path": path, "content": content})

    async def fs_read_text_file(self, path: str) -> str:
        res = await self._call_fs_candidates(["read_text_file", "read_file", "filesystem:read_text_file", "filesystem:read_file"], {"path": path})
        return _first_text(res) or ""

    async def fs_list_directory(self, path: str):
        res = await self._call_fs_candidates(["list_directory", "filesystem:list_directory"], {"path": path})
        return _first_json(res) or {}

    async def git_set_workdir(self, path: str):
        res = await self.git.call_tool("git_set_working_dir", {"path": path})
        return _first_text(res) or _first_json(res) or ""

    async def git_init(self):
        res = await self.git.call_tool("git_init", {})
        return _first_text(res) or ""

    async def git_add(self, paths: List[str]):
        res = await self.git.call_tool("git_add", {"paths": paths})
        return _first_text(res) or ""

    async def git_commit(self, message: str):
        res = await self.git.call_tool("git_commit", {"message": message})
        return _first_text(res) or ""

    async def git_status(self) -> str:
        res = await self.git.call_tool("git_status", {})
        return _first_text(res) or _first_json(res) or ""

    async def git_log(self, limit: int = 5):
        res = await self.git.call_tool("git_log", {"limit": limit})
        return _first_text(res) or _first_json(res) or ""

def create_repo_with_readme_and_commit(repo_path: str, readme_text: str, commit_msg: str, *, allowed_dirs: Optional[List[str]] = None) -> None:
    if allowed_dirs is None:
        allowed_dirs = [
            r"C:/Users/angel/Projects",
            r"C:/Users/angel/Desktop",
            r"C:/Users/angel/OneDrive/Documentos/.universidad/.2025/s2/redes/proyecto1-redes",
            r"C:/Users/angel/OneDrive/Documentos/.universidad/.2025/s2/redes",
        ]
    async def _run():
        async with AsyncMCPClient(allowed_dirs=allowed_dirs) as mcp:
            # crea carpeta y README por  MCP con fallback
            try:
                await mcp.fs_create_directory(repo_path)
                await mcp.fs_write_file(f"{repo_path}/README.md", readme_text)
            except Exception:
                os.makedirs(repo_path, exist_ok=True)
                with open(os.path.join(repo_path, "README.md"), "w", encoding="utf-8") as f:
                    f.write(readme_text)

            # init repo y rama
            ensure_repo(repo_path)
            ensure_branch(repo_path, "main")

            # commit del README MCP con fallback
            try:
                await mcp.git_set_workdir(repo_path)
                await mcp.git_add(["README.md"])
                await mcp.git_commit(commit_msg)
            except Exception:
                run_git(repo_path, "add", "README.md")
                run_git(repo_path, "commit", "-m", commit_msg)

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
    - Sin 'git status' temprano (evita warning de working dir)
    - Rutas absolutas para git_add
    - Reintento único de git_set_workdir
    """
    import os

    if allowed_dirs is None:
        allowed_dirs = [
            r"C:/Users/angel/Projects",
            r"C:/Users/angel/Desktop",
            r"C:/Users/angel/OneDrive/Documentos/.universidad/.2025/s2/redes/proyecto1-redes",
            r"C:/Users/angel/OneDrive/Documentos/.universidad/.2025/s2/redes/",

        ]

    readme_abs = os.path.normpath(os.path.join(repo_path, "README.md"))
    git_dir = os.path.normpath(os.path.join(repo_path, ".git"))

    async def _run():
        async with AsyncMCPClient(allowed_dirs=allowed_dirs, cwd=os.getcwd()) as mcp:
            try:
                _ = await mcp.fs_list_directory(git_dir)  # lanzará si no existe
            except Exception as e:
                raise RuntimeError(
                    f"'{repo_path}' no parece un repo Git inicializado (no existe {git_dir}). "
                    "Ejecuta `git init` o usa /repo para inicializar."
                ) from e

            try:
                await mcp.git_set_workdir(repo_path)
            except Exception:
                await anyio.sleep(0.05)
                await mcp.git_set_workdir(repo_path)

            await mcp.fs_write_file(readme_abs, readme_text)

            await mcp.git_add([readme_abs])

            await mcp.git_commit(commit_msg)

            try:
                print(await mcp.git_log(limit=1))
            except Exception:
                
                pass

    anyio.run(_run)
