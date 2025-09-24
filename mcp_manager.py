from __future__ import annotations
import os, json, asyncio, threading
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional, Any

from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp import ClientSession

@dataclass
class MCPServerConfig:
    name: str
    command: str
    args: List[str] = field(default_factory=list)
    cwd: Optional[str] = None

#  normalizadores
def _normalize_git_args(tool: str, args: dict) -> tuple[str, dict]:
    a = dict(args or {})
    if tool in ("git_set_working_dir", "git:set_working_dir"):
        if isinstance(a.get("path"), str): a["path"] = a["path"].strip()

    if tool in ("git_add", "git:add"):
        if "paths" not in a:
            if "path" in a and isinstance(a["path"], str):
                a["paths"] = [a.pop("path").strip()]
            elif "file" in a and isinstance(a["file"], str):
                a["paths"] = [a.pop("file").strip()]
            elif "files" in a and isinstance(a["files"], list):
                a["paths"] = [str(p).strip() for p in a.pop("files") if str(p).strip()]
        if isinstance(a.get("paths"), list):
            a["paths"] = [str(p).strip() for p in a["paths"] if str(p).strip()]

    if tool in ("git_commit", "git:commit"):
        if "message" in a: a["message"] = str(a["message"])

    if tool in ("git_remote","git:remote","git_remote_add","git:remote_add"):
        if "mode" not in a: a["mode"] = "add" if "url" in a else "list"
        if "remote_name" in a and "name" not in a: a["name"] = a.pop("remote_name")

    if tool in ("git_push","git:push"):
        if "remote" not in a and "remote_name" in a: a["remote"] = a.pop("remote_name")
        a.setdefault("branch","main")
        a.setdefault("set_upstream", True)
    return tool, a

def _normalize_fs_args(tool: str, args: dict) -> tuple[str, dict]:
    def _norm(p: str) -> str: return os.path.normpath(p).replace("\\","/")
    a = dict(args or {})
    for k in ("path","source","destination","dest","from","to"):
        if k in a and isinstance(a[k], str): a[k] = _norm(a[k])

    if tool in ("move_file","filesystem:move_file","copy_file","filesystem:copy_file"):
        if "destination" in a and "dest" not in a: a["dest"] = a["destination"]
        if "to" in a and "dest" not in a: a["dest"] = a["to"]
        if "from" in a and "source" not in a: a["source"] = a["from"]

    if tool in ("list_directory","filesystem:list_directory"):
        if isinstance(a.get("path"), str): a["path"] = a["path"].rstrip("/")
    return tool, a

#gramamr
def _normalize_gram_args(tool: str, args: dict):
    a = dict(args or {})
    if tool in ("gram_fix","gram:gram_fix","gram_check","gram:gram_check","gram_fix_file","gram:gram_fix_file"):
        a.setdefault("lang","es")
    return tool, a

def _normalize_yt_args(tool: str, args: dict) -> tuple[str, dict]:
    a = dict(args or {})

    def _upper_region(v):
        try:
            return str(v).strip().upper()
        except Exception:
            return None

    if tool in ("yt_init", "yt:yt_init"):
        return tool, {}  # sin args

    if tool in ("yt_list_regions", "yt:yt_list_regions"):
        return tool, {}

    if tool in ("yt_list_categories", "yt:yt_list_categories"):
        a.setdefault("region", "US")
        a["region"] = _upper_region(a["region"]) or "US"
        return tool, a

    if tool in ("yt_fetch_most_popular", "yt:yt_fetch_most_popular"):
        a.setdefault("region", "US")
        a["region"] = _upper_region(a["region"]) or "US"
        a.setdefault("limit", 10)
        a["limit"] = max(1, min(50, int(a["limit"])))
        return tool, a

    if tool in ("yt_register_keywords", "yt:yt_register_keywords"):
        kws = a.get("keywords")
        if isinstance(kws, str):
            kws = [k.strip() for k in kws.split(",") if k.strip()]
        if not isinstance(kws, list):
            kws = []
        a["keywords"] = [str(k).strip() for k in kws if str(k).strip()]
        return tool, a

    if tool in ("yt_search_recent", "yt:yt_search_recent"):
        a.setdefault("days", 7)
        a.setdefault("per_keyword", 10)
        a.setdefault("order", "viewCount")
        a["days"] = max(1, min(90, int(a["days"])))
        a["per_keyword"] = max(1, min(50, int(a["per_keyword"])))
        if a.get("order") not in ("viewCount", "date"):
            a["order"] = "viewCount"
        if "region" in a and a["region"]:
            a["region"] = _upper_region(a["region"]) or "US"
        return tool, a

    if tool in ("yt_calc_trends", "yt:yt_calc_trends"):
        a.setdefault("limit", 10)
        a["limit"] = max(1, min(50, int(a["limit"])))
        return tool, a

    if tool in ("yt_trend_details", "yt:yt_trend_details"):
        a["keyword"] = str(a.get("keyword") or "").strip()
        a.setdefault("top", 10)
        a["top"] = max(1, min(50, int(a["top"])))
        return tool, a

    if tool in ("yt_export_report", "yt:yt_export_report"):
        if "path" in a and a["path"]:
            a["path"] = os.path.normpath(str(a["path"]))
        return tool, a

    # Por defecto, pásalo tal cual
    return tool, a

#  Multiplexer
class MCPMultiplexer:
    """
    Arranca cada servidor MCP una sola vez.
    Mantiene ClientSession y procesos vivos en un AsyncExitStack.
    todos los llamados a async corren en un loop dedicado en un hilo.
    Los wrappers sync envían corutinas a ese loop (sin abrir loops nuevos).
    """
    def __init__(self, servers: List[MCPServerConfig]):
        self.servers = servers
        self._stack: Optional[AsyncExitStack] = None
        self._sessions: Dict[str, ClientSession] = {}
        self._started = False

        # event loop dedicado en hilo
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    # loop thread
    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _submit(self, coro):
        """Ejecuta una corutina en el loop dedicado y espera el resultado."""
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result()

    #  lifecycle
    async def start(self):
        if self._started:
            return
        self._stack = AsyncExitStack()
        await self._stack.__aenter__()
        # entrar a cada servidor y mantener su contexto
        for cfg in self.servers:
            params = StdioServerParameters(command=cfg.command, args=cfg.args, cwd=cfg.cwd)
            r, w = await self._stack.enter_async_context(stdio_client(params))
            sess = ClientSession(r, w)
            sess = await self._stack.enter_async_context(sess)
            await sess.initialize()
            self._sessions[cfg.name] = sess
            print(f"[MCP] started '{cfg.name}' -> {cfg.command} {' '.join(cfg.args) if cfg.args else ''}")
        self._started = True

    async def stop(self):
        if not self._started:
            return
        try:
            if self._stack:
                await self._stack.aclose()
        finally:
            self._stack = None
            self._sessions.clear()
            self._started = False
        # cerrar el loop/hilo
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=1)

    async def _ensure_started(self):
        if not self._started:
            await self.start()

    #  API async
    async def list_all_tools(self) -> Dict[str, Dict[str, str]]:
        await self._ensure_started()
        out: Dict[str, Dict[str, str]] = {}
        for name, sess in self._sessions.items():
            resp = await sess.list_tools()
            out[name] = {t.name: getattr(t, "description", "") for t in resp.tools}
        return out

    async def call_tool(self, server_name: str, tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        await self._ensure_started()
        sess = self._sessions.get(server_name)
        if not sess:
            return {"error": f"Servidor desconocido: {server_name}"}

        tool_to_call = tool
        call_args = args or {}
        if server_name == "git":
            tool_to_call, call_args = _normalize_git_args(tool_to_call, call_args)
        elif server_name == "fs":
            tool_to_call, call_args = _normalize_fs_args(tool_to_call, call_args)
        elif server_name == "gram":
            tool_to_call, call_args = _normalize_gram_args(tool_to_call, call_args)
        elif server_name == "yt":
            tool_to_call, call_args = _normalize_yt_args(tool_to_call, call_args)

        print(f"[MCP] calling '{server_name}'")


        res = await sess.call_tool(tool_to_call, call_args)
        for item in getattr(res, "content", []) or []:
            if hasattr(item, "value") and isinstance(item.value, (dict, list, str)):
                return {"value": item.value} if not isinstance(item.value, dict) else item.value
            if hasattr(item, "text") and item.text:
                try:
                    return json.loads(item.text)
                except Exception:
                    return {"text": item.text[:4000]}
        return {"error": "Respuesta vacía del servidor MCP"}

    #  API sync (thread-safe)
    def start_sync(self):
        return self._submit(self.start())

    def stop_sync(self):
        return self._submit(self.stop())

    def list_all_tools_sync(self):
        return self._submit(self.list_all_tools())

    def call_tool_sync(self, server_name: str, tool: str, args: Dict[str, Any]):
        return self._submit(self.call_tool(server_name, tool, args))
