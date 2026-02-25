<!-- codelens:start -->
# CodeLens MCP — Tool Routing

Use CodeLens MCP tools BEFORE built-in grep/glob/read. Rule: regex query → codelens_grep, natural language → codelens_search.

**CRITICAL:** "Find weaknesses", "project issues", "technical debt" = semantic → codelens_search or codelens_agentic_search. Do NOT use batch_grep for open-ended analysis. batch_grep = explicit regex patterns only.

## Syntactic (patterns, regex)

| Task | Tool | Fallback |
|------|------|----------|
| Pattern/regex in code | codelens_grep | built-in grep |
| Find files by name | codelens_list_files | built-in glob |

## Semantic (concepts, symbols)

| Task | Tool | Fallback |
|------|------|----------|
| Search by concept | codelens_search | grep/glob |
| Find definitions | codelens_search (mode=symbol) | grep/glob |
| Find usages | codelens_search (mode=refs) | grep |
| Smart search | codelens_agentic_search | search + grep |

## Context

| Task | Tool |
|------|------|
| Project overview | codelens_overview |
| Save memory | codelens_remember |
| Recall memory | codelens_recall |
<!-- codelens:end -->
