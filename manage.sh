#!/usr/bin/env bash
#
# LLM Delegator MCP Manager
# Installer/Désinstaller le serveur MCP dans Claude Code
#

set -e

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MCP_SERVER_SCRIPT="$SCRIPT_DIR/glm_mcp_server.py"
CLAUDE_CONFIG_DIR="$HOME/.claude"
CLAUDE_CONFIG_FILE="$CLAUDE_CONFIG_DIR/settings.json"
CLAUDE_CONFIG_OLD="$CLAUDE_CONFIG_DIR/config.json"
CLAUDE_GLM_DIR="$HOME/.claude-glm"
CLAUDE_GLM_CONFIG="$CLAUDE_GLM_DIR/config.json"

# Fonctions d'affichage
info() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }
warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }

# Banner
banner() {
    echo -e "${BLUE}"
    echo "╔════════════════════════════════════════════════╗"
    echo "║     LLM Delegator MCP Manager                  ║"
    echo "║     Multi-Provider Expert Subagents            ║"
    echo "╚════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

# Vérifier les prérequis
check_prerequisites() {
    info "Vérification des prérequis..."

    # Vérifier Python
    if ! command -v python3 &> /dev/null; then
        error "Python 3 n'est pas installé"
        exit 1
    fi

    # Vérifier le fichier MCP
    if [[ ! -f "$MCP_SERVER_SCRIPT" ]]; then
        error "Fichier MCP introuvable: $MCP_SERVER_SCRIPT"
        exit 1
    fi

    success "Prérequis OK"
}

# Créer le répertoire ~/.claude-glm
setup_claude_glm_dir() {
    if [[ ! -d "$CLAUDE_GLM_DIR" ]]; then
        mkdir -p "$CLAUDE_GLM_DIR"
        success "Créé $CLAUDE_GLM_DIR"
    fi

    # Créer un fichier de configuration par défaut
    if [[ ! -f "$CLAUDE_GLM_CONFIG" ]]; then
        cat > "$CLAUDE_GLM_CONFIG" << 'EOF'
{
  "defaultProvider": "anthropic-compatible",
  "defaultBaseUrl": "https://api.anthropic.com/v1",
  "defaultModel": "claude-sonnet-4-20250514",
  "profiles": {
    "claude": {
      "provider": "anthropic-compatible",
      "baseUrl": "https://api.anthropic.com/v1",
      "model": "claude-sonnet-4-20250514",
      "apiKeyEnv": "ANTHROPIC_API_KEY"
    },
    "openai": {
      "provider": "openai-compatible",
      "baseUrl": "https://api.openai.com/v1",
      "model": "gpt-4o",
      "apiKeyEnv": "OPENAI_API_KEY"
    },
    "glm": {
      "provider": "anthropic-compatible",
      "baseUrl": "https://api.z.ai/api/anthropic",
      "model": "glm-5",
      "apiKeyEnv": "GLM_API_KEY"
    },
    "ollama": {
      "provider": "openai-compatible",
      "baseUrl": "http://localhost:11434/v1",
      "model": "llama3.1",
      "apiKeyEnv": ""
    }
  }
}
EOF
        success "Créé $CLAUDE_GLM_CONFIG"
    fi
}

# Trouver le fichier de configuration Claude
find_claude_config() {
    if [[ -f "$CLAUDE_CONFIG_FILE" ]]; then
        echo "$CLAUDE_CONFIG_FILE"
    elif [[ -f "$CLAUDE_CONFIG_OLD" ]]; then
        echo "$CLAUDE_CONFIG_OLD"
    else
        echo ""
    fi
}

# Installer le MCP
install_mcp() {
    banner

    check_prerequisites
    setup_claude_glm_dir

    # Demander le nom du serveur
    read -p "$(echo -e ${YELLOW}Nom du serveur MCP [default: llm-experts]: ${NC})" SERVER_NAME
    SERVER_NAME=${SERVER_NAME:-llm-experts}

    # Demander le profile à utiliser
    echo ""
    info "Profils disponibles :"
    echo "  1) claude    - Anthropic Claude (claude-sonnet-4)"
    echo "  2) openai    - OpenAI GPT-4"
    echo "  3) glm       - GLM-5 via Z.AI (also supports glm-4.7)"
    echo "  4) ollama    - Ollama local"
    echo "  5) custom    - Configuration personnalisée"
    read -p "$(echo -e ${YELLOW}Choix [1-5, default: 1]: ${NC})" PROFILE_CHOICE
    PROFILE_CHOICE=${PROFILE_CHOICE:-1}

    case $PROFILE_CHOICE in
        1) PROFILE="claude" ;;
        2) PROFILE="openai" ;;
        3) PROFILE="glm" ;;
        4) PROFILE="ollama" ;;
        5)
            read -p "$(echo -e ${YELLOW}Provider (openai-compatible/anthropic-compatible): ${NC})" CUSTOM_PROVIDER
            read -p "$(echo -e ${YELLOW}Base URL: ${NC})" CUSTOM_URL
            read -p "$(echo -e ${YELLOW}Model: ${NC})" CUSTOM_MODEL
            read -p "$(echo -e ${YELLOW}API Key env var (ou laisser vide pour local): ${NC})" CUSTOM_KEY
            ;;
        *)
            warning "Choix invalide, utilisation du profil par défaut"
            PROFILE="claude"
            ;;
    esac

    # Construire la configuration MCP
    if [[ $PROFILE_CHOICE -eq 5 ]]; then
        PROVIDER=$CUSTOM_PROVIDER
        BASE_URL=$CUSTOM_URL
        MODEL=$CUSTOM_MODEL
        API_KEY_ENV=$CUSTOM_KEY
    else
        # Lire la configuration du profil
        if command -v jq &> /dev/null; then
            PROVIDER=$(jq -r ".profiles.$PROFILE.provider" "$CLAUDE_GLM_CONFIG")
            BASE_URL=$(jq -r ".profiles.$PROFILE.baseUrl" "$CLAUDE_GLM_CONFIG")
            MODEL=$(jq -r ".profiles.$PROFILE.model" "$CLAUDE_GLM_CONFIG")
            API_KEY_ENV=$(jq -r ".profiles.$PROFILE.apiKeyEnv" "$CLAUDE_GLM_CONFIG")
        else
            # Fallback sans jq
            warning "jq non installé, utilisation des valeurs par défaut"
            PROVIDER="anthropic-compatible"
            BASE_URL="https://api.anthropic.com/v1"
            MODEL="claude-sonnet-4-20250514"
            API_KEY_ENV="ANTHROPIC_API_KEY"
        fi
    fi

    # Construire les arguments
    ARGS=(
        "--provider" "$PROVIDER"
        "--base-url" "$BASE_URL"
        "--model" "$MODEL"
    )

    # Ajouter la clé API si nécessaire
    if [[ -n "$API_KEY_ENV" ]]; then
        ARGS+=("--api-key" "\$$API_KEY_ENV")
    fi

    # Trouver le fichier de config Claude
    CLAUDE_CONFIG=$(find_claude_config)

    if [[ -z "$CLAUDE_CONFIG" ]]; then
        # Créer le fichier de configuration
        CLAUDE_CONFIG="$CLAUDE_CONFIG_FILE"
        mkdir -p "$CLAUDE_CONFIG_DIR"
        echo "{\"mcpServers\":{}}" > "$CLAUDE_CONFIG"
        info "Créé $CLAUDE_CONFIG"
    fi

    # Ajouter la configuration MCP
    info "Ajout du serveur MCP '$SERVER_NAME' à $CLAUDE_CONFIG..."

    if command -v jq &> /dev/null; then
        # Utiliser jq pour modifier le JSON
        TMP_FILE=$(mktemp)
        jq --arg server "$SERVER_NAME" \
           --arg script "$MCP_SERVER_SCRIPT" \
           --arg provider "${ARGS[0]}" \
           --arg url "${ARGS[1]}" \
           --arg model "${ARGS[2]}" \
           --arg apikey "${ARGS[3]:-}" \
           '.mcpServers[$server] = {
             "type": "stdio",
             "command": "python3",
             "args": [$script, $provider, $url] + (if $apikey != "" then [$apikey, $model] else [$model])
           }' "$CLAUDE_CONFIG" > "$TMP_FILE"
        mv "$TMP_FILE" "$CLAUDE_CONFIG"
    else
        warning "jq non installé, édition manuelle requise"
        echo ""
        echo "Ajoutez manuellement à $CLAUDE_CONFIG :"
        echo ""
        echo "{"
        echo "  \"mcpServers\": {"
        echo "    \"$SERVER_NAME\": {"
        echo "      \"type\": \"stdio\","
        echo "      \"command\": \"python3\","
        echo "      \"args\": ["
        echo "        \"$MCP_SERVER_SCRIPT\","
        for arg in "${ARGS[@]}"; do
            echo "        \"$arg\","
        done
        echo "      ]"
        echo "    }"
        echo "  }"
        echo "}"
        echo ""
        read -p "$(echo -e ${YELLOW}Appuyez sur Enter une fois la modification faite... ${NC})"
    fi

    success "Installation terminée !"
    echo ""
    info "Serveur MCP: $SERVER_NAME"
    info "Provider: $PROVIDER"
    info "Model: $MODEL"
    echo ""
    warning "N'oubliez pas d'exporter votre clé API :"
    if [[ -n "$API_KEY_ENV" ]]; then
        echo "  export $API_KEY_ENV=\"your_api_key_here\""
    fi
    echo ""
    warning "Redémarrez Claude Code pour appliquer les changements"
}

# Désinstaller le MCP
uninstall_mcp() {
    banner

    CLAUDE_CONFIG=$(find_claude_config)

    if [[ -z "$CLAUDE_CONFIG" ]]; then
        error "Fichier de configuration Claude non trouvé"
        exit 1
    fi

    # Lister les serveurs MCP installés
    if command -v jq &> /dev/null; then
        SERVERS=$(jq -r '.mcpServers | keys[]' "$CLAUDE_CONFIG" 2>/dev/null | grep -E "(llm|glm|claude|openai|ollama|expert)" || true)

        if [[ -z "$SERVERS" ]]; then
            warning "Aucun serveur LLM Delegator trouvé"
            echo ""
            echo "Serveurs MCP installés :"
            jq -r '.mcpServers | keys[]' "$CLAUDE_CONFIG" 2>/dev/null || echo "  (aucun)"
            exit 0
        fi

        echo ""
        info "Serveurs LLM Delegator installés :"
        echo "$SERVERS" | nl
        echo ""

        read -p "$(echo -e ${YELLOW}Nom du serveur à désinstaller (ou 'all' pour tout): ${NC})" SERVER_TO_REMOVE

        if [[ "$SERVER_TO_REMOVE" == "all" ]]; then
            for server in $SERVERS; do
                info "Suppression de $server..."
                TMP_FILE=$(mktemp)
                jq --arg server "$server" 'del(.mcpServers[$server])' "$CLAUDE_CONFIG" > "$TMP_FILE"
                mv "$TMP_FILE" "$CLAUDE_CONFIG"
                success "Supprimé: $server"
            done
        else
            TMP_FILE=$(mktemp)
            jq --arg server "$SERVER_TO_REMOVE" 'del(.mcpServers[$server])' "$CLAUDE_CONFIG" > "$TMP_FILE"
            mv "$TMP_FILE" "$CLAUDE_CONFIG"
            success "Supprimé: $SERVER_TO_REMOVE"
        fi
    else
        warning "jq non installé, désinstallation manuelle requise"
        echo ""
        echo "Éditez $CLAUDE_CONFIG et supprimez le serveur MCP souhaité"
    fi

    echo ""
    warning "Redémarrez Claude Code pour appliquer les changements"
}

# Lister les serveurs installés
list_servers() {
    banner

    CLAUDE_CONFIG=$(find_claude_config)

    if [[ -z "$CLAUDE_CONFIG" ]]; then
        error "Fichier de configuration Claude non trouvé"
        exit 1
    fi

    echo ""
    info "Serveurs MCP installés :"
    echo ""

    if command -v jq &> /dev/null; then
        jq -r '.mcpServers | to_entries[] | "  \(.key): \(.value.command // "N/A")"' "$CLAUDE_CONFIG" 2>/dev/null
    else
        grep -o '"[^"]*":' "$CLAUDE_CONFIG" | head -10
    fi
}

# Afficher l'aide
show_help() {
    banner
    cat << EOF
Usage: ./manage.sh [COMMANDE]

Commandes:
  install     Installer le serveur MCP dans Claude Code
  uninstall   Désinstaller le serveur MCP
  list        Lister les serveurs MCP installés
  help        Afficher cette aide

Exemples:
  ./manage.sh install
  ./manage.sh uninstall
  ./manage.sh list

EOF
}

# Main
case "${1:-}" in
    install)
        install_mcp
        ;;
    uninstall)
        uninstall_mcp
        ;;
    list)
        list_servers
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        banner
        echo "Usage: $0 {install|uninstall|list|help}"
        echo ""
        echo "Exemples:"
        echo "  $0 install    # Installer le MCP"
        echo "  $0 uninstall  # Désinstaller le MCP"
        echo "  $0 list       # Lister les serveurs"
        exit 1
        ;;
esac
