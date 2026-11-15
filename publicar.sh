#!/usr/bin/env bash
# Publica o ZekFlix no GitHub (ezekielso/zekflix) e cria a versão v1.0.0.
set -e
cd "$(dirname "$(readlink -f "$0")")"

USUARIO="ezekielso"
REPO="zekflix"
VERSAO="${1:-v1.0.0}"

# Segurança: não deixa publicar se existir uma chave escrita no código
if grep -nE 'OMDB_API_KEY *= *"[^"]+"' zekflix.py; then
    echo "ERRO: há uma chave do OMDb escrita no zekflix.py. Apague-a antes de publicar."
    exit 1
fi

echo "==> Verificando programas necessários"
command -v git >/dev/null || sudo dnf install -y git
command -v gh  >/dev/null || sudo dnf install -y gh

echo "==> Login no GitHub"
gh auth status >/dev/null 2>&1 || gh auth login
gh auth setup-git

echo "==> Configurando o git (e-mail privado do GitHub)"
ID=$(gh api user --jq .id)
git config --global user.name "$USUARIO"
git config --global user.email "${ID}+${USUARIO}@users.noreply.github.com"

echo "==> Preparando os arquivos"
[ -d .git ] || git init -b main
git add .
git commit -m "ZekFlix $VERSAO" || true

echo "==> Criando/enviando o repositório"
if gh repo view "$USUARIO/$REPO" >/dev/null 2>&1; then
    git remote get-url origin >/dev/null 2>&1 || \
        git remote add origin "https://github.com/$USUARIO/$REPO.git"
    git push -u origin main
else
    gh repo create "$USUARIO/$REPO" --public --source=. --remote=origin --push \
        --description "ZekFlix: seus filmes e séries locais em uma interface estilo Netflix para Linux"
fi

echo "==> Colocando tópicos"
gh repo edit "$USUARIO/$REPO" \
    --add-topic linux --add-topic fedora --add-topic python --add-topic pyqt6 \
    --add-topic appimage --add-topic media-player --add-topic netflix --add-topic mpv

echo "==> Criando a versão $VERSAO (o GitHub compila o AppImage sozinho)"
git tag "$VERSAO" 2>/dev/null || echo "A tag $VERSAO já existe."
git push origin "$VERSAO"

echo
echo "Pronto! Acompanhe a compilação (10-15 min) em:"
echo "  https://github.com/$USUARIO/$REPO/actions"
echo "Quando terminar, o AppImage estará em:"
echo "  https://github.com/$USUARIO/$REPO/releases/latest"
