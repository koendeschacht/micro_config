# Project LSP profiles

Edit [project-lsp.json](project-lsp.json) to add source roots for a Git project. The
key is the name of the repository that owns the worktree's Git common directory
(`git rev-parse --git-common-dir`), so all worktrees of `james` use the `james`
profile regardless of their folder names.

`sourceRoots` contains glob patterns relative to the active worktree. Micro
expands them and builds a temporary Pyrefly config under `/tmp/micro-pyrefly/`,
alongside the project's existing `[tool.pyrefly]` settings. The source tree is
unchanged. Restart micro after editing a profile.

Pyrefly can still index only the active package. Its references request can
also return nothing for a symbol whose call sites it can resolve. For find
references, micro scans matching Python names across the worktree, checks each
occurrence with Pyrefly's definition request, and shows only occurrences that
resolve to the selected declaration. This may take longer for common names.
The filled status circle means Pyrefly has finished its current indexing pass,
not that every package has been indexed.
