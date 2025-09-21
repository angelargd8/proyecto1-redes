from __future__ import annotations
import os
import re
import subprocess
from typing import Dict, Any, Sequence, Optional

from mcp_manager import MCPMultiplexer

#  Utilidades Git/CLI 

def _run_git(repo: str, *args: str) -> str:
    p = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or "git failed").strip())
    return (p.stdout or "").strip()

def _try_git(repo: str, *args: str) -> tuple[bool, str]:
    try:
        return True, _run_git(repo, *args)
    except Exception as e:
        return False, str(e)

def _slug_from_github_url(url: str) -> Optional[str]:
    url = url.strip().rstrip("/")
    m = (
        re.match(r"^https://github\.com/([^/]+/[^/]+?)(?:\.git)?$", url, re.I)
        or re.match(r"^git@github\.com:([^/]+/[^/]+?)(?:\.git)?$", url, re.I)
    )
    return m.group(1) if m else None

def _ensure_remote_repo_github(remote_url: str, private: bool = True) -> None:
    slug = _slug_from_github_url(remote_url)
    if not slug:
        return
    v = subprocess.run(["gh", "repo", "view", slug], capture_output=True, text=True)
    if v.returncode == 0:
        return
    args = ["gh", "repo", "create", slug, "--confirm"]
    if private:
        args.insert(3, "--private")
    c = subprocess.run(args, capture_output=True, text=True)
    if c.returncode != 0:
        err = (c.stderr or c.stdout or "").strip()
        raise RuntimeError("gh repo create falló:\n" + err)

#  FS y llamadas MCP 

def _fs_path(p: str) -> str:
    return os.path.normpath(p).replace("\\", "/")

def _call_git(mcp: MCPMultiplexer, tool_names: Sequence[str], args: Dict[str, Any]) -> Dict[str, Any]:
    last = {"error": "no_tool_ran"}
    for name in tool_names:
        out = mcp.call_tool_sync("git", name, args)
        if not isinstance(out, dict):
            return {"value": out}
        if "error" not in out:
            return out
        last = out
    return last

def _call_fs(mcp: MCPMultiplexer, tool_names: Sequence[str], args: Dict[str, Any]) -> Dict[str, Any]:
    last = {"error": "no_tool_ran"}
    a = dict(args)
    if "path" in a and isinstance(a["path"], str):
        a["path"] = _fs_path(a["path"])
    if "dest" in a and isinstance(a["dest"], str):
        a["dest"] = _fs_path(a["dest"])
    for name in tool_names:
        out = mcp.call_tool_sync("fs", name, a)
        if not isinstance(out, dict):
            return {"value": out}
        if "error" not in out:
            return out
        last = out
    return last

#  Helpers 

def _ensure_workdir(mcp: MCPMultiplexer, repo_abs: str) -> None:
    r = _call_git(mcp, ["git_set_working_dir", "git:set_working_dir"], {"path": repo_abs})
    if "error" in r:
        # el CLI seguirá funcionando aunque la tool falle
        pass

def _ensure_git_identity(repo_abs: str) -> None:
    ok, _ = _try_git(repo_abs, "config", "--get", "user.name")
    if not ok:
        _run_git(repo_abs, "config", "user.name", "autobot")
    ok, _ = _try_git(repo_abs, "config", "--get", "user.email")
    if not ok:
        _run_git(repo_abs, "config", "user.email", "autobot@example.com")

def _git_add_all(mcp: MCPMultiplexer, repo_abs: str) -> None:
    # Intenta con MCP 
    tried_mcp = False
    for payload in ({"paths": ["."]}, {"files": ["."]}, {"path": "."}):
        r = _call_git(mcp, ["git_add", "git:add"], payload)
        tried_mcp = True
        if "error" not in r:
            break
    # y si nada sirve, CLI 
    _run_git(repo_abs, "add", "-A")

def _has_head(repo_abs: str) -> bool:
    p = subprocess.run(["git", "-C", repo_abs, "rev-parse", "--verify", "HEAD"],
                       capture_output=True, text=True)
    return p.returncode == 0

def _has_staged(repo_abs: str) -> bool:
    ok, out = _try_git(repo_abs, "diff", "--cached", "--name-only")
    return ok and bool(out.strip())

def _checkout_or_create_branch(mcp: MCPMultiplexer, repo_abs: str, branch: str) -> None:
    r = _call_git(mcp, ["git_checkout", "git:checkout", "git_switch", "git:switch"], {"branchOrPath": branch})
    if "error" in r:
        _run_git(repo_abs, "checkout", "-B", branch)

def _safe_capture(cmd: list[str]) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True)
        return (p.stdout or p.stderr or "").strip()
    except Exception:
        return ""

#  Intents  

def commit_all(
    mcp: MCPMultiplexer,
    repo_path: str,
    message: str,
    *,
    allow_empty_if_no_head: bool = True,
) -> str:
    """Stagea todo y hace commit robusto (MCP + fallback CLI)."""
    repo_abs = os.path.normpath(repo_path)
    _ensure_workdir(mcp, repo_abs)
    _ensure_git_identity(repo_abs)
    _git_add_all(mcp, repo_abs)

    staged = _has_staged(repo_abs)
    has_head = _has_head(repo_abs)

    if not staged and not has_head and allow_empty_if_no_head:
        _run_git(repo_abs, "commit", "--allow-empty", "-m", message)
    elif staged:
        r = _call_git(mcp, ["git_commit", "git:commit"], {"message": message})
        if "error" in r:
            _run_git(repo_abs, "commit", "-m", message)
    # else: nada nuevo que commitear

    head = _safe_capture(["git", "-C", repo_abs, "rev-parse", "--short", "HEAD"])
    log1 = _safe_capture(["git", "-C", repo_abs, "log", "--oneline", "-n", "1"])
    status = _safe_capture(["git", "-C", repo_abs, "status", "--porcelain"])
    return (
        f"Commit listo en {repo_abs}.\n"
        f"HEAD: {head or '(sin commits)'} | último commit: {log1 or '(no hay)'}\n"
        f"Status (porcelain):\n{status or '(limpio)'}"
    )

def set_remote_and_push(
    mcp: MCPMultiplexer,
    repo_path: str,
    remote_url: str,
    *,
    branch: str = "main",
    private_remote: bool = True,
) -> str:
    repo_abs = os.path.normpath(repo_path)
    _ensure_workdir(mcp, repo_abs)

    # Crear repo remoto si falta 
    _ensure_remote_repo_github(remote_url, private=private_remote)

    # Intento MCP y verificación/corrección por CLI
    _call_git(
        mcp,
        ["git_remote", "git:remote", "git_remote_add", "git:remote_add", "git_set_remote"],
        {"name": "origin", "url": remote_url},
    )
    ok, cur = _try_git(repo_abs, "remote", "get-url", "origin")
    if ok:
        if cur != remote_url:
            _run_git(repo_abs, "remote", "set-url", "origin", remote_url)
        remote_msg = "origin configurado (verificado por CLI)."
    else:
        _run_git(repo_abs, "remote", "add", "origin", remote_url)
        remote_msg = "origin agregado (CLI)."

    # Push con upstream (CLI y luego MCP si hiciera falta)
    ok_push, push_out = _try_git(repo_abs, "push", "-u", "origin", branch)
    if not ok_push:
        rpush = _call_git(mcp, ["git_push", "git:push"], {"remote": "origin", "branch": branch, "set_upstream": True})
        if "error" in rpush:
            return (
                f"Remoto configurado pero falló el push.\n"
                f"CLI: {push_out}\nMCP: {rpush}\n"
                "Solución: autentícate en GitHub:\n"
                "  gh auth login\n  gh auth status\n"
                f"Luego: git -C \"{repo_abs}\" push -u origin {branch}"
            )

    ok_ls, _ = _try_git(repo_abs, "ls-remote", "--heads", "origin")
    rem = _safe_capture(["git", "-C", repo_abs, "remote", "-v"])
    br = _safe_capture(["git", "-C", repo_abs, "branch", "-vv"])
    return (
        f"Remoto: {remote_url} → {remote_msg} "
        f"{'Push OK.' if ok_ls else 'Push realizado (verifica auth si falla ls-remote).'}\n"
        f"Remotos:\n{rem}\nRamas:\n{br}"
    )

def _verify_head(repo_abs: str) -> bool:
    p = subprocess.run(["git","-C",repo_abs,"rev-parse","--verify","HEAD"],
                       capture_output=True, text=True)
    return p.returncode == 0

def _commit_cli_force(repo_abs: str, message: str) -> tuple[bool, str]:
    """Hace commit por CLI y devuelve (ok, detalle)."""
    # primero prueba commit normal
    p = subprocess.run(["git","-C",repo_abs,"commit","-m",message],
                       capture_output=True, text=True)
    if p.returncode == 0 and _verify_head(repo_abs):
        return True, (p.stdout or p.stderr or "").strip()

    # si no había nada staged y no existe HEAD, permite vacío
    if not _verify_head(repo_abs):
        p2 = subprocess.run(["git","-C",repo_abs,"commit","--allow-empty","-m",message],
                            capture_output=True, text=True)
        if p2.returncode == 0 and _verify_head(repo_abs):
            return True, (p2.stdout or p2.stderr or "").strip()

    # fallo: devuelve detalle
    det = (p.stdout + p.stderr if p.stdout or p.stderr else "") or "commit failed"
    if not det.strip():
        det = "commit failed (no output)"
    return False, det.strip()

def commit_all(
    mcp: MCPMultiplexer,
    repo_path: str,
    message: str,
    *,
    allow_empty_if_no_head: bool = True,
) -> str:
    repo_abs = os.path.normpath(repo_path)
    _ensure_workdir(mcp, repo_abs)
    _ensure_git_identity(repo_abs)

    # Add (MCP to CLI)
    _git_add_all(mcp, repo_abs)

    # intenta commit por MCP
    r = _call_git(mcp, ["git_commit","git:commit"], {"message": message})
    # pase lo que pase, verifica HEAD; si no existe, fuerza commit por CLI
    if not _verify_head(repo_abs):
        ok, detail = _commit_cli_force(repo_abs, message)
        if not ok:
            staged = _safe_capture(["git","-C",repo_abs,"diff","--cached","--name-status"])
            status = _safe_capture(["git","-C",repo_abs,"status","--porcelain=v1"])
            return (
                "No se pudo materializar el commit.\n"
                f"Detalle CLI: {detail}\n"
                f"Staged (--cached):\n{staged or '(vacío)'}\n"
                f"Status:\n{status or '(limpio)'}\n"
                "Sugerencias:\n"
                "  - Asegúrate de que el repo no tenga hooks que rechacen el commit.\n"
                "  - Verifica permisos de escritura en la carpeta.\n"
                "  - Prueba manualmente: git -C \"{repo_abs}\" commit -m \"{message}\""
            )

    head = _safe_capture(["git","-C",repo_abs,"rev-parse","--short","HEAD"])
    log1 = _safe_capture(["git","-C",repo_abs,"log","--oneline","-n","1"])
    status = _safe_capture(["git","-C",repo_abs,"status","--porcelain"])
    return (
        f"Commit listo en {repo_abs}.\n"
        f"HEAD: {head or '(sin commits)'} | último commit: {log1 or '(no hay)'}\n"
        f"Status (porcelain):\n{status or '(limpio)'}"
    )

def create_repo_hybrid(
    mcp: MCPMultiplexer,
    repo_path: str,
    readme_text: str,
    commit_msg: str,
    *,
    remote_url: str | None = None,
    default_branch: str = "main",
    private_remote: bool = True,
) -> str:
    repo_abs = os.path.normpath(repo_path)

    # Carpeta + README si falta
    r1 = _call_fs(mcp, ["create_directory","filesystem:create_directory"], {"path": repo_abs})
    if "error" in r1:
        return f"Error al crear carpeta: {r1}"
    readme = os.path.join(repo_abs, "README.md")
    if not os.path.exists(readme):
        r2 = _call_fs(mcp, ["write_file","filesystem:write_file"], {"path": readme, "content": readme_text})
        if "error" in r2:
            return f"Error al escribir README.md: {r2}"

    # init + rama + identidad
    _ensure_workdir(mcp, repo_abs)
    r_init = _call_git(mcp, ["git_init","git:init"], {})
    if "error" in r_init:
        # fallback: init por CLI
        _run_git(repo_abs, "init")
    _checkout_or_create_branch(mcp, repo_abs, default_branch)
    _ensure_git_identity(repo_abs)

    # add + commit (siempre verificado)
    _git_add_all(mcp, repo_abs)

    # commit por MCP
    _call_git(mcp, ["git_commit","git:commit"], {"message": commit_msg})

    # verificación; si no hay HEAD, fuerza por CLI
    if not _verify_head(repo_abs):
        ok, detail = _commit_cli_force(repo_abs, commit_msg)
        if not ok:
            staged = _safe_capture(["git","-C",repo_abs,"diff","--cached","--name-status"])
            status = _safe_capture(["git","-C",repo_abs,"status","--porcelain=v1"])
            return (
                "Repo creado pero el commit inicial NO se materializó.\n"
                f"Detalle CLI: {detail}\n"
                f"Staged (--cached):\n{staged or '(vacío)'}\n"
                f"Status:\n{status or '(limpio)'}"
            )

    # remoto + push (igual que ya lo tenías)
    remote_summary = "Sin remoto."
    if remote_url:
        remote_summary = set_remote_and_push(
            mcp, repo_abs, remote_url, branch=default_branch, private_remote=private_remote
        )

    # resumen
    head = _safe_capture(["git","-C",repo_abs,"rev-parse","--short","HEAD"])
    log1 = _safe_capture(["git","-C",repo_abs,"log","--oneline","-n","1"])
    br   = _safe_capture(["git","-C",repo_abs,"branch","-vv"])
    rem  = _safe_capture(["git","-C",repo_abs,"remote","-v"])
    status = _safe_capture(["git","-C",repo_abs,"status","--porcelain"])
    try:
        remote_heads = _run_git(repo_abs, "ls-remote", "--heads", "origin") if remote_url else ""
    except Exception:
        remote_heads = "(no accesible)"

    return (
        f"Repositorio listo en {repo_abs}.\n"
        f"HEAD: {head or '(sin commits)'} | último commit: {log1 or '(no hay)'}\n"
        f"Remotos:\n{rem}\nRamas:\n{br}\n"
        f"Status (porcelain):\n{status or '(limpio)'}\n"
        + (f"Heads remotos:\n{remote_heads}\n" if remote_url else "")
        + remote_summary
    )