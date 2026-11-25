# Security policy

SGXray holds people's portfolios, so security is built in, tested and written down.

## Reporting a problem

Please don't open a public issue. Use GitHub's **Report a vulnerability** (Security tab → Advisories), so it can
be fixed before anyone else sees it. You'll get a reply within a week.

## How SGXray is protected

- **Passwords** are stored only as salted scrypt hashes, 12 to 128 characters, with the most common ones refused.
- **Guessing is slowed down.** After 5 wrong passwords for one email (or 20 from one network address) within
  15 minutes, log-ins pause for 15 minutes, then 30, then 60 if it keeps happening that day.
- **Floods are slowed down too.** Page views and saved changes are limited per person (or per network
  address when logged out), well above what anyone reading or typing can reach.
- **Sessions are kept on the server**, so logging out, changing your password or deleting your account really
  ends them. The cookie is HttpOnly, SameSite and Secure on the live site.
- **Your data is yours alone.** Every query is limited to the logged-in person, and another person's trade or
  plan number gives "not found".
- **Every form carries a token** that other websites can't know, and a strict Content Security Policy blocks
  injected scripts.
- **Nothing secret is logged or committed.** The security log holds events and network addresses only, and is
  kept 180 days.
- **No outside service gets your data.** Yahoo Finance and the news feeds only ever receive stock codes and
  fixed addresses.
- **Your data, your call.** Download it or delete your account at any time from the Account page (see the
  [privacy notice](templates/privacy.html)).

The exact limits are in the [full audit record](docs/security-audits.md#the-limits-exactly).

## Audits

| Date | What was checked | Outcome |
|---|---|---|
| 10 Nov 2026 | 70-point launch checklist (OWASP ASVS, API Top 10, LLM Top 10) | 7 fixes |
| 11 Nov 2026 | Pre-launch checklist and legal risks (Singapore's PDPA) | 2 fixes, launch tasks listed |
| 25 Nov 2026 | Full audit: dependency, code and secret scanners; 125 attacks on a running copy; a 20-attack checklist; every calculation against outside references; a legal read | 11 fixes, each with a test |

Every check, its evidence and what's still open before launch: [docs/security-audits.md](docs/security-audits.md).
