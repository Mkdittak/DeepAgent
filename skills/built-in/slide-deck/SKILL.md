---
name: slide-deck
description: Build clear, well-structured presentations with generate_pptx - outline first, one idea per slide, tight scannable bullets, strong opening and closing slides. Use when the user asks for a presentation, slide deck, pitch deck, slides, or PPTX output.
license: Apache-2.0
metadata:
  author: deepagent
  version: "1.0"
---

# Slide Deck

Decks fail from overstuffed slides and missing structure, not from missing
facts. Follow this workflow for every presentation request.

## Workflow

1. **Outline before building.** Decide the deck's single message, then list
   slide titles that tell that story in order. A good deck reads as a story
   from its titles alone.
2. **Size the deck to the ask.** Default 5-8 content slides; a quick overview
   is 3-5; go past 10 only if the user asked for depth. Never pad.
3. **One idea per slide.** The slide title states the idea as a claim
   ("Q3 revenue grew 18%"), not a category ("Revenue"). Bullets support that
   one claim only.
4. **Write scannable bullets.** 3-5 bullets per slide, each a single line
   (aim under ~12 words), parallel in construction, no full sentences with
   trailing punctuation. Numbers beat adjectives.
5. **Open and close deliberately.** First content slide = context and the core
   message up front. Last slide = summary, conclusion, or next steps — never
   trail off on a detail slide.

## Tool contract

Call `generate_pptx(title, slides)` exactly once, after the outline is settled:

- `title`: the deck title (becomes the title slide).
- `slides`: a list of dicts, each `{"title": str, "bullets": list[str]}`.

Example:

```json
{
  "title": "Quarterly Review",
  "slides": [
    {"title": "Q3 revenue grew 18%", "bullets": ["$4.2M total, up from $3.6M", "Growth led by enterprise tier", "Churn flat at 2.1%"]}
  ]
}
```

## Rules

- If the content needs research first, finish the research before outlining.
- Do not duplicate the deck's content in your chat reply — summarize in one or
  two sentences and point to the generated file.
