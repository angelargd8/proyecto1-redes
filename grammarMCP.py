import asyncio
import json
import os
from typing import List, Dict, Any

import language_tool_python
import mcp
from mcp.server.fastmcp import FastMCP
from dataclasses import dataclass

SUPPORTED = {"es", "en", "pt", "fr", "de", "it"}

@dataclass
class Issue:
    offset: int
    length: int
    message: str
    rule: str
    replacements: List[str]

def _mk_tool(lang: str) -> language_tool_python.LanguageTool:
    lang = (lang or "es").lower()
    if lang not in SUPPORTED:
        # fallback: es/en
        lang = "es" if lang.startswith("es") else "en"
    #api pagada
    # return language_tool_python.LanguageToolPublicAPI(lang)
    return language_tool_python.LanguageTool(lang)  #local

def _check_text(text: str, lang: str) -> List[Issue]:
    tool = _mk_tool(lang)
    matches = tool.check(text or "")
    out: List[Issue] = []
    for m in matches:
        out.append(Issue(
            offset=m.offset,
            length=m.errorLength,
            message=m.message,
            rule=m.ruleId,
            replacements=m.replacements[:5] if m.replacements else []
        ))
    return out

def _apply_suggestions(text: str, issues: List[Issue], aggressive=False) -> str:
    """
    Aplica primera (o mejor) sugerencia de cada issue, de derecha a izquierda.
    Si aggressive=True intenta preferir la sugerencia más larga (más “arregladora”).
    """
    s = text
    # aplicar de mayor offset a menor para no invalidar índices
    for iss in sorted(issues, key=lambda x: x.offset, reverse=True):
        rep = ""
        if iss.replacements:
            rep = max(iss.replacements, key=len) if aggressive else iss.replacements[0]
        if iss.length <= 0:
            # insercion 
            s = s[:iss.offset] + rep + s[iss.offset:]
        else:
            s = s[:iss.offset] + rep + s[iss.offset + iss.length:]
    return s

APPmcp = FastMCP("grammar-mcp", "MCP server for grammar checking/fixing with LanguageTool.")

@APPmcp.tool()
#Devuelve los errores gramaticales/ortográficos encontrados.
def gram_check(text: str, lang: str = "es") -> Dict[str, Any]:
    issues = _check_text(text, lang)
    return {
        "lang": lang,
        "count": len(issues),
        "issues": [iss.__dict__ for iss in issues],
    }

@APPmcp.tool()
#Corrige el texto aplicando sugerencias. aggressive=True aplica sugerencias más “largas”.
def gram_fix(text: str, lang: str = "es", aggressive: bool = False) -> Dict[str, Any]:

    issues = _check_text(text, lang)
    fixed = _apply_suggestions(text, issues, aggressive=aggressive)
    return {
        "lang": lang,
        "original_len": len(text or ""),
        "fixed_len": len(fixed),
        "changes": len(issues),
        "fixed_text": fixed,
    }

@APPmcp.tool()
#Lee un archivo, lo corrige y lo guarda. Crea backup .bak si backup=True.
def gram_fix_file(path: str, lang: str = "es", backup: bool = True) -> Dict[str, Any]:

    if not os.path.isfile(path):
        return {"error": f"File not found: {path}"}
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        txt = f.read()
    issues = _check_text(txt, lang)
    fixed = _apply_suggestions(txt, issues, aggressive=False)
    if backup:
        with open(path + ".bak", "w", encoding="utf-8") as b:
            b.write(txt)
    with open(path, "w", encoding="utf-8") as f:
        f.write(fixed)
    return {
        "path": path,
        "lang": lang,
        "changes": len(issues),
        "bytes_written": len(fixed.encode("utf-8")),
        "backup": path + ".bak" if backup else None,
    }

if __name__ == "__main__":
    # stdio server
    APPmcp.run()
