# Projet 1 : Use of existing protocol

# Remote server!: 
https://github.com/angelargd8/RemoteServerMCP 


# Description:
This project implements a CLI chatbot that acts as an MCP host and connects to multiple MCP servers (tools) to perform real actions: create and manage local Git repositories, read/write the filesystem, and explore YouTube trends. The chatbot uses an LLM to understand natural-language prompts and trigger tool calls automatically.

## Features
- **LLM connection** (OpenAI Responses API) with tool-calling.
- **Session context**: preserves conversation state across turns.
- **Structured logging**: JSONL logs of prompts, tool calls, outputs, and model responses.
- **Git & Filesystem tools** (MCP):
  - Create a repository in an allowed directory.
  - Write/update `README.md`.
  - Commit changes and push to a remote (HTTPS/SSH).
- **YouTube Trends (local MCP server)**:
  - Initialize YouTube client (API key).
  - List regions/categories.
  - Fetch “Most Popular” by region.
  - Register keywords and search recent videos by keyword(s).
  - Compute a simple trend score and get per-keyword “deep dives”.
  - Export results (CSV/JSON).



### Create the environment:

```
python3 -m venv .venv
```

## activate it:

```
source .venv/bin/activate
```

## download dependencies:

```
pip install -r requirements.txt
```

If you want to install it one by one:
```
pip install anthropic dotenv openai mpc "mcp[cli]" google-api-python-client
```


## Example prompts: 

- crea una carpteta en C:/Users/angel/OneDrive/Documentos/.universidad/.2025/s2/redes/ que se llame CARPETA

- puedes crear un repositorio que se llame pruebaMCP  en C:/Users/angel/OneDrive/Documentos/.universidad/.2025/s2/redes/ con un readme que diga: esto es un readme y hacerle un commit que diga: chore init

- Escribe en el README del repo C:/Users/angel/OneDrive/Documentos/.universidad/.2025/s2/redes/pruebaMCP el texto: Notas de uso y haz commit que diga docs: notes

- Haz push del repo C:/Users/angel/OneDrive/Documentos/.universidad/.2025/s2/redes/pruebaMCP al remoto https://github.com/angelargd8/pruebaMCP.git  en la branch main

## Example prompts for youtube api:
- lista códigos de region de youtube 
- dame el top de tendencias en youtube guatemala limite 15
- registra keywords: minecraft, marvel
- busca 10 videos por keyword de los ultimos 7 días en GT
- calcula tendencias top 5
- profundiza en marvel top 5
- calcula tendencias top 3
- exporta reporte csv
- dime el top de tendencias en youtube SV

## Example promps for zotero:
- Citame en APA esta URL: https://academia-lab.com/enciclopedia/modelo-basado-en-agentes/

- crea la referencia https://es.wikipedia.org/wiki/GNU/Linux

- haz la bibliografia de https://normas-apa.org/introduccion/que-son-las-normas-apa/



# References: 
- https://modelcontextprotocol.io/quickstart/server

Note: The next reference I  I am aware of is about anthropic. First I tried, but when I saw that I had to pay, I preferred OpenIA. So I just adapted the code from anthropic to OpenIA, it's not a big difference as you can see
- https://markaicode.com/claude-sonnet-4-python-api-integration/

