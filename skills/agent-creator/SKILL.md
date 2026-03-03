---
name: agent-creator
description: "Design and create new AI agent definition files (.md) for the agents/ directory. Use when the user wants to create a new agent, update an existing agent's personality/rules/workflow, or audit the current agent roster. Triggers include: 'create an agent', 'new agent', 'design an agent', 'update advisor/coder', 'add a role', or any request to define how an AI persona should behave in conversations."
---

# Agent Creator

Design focused, well-structured AI agent definition files for the `agents/` directory.

## What Is an Agent File?

A markdown file (`agents/<name>.md`) that a user pastes into a new AI conversation to activate a specific persona. It defines:
- **Identity** — what the agent IS and what it does NOT do
- **Personality** — tone, bluntness level, communication style
- **Bootstrap** — what files to auto-read at conversation start
- **Modes** — distinct operating modes the agent switches between
- **Workflow** — step-by-step process the agent follows
- **Constraints** — hard boundaries the agent must not cross
- **Memory** — how context persists across conversations (optional)

## Core Principles

### Lean Over Bloated
- Every agent should fit one clear job. If it needs 10 modes, it's probably 2 agents.
- Target 150–400 lines. Under 150 means it's too vague. Over 400 means it's doing too much.

### No Overlap
- Before creating a new agent, audit `agents/` for existing roles that could absorb the job.
- Push back if the new agent overlaps >30% with an existing one.

### Personality Is Required
- Generic agents are useless. Every agent needs a clear tone and bluntness level.
- Define what the agent says when the user is wrong, stuck, or wasting time.

### Context-Aware Bootstrap
- Every agent should auto-read the minimum files needed to be useful immediately.
- Never dump file summaries back to the user — just be ready.

### Boundaries Are the Most Important Part
- What the agent REFUSES to do matters more than what it does.
- Prevents scope creep and keeps agents focused.

## Creation Process

### Step 1: Define the Job (Not the Title)

Ask:
1. What specific problem does this agent solve?
2. What does the user say to trigger needing this agent?
3. What does the agent produce as output? (decisions? code? plans? reviews?)

If the answer to #1 is vague ("helps with stuff"), stop and sharpen it before proceeding.

### Step 2: Check for Overlap

Read all existing files in `agents/`:
- If an existing agent covers >30% of the job → recommend expanding that agent instead
- If the overlap is <30% but exists → define explicit boundaries ("Agent X does THIS part, new agent does THAT part")

### Step 3: Choose the Agent Archetype

| Archetype | Does | Doesn't | Example |
|-----------|------|---------|---------|
| **Thinker** | Strategy, critique, decisions, prioritization | Write code, edit files, run commands | Advisor |
| **Doer** | Execute specific tasks, write code, make changes | Argue strategy, change plans | Coder |
| **Reviewer** | Audit, validate, test, find problems | Fix problems, implement solutions | QA Agent |
| **Specialist** | Deep expertise in one narrow domain | Anything outside that domain | DB Migration Agent |

Most projects need 1 Thinker + 1-2 Doers. Add Reviewers and Specialists only when a clear recurring need exists.

### Step 4: Write the Agent File

Use this structure (see [references/agent-template.md](references/agent-template.md) for the full template):

```
# <Role Name> Agent

## Identity
[1-2 sentences: what this agent IS]
[1 sentence: what this agent is NOT]

## Personality & Communication
[Bluntness level 1-5]
[Tone description]
[What it says when the user is wrong]

## Auto-Bootstrap
[Files to read silently at start]
[What to say after reading]

## Modes of Operation (if applicable)
[2-5 modes max, with triggers]

## Workflow
[Numbered steps]

## Constraints
[Hard NOs — what this agent refuses to do]

## Memory (optional)
[How context persists across sessions]
```

### Step 5: Validate

Before delivering the agent file, check:
- [ ] Identity is one clear job, not a laundry list
- [ ] Personality is specific (not "be helpful and professional")
- [ ] Bootstrap reads only necessary files (not everything)
- [ ] Constraints explicitly list what the agent WON'T do
- [ ] No significant overlap with existing agents
- [ ] Under 400 lines
- [ ] Includes a "What to say when..." section for common situations

## Current Agent Roster

Always check `agents/` for the latest roster. As of skill creation:

| Agent | File | Archetype | Job |
|-------|------|-----------|-----|
| Strategic Advisor | `advisor.md` | Thinker | Strategy, prioritization, critique, mentoring |
| Lead Coder | `coder.md` | Doer | Execute handoff briefs, write code |

## Anti-Patterns to Avoid

- **The Swiss Army Agent** — does everything, excels at nothing. Split it.
- **The Polite Agent** — agrees with everything, never pushes back. Useless. Define bluntness.
- **The Context Hog** — reads 10 files on bootstrap. Pick the 2-3 that actually matter.
- **The Ruleless Agent** — no constraints section. Will inevitably drift into other agents' territory.
- **The Clone** — 80% identical to an existing agent with a different name. Merge it.
