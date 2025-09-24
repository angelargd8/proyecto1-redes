from mcp_manager import MCPMultiplexer, MCPServerConfig
from client import OpenAIResponsesClient
from agent import MCPAgent
import shutil, os, re, json, sys
from agent import MCPAgent, DEFAULT_SYSTEM
from intents import create_repo_hybrid
from log import JsonlLogger
from ZTRClient import ztr_execute_tool_http
import anyio
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp import ClientSession
from typing import Optional, List, Dict, Any


NPX = os.environ.get("NPX_CMD") or shutil.which("npx") or r"C:\Program Files\nodejs\npx.cmd"
FS_BIN = shutil.which("server-filesystem")
GIT_BIN = shutil.which("git-mcp-server")

def _catalog_for_prompt(mcp: MCPMultiplexer) -> str:
    cat = mcp.list_all_tools_sync()
    lines = ["Tools disponibles:"]
    for srv, tools in cat.items():
        for n in tools.keys():
            lines.append(f"- {srv}:{n}")
    return "\n".join(lines)


def _norm_text(s: str) -> str:
    s = (s or "").strip()
    s = s.replace("“", '"').replace("”", '"').replace("’", "'")
    s = re.sub(r"\s+", " ", s)
    return s

#--------------------------------------------------------------------------
_GRAM_TRIG = re.compile(r'\b(corrige|arregla|revisa)\b', re.I)

#--------------------------------------------------------------------------
#trigger de zotero
_APA_TRIGGER = re.compile(r"\b(cita|c[ií]tame|referencia|bibliograf[ií]a|formatea|apa)\b", re.I)

ZTR_MCP_HTTP = "https://ztrmcp-990598886898.us-central1.run.app/mcp/sse?version=1.0"

#-------------------------------------------------------------------------
# trigger general de tema YouTubes
_YT_TOPIC = re.compile(
    r"(youtube|yt|tenden|trending|keywords?|palabras\s+clave|categor[ií]as|regiones?|regi[oó]n|exporta|profundiza|detalle|detalles|videos?)",
    re.I,
)

COUNTRY_ALIASES = {
    "gt": "GT", "sv": "SV", "mx": "MX", "us": "US", "ar": "AR", "co": "CO", "pe": "PE",
    "cl": "CL", "es": "ES", "br": "BR", "uy": "UY", "py": "PY", "bo": "BO",
    "guatemala": "GT",
    "el salvador": "SV", "salvador": "SV",
    "méxico": "MX", "mexico": "MX",
    "estados unidos": "US", "eeuu": "US", "usa": "US",
    "canada": "CA",
    "argentina": "AR",
    "colombia": "CO",
    "perú": "PE", "peru": "PE",
    "chile": "CL",
    "españa": "ES", "spain": "ES",
    "brasil": "BR",
    "uruguay": "UY",
    "paraguay": "PY",
    "bolivia": "BO",
}

#-------------------------------------------------------------------------

def _trigger_gram(text: str):
    if not _GRAM_TRIG.search(text): 
        return None
    # Texto entre comillas → corrige inline; si no, intenta archivo con fs:path
    m = re.search(r'"([^"]+)"|“([^”]+)”', text)
    if m:
        payload = m.group(1) or m.group(2)
        return {"action":"tool_call","server":"gram","tool":"gram_fix","args":{"text": payload, "lang":"es"}}
    p = re.search(r'path\s*=\s*(\S+)', text)
    if p:
        return {"action":"tool_call","server":"gram","tool":"gram_fix_file","args":{"path": p.group(1), "lang":"es"}}
    return None

#-------------------------------------------------------------------------

def _trigger_zotero_apa(text: str):
    text = (text or "").strip()
    if not _APA_TRIGGER.search(text): 
        return None
    # intenta extraer la URL
    m = re.search(r'https?://\S+', text)
    url = m.group(0) if m else None
    if not url:
        m2 = re.search(r'url\s*:\s*"(.*?)"', text, re.I)
        url = m2.group(1) if m2 else None
    return {"action": "apa_from_url", "url": url}

#-------------------------------------------------------------------------

def run_cite_intent(intent: dict) -> str:
    url = (intent.get("url") or "").strip()
    if not url:
        return "¿Qué URL quieres citar en APA? Ejemplo: 'Cítame en APA: https://ejemplo.com/articulo'"

    args = {"url": url, "style": "apa", "locale": "es-ES"}
    
    if ZTR_MCP_HTTP:
        r = ztr_execute_tool_http("apa_from_url", args, ZTR_MCP_HTTP)
    else:
        print("No hay URL de Zotero MCP configurada.")

    if not isinstance(r, dict):
        return "No entendí la respuesta del servidor de referencias"
    if r.get("error"):
        return f"Error al generar APA: {r['error']}"

    refs = r.get("references") or r.get("apa") or []
    if isinstance(refs, str):
        return refs
    if isinstance(refs, list) and refs:
        return "\n".join(refs)
    return "No se pudo generar una referencia APA (respuesta vacía)"


#-----------------------------------------------------------
# MCP YouTube cliente
async def _yt_call_mcp(tool: str, args: dict) -> dict:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    server_path = os.path.join(base_dir, "YTServerMCP.py")
    if not os.path.isfile(server_path):
        return {"error": f"No encontré YTServerMCP.py en: {server_path}."}

    errlog_path = os.path.join(base_dir, "youtube.mcp.err.log")
    errlog = open(errlog_path, "ab")

    yt_params = StdioServerParameters(
        command=sys.executable,
        args=[server_path],
        cwd=base_dir,
    )

    try:
        async with stdio_client(yt_params, errlog=errlog) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as sess:
                await sess.initialize()

                if tool != "yt_init":
                    init_res = await sess.call_tool("yt_init", {})
                    init_val = None
                    for it in getattr(init_res, "content", []):
                        if hasattr(it, "value"):
                            init_val = it.value
                            break
                        if hasattr(it, "text"):
                            init_val = {"msg": it.text}
                            break
                    if isinstance(init_val, dict) and init_val.get("error"):
                        return {"error": f"No pude inicializar YouTube: {init_val['error']}"}

                res = await sess.call_tool(tool, args or {})
                # Normaliza la respuesta
                for item in getattr(res, "content", []):
                    if hasattr(item, "value") and isinstance(item.value, dict):
                        return item.value
                    if hasattr(item, "value") and isinstance(item.value, str):
                        try:
                            parsed = json.loads(item.value)
                            if isinstance(parsed, dict):
                                return parsed
                            return {"value": parsed}
                        except Exception:
                            return {"msg": "non-json string from mcp", "value": item.value}
                    if hasattr(item, "text") and item.text:
                        try:
                            parsed = json.loads(item.text)
                            if isinstance(parsed, dict):
                                return parsed
                        except Exception:
                            pass
                        return {"msg": item.text}

                return {"error": "Respuesta vacía del servidor MCP de YouTube"}
    except Exception as e:
        try:
            errlog.flush()
            with open(errlog_path, "rb") as _fp:
                tail = _fp.read()[-4096:]
            hint = tail.decode("utf-8", errors="ignore")
        except Exception:
            hint = ""
        return {"error": f"Fallo al iniciar/usar YTServerMCP.py: {e}\nÚltimas líneas de youtube.mcp.err.log:\n{hint}"}
    finally:
        try:
            errlog.close()
        except Exception:
            pass

def yt_execute_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    return anyio.run(_yt_call_mcp, name, args)

# helpers/intents YouTube 
def _unwrap(r: dict | None) -> dict:
    if not isinstance(r, dict):
        return {}
    if "value" in r and isinstance(r["value"], dict):
        return r["value"]
    return r

# youtube utils e intents
def _pick_region(text: str, default: str = "GT") -> str:
    t = text.lower()
    # ISO-2 (GT, SV, MX, etc)
    m = re.search(r'\b([a-z]{2})\b', t)
    if m and m.group(1) in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[m.group(1)]
    # en/de/para <nombre>
    m = re.search(r'\b(?:en|de|para)\s+([a-záéíóúüñ ]{2,})\b', t)
    if m:
        name = m.group(1).strip()
        if name in COUNTRY_ALIASES:
            return COUNTRY_ALIASES[name]
    # nombre suelto
    for name, iso in COUNTRY_ALIASES.items():
        if re.search(rf'\b{name}\b', t):
            return iso
    return default

def _pick_int(text: str, patterns: list[tuple[str, int]], default: int) -> int:
    for pat, _max in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                n = int(m.group(1))
                return max(1, min(_max or n, n))
            except:
                pass
    return default

def _parse_keywords(text: str) -> list[str]:
    m = re.search(r'(?:keywords|palabras\s+clave)\s*:\s*([^;:\n]+)$', text, re.IGNORECASE)
    if m:
        return [x.strip() for x in m.group(1).split(",") if x.strip()]
    qs = re.findall(r'"([^"]+)"|“([^”]+)”', text)
    vals = [a or b for (a, b) in qs if (a or b)]
    if vals:
        return vals
    m = re.search(r'\bregistra.*?:\s*([^;:\n]+)$', text, re.IGNORECASE)
    if m:
        return [x.strip() for x in m.group(1).split(",") if x.strip()]
    return []

def _trigger_yt(text: str) -> dict | None:
    t = _norm_text(text)
    tl = t.lower()
    if not _YT_TOPIC.search(tl):
        return None

    # listar regiones
    if re.search(r"(lista(r)?\s+regiones|c[oó]digos?\s+de\s+regi[oó]n|regiones)", tl):
        return {"action": "list_regions"}

    # profundiza en tendencias top N, región, keyword
    if re.search(r"(profundiza|detalle|detalles)", tl):
        # top N
        top_m = re.search(r"\btop\s+(\d{1,3})\b", tl)
        top = int(top_m.group(1)) if top_m else 10
        region = _pick_region(tl, default="US")
        # keyword: intenta comillas; si no, frase tras (en|de|sobre)
        qs = _parse_keywords(t)
        kw = qs[0] if qs else None

        # si aún no hay kw, intenta tomar la primera palabra significativa antes de "top"
        if not kw:
            m = re.search(r"(?:en|de|sobre)\s+(.+)$", tl)
            if m:
                phrase = m.group(1)
                phrase = re.sub(r"\btop\s+\d{1,3}\b", "", phrase, flags=re.IGNORECASE)
                for name in COUNTRY_ALIASES.keys():
                    phrase = re.sub(rf"\b{name}\b", "", phrase, flags=re.IGNORECASE)
                kw = phrase.strip()
        if not kw:
            m2 = re.search(r"(?:profundiza|detalle|detalles)\s+(?:en|de|sobre)?\s*([a-z0-9 #+_.-]{2,})", tl)
            if m2:
                phrase = m2.group(1)
                phrase = re.sub(r"\btop\s+\d{1,3}\b", "", phrase, flags=re.IGNORECASE)
                for name in COUNTRY_ALIASES.keys():
                    phrase = re.sub(rf"\b{name}\b", "", phrase, flags=re.IGNORECASE)
                kw = phrase.strip()
        return {"action": "trend_details", "keyword": kw, "top": top, "region": region}

    # listar categorías
    if re.search(r"(categor[ií]as|lista(r)?\s+categor[ií]as)", tl):
        region = _pick_region(tl, default="US")
        return {"action": "list_categories", "region": region}

    # registrar keywords
    if re.search(r"(calcula|score|puntaje|ranking).*(tenden)", tl) or re.search(r"(tenden).*(calcula|score|puntaje)", tl):
        limit = _pick_int(tl, [(r"top\s+(\d{1,3})", 50), (r"l[ií]mite\s+(\d{1,3})", 50)], default=10)
        return {"action": "calc", "limit": limit}

    # registrar keywords
    if re.search(r"(registra|agrega).*(keywords?|palabras\s+clave)", tl):
        kws = _parse_keywords(t)
        return {"action": "register_keywords", "keywords": kws}

    # buscar por keywords
    if (re.search(r"busca(r)?", tl) and re.search(r"keywords?", tl)) or (re.search(r"videos?", tl) and re.search(r"(d[ií]as|[uú]ltim[ao]s)", tl)):
        days = _pick_int(tl, [(r"(?:[uú]ltim[ao]s?)?\s*(\d{1,3})\s*d[ií]as", 90)], default=7)
        per_keyword = _pick_int(tl, [(r"(\d{1,3})\s+por\s+keyword", 50), (r"(\d{1,3})\s+videos?", 50)], default=10)
        order = "date" if re.search(r"(nuevos|recientes|fecha|date)", tl) else "viewCount"
        region = _pick_region(tl, default="US") if re.search(r"(en|pa[ií]s)", tl) else None
        return {"action": "search", "days": days, "per_keyword": per_keyword, "order": order, "region": region}

    # exportar
    if re.search(r"exporta(r)?", tl):
        fmt = "csv" if re.search(r"\bcsv\b", tl) else ("json" if re.search(r"\bjson\b", tl) else "csv")
        m = re.search(r'"([^"]+)"', t)
        out_path = m.group(1) if m else None
        return {"action": "export", "format": fmt, "out_path": out_path}
    
    # fallback trending
    region = _pick_region(tl, default="US")
    limit = _pick_int(tl, [(r"top\s+(\d{1,3})", 50), (r"l[ií]mite\s+(\d{1,3})", 50), (r"muestra\s+(\d{1,3})", 50)], default=10)
    return {"action": "trending", "region": region, "limit": limit}

# YouTube intent execution
def run_yt_intent(intent: dict) -> str:
    r = yt_execute_tool("yt_init", {})
    r = _unwrap(r)
    if r.get("error"):
        return f"Error YouTube: {r['error']}"

    act = intent.get("action")

    if act == "list_regions":
        r = yt_execute_tool("yt_list_regions", {})
        r = _unwrap(r)
        if r.get("error"):
            return f"Error: {r['error']}"
        regions = r.get("regions", [])
        if not regions:
            return "No se recibieron regiones desde YouTube."
        lines = [f"{reg.get('code')}: {reg.get('name')}" for reg in regions]
        return "Regiones disponibles:\n" + "\n".join(lines)

    if act == "list_categories":
        region = intent.get("region", "US")
        r = yt_execute_tool("yt_list_categories", {"region": region})
        r = _unwrap(r)
        if r.get("error"):
            return f"Error: {r['error']}"
        cats = r.get("categories", [])
        if not cats:
            return f"No se recibieron categorías para {region}."
        return f"Categorías en {region}:\n" + "\n".join(f"{c.get('id')} — {c.get('title')}" for c in cats[:20])

    if act == "trending":
        region = intent.get("region", "US")
        limit  = intent.get("limit", 10)
        r = yt_execute_tool("yt_fetch_most_popular", {"region": region, "limit": limit})
        r = _unwrap(r)

        if r.get("error"):
            return f"Error: {r['error']}"
        items = r.get("items", [])
        region_used = r.get("region") or r.get("regionCode") or region
        if not items:
            return f"No encontré tendencias para región {region_used}."
        
        lines = [f"Top en {region_used}:"]
        for i, v in enumerate(items[:limit], 1):
            lines.append(f"{i}. {v.get('title')} — {v.get('channelTitle')} (views: {v.get('views',0)})")
        return "\n".join(lines)

    if act == "register_keywords":
        kws = intent.get("keywords", [])
        if not kws:
            return "Dime las keywords: p.ej. 'registra keywords: minecraft, free fire'"
        r = yt_execute_tool("yt_register_keywords", {"keywords": kws})
        r = _unwrap(r)
        if r.get("error"):
            return f"Error: {r['error']}"
        return "Keywords registradas: " + ", ".join(r.get("keywords", []))

    if act == "search":
        days = intent.get("days", 7)
        per_keyword = intent.get("per_keyword", 10)
        order = intent.get("order", "viewCount")
        args = {"days": days, "per_keyword": per_keyword, "order": order}
        if intent.get("region"):
            args["region"] = intent["region"]

        r = yt_execute_tool("yt_search_recent", args)
        r = _unwrap(r)
        if r.get("error"):
            return f"Error: {r['error']}"
        results = r.get("results", {}) or {}

        if not results:
            return "No se recibieron resultados de búsqueda."
        lines = [f"Búsqueda OK: {r.get('total',0)} videos sobre {', '.join(r.get('keywords',[]))}"]
        max_show = min(per_keyword, 10)

        for kw, vids in results.items():
            lines.append(f"\nKeyword: {kw} (mostrando hasta {max_show})")
            for v in vids[:max_show]:
                lines.append(f"- {v.get('title')} — {v.get('channelTitle')} ({v.get('views',0)} v)")
        return "\n".join(lines)

    if act == "calc":
        r = yt_execute_tool("yt_calc_trends", {"limit": intent.get("limit", 10)})
        r = _unwrap(r)
        if r.get("error"):
            return f"Error: {r['error']}"
        kws = r.get("keywords", [])
        vids = r.get("top_videos", [])
        if not kws and not vids:
            return "No hay datos para calcular tendencias."
        out = ["Top keywords: " + ", ".join(f"{k.get('keyword')}({k.get('score')})" for k in kws)]
        out += ["Top videos:"] + [
            f"- {v.get('title')} [{v.get('views',0)} v] score={v.get('score')}" for v in vids[:intent.get("limit",10)]
        ]
        return "\n".join(out)

    if act == "trend_details":
        kw = (intent.get("keyword") or "").strip()
        top = intent.get("top", 10)
        region = intent.get("region")

        if not kw:
            return "¿De qué keyword quieres detalles?"

        r = yt_execute_tool("yt_trend_details", {"keyword": kw, "top": top})
        r = _unwrap(r)
        items = (r or {}).get("items") or []
        if r.get("error") or not items:
            _ = yt_execute_tool("yt_register_keywords", {"keywords": [kw]})
            search_args = {"days": 7, "per_keyword": max(10, top), "order": "viewCount"}
            if region:
                search_args["region"] = region
            _ = yt_execute_tool("yt_search_recent", search_args)
            _ = yt_execute_tool("yt_calc_trends", {"limit": max(20, top)})
            r = yt_execute_tool("yt_trend_details", {"keyword": kw, "top": top})
            r = _unwrap(r)
            items = (r or {}).get("items") or []
        if r.get("error"):
            return f"Error: {r['error']}"
        if not items:
            return (f"No hay resultados para '{kw}'. Intenta 'registra keywords: {kw}' "
                    "y luego 'busca 10 videos por keyword de los últimos 7 días' y 'calcula tendencias'.")
        lines = [f"Detalles de '{kw}':"]
        for v in items:
            lines.append(
                f"- {v.get('title')} — {v.get('channelTitle')} "
                f"(views {v.get('views',0)}, score {v.get('score',0)})"
            )
        return "\n".join(lines)

    if act == "export":
        args = {"path": intent.get("out_path")}
        r = yt_execute_tool("yt_export_report", args)
        r = _unwrap(r)
        if r.get("error"):
            return f"Error: {r['error']}"
        return f"Exportado: {r.get('path')} ({r.get('rows',0)} filas)"

    return "No entendí la intención de YouTube."

    


class ChatService:
    def __init__(self, *, model: str = "gpt-4o-mini", fs_dirs: List[str] | None = None, logger: JsonlLogger | None = None ):
        self.llm = OpenAIResponsesClient(model=model)
        servers = []
        # filesystem
        dirs = fs_dirs or [
            r"C:\\Users\\angel\\Projects",
            r"C:\\Users\\angel\\Desktop",
            r"C:\\Users\\angel\\OneDrive\\Documentos\\.universidad\\.2025\\s2\\redes\\dos",
            r"C:\\Users\\angel\\OneDrive\\Documentos\\.universidad\\.2025\\s2\\redes",
            r"C:\\Users\\angel\\OneDrive\\Documentos\\.universidad\\.2025\\s2\\redes\\proyecto1-redes",
        ]

        servers = []
        if FS_BIN:
            servers.append(MCPServerConfig(name="fs", command=FS_BIN, args=[*dirs]))
        else:
            servers.append(MCPServerConfig(name="fs", command=NPX, args=["-y", "@modelcontextprotocol/server-filesystem", *dirs]))

        if GIT_BIN:
            servers.append(MCPServerConfig(name="git", command=GIT_BIN, args=[]))
        else:
            servers.append(MCPServerConfig(name="git", command=NPX, args=["-y", "@cyanheads/git-mcp-server"]))

        # youtube
        YT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "YTServerMCP.py")
        if os.path.isfile(YT_PATH):
            servers.append(MCPServerConfig(name="yt", command=sys.executable, args=[YT_PATH]))
        
        # grammar
        GRAM_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "grammarMCP.py")
        if os.path.isfile(GRAM_PATH):
            servers.append(MCPServerConfig(name="gram", command=sys.executable, args=[GRAM_PATH]))

        self.mcp = MCPMultiplexer(servers)
        self.mcp.start_sync() 
        
        tools_text = _catalog_for_prompt(self.mcp)
        # self.agent = MCPAgent(self.llm, self.mcp)
        system_msg = tools_text + "\n\n" + DEFAULT_SYSTEM
        self.agent = MCPAgent(self.llm, self.mcp, system_prompt=system_msg)
        self.logger = logger or JsonlLogger()
    


    def list_tools(self) -> str:
        catalog = self.mcp.list_all_tools_sync()
        lines = []
        for srv, tools in catalog.items():
            lines.append(f"[{srv}]")
            for n, d in tools.items():
                lines.append(f"- {n}: {d}")
        return "\n".join(lines)

    def ask(self, user_msg: str) -> str:
        self.logger.event(
            channel="system",
            kind="info",
            info="User message",
            user_message=user_msg,
        )

        out = None

        try:
            # list tools
            if re.search(r'\b(list|lista)\s+(tools|herramientas)\b', user_msg, re.I):
                out = self.list_tools()

            if out is None:
                m = re.match(r'^\s*repo\s+create\s+"?([^"]+)"?(?:\s+remote=(\S+))?', user_msg.strip(), re.I)
                if m:
                    repo_path = m.group(1)
                    remote = m.group(2)
                    out = create_repo_hybrid(
                        self.mcp,
                        repo_path=repo_path,
                        readme_text="# README\n",
                        commit_msg="initial commit",
                        remote_url=remote,
                        default_branch="main",
                        private_remote=True,
                    )
            
            # YouTube
            if out is None:
                yt_int = _trigger_yt(_norm_text(user_msg))
                if yt_int:
                    print("[MCP] calling yt")
                    out = run_yt_intent(yt_int)
                    self.logger.event("yt", "intent", intent=yt_int, result_preview=str(out)[:400])
            

            # zotero
            if out is None:
                cite_int = _trigger_zotero_apa(_norm_text(user_msg))
                if cite_int:
                    print("[MCP] calling zotero")
                    out = run_cite_intent(cite_int)
                    self.logger.event("ztr", "intent", intent=cite_int, result_preview=str(out)[:400])


            #grammar
            if out is None:
                tc = _trigger_gram(user_msg)
                if tc:
                    print("[MCP] calling gram")
                    self.logger.event("gram", "intent", intent=tc)
                    out = self.agent.run(json.dumps(tc, ensure_ascii=False))
            
            # Agente normal
            if out is None:
                # print("[MCP] calling agent")
                out = self.agent.run(user_msg)

            return out

        except Exception as e:
            out = f"ERROR: {e}"
            self.logger.event(
                channel="chat",
                kind="response_error",
                error=str(e),
            )

        finally:
            # log de response final
            self.logger.event(
                channel="chat",
                kind="response",
                answer=str(out)[:4000],
            )

            return out
