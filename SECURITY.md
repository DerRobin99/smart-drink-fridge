# Security Policy

## Supported versions

Security fixes are provided for the latest published release and the current
`main` branch. Older releases may no longer receive security updates. Before
reporting a vulnerability, verify whether it is still present in the latest
version.

| Version | Supported |
|---|---|
| Latest release | Yes |
| `main` | Yes |
| Older releases | No |

## Reporting a vulnerability

Please do **not** disclose security vulnerabilities in a public issue,
discussion, or pull request.

Use GitHub's private vulnerability reporting form instead:

[Report a vulnerability privately](https://github.com/DerRobin99/smart-drink-fridge/security/advisories/new)

Include, where possible:

- the affected version or commit;
- a clear description of the impact;
- reproducible steps or a minimal proof of concept;
- relevant configuration details with all secrets removed; and
- any suggested mitigation or fix.

You should receive an initial acknowledgement within seven days. Status updates
will be provided through the private advisory while the report is investigated.
Please allow time for a fix and coordinated release before publishing details.

## Scope

Reports about authentication, authorization, secret handling, Docker update
permissions, database access, and unintended remote access are welcome. The
project is designed for a trusted private network; exposing its Flask service
directly to the public internet is outside the supported deployment model.

