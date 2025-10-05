<!--
  ~ Copyright (c) 2023-2024 Datalayer, Inc.
  ~
  ~ BSD 3-Clause License
-->

# Tornado URL Routing - Trailing Slash Issue

## The Problem

When you register a Tornado handler at `/mcp`, requests to `/mcp/` (with trailing slash) will get a **307 redirect** from `/mcp` to `/mcp/`. This can cause issues:

1. The redirect may lose custom headers
2. The redirect may hit a different handler that doesn't have the same configuration
3. Some clients don't handle redirects well for POST requests

### Example Log Output
```
[I] 307 POST /mcp (@127.0.0.1) 0.66ms          # Redirect issued
[W] 403 POST /mcp/ (@127.0.0.1) 0.67ms         # Redirected request hits CSRF check
```

## The Solution

Use a **regex pattern with optional trailing slash** in your URL:

```python
# ❌ BAD - Only matches /mcp (without trailing slash)
handlers = [
    ("/mcp", MyHandler),
]

# ✅ GOOD - Matches both /mcp and /mcp/
handlers = [
    ("/mcp/?", MyHandler),  # The ? makes the trailing slash optional
]
```

## Why This Works

In Tornado URL patterns:
- `/mcp` - Matches only `/mcp` (no trailing slash)
- `/mcp/` - Matches only `/mcp/` (with trailing slash)
- `/mcp/?` - Matches both `/mcp` and `/mcp/` (optional trailing slash)

The `?` is a regex quantifier meaning "0 or 1 of the preceding character" (in this case, the `/`).

## Other Common Patterns

```python
# Match /api/users with optional trailing slash
("/api/users/?", UsersHandler)

# Match /api/users/123 with optional trailing slash
("/api/users/(\d+)/?", UserHandler)

# Match /api/notebooks/path/to/notebook.ipynb
("/api/notebooks/(.*)/?", NotebookHandler)

# Match everything under /mcp/
("/mcp/(.*)/?", MCPSubHandler)

# Match specific subdirectories
("/mcp/(healthz|tools/list|tools/call)/?", UtilityHandler)
```

## When Using url_path_join

When using Jupyter Server's `url_path_join`, the pattern still works:

```python
from jupyter_server.utils import url_path_join

base_url = "/jupyter"  # Could be "/" or "/jupyter" etc.

handlers = [
    (url_path_join(base_url, "/mcp/?"), MCPHandler),
]

# This creates patterns like:
# - "/mcp/?" when base_url is "/"
# - "/jupyter/mcp/?" when base_url is "/jupyter"
```

## Testing

```bash
# Test without trailing slash
curl http://localhost:4040/mcp

# Test with trailing slash
curl http://localhost:4040/mcp/

# Both should return the same response with 200 status (not 307)
```

## Related Issues

### Issue: Different handlers for /path and /path/
If you accidentally register two handlers:
```python
handlers = [
    ("/mcp", HandlerA),
    ("/mcp/", HandlerB),
]
```

Then `/mcp` hits `HandlerA` and `/mcp/` hits `HandlerB`. This can cause inconsistent behavior!

**Solution**: Use one handler with optional trailing slash pattern.

### Issue: XSRF checks on redirected requests
When Tornado redirects `/mcp` → `/mcp/`, the POST request is resent, but if `HandlerA` has CSRF disabled but `HandlerB` doesn't, you get a 403 error.

**Solution**: Use the optional trailing slash pattern so both URLs hit the same handler with the same configuration.

## Best Practices

1. **Always use optional trailing slash** for API endpoints: `/api/endpoint/?`
2. **Be consistent** - Either always require trailing slashes or make them optional
3. **Test both variants** - Test your endpoints with and without trailing slashes
4. **Check redirects** - Monitor your logs for 307 redirects, they're usually a sign of pattern mismatch

## References

- Tornado Web Framework: https://www.tornadoweb.org/
- Python Regex: https://docs.python.org/3/library/re.html
- Jupyter Server Handlers: https://jupyter-server.readthedocs.io/
