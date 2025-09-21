from __future__ import annotations
import os, json, math, csv, sys
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta, timezone

try:
    from googleapiclient.discovery import build 
except Exception:
    build = None

# cliente de YouTube
_YT = None
_STATE = {
    "keywords": [],             # lista de keywords registradas
    "last_search": {},          # keyword -> [ {video...}, ... ]
    "last_calc": {              # resultados de cálculo de tendencias
        "keywords": [],         # ranking de keywords
        "videos": []            # ranking de videos
    },
    "last_fetch_popular": [],   # Ultimo fetch de trending 
    }


# Utilidades
def _ok(msg: str = "ok", **extra) -> Dict[str, Any]:
    d = {"ok": True, "msg": msg}
    d.update(extra)
    return d

def _err(msg: str, **extra) -> Dict[str, Any]:
    d = {"error": msg}
    d.update(extra)
    return d

def _ensure_init() -> Optional[Dict[str, Any]]:
    if _YT is None:
        return _err("YouTube no está inicializado. Llama primero a yt_init(api_key) o define YOUTUBE_API_KEY.")
    return None

def _dt_iso_utc(d: datetime) -> str:
    # ISO 8601 con 'Z'
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _published_after_iso(days: int) -> str:
    return _dt_iso_utc(datetime.now(timezone.utc) - timedelta(days=max(0, days)))

def _as_int(x, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default

def _chunked(seq: List[str], n: int) -> List[List[str]]:
    return [seq[i:i+n] for i in range(0, len(seq), n)]

# Implementaciones de tools
def yt_init(args: Dict[str, Any]) -> Dict[str, Any]:
    global _YT
    if build is None:
        return _err("Falta dependencia: instala google-api-python-client")
    api_key = (args or {}).get("api_key") or os.getenv("YOUTUBE_API_KEY", "")
    if not api_key:
        return _err("YouTube no está inicializado: falta YOUTUBE_API_KEY en .env ")
    try:
        _YT = build("youtube", "v3", developerKey=api_key)
    except Exception as ex:
        return _err(f"Fallo creando cliente de YouTube: {ex}")
    return _ok("YouTube client listo.")


def yt_list_regions(args: Dict[str, Any]) -> Dict[str, Any]:
    e = _ensure_init()
    if e: return e
    try:
        resp = _YT.i18nRegions().list(part="snippet").execute()
        items = resp.get("items", [])
        if not items:
            return _err(
                "yt_list_regions devolvió 0 items. Revisa que tu API key esté correcta, "
                "que 'YouTube Data API v3' esté habilitada en tu proyecto, y que la key no tenga "
                "restricciones incompatibles (para scripts/servidor NO uses 'HTTP referrers')."
            )
        regions = [{"code": it.get("id"), "name": it.get("snippet", {}).get("name")} for it in items]
        return _ok("regions", regions=regions, count=len(regions))
    except Exception as ex:
        return _err(f"yt_list_regions falló: {ex}")

def yt_list_categories(args: Dict[str, Any]) -> Dict[str, Any]:
    """ Lista categorías de video por región """
    e = _ensure_init()
    if e: return e
    region = (args or {}).get("region") or "US"
    try:
        resp = _YT.videoCategories().list(part="snippet", regionCode=region).execute()
        cats = []
        for it in resp.get("items", []):
            if it.get("kind") == "youtube#videoCategory":
                cats.append({"id": it.get("id"), "title": it.get("snippet", {}).get("title")})
        return _ok("categories", region=region, categories=cats, count=len(cats))
    except Exception as ex:
        return _err(f"yt_list_categories falló: {ex}")

def yt_fetch_most_popular(args: Dict[str, Any]) -> Dict[str, Any]:
    e = _ensure_init()
    if e: return e
    region = (args or {}).get("region") or "GT"
    categoryId = (args or {}).get("categoryId")
    max_pages = _as_int((args or {}).get("max_pages", 1), 1)
    limit = _as_int((args or {}).get("limit", 10), 10)

    req = {
        "part": "snippet,statistics",
        "chart": "mostPopular",
        "regionCode": region,
        "maxResults": 50,
    }
    if categoryId:
        req["videoCategoryId"] = categoryId

    out: List[Dict[str, Any]] = []
    page = 0
    try:
        while page < max_pages:
            resp = _YT.videos().list(**req).execute()
            print(f"[yt_fetch_most_popular] API resp keys: {list(resp.keys())}", file=sys.stderr)
            items = resp.get("items", [])
            for it in items:
                out.append({
                    "videoId": it.get("id"),
                    "title": it.get("snippet", {}).get("title"),
                    "channelTitle": it.get("snippet", {}).get("channelTitle"),
                    "publishedAt": it.get("snippet", {}).get("publishedAt"),
                    "views": _as_int(it.get("statistics", {}).get("viewCount")),
                    "regionCode": region,
                })
            tok = resp.get("nextPageToken")
            if not tok:
                break
            req["pageToken"] = tok
            page += 1
    except Exception as ex:
        return _err(f"yt_fetch_most_popular falló: {ex}")

    if not out:
        return _err(f"No se recibieron videos en 'mostPopular' para region={region}")

    out = out[:max(1, limit)]
    _STATE["last_fetch_popular"] = out
    return _ok("most_popular", region=region, count=len(out), items=out)


def yt_register_keywords(args: Dict[str, Any]) -> Dict[str, Any]:
    """ Registra keywords (lista o string 'k1, k2') """
    kws = args.get("keywords") if args else None
    if not kws:
        return _err("Faltan 'keywords'.")
    if isinstance(kws, str):
        kws = [k.strip() for k in kws.split(",") if k.strip()]
    elif isinstance(kws, list):
        kws = [str(k).strip() for k in kws if str(k).strip()]
    else:
        return _err("Formato de 'keywords' inválido.")

    exist = set(_STATE["keywords"])
    for k in kws:
        exist.add(k)
    _STATE["keywords"] = sorted(exist)
    return _ok("keywords_registradas", keywords=_STATE["keywords"])


def yt_search_recent(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Busca videos recientes por cada keyword registrada.
    params: days (int), order ('date'|'viewCount'|'rating'|'relevance'), per_keyword (int), region (opcional)
    """
    e = _ensure_init()
    if e: return e
    if not _STATE["keywords"]:
        return _err("No hay keywords registradas. Llama primero a yt_register_keywords.")
    days = _as_int((args or {}).get("days", 7), 7)
    order = (args or {}).get("order") or "viewCount"
    per_keyword = _as_int((args or {}).get("per_keyword", 10), 10)
    region = (args or {}).get("region")

    published_after = _published_after_iso(days)
    all_results: Dict[str, List[Dict[str, Any]]] = {}
    try:
        for kw in _STATE["keywords"]:
            # search.list para obtener IDs
            sreq = {
                "part": "snippet",
                "q": kw,
                "type": "video",
                "maxResults": min(50, per_keyword),
                "order": order,
                "publishedAfter": published_after,
            }
            if region:
                sreq["regionCode"] = region
            sresp = _YT.search().list(**sreq).execute()
            video_ids = [it.get("id", {}).get("videoId") for it in sresp.get("items", []) if it.get("id")]
            video_ids = [vid for vid in video_ids if vid]

            #  videos.list para estadísticas
            details: List[Dict[str, Any]] = []
            for batch in _chunked(video_ids, 50):
                if not batch:
                    continue
                vresp = _YT.videos().list(
                    part="snippet,statistics,contentDetails",
                    id=",".join(batch)
                ).execute()
                for v in vresp.get("items", []):
                    stats = v.get("statistics", {}) or {}
                    snip = v.get("snippet", {}) or {}
                    details.append({
                        "videoId": v.get("id"),
                        "title": snip.get("title"),
                        "channelTitle": snip.get("channelTitle"),
                        "publishedAt": snip.get("publishedAt"),
                        "views": _as_int(stats.get("viewCount")),
                        "likes": _as_int(stats.get("likeCount")),
                        "comments": _as_int(stats.get("commentCount")),
                        "keyword": kw,
                    })
            all_results[kw] = details
    except Exception as ex:
        return _err(f"yt_search_recent falló: {ex}")

    _STATE["last_search"] = all_results
    total = sum(len(v) for v in all_results.values())
    return _ok("search_recent",
               keywords=_STATE["keywords"],
               total=total,
               results=all_results)  


def yt_calc_trends(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Calcula score simple:
      score_video = views / sqrt(horas_desde_publicacion + 1)
    Primero intenta con resultados de keywords (last_search).
    Si no hay, y existe last_fetch_popular (trending), calcula sobre eso.
    """
    limit = _as_int((args or {}).get("limit", 10), 10)

    source = "keywords" if _STATE.get("last_search") else ("most_popular" if _STATE.get("last_fetch_popular") else None)
    if not source:
        return _err("No hay datos. Ejecuta primero 'yt_search_recent' o 'yt_fetch_most_popular'.")

    now = datetime.now(timezone.utc)

    def hours_since(published_iso: str) -> float:
        try:
            dt = datetime.fromisoformat(published_iso.replace("Z", "+00:00"))
            return max(0.0, (now - dt).total_seconds() / 3600.0)
        except Exception:
            return 24.0

    videos_scored: List[Dict[str, Any]] = []

    if source == "keywords":
        for kw, vids in _STATE["last_search"].items():
            for v in vids:
                h = hours_since(v.get("publishedAt") or "")
                score = float(v.get("views", 0)) / math.sqrt(h + 1.0)
                vv = dict(v)
                vv["score"] = round(score, 3)
                videos_scored.append(vv)
    else:
        for v in _STATE["last_fetch_popular"]:
            h = hours_since(v.get("publishedAt") or "")
            score = float(v.get("views", 0)) / math.sqrt(h + 1.0)
            vv = dict(v)
            vv["score"] = round(score, 3)
            videos_scored.append(vv)

    videos_scored.sort(key=lambda x: x["score"], reverse=True)

    # Scores por keyword
    kw_scores: Dict[str, float] = {}
    for v in videos_scored:
        k = v.get("keyword")
        if k:
            kw_scores[k] = kw_scores.get(k, 0.0) + float(v["score"])

    kw_rank = [{"keyword": k, "score": round(s, 3)} for k, s in kw_scores.items()]
    kw_rank.sort(key=lambda x: x["score"], reverse=True)

    _STATE["last_calc"] = {"keywords": kw_rank, "videos": videos_scored}
    return _ok("calc_trends", keywords=kw_rank[:limit], top_videos=videos_scored[:limit])


def yt_trend_details(args: Dict[str, Any]) -> Dict[str, Any]:
    """ Devuelve detalle de una keyword (top N videos por score) """
    if not _STATE["last_calc"].get("videos"):
        return _err("No hay cálculo previo. Llama antes a yt_search_recent y yt_calc_trends.")

    kw = (args or {}).get("keyword")
    top = _as_int((args or {}).get("top", 10), 10)
    if not kw:
        return _err("Falta 'keyword'.")

    kwn = str(kw).strip().lower()
    filtered = [v for v in _STATE["last_calc"]["videos"] if str(v.get("keyword","")).strip().lower() == kwn]
    filtered.sort(key=lambda x: x["score"], reverse=True)
    return _ok("trend_details", keyword=kw, count=min(top, len(filtered)), items=filtered[:top])

def yt_export_report(args: Dict[str, Any]) -> Dict[str, Any]:
    """ Exporta CSV del último cálculo: columns = keyword, videoId, title, views, score """
    if not _STATE["last_calc"].get("videos"):
        return _err("No hay cálculo previo. Llama antes a yt_search_recent y yt_calc_trends.")

    path = (args or {}).get("path")
    if not path:
        base = os.path.splitext(os.path.abspath(__file__))[0]
        path = base + "_trends_report.csv"

    rows = _STATE["last_calc"]["videos"]
    try:
        with open(path, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["keyword", "videoId", "title", "channelTitle", "publishedAt", "views", "score"])
            for r in rows:
                w.writerow([
                    r.get("keyword",""),
                    r.get("videoId",""),
                    r.get("title",""),
                    r.get("channelTitle",""),
                    r.get("publishedAt",""),
                    r.get("views",0),
                    r.get("score",0.0),
                ])
        return _ok("export_report", path=path, rows=len(rows))
    except Exception as ex:
        return _err(f"yt_export_report falló: {ex}")


# Enrutador 
_TOOL_MAP = {
    "yt_init": yt_init,
    "yt_list_regions": yt_list_regions,
    "yt_list_categories": yt_list_categories,
    "yt_fetch_most_popular": yt_fetch_most_popular,
    "yt_register_keywords": yt_register_keywords,
    "yt_search_recent": yt_search_recent,
    "yt_calc_trends": yt_calc_trends,
    "yt_trend_details": yt_trend_details,
    "yt_export_report": yt_export_report,
}

def execute_tool_sync(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Punto de entrada síncrono
    Retorna siempre un dict serializable: {"ok":..., ...} o {"error": "..."}.
    """
    try:
        fn = _TOOL_MAP.get(tool_name)
        if not fn:
            return _err(f"Tool desconocida: {tool_name}")
        return fn(args or {})
    except Exception as ex:
        return _err(f"execute_tool_sync error: {ex}")
