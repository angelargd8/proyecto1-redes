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