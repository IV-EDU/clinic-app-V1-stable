# Handoff Brief Format

When the Advisor finishes a strategy session and the user needs to hand work to a code agent, **overwrite `handoff.md` in the root directory** with this exact structure:

```
## Task: [one-line description]

### Recommended Agent:
[Specify the model class (Heavyweight vs Nimble Coder) and WHY]
- **Heavyweight / Reasoning:** For architecture, massive multi-file refactors, or complex DB/routing logic.
- **Nimble Coder / UI:** For CSS/JS plumbing, modular front-end work, and scoped features.

### Goal
[2-3 sentences: what we're trying to achieve and why]

### Edge Cases & UX
[2-3 edge cases the Advisor MUST think of proactively, with solutions for each]

### Plan
1. [Specific step]
2. [Specific step]
3. [Specific step]

### Constraints
- [Anything the code agent needs to know: don't touch X, use Y pattern, etc.]
- [⚠️ IF THE IDEA HAS FLAWS BUT THE USER INSISTS: Document the risks here]

### Definition of Done
- [How to verify this is complete]

### Manager Review Step (Mandatory)
Before executing, the code agent MUST state:
1. "I will be modifying these specific files: [list]"
2. "I will NOT be touching [protected files]. (Or explain why if you must.)"
3. "The risk level is [Low/Medium/High] because [1 sentence]."
```

Keep handoff briefs **short and actionable**. The code agent doesn't need strategy — it needs clear instructions.
