YOUTUBE_TOOLS = [
  {
    "type": "function",
    "name": "yt_init",
    "description": "Inicializa cliente de YouTube con api_key o desde variable de entorno YOUTUBE_API_KEY.",
    "parameters": {
      "type": "object",
      "properties": {
        "api_key": {"type": "string", "description": "API key de YouTube", "nullable": True}
      }
    }
  },
  {
    "type": "function",
    "name": "yt_list_regions",
    "description": "Lista códigos de región (i18nRegions).",
    "parameters": {"type": "object", "properties": {}}
  },
  {
    "type": "function",
    "name": "yt_list_categories",
    "description": "Lista categorías de video por región.",
    "parameters": {
      "type": "object",
      "properties": {
        "region": {"type": "string", "description": "ISO-3166, p.ej. GT", "default": "GT"}
      }
    }
  },
  {
    "type": "function",
    "name": "yt_fetch_most_popular",
    "description": "Top de tendencias por país.",
    "parameters": {
      "type": "object",
      "properties": {
        "region": {"type": "string", "default": "GT"},
        "categoryId": {"type": "string", "nullable": True},
        "max_pages": {"type": "integer", "default": 1},
        "limit": {"type": "integer", "default": 10}
      }
    }
  },
  {
    "type": "function",
    "name": "yt_register_keywords",
    "description": "Registra keywords a observar (array o string separado por comas).",
    "parameters": {
      "type": "object",
      "properties": {
        "keywords": {
          "oneOf": [
            {"type": "array", "items": {"type": "string"}, "minItems": 1},
            {"type": "string"}
          ]
        }
      },
      "required": ["keywords"]
    }
  },
  {
    "type": "function",
    "name": "yt_search_recent",
    "description": "Busca videos recientes por keywords registradas.",
    "parameters": {
      "type": "object",
      "properties": {
        "days": {"type": "integer", "default": 7},
        "per_keyword": {"type": "integer", "default": 10},
        "order": {"type": "string", "enum": ["date","viewCount","rating","relevance"], "default": "viewCount"},
        "region": {"type": "string", "nullable": True}
      }
    }
  },
  {
    "type": "function",
    "name": "yt_calc_trends",
    "description": "Calcula score de tendencias a partir del último yt_search_recent.",
    "parameters": {
      "type": "object",
      "properties": {}
    }
  },
  {
    "type": "function",
    "name": "yt_trend_details",
    "description": "Detalles de una keyword calculada (top N por score).",
    "parameters": {
      "type": "object",
      "properties": {
        "keyword": {"type": "string"},
        "top": {"type": "integer", "default": 10}
      },
      "required": ["keyword"]
    }
  },
  {
    "type": "function",
    "name": "yt_export_report",
    "description": "Exporta CSV del último cálculo (ruta opcional).",
    "parameters": {
      "type": "object",
      "properties": {
        "path": {"type": "string", "nullable": True}
      }
    }
  }
]
