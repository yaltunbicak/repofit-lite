# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

## Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly:

1. **Do NOT open a public issue.**
2. Email: security@dataguess.com
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
4. We will respond within 48 hours.

## Security Considerations

RepoFit handles:
- **API tokens** (GitHub, GitLab, LLM providers) via `.env` file. Never committed to git.
- **LLM prompts** containing user document content. Sent to configured LLM provider.
- **Cached API responses** stored locally in `./cache/`. May contain repository metadata.

### Best Practices

- Never commit `.env` files
- Use read-only GitHub tokens (no `write` scopes needed)
- Review cached data before sharing `./cache/` directory
- Use `--no-cache` when analyzing sensitive documents
