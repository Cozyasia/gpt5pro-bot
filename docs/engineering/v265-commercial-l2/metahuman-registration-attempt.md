# Actual MetaHumanSDK evaluation registration attempt

2026-09-10. User authorised the registrant name/email for evaluation access and
related technical correspondence. Personal contact data is not included here.

Performed HTTPS POST https://api.metahumansdk.io/auth/token using documented
application/x-www-form-urlencoded name/mail/comment. Public-fixture-only purpose
was stated. Three bounded attempts returned HTTP 504 from this environment;
backoff was 3 seconds then 8 seconds. No other HTTP response fields were logged.
This establishes failed access attempts, not that the vendor is universally down.

No token was obtained. The reserved 0600 file outside the repository was removed
on failure. No fixtures were uploaded; no head config, UV, GLB or geometry was
returned. Case02, case06, case07 and case08 vendor tests remain UNTESTED.
No comparison scores or technical NO-GO are inferred from an access error.

Support route: support@metahumansdk.io, published in the indexed official page
https://metahumansdk.io/privacy . Direct retrieval of that page and the home page
returned 404 in the web tool, so the contact's current availability is unconfirmed.
The exact address is supported by the indexed official text, not guessed.

Sent a Gmail message to that address requesting evaluation/trial access, correct
registration endpoint, current reconstruction/GLB docs and commercial server-side
availability. Subject: Evaluation access request: 3D Face Reconstruction API
/auth/token returns 504. Gmail returned SENT. Delivery/response is not assumed.
The message explicitly disclaims payment authorisation or acceptance of a paid
Order Form, commercial contract or DPA. No credentials or photos were attached.

At the initial mailbox check no relevant incoming verification message was found.
No FaceVerse correspondence or additional vendor survey occurred. Procurement
pilot specification remains prepared; new procurement messages were not sent
because MetaHuman technical NO-GO has not been established. No toy loss tuning,
renderer, production import, merge, deployment or paid commitment occurred.

## Reproduction / safety

Local operator supplies V265_EVALUATION_NAME / V265_EVALUATION_EMAIL and an unused
--secret-file outside the repository. Registration script refuses CI, creates the
secret with O_EXCL and 0600, and logs only attempt numbers/status codes or generic
transport errors. Response bodies are not logged. Only 500/502/503/504 or transport
errors are retried, at most three attempts; non-transient HTTP errors stop early.
Mocked tests verify retry bounds, backoff, failure cleanup and token redaction.
CI tests do not make registration requests.
