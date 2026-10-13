---
name: harness-assembly-cdx
description: Assemble a new project's selected language, component classification, user decision records, and checks before its first product code; also use when changing its stack.
---

# 프로젝트 하네스 조립 for Codex

> 담는 것: Codex의 프로젝트 조립 진입점. 담지 않는 것: 공통 절차(→ [조립 절차](../../../dev/workflows/harness-assembly.md)). 읽는 시점: 새 프로젝트의 스택과 첫 분류를 구성할 때.

Read and follow [the assembly workflow](../../../dev/workflows/harness-assembly.md), including its stack-fit step (`--doctor`, then `kernel.pack_check` with zero `[UNVERIFIED]`).
Start with the workflow's git and remote step, and once the language is chosen bind the component graph to it with `python -X utf8 -m kernel.graph_workflow bind`.
Ask the user about new classifications with a concrete proposal and record their actual response.
Follow AGENTS.md and use Codex-native tools within its read boundary.
