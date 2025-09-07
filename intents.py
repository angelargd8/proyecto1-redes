from dataclasses import dataclass
from typing import Optional, Union
import re, os

@dataclass
class CreateRepoIntent:
    repo_path: str
    readme_text: str
    commit_msg: str

@dataclass
class UpdateReadmeIntent:
    repo_path: str
    readme_text: str
    commit_msg: str

@dataclass
class PushIntent:
    repo_path: str
    remote_url: str
    branch: str = "main"

@dataclass
class SetWorkingDirIntent:
    repo_path: str

Intent = Union[CreateRepoIntent, UpdateReadmeIntent, PushIntent, SetWorkingDirIntent]

# helpersss
# Conectores de slot (ruta, texto, commit)
_TERMINATORS = (
    r'(?=\s+(?:y|e|con|hacer(?:le)?|haga|haz|commit|al\s+remoto|remoto\s+es|url\s+remoto|remote\s+url|'
    r'en\s+la\s+branch|la\s+rama|rama|branch|que|el\s+texto|texto|el\s+contenido|contenido)\b|$)'
)

def _unquote(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith('“') and s.endswith('”')):
        return s[1:-1].strip()
    return s

def _clean_path(p: str) -> str:
    p = _unquote(p)
    p = p.strip().rstrip(" .")
    return os.path.normpath(p)

def _strip_urls(text: str) -> str:
    return re.sub(r'https?://\S+|git@[^:\s]+:[^\s]+\b', ' ', text)


def _extract_name(text: str) -> Optional[str]:
    m = re.search(r'\bque\s+se\s+llame\s+([A-Za-z0-9._\-]+)\b', text, re.IGNORECASE)
    return m.group(1) if m else None


def _extract_path(text: str) -> Optional[str]:
    """
    Soporta:
      - en "C:/..."; en C:/...
      - del repo "C:/..."; del repo C:/...
      - al repositorio "C:/..."; al repositorio C:/...
    Corta antes de 'al remoto', 'branch', 'el texto', etc.
    """
    patterns = [
        r'\ben\s+["“]([^"”\r\n]+)["”]' + _TERMINATORS,
        r'\bdel\s+(?:repo|repositorio)\s+["“]([^"”\r\n]+)["”]' + _TERMINATORS,
        r'\bal\s+(?:repo|repositorio)\s+["“]([^"”\r\n]+)["”]' + _TERMINATORS,

        r'\ben\s+([A-Za-z]:[\\/][^:"<>|?\r\n]+?)' + _TERMINATORS,
        r'\bdel\s+(?:repo|repositorio)\s+([A-Za-z]:[\\/][^:"<>|?\r\n]+?)' + _TERMINATORS,
        r'\bal\s+(?:repo|repositorio)\s+([A-Za-z]:[\\/][^:"<>|?\r\n]+?)' + _TERMINATORS,
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
        if m:
            return _clean_path(m.group(1))

    # Fallback: ultima ruta absoluta
    no_urls = _strip_urls(text)
    m_all = list(re.finditer(r'([A-Za-z]:[\\/][^:"<>|?\r\n]+)', no_urls))  # nota: ':' EXCLUIDO
    if m_all:
        cand = m_all[-1].group(1)
        
        cand = re.sub(r'\s+(?:al\s+remoto|link|url|enlace|en\s+la\s+branch|branch|el\s+texto|texto|el\s+contenido|contenido)\b.*$',
                      '', cand, flags=re.IGNORECASE)
        return _clean_path(cand)
    return None

def _extract_readme_text(text: str) -> Optional[str]:
    """
    Soporta:
      - 'readme que diga: ...'
      - 'el texto: ...'
      - 'README "..."'
      (sin comillas también; corta en conectores)
    """
    m = re.search(
        r'\breadme\s+que\s+dig[aá]\s*:?\s*(.+?)' + _TERMINATORS,
        text, re.IGNORECASE | re.DOTALL
    )
    if m:
        return _unquote(m.group(1).strip())

    m = re.search(
        r'\bel\s+texto\s*:?\s*(.+?)' + _TERMINATORS,
        text, re.IGNORECASE | re.DOTALL
    )
    if m:
        return _unquote(m.group(1).strip())

    m = re.search(r'\bREADME\b\s*["“](.+?)["”]', text, re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip()

    # 'contenido: ...' (alias)
    m = re.search(
        r'\bcontenido\s*:?\s*(.+?)' + _TERMINATORS,
        text, re.IGNORECASE | re.DOTALL
    )
    if m:
        return _unquote(m.group(1).strip())

    return None

def _extract_commit_msg(text: str) -> Optional[str]:
    """
    Soporta:
      - 'commit que diga: ...'
      - 'commit: ...'
      - 'haga/haz/hacer(le) un commit ...'
      - 'commit ...'
    """
    m = re.search(
        r'\bcommit\s+que\s+dig[aá]\s*:?\s*(.+?)' + _TERMINATORS,
        text, re.IGNORECASE | re.DOTALL
    )
    if m:
        return _unquote(m.group(1).strip())

    m = re.search(
        r'\bcommit\s*:\s*(.+?)' + _TERMINATORS,
        text, re.IGNORECASE | re.DOTALL
    )
    if m:
        return _unquote(m.group(1).strip())

    m = re.search(
        r'\b(?:haga|haz|hacer(?:le)?)\s+un\s+commit\s+(.+?)' + _TERMINATORS,
        text, re.IGNORECASE | re.DOTALL
    )
    if m:
        return _unquote(m.group(1).strip())

    m = re.search(
        r'\bcommit\s+(.+?)' + _TERMINATORS,
        text, re.IGNORECASE | re.DOTALL
    )
    if m:
        return _unquote(m.group(1).strip())

    return None

def _extract_remote(text: str) -> Optional[str]:
    m = re.search(r'(https?://[^\s]+|git@[^:\s]+:[^\s]+\.git)', text, re.IGNORECASE)
    return m.group(1).strip() if m else None

def _extract_branch(text: str) -> Optional[str]:
    """
    Soporta:
      - 'en la branch main'
      - 'en la branch del main'
      - 'branch: main'
      - 'rama main'
    """
    m = re.search(r'\b(?:en\s+la\s+)?branch(?:\s*:\s*|\s+)(?:del\s+)?([A-Za-z0-9._\-./]+)\b',
                  text, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r'\brama(?:\s*:\s*|\s+)(?:del\s+)?([A-Za-z0-9._\-./]+)\b',
                  text, re.IGNORECASE)
    return m.group(1) if m else None

# parse_intent
def parse_intent(user_text: str) -> Optional[Intent]:
    t = user_text.strip()

    # CREATE REPO
    if re.search(r'\b(crea|crear|init|inicializa)\b.*\b(repo|repositorio)\b', t, re.IGNORECASE) or \
       (re.search(r'\bque\s+se\s+llame\b', t, re.IGNORECASE) and re.search(r'\ben\s+', t, re.IGNORECASE)):
        base = _extract_path(t)
        name = _extract_name(t)
        readme = _extract_readme_text(t) or "# README\n"
        msg = _extract_commit_msg(t) or "chore: init"
        if base:
            repo_path = base
            if name and os.path.isdir(base):
                repo_path = os.path.join(base, name)
            return CreateRepoIntent(repo_path=repo_path, readme_text=readme, commit_msg=msg)

    #  UPDATE README 
    if re.search(r'\b(actualiza|update|escribe|modifica)\b.*\breadme\b', t, re.IGNORECASE) or \
       re.search(r'\bescribe\s+en\s+el\s+readme\b', t, re.IGNORECASE):
        # Soporta "en C:/..." y "del repo C:/..."
        p = _extract_path(t)
        readme = _extract_readme_text(t)
        msg = _extract_commit_msg(t) or "docs: update README"
        if p and readme:
            return UpdateReadmeIntent(repo_path=p, readme_text=readme, commit_msg=msg)

    # PUSH
    if re.search(r'\bpush\b', t, re.IGNORECASE):
        p = _extract_path(t)
        remote = _extract_remote(t)
        branch = _extract_branch(t) or "main"
        if p and remote:
            return PushIntent(repo_path=p, remote_url=remote, branch=branch)

    # SET WORKING DIR
    if re.search(r'\b(usa|establece|set|cambia)\b.*\b(carpeta|ruta|directorio|working\s*dir)\b', t, re.IGNORECASE):
        p = _extract_path(t)
        if p:
            return SetWorkingDirIntent(repo_path=p)

    return None
