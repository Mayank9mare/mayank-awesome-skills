# Socratic Questioning

The Socratic method is not "answer every question with a question". It's a disciplined way of
getting the learner to **construct** an idea, and of **exposing** the ideas they hold that are
wrong. Socrates had three moves worth stealing:

| Move | What it is | Use it for |
|---|---|---|
| **Maieutics** ("midwifery") | Drawing out an idea the learner can almost reach, through questions that each take one small step. | Building new understanding from what they already know. |
| **Elenchus** ("refutation") | Taking the learner's stated belief seriously, following it to a consequence they themselves reject. | Dismantling misconceptions. Telling someone they're wrong rarely sticks; letting them catch the contradiction does. |
| **Aporia** ("productive puzzlement") | The moment the learner realises their model can't explain something. | The best moment to teach. Don't rush to rescue them; let the puzzle sit for one beat. |

## The six question types (Paul & Elder)

Rotate through these. A dialogue made only of "what is X?" questions is a quiz, not Socratic.

1. **Clarification** — "What do you mean by 'faster'? Latency or throughput?" · "Can you give an example?"
2. **Assumptions** — "What are you assuming about the network here?" · "Is that always true, or only for ideal gases?"
3. **Reasons & evidence** — "How do you know?" · "What in the code tells you that?" · "What would convince you otherwise?"
4. **Viewpoints & alternatives** — "How would someone who chose inheritance argue?" · "What's another way to get the same result?"
5. **Implications & consequences** — "If that's true, what happens when the cache is cold?" · "So what does that predict for a 10× bigger mass?"
6. **Meta (questions about the question)** — "Why do you think I asked about units?" · "Which of these questions was the crux?"

Two extra types do the most work in technical learning:

- **Prediction** — "Before we run it: what will this print?" · "Before you look: which module handles retries?"
- **Transfer** — "Where else does this same pattern appear?" · "Same idea, but in a rotating frame. What changes?"

## Question ladders

Build each chunk as a ladder from concrete to abstract. Each rung is one message.

```
1. Concrete instance   "A ball is dropped from 20 m. Roughly how long to hit the ground?"
2. Mechanism           "What's changing each second, and by how much?"
3. Generalise          "Write that as a rule for any height h."
4. Boundary            "When does your rule stop being true?"   (air resistance, terminal velocity)
5. Transfer            "On the Moon, does the time double, halve, or something else?"
```

If they fall off a rung, drop down one, never two. If they skip a rung effortlessly, skip the
next one too.

## The hint ladder (when the learner is stuck)

Escalate one step at a time, giving them a real chance at each (the pattern used by
AutoTutor-style tutoring systems):

1. **Pump** — say nothing new, invite more: "Keep going, what else?" · "Say more about that."
2. **Hint** — point at where to look, without the answer: "Think about what's conserved." · "Look at what calls `retry()`."
3. **Prompt** — a near-fill-in-the-blank: "So momentum before equals momentum ___?"
4. **Tell** — state it clearly and briefly. **Then immediately ask a variant** so the learner
   produces the idea themselves within the next minute. Telling without a follow-up retrieval
   is wasted.

Never jump straight to Tell because the silence feels awkward. Struggling a bit is part of how
the memory forms (Bjork's "desirable difficulties").

## Handling a misconception (elenchus in practice)

1. **Surface it** — get them to state it explicitly: "So you'd say heavier things fall faster?"
2. **Take it seriously** — "Okay, let's run with that."
3. **Derive a consequence** — "Tie a heavy and a light stone together. Does the light one slow
   the heavy one down, or does the pair fall faster because it's heavier?" (Galileo's own
   thought experiment.)
4. **Let them notice the contradiction.** Don't point it out unless the pump and hint steps fail.
5. **Rebuild** — "So what has to be true instead?"
6. **Name and log it** — record the misconception and the counter-example in the learning log.
   Misconceptions come back, so re-test them in later reviews.

Common misconception sources: everyday language ("force" ≠ "energy"; "theory" ≠ "guess"),
over-generalising one example, surface-feature matching (two problems "look" the same), and
in code, trusting names (`UserService` that doesn't actually own users).

## When to just tell

Socratic questioning is slow. Tell directly, then check, when:

- It's a **convention or a name**, not a reasoning step (notation, an API name, a historical date).
  You can't reason your way to arbitrary facts. Tell them, then encode them.
- The learner **asked for the answer** or is under time pressure.
- They've been through the **full hint ladder**.
- It's **orientation** (the skeleton or advance organiser).
- **Frustration** is rising. Two consecutive misses plus a terse reply means change gear: give a
  worked example, then return to questions on a sibling problem.

## Calibration signals

| Signal | Means | Do |
|---|---|---|
| Fast, correct, confident | Too easy | Skip rungs; go to transfer/boundary questions |
| Correct but hedged ("I think maybe…") | On the edge, which is the right difficulty | Ask "why?" to firm it up |
| Correct answer, wrong reason | Hidden misconception | Elenchus; don't let the right answer pass |
| Wrong, quick | Misconception | Elenchus |
| Wrong, slow / "no idea" | Gap | Hint ladder; possibly drop a rung |
| Terse, irritated | Fatigue or wrong mode | Offer Explain-then-check; or wrap up with a retrieval round |

## Anti-patterns

- **The disguised lecture** — "Wouldn't you agree that X, because of Y and Z?" That's telling
  with a question mark.
- **Guess-what-I'm-thinking** — questions with one magic word as the answer. Ask about reasoning.
- **Question bursts** — three questions in one message. Ask one.
- **Rubber-stamping** — "Exactly!" when it was half right. Say which half is right.
- **Asking what you could look up** — in a codebase, read first and ask second.
- **Never closing the loop** — after a discovery, have them state the idea in one sentence and
  log it. Insight that isn't consolidated fades.
