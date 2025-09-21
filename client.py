from __future__ import annotations
import os, time
from dataclasses import dataclass
from typing import Optional, Tuple
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

@dataclass
class LlmUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None

class OpenAIResponsesClient:
    def __init__(self, model: str = "gpt-4o-mini"):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("Falta OPENAI_API_KEY en el entorno")
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def create(self, input_parts, *, previous_response_id: Optional[str] = None, max_output_tokens: int = 700):
        kwargs = dict(model=self.model, input=input_parts, max_output_tokens=max_output_tokens, store=True)
        if previous_response_id:
            kwargs["previous_response_id"] = previous_response_id
        return self.client.responses.create(**kwargs)

    def retrieve(self, rid: str):
        return self.client.responses.retrieve(rid)

    def wait_until_ready(self, resp, *, poll_interval=0.25, timeout=60.0):
        rid = resp.id
        t0 = time.time()
        status = getattr(resp, "status", None)
        while status in ("in_progress", "queued") or status is None:
            if time.time() - t0 > timeout:
                break
            time.sleep(poll_interval)
            resp = self.client.responses.retrieve(rid)
            status = getattr(resp, "status", None)
        return resp

    @staticmethod
    def collect_text(resp) -> str:
        txt = getattr(resp, "output_text", None)
        if txt:
            return txt
        chunks = []
        out = getattr(resp, "output", None)
        if out:
            for item in out:
                for c in getattr(item, "content", []) or []:
                    t = getattr(c, "text", None)
                    if t:
                        chunks.append(t)
        return "\n".join(chunks) if chunks else ""


