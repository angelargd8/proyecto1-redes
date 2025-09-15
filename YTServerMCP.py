from __future__ import annotations
import json, os, sys
from typing import Any, Dict
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv 

try:    
    load_dotenv()
    print(f"[YTServerMCP] .env cargado; YOUTUBE_API_KEY={'YES' if os.getenv('YOUTUBE_API_KEY') else 'NO'}", file=sys.stderr)
except Exception as e:
    print(f"[YTServerMCP] Advertencia: no se pudo cargar .env ({e})", file=sys.stderr)

from YTtool import (
    yt_init, yt_list_regions, yt_list_categories, yt_fetch_most_popular,
    yt_register_keywords, yt_search_recent, yt_calc_trends, yt_trend_details,
    yt_export_report,
)


mcp = FastMCP("youtube-mcp")

STATE_DIR = os.path.join(os.path.dirname(__file__), ".yt_state")
os.makedirs(STATE_DIR, exist_ok=True)

def _state_path(name: str) -> str:
    return os.path.join(STATE_DIR, name)

def _load_json(name: str, default):
    try:
        p = _state_path(name)
        if os.path.isfile(p):
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default

def _save_json(name: str, data):
    try:
        with open(_state_path(name), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[YTServerMCP] WARN save {name}: {e}", file=sys.stderr, flush=True)

def _get_saved_keywords() -> list[str]:
    return _load_json("keywords.json", [])

def _set_saved_keywords(kws: list[str]) -> None:
    # normaliza y ordena para evitar duplicados
    norm = sorted({(k or "").strip() for k in kws if (k or "").strip()})
    _save_json("keywords.json", norm)

def _save_last_search(payload: dict) -> None:
    _save_json("last_search.json", payload or {})

def _save_last_calc(payload: dict) -> None:
    _save_json("last_calc.json", payload or {})

async def _ensure_keywords_loaded_for_this_process():
    try:
        saved_kws = _get_saved_keywords()
        if saved_kws:
            await _wrap(yt_register_keywords)({"keywords": saved_kws})
    except Exception as e:
        print(f"[YTServerMCP] WARN ensure keywords: {e}", file=sys.stderr, flush=True)

def _wrap(fn):
    async def _inner(args: Dict[str, Any] | None = None):
        args = args or {}
        try:
            res = fn(args) 
            print(f"[YTServerMCP] result {fn.__name__} -> {res}", file=sys.stderr, flush=True)
            
            return res
        except Exception as e:
            print(f"[YTServerMCP] ERROR en {fn.__name__}: {e}", file=sys.stderr, flush=True)
            return {"error": f"{fn.__name__} falló: {e}"}
    return _inner

@mcp.tool("yt_init", description="Inicializa YouTube usando siempre la API key de .env (YOUTUBE_API_KEY).")
async def tool_yt_init():
    api_key = os.getenv("YOUTUBE_API_KEY", "")
    if not api_key:
        return {"error": "No se encontró YOUTUBE_API_KEY en el .env"}

    res = await _wrap(yt_init)({"api_key": api_key})

    # keywords
    try:
        saved_kws = _get_saved_keywords()
        if saved_kws:
            _ = await _wrap(yt_register_keywords)({"keywords": saved_kws})
    except Exception as e:
        print(f"[YTServerMCP] WARN re-register keywords: {e}", file=sys.stderr, flush=True)

    return res

@mcp.tool("yt_list_regions", description="Lista códigos de región (i18nRegions).")
async def tool_yt_list_regions():
    return await _wrap(yt_list_regions)({})

@mcp.tool("yt_list_categories", description="Lista categorías por región.")
async def tool_yt_list_categories(region: str = "GT"):
    return await _wrap(yt_list_categories)({"region": region})

@mcp.tool("yt_fetch_most_popular", description="Top de tendencias por país.")
async def tool_yt_fetch_most_popular(
    region: str = "GT",
    categoryId: str | None = None,
    max_pages: int = 1,
    limit: int = 10,
):
    return await _wrap(yt_fetch_most_popular)({
        "region": region, "categoryId": categoryId, "max_pages": max_pages, "limit": limit
    })

@mcp.tool("yt_register_keywords", description="Registra keywords a observar.")
async def tool_yt_register_keywords(keywords: list[str] | str):
    res = await _wrap(yt_register_keywords)({"keywords": keywords})
    try:
        kws = res.get("keywords") if isinstance(res, dict) else None
        if isinstance(kws, list) and kws:
            _set_saved_keywords(kws)
    except Exception as e:
        print(f"[YTServerMCP] WARN save keywords: {e}", file=sys.stderr, flush=True)
    return res


@mcp.tool("yt_search_recent", description="Busca videos recientes por keywords registradas.")
async def tool_yt_search_recent(days: int = 7, per_keyword: int = 10, order: str = "viewCount", region: str | None = None):
    await _ensure_keywords_loaded_for_this_process()
    payload = {"days": days, "per_keyword": per_keyword, "order": order}
    if region: payload["region"] = region
    res = await _wrap(yt_search_recent)(payload)
    try:
        if isinstance(res, dict) and not res.get("error"):
            _save_last_search(res)
    except Exception as e:
        print(f"[YTServerMCP] WARN save last_search: {e}", file=sys.stderr, flush=True)
    return res

@mcp.tool("yt_calc_trends", description="Calcula score de tendencias desde último search/trending.")
async def tool_yt_calc_trends(limit: int = 10):
    # asegurar keywords en el proceso actual
    await _ensure_keywords_loaded_for_this_process()

    # intento directo de cálculo
    res = await _wrap(yt_calc_trends)({"limit": limit})

    # si no hay datos, hacer un search mínimo y reintentar
    try:
        err = (isinstance(res, dict) and str(res.get("error", "")).lower()) or ""
        if "no hay datos" in err:
            saved_kws = _get_saved_keywords()
            if saved_kws:
                # pequeño search para poblar memoria del proceso
                await _wrap(yt_search_recent)({
                    "days": 7,
                    "per_keyword": max(10, limit),
                    "order": "viewCount"
                })
                # reintento
                res = await _wrap(yt_calc_trends)({"limit": limit})
    except Exception as e:
        print(f"[YTServerMCP] WARN calc fallback: {e}", file=sys.stderr, flush=True)

    # guardar último cálculo si procede
    try:
        if isinstance(res, dict) and not res.get("error"):
            _save_last_calc(res)
    except Exception as e:
        print(f"[YTServerMCP] WARN save last_calc: {e}", file=sys.stderr, flush=True)

    return res

@mcp.tool("yt_trend_details", description="Top N videos por score para una keyword.")
async def tool_yt_trend_details(keyword: str, top: int = 10):
    await _ensure_keywords_loaded_for_this_process()

    res = await _wrap(yt_trend_details)({"keyword": keyword, "top": top})
    try:
        err = (isinstance(res, dict) and str(res.get("error", "")).lower()) or ""
        if "no hay cálculo previo" in err or "no hay c\u00e1lculo previo" in err:
            # Hacer un search mínimo y un cálculo para reintentar
            saved_kws = _get_saved_keywords()
            if saved_kws and keyword:
                if keyword not in saved_kws:
                    await _wrap(yt_register_keywords)({"keywords": saved_kws + [keyword]})
                await _wrap(yt_search_recent)({"days": 7, "per_keyword": max(10, top), "order": "viewCount"})
                await _wrap(yt_calc_trends)({"limit": max(10, top)})
                res = await _wrap(yt_trend_details)({"keyword": keyword, "top": top})
    except Exception as e:
        print(f"[YTServerMCP] WARN details fallback: {e}", file=sys.stderr, flush=True)

    return res



@mcp.tool("yt_export_report", description="Exporta CSV del último cálculo.")
async def tool_yt_export_report(path: str | None = None):
    # asegurar keywords para este proceso
    await _ensure_keywords_loaded_for_this_process()

    # intento directo de export
    res = await _wrap(yt_export_report)({"path": path})

    # si el server dice que no hay cálculo previo, rehidratar y reintentar
    try:
        err = (isinstance(res, dict) and str(res.get("error", "")).lower()) or ""
        if "no hay cálculo previo" in err or "no hay c\u00e1lculo previo" in err:

            # intentar rehidratar el último search 
            try:
                last_search = _load_json("last_search.json", {})
            except Exception:
                last_search = {}

            # keywords guardadas
            saved_kws = _get_saved_keywords()
            if saved_kws:
                await _wrap(yt_register_keywords)({"keywords": saved_kws})

            # si no hay nada guardado, hace un search mínimo para poblar memoria
            if not last_search or not last_search.get("results"):
                await _wrap(yt_search_recent)({
                    "days": 7,
                    "per_keyword": 10,
                    "order": "viewCount"
                })
            else:
                # reproducir parámetros del último search
                params = {
                    "days": last_search.get("days", 7),
                    "per_keyword": last_search.get("per_keyword", 10),
                    "order": last_search.get("order", "viewCount")
                }
                if last_search.get("region"):
                    params["region"] = last_search["region"]
                await _wrap(yt_search_recent)(params)

            # rehidratar el último cálculo si tienes límite guardado
            try:
                last_calc = _load_json("last_calc.json", {})
                limit = int(last_calc.get("limit", 10)) if isinstance(last_calc, dict) else 10
            except Exception:
                limit = 10

            await _wrap(yt_calc_trends)({"limit": max(10, limit)})

            # reintentar export ahora que hay cálculo en memoria
            res = await _wrap(yt_export_report)({"path": path})

    except Exception as e:
        print(f"[YTServerMCP] WARN export fallback: {e}", file=sys.stderr, flush=True)

    # log
    try:
        if isinstance(res, dict) and not res.get("error"):
            if path and not res.get("path"):
                res["path"] = path  
            if res.get("path"):
                print(f"[YTServerMCP] Reporte exportado a {res['path']}", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"[YTServerMCP] WARN export report log: {e}", file=sys.stderr, flush=True)

    return res


if __name__ == "__main__":
    mcp.run()
