from __future__ import annotations
import os, json, time, re
from typing import Optional, List, Dict, Any

from client import OpeniaGPT4ominiClient 
from toolsYoutube import YOUTUBE_TOOLS
from YTtool import execute_tool_sync as yt_execute_tool
from log import JsonlLogger

# helpers Git por si el modelo llama tools
from mcpClient import (
    create_repo_with_readme_and_commit,
    commit_readme_in_existing_repo,
    push_to_github,
    run_git,
)

# Fallback Git por intencion si el modelo no llama tools
from intents import parse_intent
from actions import execute_intent

#para debbugear xd
DEBUG = False # ahorita esta en false, porque siento que se ve feo en el CLI
def _dbg(*a):
    if DEBUG:
        print("[ChatTool DEBUG]", *a)

def _norm_text(s: str) -> str:
    s = (s or "").strip()
    s = s.replace("“", '"').replace("”", '"').replace("’", "'")
    s = re.sub(r"\s+", " ", s)
    return s

# trigger general de tema YouTube
_YT_TOPIC = re.compile(
    r"(youtube|yt|tenden|trending|keywords?|palabras\s+clave|categor[ií]as|regiones?|regi[oó]n|exporta|profundiza|detalle|detalles|videos?)",
    re.I,
)


# Herramientas: Git/ filesystem
# Responses API: name al nivel superior
GIT_TOOLS = [
    {
        "type": "function",
        "name": "git_create_repo",
        "description": "Crea un repositorio local, escribe README y hace commit inicial.",
        "parameters": {
            "type": "object",
            "properties": {
                "repo_path":   {"type": "string", "description": "Ruta local del repo a crear."},
                "readme_text": {"type": "string", "description": "Contenido del README.md"},
                "commit_msg":  {"type": "string", "description": "Mensaje de commit", "default": "chore: init"},
            },
            "required": ["repo_path", "readme_text"]
        }
    },
    {
        "type": "function",
        "name": "git_update_readme",
        "description": "Escribe/actualiza README.md en un repo existente y hace commit.",
        "parameters": {
            "type": "object",
            "properties": {
                "repo_path":   {"type": "string", "description": "Ruta local del repo."},
                "readme_text": {"type": "string", "description": "Nuevo contenido del README.md"},
                "commit_msg":  {"type": "string", "description": "Mensaje de commit", "default": "docs: update README"},
            },
            "required": ["repo_path", "readme_text"]
        }
    },
    {
        "type": "function",
        "name": "git_push",
        "description": "Hace push al remoto (si el remoto existe y tienes permisos).",
        "parameters": {
            "type": "object",
            "properties": {
                "repo_path":  {"type": "string", "description": "Ruta local del repo."},
                "remote_url": {"type": "string", "description": "URL del remoto (https o ssh)."},
                "branch":     {"type": "string", "description": "Rama a subir", "default": "main"},
            },
            "required": ["repo_path", "remote_url"]
        }
    },
]

def _normalize_tools_shape(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Asegura que cada tool tenga 'name' al nivel superior (Responses API)."""
    out = []
    for t in tools:
        if "name" in t:
            out.append(t)
            continue
        fn = t.get("function", {})
        if fn:
            out.append({
                "type": t.get("type", "function"),
                "name": fn.get("name"),
                "description": fn.get("description"),
                "parameters": fn.get("parameters", {"type": "object", "properties": {}})
            })
        else:
            out.append(t)
    return out

ALL_TOOLS = _normalize_tools_shape(GIT_TOOLS + YOUTUBE_TOOLS)

COUNTRY_ALIASES = {
    # ISO-2 directos
    "gt": "GT", "sv": "SV", "mx": "MX", "us": "US", "ar": "AR", "co": "CO", "pe": "PE",
    "cl": "CL", "es": "ES", "br": "BR", "uy": "UY", "py": "PY", "bo": "BO",
    # nombres
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


# SYSTEM_PROMPT = (
#     "Eres un asistente que puede usar herramientas para Git y YouTube.\n"
#     "- Para Git: llama git_create_repo, git_update_readme, git_push según la intención del usuario.\n"
#     "- Para YouTube: si el usuario pide algo de YouTube y no está inicializado, primero llama a yt_init y luego a la tool solicitada.\n"
#     "Responde SIEMPRE con contenido útil. Si por alguna razón no puedes llamar tools, explica por qué."
# )

SYSTEM_PROMPT = (
    "Eres un asistente que puede usar herramientas para Git y YouTube.\n"
    "REGLAS PARA GIT: llama git_create_repo, git_update_readme, git_push según la intención del usuario.\n"
    "REGLAS PARA YOUTUBE:\n"
    "1) Siempre inicializa con yt_init antes de otras operaciones de YouTube.\n"
    "2) Si el usuario dice un país por nombre (p.ej. Guatemala, México), usa su ISO-2 (GT, MX, ...).\n"
    "3) Si dice 'top N', 'límite N' o 'muestra N', pasa limit=N.\n"
    "4) Si dice 'últimos X días', usa days=X.\n"
    "5) Para keywords, si dice 'registra keywords: k1, k2, ...', pasa ese array.\n"
    "6) Para búsqueda por keywords, usa yt_search_recent con days/per_keyword/order/region si las dice.\n"
    "7) Luego yt_calc_trends para calcular score; yt_trend_details para profundizar; yt_export_report para CSV/JSON.\n"
    "Cuando la intención sea de YouTube, PREFIERE usar estas herramientas (no inventes resultados)."
)

ALLOWED_DIRS_DEFAULT = [
    r"C:/Users/angel/Projects",
    r"C:/Users/angel/Desktop",
    r"C:/Users/angel/OneDrive/Documentos/.universidad/.2025/s2/redes/proyecto1-redes",
    r"C:/Users/angel/OneDrive/Documentos/.universidad/.2025/s2/redes",
]


# Helpers Git/FS para ejecución de tools
def _allowed(path: str, allowed_dirs: List[str]) -> bool:
    try:
        p = os.path.normpath(path)
        for root in allowed_dirs:
            rootn = os.path.normpath(root)
            if os.path.commonpath([p, rootn]) == rootn:
                return True
    except Exception:
        pass
    return False

def _exec_git_tool(name: str, args: Dict[str, Any], allowed_dirs: List[str]) -> Dict[str, Any]:
    try:
        repo_path = args.get("repo_path", "")
        if not _allowed(repo_path, allowed_dirs):
            return {"error": f"Ruta fuera de allowed_dirs: {repo_path}"}

        if name == "git_create_repo":
            readme_text = args.get("readme_text", "# README\n")
            commit_msg  = args.get("commit_msg", "chore: init")
            create_repo_with_readme_and_commit(
                repo_path=repo_path,
                readme_text=readme_text,
                commit_msg=commit_msg,
                allowed_dirs=allowed_dirs,
            )
            return {"ok": True, "action": "create_repo", "repo_path": repo_path, "commit_msg": commit_msg}

        if name == "git_update_readme":
            readme_text = args.get("readme_text", "")
            commit_msg  = args.get("commit_msg", "docs: update README")
            commit_readme_in_existing_repo(
                repo_path=repo_path,
                readme_text=readme_text,
                commit_msg=commit_msg,
                allowed_dirs=allowed_dirs,
            )
            return {"ok": True, "action": "update_readme", "repo_path": repo_path, "commit_msg": commit_msg}

        if name == "git_push":
            remote_url = (args.get("remote_url") or "").strip()
            branch     = (args.get("branch") or "main").strip()

            # Si no vino remote_url, intenta usar origin configurado en el repo
            if not remote_url:
                try:
                    remote_url = run_git(repo_path, "remote", "get-url", "origin")
                except Exception:
                    return {
                        "error": "Falta 'remote_url' y el repo no tiene remoto 'origin'. "
                                "Pasa 'remote_url' o configura 'origin' (git remote add origin ...)."
                    }

            # push
            push_to_github(repo_path, remote_url, branch=branch)
            return {
                "ok": True,
                "action": "push",
                "repo_path": repo_path,
                "remote_url": remote_url,
                "branch": branch
            }

        return {"error": f"Tool Git desconocida: {name}"}
    except Exception as e:
        return {"error": str(e)}


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

def parse_yt_intent(text: str) -> dict | None:
    t = _norm_text(text)
    tl = t.lower()

    # verificar que estan hablando de youtube
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

        # región si el usuario dijo país
        region = _pick_region(tl, default="US")

        # keyword: intenta comillas; si no, frase tras (en|de|sobre)
        qs = _parse_keywords(t)
        kw = qs[0] if qs else None
        if not kw:
            m = re.search(r"(?:en|de|sobre)\s+(.+)$", tl)
            if m:
                phrase = m.group(1)
                # quita top N
                phrase = re.sub(r"\btop\s+\d{1,3}\b", "", phrase, flags=re.IGNORECASE)
                # quita nombre/código de país (gt, sv, guatemala, mexico, etc.)
                for name in COUNTRY_ALIASES.keys():
                    phrase = re.sub(rf"\b{name}\b", "", phrase, flags=re.IGNORECASE)
                kw = phrase.strip()

        # si aún no hay kw, intenta tomar la primera palabra significativa antes de "top"
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

    # detalles de tendencias top N, keyword
    if re.search(r"(profundiza|detalle|detalles)", tl):
        m = re.search(r"(?:en|de|sobre)\s+([a-z0-9 #+_.-]{2,})", tl)
        kw = m.group(1).strip() if m else None
        qs = _parse_keywords(t)
        if qs:
            kw = qs[0]
        top = _pick_int(tl, [(r"top\s+(\d{1,3})", 50)], default=10)
        return {"action": "trend_details", "keyword": kw, "top": top}

    # calcular tendencias top N
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

    # fallback trending us
    region = _pick_region(tl, default="US")
    limit = _pick_int(tl, [(r"top\s+(\d{1,3})", 50), (r"l[ií]mite\s+(\d{1,3})", 50), (r"muestra\s+(\d{1,3})", 50)], default=10)
    return {"action": "trending", "region": region, "limit": limit}

    # # fallback: trendings
    # region = _pick_region(tl, default="US")
    # return {"action":"trending","region":region,"limit":10}


def run_yt_intent(intent: dict) -> str:
    # init 
    r = yt_execute_tool("yt_init", {})
    if r.get("error"):
        return f"Error YouTube: {r['error']}"

    act = intent.get("action")
    if act == "list_regions":
        r = yt_execute_tool("yt_list_regions", {})
        if r.get("error"): return f"Error: {r['error']}"
        regions = r.get("regions", [])
        return "Regiones (códigos): " + ", ".join(sorted(x["code"] for x in regions))

    if act == "list_categories":
        r = yt_execute_tool("yt_list_categories", {"region": intent.get("region", "US")})
        if r.get("error"): return f"Error: {r['error']}"
        cats = r.get("categories", [])
        return f"Categorías en {intent.get('region','US')}: " + ", ".join(f"{c['id']}:{c['title']}" for c in cats[:20])

    if act == "trending":
        args = {"region": intent.get("region","US"), "limit": intent.get("limit",10)}
        r = yt_execute_tool("yt_fetch_most_popular", args)
        if r.get("error"): return f"Error: {r['error']}"
        items = r.get("items", [])
        lines = [f"Top en {r.get('region','?')}:"] + [
            f"{i+1}. {v.get('title')} — {v.get('channelTitle')} (views: {v.get('views',0)})"
            for i, v in enumerate(items)
        ]
        return "\n".join(lines)

    if act == "register_keywords":
        kws = intent.get("keywords", [])
        if not kws: return "Dime las keywords: p.ej. 'registra keywords: minecraft, free fire'"
        r = yt_execute_tool("yt_register_keywords", {"keywords": kws})
        if r.get("error"): return f"Error: {r['error']}"
        return "Keywords registradas: " + ", ".join(r.get("keywords", []))

    if act == "search":
        days = intent.get("days", 7)
        per_keyword = intent.get("per_keyword", 10)
        order = intent.get("order", "viewCount")
        args = {"days": days, "per_keyword": per_keyword, "order": order}
        if intent.get("region"):
            args["region"] = intent["region"]

        r = yt_execute_tool("yt_search_recent", args)
        if r.get("error"):
            return f"Error: {r['error']}"
        results = r.get("results", {}) or {}
        lines = [f"Búsqueda OK: {r.get('total',0)} videos sobre {', '.join(r.get('keywords',[]))}"]
        max_show = min(per_keyword, 10)
        for kw, vids in results.items():
            lines.append(f"\nKeyword: {kw} (mostrando hasta {max_show})")
            for v in vids[:max_show]:
                lines.append(f"- {v.get('title')} — {v.get('channelTitle')} ({v.get('views',0)} v)")
        return "\n".join(lines)

    if act == "calc":
        r = yt_execute_tool("yt_calc_trends", {"limit": intent.get("limit", 10)})
        if r.get("error"): return f"Error: {r['error']}"
        kws = r.get("keywords", [])
        vids = r.get("top_videos", [])
        out = ["Top keywords: " + ", ".join(f"{k['keyword']}({k['score']})" for k in kws)]
        out += ["Top videos:"] + [f"- {v['title']} [{v.get('views',0)} v] score={v.get('score')}" for v in vids[:intent.get("limit",10)]]
        return "\n".join(out)

    if act == "trend_details":
        kw = (intent.get("keyword") or "").strip()
        top = intent.get("top", 10)
        region = intent.get("region")

        if not kw:
            return "¿De qué keyword quieres detalles?"

        # init siempre
        _ = yt_execute_tool("yt_init", {})

        #intenta detalle directo 
        r = yt_execute_tool("yt_trend_details", {"keyword": kw, "top": top})
        items = (r or {}).get("items") or []
        if r.get("error") or not items:
            # auto-pipeline: registra kw si hace falta, busca, calcula y reintenta
            _ = yt_execute_tool("yt_register_keywords", {"keywords": [kw]})
            search_args = {"days": 7, "per_keyword": max(10, top), "order": "viewCount"}
            if region: search_args["region"] = region
            _ = yt_execute_tool("yt_search_recent", search_args)

            _ = yt_execute_tool("yt_calc_trends", {"limit": max(20, top)})
            r = yt_execute_tool("yt_trend_details", {"keyword": kw, "top": top})
            items = (r or {}).get("items") or []

        if r.get("error"):
            return f"Error: {r['error']}"
        if not items:
            return f"No hay resultados para '{kw}'. Intenta 'registra keywords: {kw}' y luego 'busca 10 videos por keyword de los últimos 7 días' y 'calcula tendencias'."

        # salida formateada
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
        if r.get("error"): return f"Error: {r['error']}"
        return f"Exportado: {r.get('path')} ({r.get('rows',0)} filas)"

    return "No entendí la intención de YouTube."


# Utilidades para manejar dict/obj en tool_calls del SDK
def _tc_get(tc: Any, key: str, default=None):
    """Obtiene atributo de un tool_call que puede ser dict u objeto."""
    if isinstance(tc, dict):
        if key in tc:
            return tc.get(key, default)
        fn = tc.get("function") if isinstance(tc.get("function", None), dict) else None
        if fn and key in fn:
            return fn.get(key, default)
        if key == "id" and "tool_call_id" in tc:
            return tc["tool_call_id"]
        return default
    # objeto 
    val = getattr(tc, key, None)
    if val is not None:
        return val
    fn = getattr(tc, "function", None)
    if fn is not None:
        sub = getattr(fn, key, None)
        if sub is not None:
            return sub
    if key == "id":
        alt = getattr(tc, "tool_call_id", None)
        if alt is not None:
            return alt
    return default

def _extract_tool_calls(resp) -> List[Any]:
    """Devuelve la lista de tool_calls desde required_action"""
    ra = getattr(resp, "required_action", None)
    if ra is None and isinstance(resp, dict):
        ra = resp.get("required_action")
    if not ra:
        return []

    sto = getattr(ra, "submit_tool_outputs", None)
    if sto is None and isinstance(ra, dict):
        sto = ra.get("submit_tool_outputs")
    if not sto:
        return []

    tcalls = getattr(sto, "tool_calls", None)
    if tcalls is None and isinstance(sto, dict):
        tcalls = sto.get("tool_calls")
    return tcalls or []


def _collect_text(resp) -> str:
    #  si output_text existe
    txt = getattr(resp, "output_text", None)
    if txt:
        return txt

    # recolectar de resp.output[*].content[*].text 
    chunks = []
    out = getattr(resp, "output", None)
    if out is None and isinstance(resp, dict):
        out = resp.get("output")

    if out:
        for item in out:
            content = getattr(item, "content", None)
            if content is None and isinstance(item, dict):
                content = item.get("content", [])
            if not content:
                continue
            for c in content:
                t = getattr(c, "text", None)
                if t is None and isinstance(c, dict):
                    t = c.get("text")
                if t:
                    chunks.append(t)

    if chunks:
        return "\n".join(chunks)

    # mostrar el estado
    st = getattr(resp, "status", None)
    return f"(sin contenido; status={st})"


# Heurísticas de fallback
_YT_WORDS = re.compile(r"\b(youtube|tendenc|trending|top\s+videos?)\b", re.I)
_COUNTRY_GT = re.compile(r"\b(guatemala|gt)\b", re.I)

def _try_youtube_fallback(user_msg: str) -> Optional[str]:
    if not _YT_WORDS.search(user_msg or ""):
        return None
    region = "GT" if _COUNTRY_GT.search(user_msg or "") else "US"
    init_res = yt_execute_tool("yt_init", {})
    if isinstance(init_res, dict) and init_res.get("error"):
        return f"No pude inicializar YouTube: {init_res.get('error')}"
    pop = yt_execute_tool("yt_fetch_most_popular", {"region": region, "limit": 10})
    if isinstance(pop, dict) and pop.get("error"):
        return f"No pude obtener tendencias: {pop.get('error')}"
    items = (pop or {}).get("items") or []
    if not items:
        return f"No encontré tendencias para región {region}."
    lines = [f"Top en {region}:"]
    for i, v in enumerate(items[:10], 1):
        lines.append(f"{i}. {v.get('title')} — {v.get('channelTitle')} (views: {v.get('views')})")
    return "\n".join(lines)

# Detectar si el texto parece intención Git
_GIT_HINT = re.compile(r"\b(repo|repositorio|readme|commit|push|remoto|branch)\b", re.I)

def _try_git_fallback(user_msg: str) -> Optional[str]:
    if not _GIT_HINT.search(user_msg or ""):
        return None
    try:
        intent = parse_intent(user_msg)
        if not intent:
            return None
        res = execute_intent(intent, allowed_dirs=ALLOWED_DIRS_DEFAULT)
        return str(res)
    except Exception as e:
        return f"No pude ejecutar acción Git por fallback: {e}"


# Servicio de chat con tool-callin
class ToolCallingChatService:
    def __init__(self, model: str = "gpt-4o-mini", allowed_dirs: Optional[List[str]] = None, client: OpeniaGPT4ominiClient | None = None, logger: JsonlLogger | None = None):
        self.llm = client or OpeniaGPT4ominiClient(model=model)
        self.model = self.llm.model
        self.allowed_dirs = allowed_dirs or ALLOWED_DIRS_DEFAULT
        self.sessions: Dict[str, str] = {}  # session_id -> prev_response_ids
        self.logger = logger or JsonlLogger()

    def _wait_until_ready(self, resp, *, poll_interval=0.25, timeout=60.0):
        rid = resp.id
        t0 = time.time()
        status = getattr(resp, "status", None)
        while status in ("in_progress", "queued") or status is None:
            if time.time() - t0 > timeout:
                break
            time.sleep(poll_interval)
            resp = self.llm.client.responses.retrieve(rid)
            status = getattr(resp, "status", None)
        _dbg("wait_until_ready ->", status)
        return resp

    def _handle_required_action(self, resp):
        guard = 0
        while getattr(resp, "status", None) == "requires_action" and guard < 8:
            guard += 1
            tcalls = _extract_tool_calls(resp)
            _dbg("required_action tool_calls:", tcalls)
            if not tcalls:
                _dbg("required_action (sin tool_calls) payload:", getattr(resp, "required_action", None))
                break

            outputs = []
            for tc in tcalls:
                name = _tc_get(tc, "name")
                args_json = _tc_get(tc, "arguments", "{}")
                tc_id = _tc_get(tc, "id")
                try:
                    args = json.loads(args_json or "{}")
                except Exception:
                    args = {}

                self.logger.event("tool", "call",
                    session_id=None,
                    turn=None,
                    tool={"name": name, "args": args, "id": tc_id}
                )

                _dbg("-> exec tool:", name, "id:", tc_id, "args:", args)

                if name and name.startswith("git_"):
                    result = _exec_git_tool(name, args, self.allowed_dirs)

                elif name and name.startswith("yt_"):
                    result = yt_execute_tool(name, args)
                    # Si no estaba inicializado, init y retry
                    msg = (isinstance(result, dict) and str(result.get("error", "")).lower()) or ""
                    if "no está inicializado" in msg or "no esta inicializado" in msg:
                        _dbg("YouTube no inicializado -> yt_init + retry", name)
                        _ = yt_execute_tool("yt_init", {})
                        result = yt_execute_tool(name, args)
                
                else:
                    result = {"error": f"Tool desconocida: {name}"}

                self.logger.event("tool", "result",
                    session_id=None,
                    turn=None,
                    tool={"name": name, "id": tc_id},
                    result_preview=str(result)[:800]
                )

                outputs.append({
                    "tool_call_id": tc_id,
                    "output": json.dumps(result, ensure_ascii=False)
                })

            resp = self.llm.client.responses.submit_tool_outputs(
                response_id=resp.id,
                tool_outputs=outputs,
            )
            resp = self._wait_until_ready(resp)
        return resp

    def _drain_or_drop(self, prev_id: Optional[str]) -> Optional[str]:
        if not prev_id:
            return None
        try:
            r = self.llm.client.responses.retrieve(prev_id) 
            r = self._wait_until_ready(r)
            if getattr(r, "status", None) == "requires_action":
                r = self._handle_required_action(r)
            if getattr(r, "status", None) == "completed":
                return prev_id
            _dbg("drain_or_drop: dropping prev (status=", getattr(r, "status", None), ")")
            return None
        except Exception as e:
            _dbg("drain_or_drop error:", e)
            return None

    def ask(self, session_id: str, user_msg: str, max_output_tokens: int = 700) -> str:
        prev_id_clean = self._drain_or_drop(self.sessions.get(session_id))

        self.logger.event(
            "chat", "request",
            session_id=session_id,
            turn=None,
            request={"text": user_msg, "model": self.model}
        )


        # Enviar el input como content parts
        user_input_parts = [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": user_msg}
                ]
            }
        ]

        create_kwargs = dict(
            model=self.model,
            input=user_input_parts,
            max_output_tokens=max_output_tokens,
            tools=ALL_TOOLS,
            tool_choice="auto",
            instructions=SYSTEM_PROMPT,
            store=True,
        )
        if prev_id_clean:
            create_kwargs["previous_response_id"] = prev_id_clean

        yt_int = parse_yt_intent(_norm_text(user_msg))
        if yt_int:
            text = run_yt_intent(yt_int)
            self.logger.event("yt", "intent",
                session_id=session_id,
                turn=None,
                intent=yt_int,
                result_preview=text[:400]
            )
            self.sessions[session_id] = None
            return text


        git_intent_text = _try_git_fallback(user_msg) #
        if git_intent_text:
            self.logger.event("git", "fallback_intent",
                session_id=session_id,
                turn=None,
                request={"text": user_msg},
                result_preview=git_intent_text[:400]
            )
            self.sessions[session_id] = None
            return git_intent_text

        resp = self.llm.client.responses.create(**create_kwargs)
        self.logger.event("llm", "responses.create",
            session_id=session_id,
            request={"input": user_input_parts, "tools_count": len(ALL_TOOLS)}
        )


        _dbg("create status:", getattr(resp, "status", None))

        resp = self._wait_until_ready(resp)
        self.logger.event("llm", "poll",
            session_id=session_id,
            response={"id": resp.id, "status": getattr(resp, "status", None)}
        )

        resp = self._handle_required_action(resp)

        text = _collect_text(resp)
        _dbg("final status:", getattr(resp, "status", None), "text len:", len(text))

        # Fallbacks si quedo vacio
        if text.startswith("(sin contenido"):
            # Git por intención
            git_alt = _try_git_fallback(user_msg)
            if git_alt:
                text = git_alt
            else:
                #  YouTubw
                yt_alt = _try_youtube_fallback(user_msg)
                if yt_alt:
                    text = yt_alt

        # log
        self.logger.event(
            "chat", "response",
            session_id=session_id,
            turn=None,
            response={
                "id": resp.id,
                "status": getattr(resp, "status", None),
                "text": text,
                "model": self.model,
            },
            request={"text": user_msg},
        )
        self.sessions[session_id] = resp.id
        return text
