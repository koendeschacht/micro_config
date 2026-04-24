#!/bin/sh

exec /home/koen/.local/bin/pyrefly lsp "$@" 2>>/tmp/pyrefly-lsp.stderr.log
