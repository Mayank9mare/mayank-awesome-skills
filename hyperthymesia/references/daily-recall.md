# Daily Recall: Building a Date-Indexed Life Memory

**What hyperthymesia actually is.** Highly Superior Autobiographical Memory (HSAM, first
described by Parker, Cahill & McGaugh in 2006 with the case "AJ"/Jill Price) is a rare condition:
given a date, people with HSAM can say what day of the week it was and what they did. They
don't use mnemonic techniques; the memories arrive automatically. Studies find they tend to
spend a lot of time *rehearsing* autobiographical memories, often organised by date, and they
are not immune to false memories. **You can't train HSAM itself.**

What you *can* build, borrowing their two habits (date-organisation and rehearsal) plus
techniques, is a dependable date-indexed memory of your own life. Ask yourself "what happened on
14 March?" and you get an answer.

## The protocol

### Nightly (3–5 minutes)
1. **Replay the day** in order, morning to night, like walking a route.
2. **Pick 1–3 distinctive moments**: what made today *today*? (A conversation, a decision, a
   meal, a bug fixed, a place, a feeling.)
3. **Make one day-image**: an interacting scene combining the moment(s) with the **date image**
   (day-of-month as its 00–99 image: the 14th = l-r = lorry).
4. **Place it** in the current **month palace**, at the locus for that day (see below).
5. **One line in the journal**: `~/.hyperthymesia/journal/YYYY-MM.md`, e.g.
   `- 14 Sat: lorry rolling through the farmers' market; called Mum about the trip; fixed the cache bug. #people #work`

### Weekly (5–10 minutes, e.g. Sunday)
Walk the week's 7 loci. Recall each day *before* checking the journal, then fix any gaps.

### Monthly (15 minutes)
Walk the whole month palace. Write a 3-line summary at the top of the month file. Recall last
month's palace once more.

### Yearly
Walk each month's summary. Recall a few random dates (`memgym.py gen dates` style, but from
your own year), work out each weekday with Doomsday, then recall the day.

## The calendar palace

- **12 month buildings** (or rooms of one large building), each with 31 loci in a fixed route.
  Reuse the same 12 buildings every year but give each **year** a distinguishing overlay (2026
  = everything is covered in snow, 2027 = everything is underwater). Interference between years
  stays manageable because the journal backs it up.
- Alternative: each day's image carries the date image itself (the 14th's lorry), so one long
  route per month works without numbered loci.
- The day-of-week comes free from the Doomsday algorithm (advanced-systems.md §4), so you don't
  store it.

## Using it

- **"What did I do on…?"** Compute the weekday, go to that month's building and that locus,
  recall the image, then confirm with the journal. Claude can search the journal files for you.
- **Anniversaries and patterns**: the monthly summaries show what you did this time last year.
- **Work memory**: for engineers, tag the journal lines (`#incident`, `#decision`) and you get a
  recallable career log; good for performance reviews and "when did we change X?".

## Keeping it honest

- The journal is ground truth; the palace is the fast index. When they disagree, trust the journal.
- Rehearsing a wrong detail strengthens it. Fix errors at weekly review.
- Miss a night? Recover it the next morning. Two days back is still very recoverable; a week is not.
