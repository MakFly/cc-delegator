# Configuration Multi-Provider

Le serveur supporte maintenant plusieurs backends LLM via **arguments de ligne de commande**. La configuration se fait au niveau de l'installation dans `~/.claude.json`.

---

## Configuration Claude Code

Ajoutez le serveur à votre `~/.claude.json` ou `~/.claude/settings.json` :

### Anthropic Claude

```json
{
  "mcpServers": {
    "claude": {
      "type": "stdio",
      "command": "python3",
      "args": [
        "/path/to/glm-delegator/glm_mcp_server.py",
        "--provider", "anthropic-compatible",
        "--base-url", "https://api.anthropic.com/v1",
        "--api-key", "$ANTHROPIC_API_KEY",
        "--model", "claude-sonnet-4-20250514"
      ]
    }
  }
}
```

### OpenAI GPT

```json
{
  "mcpServers": {
    "openai": {
      "type": "stdio",
      "command": "python3",
      "args": [
        "/path/to/glm-delegator/glm_mcp_server.py",
        "--provider", "openai-compatible",
        "--base-url", "https://api.openai.com/v1",
        "--api-key", "$OPENAI_API_KEY",
        "--model", "gpt-4o"
      ]
    }
  }
}
```

### GLM via Z.AI

```json
{
  "mcpServers": {
    "glm": {
      "type": "stdio",
      "command": "python3",
      "args": [
        "/path/to/glm-delegator/glm_mcp_server.py",
        "--provider", "anthropic-compatible",
        "--base-url", "https://api.z.ai/api/anthropic",
        "--api-key", "$GLM_API_KEY",
        "--model", "glm-5"
      ]
    }
  }
}
```

> **Tip:** You can also use `glm-4.7` for the previous generation model.

### Ollama (Local)

```json
{
  "mcpServers": {
    "ollama": {
      "type": "stdio",
      "command": "python3",
      "args": [
        "/path/to/glm-delegator/glm_mcp_server.py",
        "--provider", "openai-compatible",
        "--base-url", "http://localhost:11434/v1",
        "--model", "llama3.1"
      ]
    }
  }
}
```

### Groq

```json
{
  "mcpServers": {
    "groq": {
      "type": "stdio",
      "command": "python3",
      "args": [
        "/path/to/glm-delegator/glm_mcp_server.py",
        "--provider", "openai-compatible",
        "--base-url", "https://api.groq.com/openai/v1",
        "--api-key", "$GROQ_API_KEY",
        "--model", "llama-3.3-70b-versatile"
      ]
    }
  }
}
```

### DeepInfra

```json
{
  "mcpServers": {
    "deepinfra": {
      "type": "stdio",
      "command": "python3",
      "args": [
        "/path/to/glm-delegator/glm_mcp_server.py",
        "--provider", "openai-compatible",
        "--base-url", "https://api.deepinfra.com/v1/openai",
        "--api-key", "$DEEPINFRA_API_KEY",
        "--model", "deepseek-ai/DeepSeek-V3"
      ]
    }
  }
}
```

---

## Arguments Disponibles

| Argument | Court | Description | Défaut |
|----------|-------|-------------|--------|
| `--provider` | `-p` | Type de provider | `anthropic-compatible` |
| `--base-url` | `-u` | URL de base de l'API | `https://api.z.ai/api/anthropic` |
| `--api-key` | `-k` | Clé API | `$GLM_API_KEY` ou `$Z_AI_API_KEY` |
| `--model` | `-m` | Nom du modèle (glm-4.7, glm-5...) | `glm-4.7` |
| `--api-version` | - | Version API (Anthropic) | `2023-06-01` |
| `--timeout` | - | Timeout en secondes | `600` |
| `--max-tokens` | - | Tokens max par réponse | `8192` |
| `--debug` | - | Activer le debug | `false` |

---

## Types de Providers

### OpenAI-compatible

Utilise le format `/v1/chat/completions`. Supporte :
- OpenAI
- DeepInfra
- TogetherAI
- Groq
- Ollama
- LM Studio
- vLLM
- Tout provider compatible OpenAI

### Anthropic-compatible

Utilise le format `/v1/messages`. Supporte :
- Anthropic
- Z.AI (GLM)
- Tout provider compatible Anthropic

---

## Plusieurs Serveurs

Vous pouvez configurer plusieurs serveurs avec différents providers dans `~/.claude.json` :

```json
{
  "mcpServers": {
    "claude-experts": {
      "type": "stdio",
      "command": "python3",
      "args": [
        "/path/to/glm-delegator/glm_mcp_server.py",
        "--provider", "anthropic-compatible",
        "--base-url", "https://api.anthropic.com/v1",
        "--api-key", "$ANTHROPIC_API_KEY",
        "--model", "claude-sonnet-4-20250514"
      ]
    },
    "ollama-local": {
      "type": "stdio",
      "command": "python3",
      "args": [
        "/path/to/glm-delegator/glm_mcp_server.py",
        "--provider", "openai-compatible",
        "--base-url", "http://localhost:11434/v1",
        "--model", "llama3.1"
      ]
    }
  }
}
```

---

## Test Local

Pour tester le serveur localement :

```bash
# GLM via Z.AI
python3 glm_mcp_server.py \
  --provider anthropic-compatible \
  --base-url https://api.z.ai/api/anthropic \
  --api-key $GLM_API_KEY \
  --model glm-4.7

# OpenAI
python3 glm_mcp_server.py \
  --provider openai-compatible \
  --base-url https://api.openai.com/v1 \
  --api-key $OPENAI_API_KEY \
  --model gpt-4o

# Ollama local
python3 glm_mcp_server.py \
  --provider openai-compatible \
  --base-url http://localhost:11434/v1 \
  --model llama3.1

# Avec debug
python3 glm_mcp_server.py --debug --provider anthropic-compatible --api-key $ANTHROPIC_API_KEY
```

---

## Variables d'Environnement

Les clés API peuvent être passées via variables d'environnement :

```bash
# Exportez vos clés
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."
export GLM_API_KEY="your_glm_key"
export GROQ_API_KEY="gsk_..."
```

Puis utilisez `$VAR_NAME` dans la configuration :

```json
{
  "args": [
    "--api-key", "$ANTHROPIC_API_KEY"
  ]
}
```

---

## Aide

```bash
python3 glm_mcp_server.py --help
```
