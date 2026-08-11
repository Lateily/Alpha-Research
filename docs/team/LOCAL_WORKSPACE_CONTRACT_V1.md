# AR Local Workspace Contract v1

## Purpose

GitHub synchronizes project truth. All Alpha Research material lives under one
local `AR/` container. Application, recruiting, and unrelated personal tools
stay outside it and are not governed or moved by this contract.

## Required containers

```text
workspace/
├── AR/
│   ├── projects/
│   │   └── alpha-research/          # clean main, stable entrypoint
│   ├── worktrees/
│   │   ├── research/
│   │   ├── macro/
│   │   ├── aios/
│   │   ├── product/
│   │   └── parked/
│   ├── runtime/                     # pointers and notes only
│   ├── archive/                     # frozen, never resumed in place
│   └── local-ai/                    # AR-only local helpers
└── application-or-personal-tools/   # untouched by AR operations
```

The outer workspace path may differ by operating system. The `AR` boundary and
its internal meanings do not.

For an existing valid clone, adoption is logical before it is physical: declare
that checkout as the member's primary AR repository and keep using it. Do not
create a second clone merely to match this diagram. Relocation into `AR/` is a
separate, explicit housekeeping task that requires a clean checkout and must
leave exactly one active primary clone.

## Worktree contract

| Domain | Scope |
|---|---|
| `research/` | Research OS, ledgers, evidence engines, and data contracts |
| `macro/` | Macro OS collection, state, MRG, consumers, and panel wiring |
| `aios/` | AIOS, adapters, policy, task registry, Skills, and harness |
| `product/` | Frontend, APIs, product management, deployment, and UX |
| `parked/` | Explicitly paused work with an owner and next decision |

After a PR exists, name its directory `pr-<number>-<short-slug>`. One worktree
means one task branch and one PR. Cross-domain changes require one declared
primary owner and explicit file scope in `ai-task.v1`; they do not justify an
unclassified worktree.

## Lifecycle

1. Update the clean `AR/projects/alpha-research` checkout from `origin/main`.
2. Create an isolated worktree under the correct domain.
3. Compile `ai-task.v1`, implement, test, and open a Draft PR.
4. Junyan reviews and decides whether to merge.
5. After merge or closure, verify the checkout is clean and run
   `git worktree remove <path>`.
6. Preserve decisions in Git and task records, not by keeping completed folders.

## Boundaries

- Production runtime is local-only and outside development worktrees.
- Never sync secrets, `.env`, caches, local databases, runtime ledgers, or dirty
  worktrees through GitHub or consumer file-sync products.
- Archive content is read-only. Resume work by creating a new branch from the
  current fact source.
- Project-specific instructions live in repository `AGENTS.md` and
  `.agents/skills/`; personal/global AI configuration must not override them.
- AR housekeeping must not move, rename, delete, or reclassify anything outside
  the `AR/` root.
