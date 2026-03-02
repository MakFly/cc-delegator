---
name: workflow
description: Execute structured 6-step development workflow with GLM experts
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Agent, AskUserQuestion
---

# Workflow

Execute a structured 6-step development workflow using GLM experts.

## Pipeline

Research → Ideate → Plan → Execute → Optimize → Review

## Steps

### Step 1: Research
Use `glm_scope_analyst` to analyze requirements, identify ambiguities and hidden dependencies.

### Step 2: Ideate
Use `glm_architect` to design the approach, evaluate tradeoffs, and recommend a path.

### Step 3: Plan
Write a detailed implementation plan. Use `glm_plan_reviewer` to validate completeness.

### Step 4: Execute
Implement the plan. **User approval required before this step.**

### Step 5: Optimize
Use `glm_code_reviewer` to review the implementation for bugs, quality, and maintainability.

### Step 6: Review
Use `glm_security_analyst` for security review of the changes.

## Usage

Each step builds on the previous. Stop and ask for user input between Plan and Execute.
