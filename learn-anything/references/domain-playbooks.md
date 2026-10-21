# Domain Playbooks

The same loop (ask → model → encode → retrieve) applied to specific kinds of material.

---

## Physics

**Organise by principle, not surface.** Novices file problems as "pulley problem", "incline
problem". Experts file them as "energy conservation", "Newton's 2nd on a system". Make the
principles the top-level chunks.

- **Skeleton:** the few laws everything derives from (Newton's laws + conservation of energy,
  momentum and angular momentum for mechanics; Maxwell's equations for E&M; the laws of
  thermodynamics).
- **Socratic moves:**
  - *Predict before computing*: "Does it go faster or slower? More or less than double?"
  - *Extreme cases*: "What if the mass were zero? Infinite? The angle 90°?" These check any
    formula and build intuition.
  - *Thought experiments*: Galileo's tied stones, Einstein's elevator, Maxwell's demon.
  - *Units and dimensions*: "What units must the answer have? What combinations of the givens
    produce those units?"
- **Model card focus:** the assumptions (frictionless, point mass, ideal gas, non-relativistic)
  go under **Boundaries**.
- **Classic misconceptions to probe:** motion needs a force (impetus); heavier objects fall
  faster; current is "used up" in a circuit; heat and temperature are the same; centrifugal
  force pushes outward in an inertial frame; there's no gravity in orbit.
- **Encode:** constants via Brown's number code (hyperthymesia), a palace per chapter for formulas that can't be
  derived quickly, and a standing image per quantity (momentum = a freight train, energy = a
  battery, entropy = a messy bedroom).

## Mathematics

- **Skeleton:** definitions → key theorems → the main proof techniques used in this area.
- **Every definition gets an example, a non-example, and an edge case.** "Is 1 prime? Why does
  the definition exclude it?" Non-examples show what each clause of the definition is for.
- **Proofs as stories.** Ask "what's the key idea in one sentence?" before the line-by-line.
  Most proofs hinge on one trick (a clever substitution, a contradiction, an invariant, a
  pigeonhole). Name the trick, because tricks transfer.
- **Socratic moves:**
  - "Try small cases. What pattern do you see?" (n = 1, 2, 3)
  - "What would a counter-example need to look like?" (inversion)
  - "Which hypothesis did we not use yet?" Unused hypotheses point to the gap.
  - "Draw it." Most algebra has a geometric picture; most calculus has a graph.
- **Encode:** memorise as little as possible; derive the rest. Proof skeletons go in a palace
  (one locus per step). Standing images for operators (∫ = a tall swan collecting slices,
  ∂ = a bent sickle shaving one variable).

## Understanding a codebase's architecture

The goal is a **situation model** (what the system does in the domain, and why) on top of a
**program model** (how the code is structured). Experts read top-down from hypotheses, using
*beacons* (recognisable idioms) to confirm or reject them (Brooks; Pennington).

**Claude's job: read the code first.** Never ask the learner something answerable by grep.
Explore, then turn what you found into prediction questions.

### Step-by-step

1. **Context (C4 level 1).** What is this system for? Who and what calls it, and what does it
   call? Ask the learner to guess from the README and directory names before you confirm.
2. **Containers (C4 level 2).** Deployables, datastores, queues. Draw it (Mermaid) together,
   with the learner naming the arrows.
3. **Trace one request end to end.** Pick the single most important user action. Follow it:
   entrypoint → routing → handler → domain logic → persistence → side effects (events, calls)
   → response. At every hop ask: *"Where do you think it goes next? Which file?"* Then reveal.
   This one trace teaches more than reading any number of files.
4. **Find the seams.** Ask the learner: "Where would you add X?" "What breaks if Y is down?"
   "Where's the transaction boundary?" These test the model.
5. **Name the patterns and conventions.** Layering (hexagonal, clean, MVC), DI style, error
   handling, how config flows. Contrast with what they know: "How is this different from the
   last service you worked on?"
6. **Inversion.** "How would you make this lose data? Double-charge? Leak a secret?" These map
   the invariants and the places where they're guarded.
7. **Model card per container** plus one for the whole system. Store them in the repo's
   `.learn/` log.

### Memory palace for a codebase

- **Building = the system.** Floors = layers (API at the top floor, domain in the middle,
  infra in the basement).
- **Rooms = services, modules or bounded contexts.** Choose rooms whose *real* function echoes
  the module: auth goes in the front-door vestibule (it checks who comes in), payments in the
  kitchen (money gets cooked), the event bus is the staircase connecting all floors, the DB is
  the basement storage.
- **Objects in each room = key classes or files**, each a substitute-word image doing
  something to the room.
- **The traced request = a walk through the palace in order**, the route.
- **Owners or teams** = people standing in the rooms (names-and-faces technique).

Useful when onboarding onto a large system, or before on-call.

## Design patterns

Teach each pattern in Alexander's form, which is how patterns were meant to be learned:
**context → problem → forces in tension → solution → consequences**. The name is the last
thing to learn, not the first.

- **Problem first (Socratic):** present the pain without the pattern. "You have 5 payment
  providers and a growing `if/else` chain. Each new provider means editing this method. What's
  bothering you about this? How would you fix it?" Let them reinvent Strategy, then name it.
- **Contrast families:** patterns are best learned as neighbours with different intents:
  - Strategy vs State vs Command (who chooses the behaviour, and when)
  - Adapter vs Facade vs Proxy vs Decorator (same interface? new interface? added behaviour?)
  - Factory Method vs Abstract Factory vs Builder
  - Observer vs Mediator vs Pub/Sub
- **Find it in the wild:** "Where in *this* repo, or a framework you use, is there an Observer?"
  (event listeners, React state subscriptions, Kafka consumers).
- **Consequences / when NOT to:** every pattern adds indirection. Ask "what does this cost?"
  and "what's the simplest thing that would work instead?"
- **Encode** the catalogue: one palace with three wings, Creational, Structural and Behavioural.
  Each pattern is a vivid scene that *acts out its intent*: Singleton = one throne, and anyone
  trying to build a second gets thrown out. Decorator = a cake getting layers piped on while
  still being a cake. Observer = a wall of eyeballs that all blink when the bell rings.

## Algorithms and data structures

- **Invariant first.** "What's true at the start of every loop iteration?" The invariant *is*
  the understanding.
- **Hand-simulate.** The learner traces it on a tiny input, out loud. Predict the next state at
  each step.
- **Break it.** "What input makes this worst case?" "What if we removed this line?"
- **Complexity by counting**, not by memorising: "How many times does this line run?"
- **Encode** only the names → key-idea pairs (and the complexity table if needed for
  interviews, using a palace).

## Languages (human)

- Comprehensible input plus spaced retrieval is the backbone. Mnemonics help with vocabulary
  and irregular forms.
- **Vocabulary**: Brown's names method: turn the foreign word into a picture by sound, then link it to the meaning. **Gender** via a standing scene
  (all masculine nouns explode, all feminine nouns burst into flames, all neuter nouns freeze).
- **Socratic for grammar:** show 4–5 example sentences and ask them to induce the rule before
  stating it.

## Fact-heavy subjects (history, biology, law, medicine)

- **Skeleton = causal or structural spine** (a timeline with causes, an organ system, a
  statute's structure), so facts hang on a model, not in a vacuum.
- **Elaborative interrogation:** "Why would that be true?" for every fact. Facts with a *why*
  are retained far better.
- **Encode lists** (cranial nerves, drug classes, the order of events) in palaces. **Dates** via
  Brown's number code.

## Learning a new technology or framework fast

1. What problem did it exist to solve? What came before it, and what hurt?
2. The core abstraction(s), usually 2–4 nouns (React: component, props, state, effect).
3. One minimal working example, typed by the learner, with a prediction before each run.
4. The main "gotchas", turned into contrast and prediction cards.
5. Compare with the tool they already know, giving them a map of what corresponds to what.
