# Security Policy

## Reporting a vulnerability

Please do not open a public issue for a vulnerability that could expose API
keys, user conversations, product data, or host execution. Instead, use GitHub
private vulnerability reporting for this repository and include:

- affected version or commit;
- reproduction steps;
- expected impact;
- any proposed mitigation.

We aim to acknowledge a complete report within seven days. Please allow time
for validation and coordinated remediation before public disclosure.

## Secrets and data

- Keep API keys in `.env` or a secret manager; never commit them.
- Treat conversation traces as potentially sensitive.
- Do not upload private catalogs or customer profiles to issue attachments.
- Rotate any credential immediately if it appears in a commit, log, or trace.
