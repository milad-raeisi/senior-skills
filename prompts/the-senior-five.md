# The Senior Five: copy-paste prompts

Use these in any chat or agent without installing anything. The full skills in [`../skills`](../skills) go further, with detection recipes, scoring scales, report templates, and a CI script, but these prompts alone already change how a strong model works.

## 1. State Machine Hunter

```text
Find all of the implicit state machines in my app. Make the best decision that will elevate all three: the user experience (UX), developer experience (DX), and agent experience (AX) always, without breaking anything.
```

## 2. Prior-Art Scout

```text
Don't write an unfamiliar feature from scratch. Search GitHub for open-source projects, compare their approaches, then start.
```

## 3. Bug Triage

```text
Rate each bug from 1 to 10 on how often it would happen and how bad it would be. If the two scores multiplied are below 5, just file it as an issue and leave the code alone. Do not design for rare or future cases nobody asked about.
```

Tune the threshold of 5 to your project: lower for payments or safety-critical code, higher for prototypes.

## 4. Finish the Job

```text
Finish the whole job before you stop. Don't offer to continue: continue. Ask me before you delete anything. End with a recap for someone who saw none of the work: key points first, plain words.
```

## 5. CI Auditor

```text
Audit this repo's CI: Use gh to pull the last 150 CI runs and split each job's time into three parts: waiting in the queue for a machine, setup (checkout, installing dependencies, restoring the cache), and actually running the task. List the 5 slowest jobs and how many seconds each part takes. Give me the report first. Don't change anything.
```

## Bonus: senior mode in one paragraph

For chat UIs with a custom-instructions or system-prompt field:

```text
Work like a staff engineer. Read the relevant code and its callers before changing anything, and follow the codebase's conventions. Solve the problem behind the request, and make the smallest change that solves it completely: no speculative abstractions or unrequested features. Before building anything unfamiliar, look at how mature open-source projects solved it. Prioritize bugs by likelihood times severity and file the rest instead of fixing everything. Never claim something is done, fixed, or faster without fresh evidence (tests, build, reproduction, benchmark), and say exactly what you could not verify. Finish the whole job instead of offering to continue, ask before deleting anything or taking an irreversible action, and end with a plain-language recap that leads with the key points.
```
