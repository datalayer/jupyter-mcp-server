<!--
  ~ Copyright (c) 2023-2024 Datalayer, Inc.
  ~
  ~ BSD 3-Clause License
-->

# Async Fix for list_notebook Tool

## Issue
When calling `list_notebook` with `document_url=local`, got RuntimeWarning:
```
RuntimeWarning: coroutine 'AsyncFileContentsManager.get' was never awaited
```

## Root Cause
The `_list_notebooks_local()` helper function was calling `contents_manager.get()` without awaiting it. Jupyter Server's `contents_manager` methods are **async** and must be awaited.

## Fix Applied

### 1. Made `_list_notebooks_local` async
```python
# Before:
def _list_notebooks_local(contents_manager, path="", notebooks=None):
    model = contents_manager.get(path, content=True, type='directory')  # ❌ Not awaited
    ...

# After:
async def _list_notebooks_local(contents_manager, path="", notebooks=None):
    model = await contents_manager.get(path, content=True, type='directory')  # ✅ Awaited
    ...
```

### 2. Updated recursive call
```python
# Before:
_list_notebooks_local(contents_manager, full_path, notebooks)  # ❌ Not awaited

# After:
await _list_notebooks_local(contents_manager, full_path, notebooks)  # ✅ Awaited
```

### 3. Updated caller in `list_notebook` tool
```python
# Before:
all_notebooks = _list_notebooks_local(contents_manager)  # ❌ Not awaited

# After:
all_notebooks = await _list_notebooks_local(contents_manager)  # ✅ Awaited
```

## Key Takeaway

**When using Jupyter Server's local API, remember:**

### Async Methods (must await)
- `await contents_manager.get(path, content=True)`
- `await contents_manager.save(model, path)`
- `await contents_manager.new(model, path)`
- `await contents_manager.delete(path)`
- `await kernel_manager.start_kernel(...)`
- `await kernel_manager.shutdown_kernel(kernel_id)`

### Sync Methods (HTTP client)
- `server_client.contents.get(path)` - No await needed
- `server_client.contents.save(model, path)` - No await needed
- `kernel_client.start()` - No await needed

## Testing
Restart the server and test:
```bash
make start-as-jupyter-server
# Then test list_notebook tool
```

Should now work without RuntimeWarning! ✅
