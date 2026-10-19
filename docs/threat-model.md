# Threat Model: Prompt Injection in the Email Assistant

## Assets

- The human user's trust that the assistant only acts within their intent.
- The user's outbound communication channel (email send, calendar invites).
- The assistant's long-term memory (preferences learned from feedback).
- The human-in-the-loop (HITL) approval gate itself — it must not be bypassable.

## Attacker

The attacker is **anyone who can get content into an email the assistant reads**: a sender,
someone CC'd on a thread, or anyone who can edit a quoted/forwarded message before it reaches
the assistant's context window. The attacker does not have access to the assistant's system
prompt, code, or infrastructure — only to the content of an email.

## Attacker capabilities

- Write arbitrary text in the email body, subject, signature, or quoted history.
- Use formatting tricks to hide instructions: HTML comments, zero-width characters, base64
  blobs, fake system/tool message framing, lookalike quoting.
- Impersonate authority (a "CEO", "IT admin") via display name or subject line.
- Reference prior turns or claim to be giving "earlier instructions" to try to get the
  assistant to treat email content as a standing policy update.

## Core rule

**Email content is untrusted data, never instructions.** Only the system prompt, the
developer-defined tools, and explicit human approval through the HITL interrupt can change
what actions the assistant takes. Nothing in an email body should be able to:

1. Change the recipient, content, or timing of an action without going through HITL.
2. Cause a send/schedule action to execute without HITL approval.
3. Write to long-term memory.
4. Change the triage classification logic itself (e.g. "classify this as ignore").

## What must never happen

- An email causes `write_email` or `schedule_meeting` to execute without human approval.
- An email causes a message to be sent to a recipient outside an allow-listed domain.
- An email causes a memory write (a preference, an "always trust sender X" rule).
- An email causes the triage router to misclassify in a way that skips HITL for the
  dangerous (respond/schedule) path — i.e. the attacker gets autonomous action by tricking
  the router into classifying a request as something innocuous.

## Out of scope for this project

- Attacks on the LLM provider's infrastructure, model weights, or API itself.
- Supply-chain attacks on dependencies.
- Attacks that require compromising the human reviewer's own judgment (e.g. a very
  convincing but policy-compliant request that a human approves). The guard's job is to make
  sure HITL is *reached* and the reviewer sees an honest, unmanipulated view of the request —
  not to replace human judgment once they've genuinely reviewed it.

## Indirect prompt injection

This threat model is specifically about **indirect prompt injection**: the attacker never
talks to the model directly, they only control data (the email) that the model later reads
as part of its context. This is the realistic threat for an email assistant — the project's
guard (`src/email_assistant/security/`) is designed around this model, assuming the LLM
itself may be fooled by the injected text, and relying on deterministic layers that don't
depend on the LLM "noticing" the attack.
