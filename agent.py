from __future__ import annotations

import json
import re
from typing import Optional, Dict, Any, List

from client import OpenAIResponsesClient
from mcp_manager import MCPMultiplexer


DEFAULT_SYSTEM = (
    "Eres un agente que puede usar herramientas MCP.\n"
    "CUANDO NECESITES UNA HERRAMIENTA, EMITE **UN ÚNICO** OBJETO JSON EXACTO:\n"
    '{"action":"tool_call","server":"<nombre-del-servidor>","tool":"<tool>","args":{...}}\n'
    "- JSON válido: comillas dobles, claves entre comillas, sin comentarios.\n"
    "- No describas lo que vas a hacer; emite el tool_call directamente.\n"
    "- Tras la OBSERVACIÓN del resultado, responde con un resumen breve o emite el siguiente tool_call.\n"
)

#  Normalizaciones "JSON-ish" 

_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)
_OBJ_RE   = re.compile(r"(\{[\s\S]*?\})")  # no-greedy

def _normalize_quotes(s: str) -> str:
    # comillas rectas
    return s.replace("“","\"").replace("”","\"").replace("‘","'").replace("’","'")

def _strip_fences(text: str) -> str:
    if not text: return ""
    m = _FENCE_RE.search(text)
    return m.group(1) if m else text

def _jsonish_to_json(s: str) -> str:
    s = _normalize_quotes(s)
    s = re.sub(r"(?m)//.*$", "", s)                       # quita // comentarios
    s = s.replace("\t", " ").replace("\r", "")
    s = s.replace("'", '"')                                # comillas simples a dobles
    s = re.sub(r'([{\s,])\s*([A-Za-z_]\w*)\s*:', r'\1"\2":', s)  # clave a "clave":
    return s.strip()

#  Extractores de tool_call 

def _safe_json_load(s: str) -> Optional[dict]:
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None

def _looks_like_tool_call(obj: dict) -> bool:
    return (
        obj.get("action") == "tool_call"
        and isinstance(obj.get("server"), str) # para que tome cualquier mcp
        and isinstance(obj.get("tool"), str)
        and isinstance(obj.get("args"), dict)
    )

def _stack_extract_first_braced_block(s: str) -> Optional[str]:
    """Extrae el primer bloque {...} balanceado usando una pila (tolerante a texto alrededor)."""
    start = s.find("{")
    if start == -1:
        return None
    stack = 0
    in_str = False
    esc = False
    for i, ch in enumerate(s[start:], start):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                stack += 1
            elif ch == "}":
                stack -= 1
                if stack == 0:
                    return s[start:i+1]
    return None

def _extract_first_tool_call(text: str) -> Optional[Dict[str, Any]]:
    """
    Estrategia en cascada:
    1) Intentar parsear TODO el texto (por si viene solo el objeto).
    2) Buscar por regex objetos {..} no-greedy y probar cada uno.
    3) Si falló, usar parser por pila para aislar el primer bloque balanceado.
    4) En cada intento, probar versión original y versión jsonish-normalizada.
    """
    if not text:
        return None
    s = _strip_fences(_normalize_quotes(text.strip()))

    # 1) todo el texto
    for cand in (s, _jsonish_to_json(s)):
        obj = _safe_json_load(cand)
        if obj and _looks_like_tool_call(obj):
            return obj

    # 2) regex no-greedy para objetos incrustados/pegados
    for m in _OBJ_RE.finditer(s):
        raw = m.group(1).strip()
        for cand in (raw, _jsonish_to_json(raw)):
            obj = _safe_json_load(cand)
            if obj and _looks_like_tool_call(obj):
                return obj

    # 3) parser por pila (más tolerante a llaves internas/narrativa alrededor)
    block = _stack_extract_first_braced_block(s)
    if block:
        for cand in (block, _jsonish_to_json(block)):
            obj = _safe_json_load(cand)
            if obj and _looks_like_tool_call(obj):
                return obj

    # 4) último intento: si existe la firma "action":"tool_call", recorta desde ahí
    sig = '"action":"tool_call"'
    i = s.find(sig)
    if i != -1:
        pre = s.rfind("{", 0, i)
        post = s.find("}", i)
        if pre != -1 and post != -1:
            frag = s[pre:post+1]
            for cand in (frag, _jsonish_to_json(frag)):
                obj = _safe_json_load(cand)
                if obj and _looks_like_tool_call(obj):
                    return obj

    return None

# ----------------------- Agente plan–act–observe -----------------------

class MCPAgent:
    def __init__(
        self,
        llm: OpenAIResponsesClient,
        mcp: MCPMultiplexer,
        *,
        max_steps: int = 4,
        system_prompt: str | None = None,
    ):
        self.llm = llm
        self.mcp = mcp
        self.max_steps = max_steps
        self.prev_response_id: Optional[str] = None
        self.system_prompt = system_prompt or DEFAULT_SYSTEM

    def _build_input(self, user_msg: str, observation: Optional[str] = None) -> List[Dict[str, Any]]:
        parts: List[Dict[str, Any]] = [
            {"role": "system", "content": [{"type": "input_text", "text": self.system_prompt}]},
            {"role": "user", "content": [{"type": "input_text", "text": user_msg}]},
        ]
        if observation:
            parts.append({
                "role": "system",
                "content": [{"type": "input_text", "text": f"OBSERVACIÓN (resultado de la herramienta): {observation}"}],
            })
        return parts

    def run(self, user_msg: str, *, max_output_tokens: int = 700) -> str:
        observation: Optional[str] = None
        final_answer: Optional[str] = None
        last_tool_result: Optional[dict] = None

        for _ in range(self.max_steps):
            parts = self._build_input(user_msg, observation)
            resp = self.llm.create(
                parts,
                previous_response_id=self.prev_response_id,
                max_output_tokens=max_output_tokens,
            )
            resp = self.llm.wait_until_ready(resp)
            text = self.llm.collect_text(resp).strip()
            self.prev_response_id = resp.id

            tool_req = _extract_first_tool_call(text)
            if not tool_req:
                final_answer = text
                break

            server = tool_req.get("server")
            tool = tool_req.get("tool")
            args = tool_req.get("args") or {}

            # Ejecutar UNA tool
            try:
                tool_res = self.mcp.call_tool_sync(server, tool, args)
            except Exception as e:
                tool_res = {"error": str(e)}

            last_tool_result = tool_res
            observation = json.dumps(tool_res, ensure_ascii=False)[:16000]

        if final_answer:
            return final_answer
        if last_tool_result is not None:
            pretty = json.dumps(last_tool_result, ensure_ascii=False, indent=2)
            return f"(Sin respuesta final del modelo; devolviendo resultado de la herramienta)\n{pretty}"
        return "(Sin respuesta del agente)"
