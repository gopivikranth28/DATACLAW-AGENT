# Skill Library

Community-contributed skills for Dataclaw. Users can browse and install these from the Skills page in the UI.

## Contributing a skill

1. Create a `.md` file in this directory
2. Add YAML frontmatter with `name`, `description`, and `tags`
3. Write the skill instructions in the body

### Format

```markdown
---
name: my_skill
description: Short description of what this skill does
tags: [category1, category2]
---

Skill instructions go here. These are injected into the agent's
system prompt when the skill is active.
```

### Guidelines

- Keep skill names lowercase with underscores (they become the filename)
- Write clear, actionable instructions the agent can follow
- Use tags to help users find relevant skills
- Test your skill before submitting
