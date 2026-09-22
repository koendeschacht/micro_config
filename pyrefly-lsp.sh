#!/bin/sh

if [ -x .venv/bin/pyrefly ]; then
    exec .venv/bin/pyrefly lsp "$@"
fi

exec /home/koen/.local/bin/pyrefly lsp "$@"
