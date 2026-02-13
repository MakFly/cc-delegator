# GLM Delegator

You have access to GLM-5 experts via MCP tools (`mcp__glm-delegator__glm_{expert}`). Each delegation is **stateless**—include full context in every call.

## Expert Directory

| Expert | MCP Tool | Specialty | Philosophy | Semantic Triggers |
|--------|----------|-----------|------------|-------------------|
| **Architect** | `glm_architect` | System design, tradeoffs, complex debugging | Pragmatic minimalism | "how should I structure", "tradeoffs of", "should I use A or B", system design, 2+ failed fixes |
| **Plan Reviewer** | `glm_plan_reviewer` | Plan validation before execution | Ruthlessly critical | "review this plan", "is this plan complete", "validate before I start", before significant work |
| **Scope Analyst** | `glm_scope_analyst` | Pre-planning, catching ambiguities | Surface problems early | "what am I missing", "clarify the scope", vague/ambiguous requests, "before we start" |
| **Code Reviewer** | `glm_code_reviewer` | Code quality, bugs, maintainability | Maintain at 2 AM | "review this code", "find issues in", "what's wrong with", after implementing features |
| **Security Analyst** | `glm_security_analyst` | Vulnerabilities, threat modeling | Attacker's mindset | "security implications", "is this secure", "vulnerabilities in", "threat model", "harden this" |

## Operating Modes

| Mode | Use When |
|------|----------|
| **Advisory** | Analysis, recommendations, review verdicts |
| **Implementation** | Making changes, fixing issues |

The mode is determined by the task, not the expert. Any expert can operate in either mode.

## Delegation Triggers

### Check on EVERY Message

1. **PROACTIVE**: Scan for semantic triggers (see Expert Directory) → delegate automatically
2. **REACTIVE**: User explicitly mentions GLM → delegate immediately

### Explicit Triggers (Highest Priority)

| Phrase | Expert |
|--------|--------|
| "ask GLM", "consult GLM" | Route based on context |
| "review this architecture" | Architect |
| "review this plan" | Plan Reviewer |
| "analyze the scope" | Scope Analyst |
| "review this code" | Code Reviewer |
| "security review", "is this secure" | Security Analyst |

### Trigger Priority

1. **Explicit user request** — Always honor
2. **Security concerns** — Sensitive data/auth
3. **Architecture decisions** — Long-term impact
4. **Failure escalation** — After 2+ failed attempts
5. **Don't delegate** — Default: handle directly

## Delegation Flow

When a trigger matches:

1. **Identify** — Match task to expert via triggers
2. **Mode** — Advisory (analysis) or Implementation (changes)
3. **Notify** — Always tell the user: `Delegating to [Expert]: [summary]`
4. **Call** — Use 7-section prompt format (below)
5. **Synthesize** — Never show raw output; extract insights, apply judgment, verify implementation

## Files Parameter

Always populate `files` when:
- Reviewing specific code (attach the files being reviewed)
- Debugging (attach error sources, stack trace files)
- Refactoring (attach files to be refactored)
- Security analysis (attach input handlers, auth code)

Omit `files` only for open-ended architecture questions or conceptual discussions.

## Prompt Format (7 Sections — MANDATORY)

```
1. TASK: [One sentence—atomic, specific goal]
2. EXPECTED OUTCOME: [What success looks like]
3. CONTEXT:
   - Current state: [what exists now]
   - Relevant code: [paths or snippets]
   - Background: [why this is needed]
4. CONSTRAINTS:
   - Technical: [versions, dependencies]
   - Patterns: [existing conventions]
   - Limitations: [what cannot change]
5. MUST DO:
   - [Requirement 1]
   - [Requirement 2]
6. MUST NOT DO:
   - [Forbidden action 1]
   - [Forbidden action 2]
7. OUTPUT FORMAT:
   - [How to structure response]
```

## Expert Templates

### Architect
- **TASK**: [Analyze/Design/Implement] [component] for [goal]
- **MUST DO**: Provide effort estimate (Quick/Short/Medium/Large); report modified files (impl)
- **MUST NOT DO**: Over-engineer; introduce unjustified dependencies
- **Output**: Advisory: Bottom line → Action plan → Effort. Implementation: Summary → Files → Verification

### Plan Reviewer
- **TASK**: Review [plan] for completeness and clarity
- **MUST DO**: Evaluate 4 criteria (Clarity, Verifiability, Completeness, Big Picture); simulate the work
- **MUST NOT DO**: Rubber-stamp; approve plans with critical gaps
- **Output**: APPROVE/REJECT → Justification → 4-criteria assessment → Improvements if rejected

### Scope Analyst
- **TASK**: Analyze [request] before planning begins
- **MUST DO**: Classify intent; identify hidden requirements; surface questions; assess risks
- **MUST NOT DO**: Start planning; make assumptions about unclear requirements
- **Output**: Intent → Findings → Questions → Risks → Recommendation (Proceed/Clarify/Reconsider)

### Code Reviewer
- **TASK**: [Review / Fix] [code] for [focus areas]
- **MUST DO**: Prioritize Correctness → Security → Performance → Maintainability
- **MUST NOT DO**: Nitpick style; flag theoretical concerns
- **Output**: Advisory: Issues → Verdict (APPROVE/REQUEST CHANGES/REJECT). Implementation: Fixes → Files → Verification

### Security Analyst
- **TASK**: [Analyze / Harden] [system] for vulnerabilities
- **MUST DO**: Check OWASP Top 10; cover auth, authz, input validation; practical remediation
- **MUST NOT DO**: Flag low-risk theoretical issues; break functionality while hardening
- **Output**: Advisory: Threats → Vulnerabilities → Risk rating. Implementation: Fixes → Files → Verification

## Retry Flow

When implementation fails verification:

```
Attempt 1 → Verify → Fail
  ↓
Attempt 2 (NEW call: original task + what was tried + error) → Verify → Fail
  ↓
Attempt 3 (NEW call: full history) → Verify → Fail
  ↓
Escalate to user
```

Always include previous attempt details in retry calls (stateless design).

## Anti-Patterns

| Don't | Do Instead |
|-------|------------|
| Delegate trivial questions | Answer directly |
| Show raw expert output | Synthesize and interpret |
| Skip user notification | ALWAYS notify before delegating |
| Retry without error context | Include FULL history of attempts |
| Assume expert remembers | Include all context every call |
| Spam multiple vague calls | One well-structured delegation |

## When NOT to Delegate

- Simple syntax questions — answer directly
- First attempt at any fix — try yourself first
- Trivial bug fixes / decisions — obvious solution
- Research/documentation — use other tools
- Direct file operations — no external insight needed
