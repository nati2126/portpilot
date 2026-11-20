32 compile errors (one per file) from 6 libraries: bloaty, civetweb, libcoap, open62541, tini, workflow.

| Condition | Errors fixed (verified by recompiling) |
|---|---|
| Rules only | 17/32 (53%) |
| AI alone, no QNX facts (qwen2.5-coder:7b) | 0/32 (0%) |
| AI alone, with QNX facts | 6/32 (19%) |
| Rules, then AI with QNX facts | 17/32 (53%) |

Of the 15 errors no rule fixes: AI without facts fixes 0/15 (0%), with facts 0/15 (0%).
Of the 17 errors a rule fixes (the AI never sees the rules): AI without facts fixes 0/17 (0%), with facts 6/17 (35%).
Accepted AI edits flagged for review (only delete or disable code): 0.
