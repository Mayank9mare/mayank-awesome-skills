# Mental Models

A mental model is a small internal simulation you can **run**: feed in a situation, get a
prediction. If someone can recite a definition but can't predict what happens when one input
changes, they don't have a model yet, just a sentence.

What experts have that novices lack is not more facts but **better-organised** facts:

- **Chunking** (Chase & Simon): experts see meaningful units. A chess master sees "a
  fianchettoed bishop", not 3 pieces. A senior engineer sees "a saga with compensation", not
  seven service calls.
- **Deep structure** (Chi, Feltovich & Glaser): asked to sort physics problems, novices group
  them by surface features ("inclined planes", "pulleys") and experts by principle ("conservation
  of energy"). Teach the principle as the organising chunk, then show it in different surface
  forms.
- **Conditionalised knowledge**: experts know *when* a piece of knowledge applies. Every chunk
  in the model needs a "use when / breaks when".

## The model card

Co-write one per major idea. The learner drafts it; you correct it.

```markdown
### Model: <name>

**One-line essence:** <the idea in ≤ 20 words, no jargon you can't define>

**Parts:** <the 3–7 things that exist in this model>
**Relationships:** <how the parts affect each other: arrows, equations, calls, dependencies>
**Behaviour:** <"when X increases / happens, Y …": 2–4 runnable predictions>
**Boundaries:** <where the model stops being true: limits, assumptions, edge cases>
**Analogy:** <familiar thing> — **breaks where:** <how the analogy misleads>
**Contrast:** <the nearest neighbouring idea it's confused with, and the difference>
**Worked example:** <one concrete instance, end to end>
**Test question:** <one question that only someone with the model could answer>
```

The **Boundaries** and **breaks where** lines matter most. Without them the learner
over-applies the model, and over-applying it is how misconceptions start.

## Building understanding: tools to reach for

### First principles
Strip the idea down to what must be true, then rebuild it. "Why is binary search O(log n)?"
→ "What happens to the search space each step?" → "How many halvings get from n to 1?" The
learner who rebuilds it once can regenerate it forever. No memorisation needed.

### Analogy, with an explicit failure point
Analogies give a borrowed model instantly (Gentner's structure-mapping), but they also bring
false inferences along. Always pair the analogy with where it fails:

- Voltage is like water pressure. **Breaks:** water flows out of a cut pipe; current does not
  flow out of a cut wire.
- A message queue is like a post office. **Breaks:** at-least-once delivery means the post
  office might deliver your letter twice.
- Recursion is like Russian dolls. **Breaks:** dolls don't return values back up the chain.

Ask the learner to find the breaking point themselves. It's an excellent Socratic question.

### Contrast pairs
Things are understood by their differences. Teach in pairs and ask "what's the difference?":
mass/weight, speed/velocity, concurrency/parallelism, process/thread, Strategy/State,
authentication/authorisation, derivative/integral, covariance/correlation.

### Multiple representations (dual coding)
Each representation shows a different face. For one idea, aim for at least two of: words, a
diagram, an equation or code, a concrete example, a physical or kinaesthetic sense ("feel" the
torque). Ask the learner to translate between them: "Draw what this equation says."

### Concreteness fading
Start concrete (a specific ball, a specific HTTP request), then semi-abstract (a diagram), then
abstract (the general law or interface). Skipping the concrete start is the most common
explaining mistake.

### Inversion
"How would you guarantee this fails?" is often easier than "how does it work?". Breaking a
thing exposes what holds it together. Great for architectures ("how would you make this
service lose data?") and proofs ("what would a counter-example need to look like?").

## A latticework of general-purpose models

Munger's point: a few cross-domain models explain a huge share of everything. Connect new
material to these whenever it fits. Each connection is another retrieval path.

| Model | Shows up in |
|---|---|
| Conservation / invariants | Physics (energy, momentum), algorithms (loop invariants), DB constraints, accounting |
| Feedback loops (positive / negative) | Control systems, autoscaling, retries causing storms, markets, populations |
| Stocks & flows | Queues, caches, thermodynamics, budgets, backlogs |
| Trade-offs / no free lunch | CAP, time vs space, bias vs variance, consistency vs latency |
| Abstraction & layering | OSI stack, hexagonal architecture, maths built from axioms |
| Indirection | Pointers, DNS, dependency injection, the Proxy/Adapter patterns, "every problem in CS…" |
| Exponential / logarithmic growth | Compound interest, algorithm complexity, decay, epidemics |
| Equilibrium | Statics, load balancing, chemical equilibrium, supply/demand |
| Local vs global optimum | Gradient descent, greedy algorithms, evolution, org design |
| Signal vs noise | Statistics, observability, measurement error |
| Bottleneck / constraint | Amdahl's law, theory of constraints, the critical path |
| Map is not the territory | Every model, including this one, has boundaries |

When a learner meets a new topic, ask: "Which of these does it remind you of?" Finding
structural similarity is understanding.

## Checking understanding — escalate in this order

1. **Restate** in their own words, no copying your phrasing.
2. **Predict** the outcome of a new, specific situation.
3. **Explain why** the prediction holds.
4. **Spot the error** in a flawed explanation or buggy example you give them.
5. **Transfer** to a different surface form with the same deep structure.
6. **Create** a new example, problem, or test case themselves.

Level 4 is underrated. Debugging a wrong explanation exercises the model hard and is fun.
