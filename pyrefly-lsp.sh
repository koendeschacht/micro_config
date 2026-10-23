#!/bin/sh

if [ -x .venv/bin/pyrefly ]; then
    exec .venv/bin/pyrefly lsp --workspace-indexing-limit 5000 "$@"
fi

exec /home/koen/.local/bin/pyrefly lsp --workspace-indexing-limit 5000 "$@"
