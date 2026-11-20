17 compile errors (one per file) from 5 libraries: bloaty, libcoap, open62541, tini, workflow.

| Condition | Errors fixed (verified by recompiling) |
|---|---|
| Rules only | 3/17 (18%) |
| AI alone, no QNX facts (qwen2.5-coder:7b) | 0/17 (0%) |
| AI alone, with QNX facts | 0/17 (0%) |
| Rules, then AI with QNX facts | 3/17 (18%) |

Of the 14 errors no rule fixes: AI without facts fixes 0/14 (0%), with facts 0/14 (0%).
Of the 3 errors a rule fixes (the AI never sees the rules): AI without facts fixes 0/3 (0%), with facts 0/3 (0%).
Accepted AI edits flagged for review (only delete or disable code): 0.
