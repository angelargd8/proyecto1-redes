# s
import os, json, uuid, datetime as dt
from typing import Any, Dict, Optional

def _utcnow():
    return dt.datetime.utcnow().isoformat() + "Z"


def _redact(x: Any):
    if isinstance(x, dict):
        return {k: ("***" if k.lower() in {"api_key","authorization","developerkey","token"} else _redact(v))
                for k, v in x.items()}
    if isinstance(x, list):
        return [_redact(v) for v in x]
    return x


def _to_jsonable(x: Any):
    # Tipos primitivos 
    if isinstance(x, (str, int, float, bool)) or x is None:
        return x
    # Estructuras
    if isinstance(x, dict):
        return {k: _to_jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, set)):
        return [_to_jsonable(v) for v in x]
    

    # OpenAI SDK usa pydantic que es una liberia para validar y transformar datos
    md = getattr(x, "model_dump", None)
    if callable(md):
        try:
            return {k: _to_jsonable(v) for k, v in md().items()}
        except Exception:
            pass
        
    # Dataclasses / objetos con __dict__
    if hasattr(x, "__dict__"):
        try:
            return {k: _to_jsonable(v) for k, v in x.__dict__.items() if not k.startswith("_")}
        except Exception:
            pass
    # Fallback: string
    return str(x)

class JsonlLogger:
    def __init__(self, path: str = "logs/app.jsonl", log_text: bool = True):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.f = open(path, "a", encoding="utf-8")
        self.log_text = log_text

    def write(self, event: Dict[str, Any]):
        ev = _redact(event)
        if not self.log_text:
            if "request" in ev and isinstance(ev["request"], dict):
                ev["request"]["text"] = "<omitted>"
            if "response" in ev and isinstance(ev["response"], dict):
                ev["response"]["text"] = "<omitted>"
        json.dump(_to_jsonable(ev), self.f, ensure_ascii=False)
        self.f.write("\n")
        self.f.flush()

    def event(self, channel: str, kind: str, session_id: Optional[str] = None,
              turn: Optional[int] = None, **kwargs):
        e = {
            "ts": _utcnow(),
            "id": str(uuid.uuid4()),
            "channel": channel,          # "llm" | "mcp" | "system"
            "kind": kind,                # "request" | "response" | "error" | "info"
            "session_id": session_id,
            "turn": turn,
        }
        e.update(kwargs)
        self.write(e)
