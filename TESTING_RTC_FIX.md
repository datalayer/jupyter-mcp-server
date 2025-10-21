# Testing the RTC Mode Fix

This document explains how to test that the WebSocket disconnect bug has been fixed.

## The Bug

**Original Issue:** MCP cell editing tools (execute_cell, overwrite_cell_source, insert_cell, delete_cell, insert_execute_code_cell) were using file mode instead of RTC mode, causing "Out-of-band changes" that broke the WebSocket connection in JupyterLab, requiring browser refresh.

**Root Cause:** jupyter-mcp-server couldn't find `yroom_manager` because it wasn't added to `web_app.settings` by jupyter-collaboration. The code fell back to file mode.

**Fix:** Access `ywebsocket_server` via `extension_manager.extension_points['jupyter_server_ydoc'].app.ywebsocket_server` and document via `room._document`.

**Additional Fix:** Reading tools (read_cell, read_cells, list_cells) also needed RTC mode to see live unsaved changes instead of stale file data.

## Test Coverage

### Automated Tests

Run the RTC mode tests:

```bash
# Install test dependencies
uv pip install pytest pytest-asyncio

# Run RTC-specific tests
pytest tests/test_rtc_mode.py -v

# Run with JUPYTER_SERVER mode only (the one with jupyter-collaboration)
TEST_MCP_SERVER=false pytest tests/test_rtc_mode.py -v -m jupyter_server
```

### What the Tests Verify

#### 1. `test_rtc_mode_for_cell_operations`
- **Purpose**: Verifies all cell operations complete without causing WebSocket disconnects
- **Tests**: insert_cell, overwrite_cell_source, execute_cell, read_cell, list_cells, delete_cell
- **Pass Criteria**: All operations complete successfully, indicating RTC mode is used
- **Failure Mode**: If file mode is used, operations would cause "Out-of-band changes"

#### 2. `test_reading_tools_see_unsaved_changes`
- **Purpose**: Verifies reading tools see live YDoc data, not stale file data
- **Tests**: read_cell, read_cells, list_cells after making unsaved edits
- **Pass Criteria**: Reading tools see modified content (modified_value=999), NOT initial content (initial_value=1)
- **Failure Mode**: If reading from disk, would see stale initial_value

**This is the KEY test for the new fix** - before our changes, reading tools would fail this test because they read from disk.

#### 3. `test_jupyter_collaboration_extension_loaded`
- **Purpose**: Confirms jupyter-collaboration infrastructure is available
- **Pass Criteria**: Can perform basic operations that require the extension

## Manual Testing

To manually reproduce and verify the fix:

### Prerequisites
```bash
# Start JupyterLab with jupyter-collaboration
cd ~/workspace/tools_and_scripts/main/notebooks/jupyter
./scripts/jupyter-server start

# Or in this repo, start test server
uv run jupyter lab --no-browser --port 8888 --NotebookApp.token=MY_TOKEN
```

### Test Scenario 1: No WebSocket Disconnect

1. **Open notebook in JupyterLab browser UI**
   - Navigate to http://localhost:8888
   - Create or open a notebook
   - Add a cell with: `x = 1`

2. **Use MCP tools to edit the same notebook**
   ```python
   # Via MCP client or Claude Code
   use_notebook("test.ipynb", kernel_id="<existing-kernel-id>")
   overwrite_cell_source(0, "x = 2")
   ```

3. **Verify in JupyterLab UI**
   - ✅ **Expected (FIXED)**: Cell updates to `x = 2`, no error, no need to refresh
   - ❌ **Broken (ORIGINAL BUG)**: "Out-of-band changes" error, WebSocket disconnect, requires browser refresh

### Test Scenario 2: Reading Tools See Live Changes

1. **Create cell via MCP**
   ```python
   use_notebook("test.ipynb", kernel_id="<existing-kernel-id>")
   insert_cell(0, "code", "initial_value = 1")
   ```

2. **Edit cell via MCP (unsaved change)**
   ```python
   overwrite_cell_source(0, "modified_value = 999")
   ```

3. **Read cell back immediately (before any save)**
   ```python
   cell = read_cell(0)
   print(cell["source"])
   ```

4. **Verify**
   - ✅ **Expected (FIXED)**: Shows `modified_value = 999` (live YDoc data)
   - ❌ **Broken (BEFORE FIX)**: Shows `initial_value = 1` (stale file data)

## Validation Script

The `validate_fixes.py` script verifies code patterns without running tests:

```bash
python3 validate_fixes.py
```

This checks:
- ✅ All 8 tools have `_get_jupyter_ydoc()` with RTC logic
- ✅ All tools use `extension_manager.extension_points['jupyter_server_ydoc']`
- ✅ All tools access document via `room._document`
- ✅ No old broken `yroom_manager` patterns

## What Makes a Test Pass vs Fail?

### Indicators RTC Mode is Working (Test PASSES):
1. No "Out-of-band changes" errors in logs
2. Cell operations complete without WebSocket disconnect
3. Reading tools see latest edits immediately (not stale file data)
4. JupyterLab UI updates automatically without refresh

### Indicators File Mode Fallback (Test FAILS):
1. "Out-of-band changes" errors in logs
2. WebSocket disconnects requiring browser refresh
3. Reading tools see old content from disk
4. JupyterLab UI requires refresh to see changes

## Files Modified

### Editing Tools (Fixed in PR #135)
- `execute_cell_tool.py`
- `overwrite_cell_source_tool.py`
- `insert_cell_tool.py`
- `insert_execute_code_cell_tool.py`
- `delete_cell_tool.py`

### Reading Tools (Fixed in follow-up)
- `read_cell_tool.py`
- `read_cells_tool.py`
- `list_cells_tool.py`

## Expected Test Results

```bash
$ pytest tests/test_rtc_mode.py -v

tests/test_rtc_mode.py::test_rtc_mode_for_cell_operations PASSED
tests/test_rtc_mode.py::test_reading_tools_see_unsaved_changes PASSED
tests/test_rtc_mode.py::test_jupyter_collaboration_extension_loaded PASSED

============================================================
✅ All cell operations completed without WebSocket disconnect!

This confirms:
  - RTC mode is being used (via extension_points)
  - No file-mode fallback occurred
  - No 'Out-of-band changes' would occur
  - WebSocket would remain stable in JupyterLab UI
============================================================
```

## Troubleshooting

### Test fails with "extension_points not found"
- Ensure jupyter-collaboration is installed: `uv pip install jupyter-collaboration`
- Check JupyterLab version compatibility (requires JupyterLab 4.x)

### Test fails with "reading tools see stale data"
- Verify the reading tools have been patched with RTC mode
- Check that `_get_jupyter_ydoc()` method exists in read_cell_tool.py

### WebSocket still disconnects
- Check server logs for "Out-of-band changes" errors
- Verify file_id_manager is accessible
- Confirm ywebsocket_server is being found (should see RTC mode logs)

## References

- Original PR: https://github.com/datalayer/jupyter-mcp-server/pull/135
- jupyter-collaboration docs: https://jupyterlab-realtime-collaboration.readthedocs.io/
- Issue: WebSocket disconnects with "Out-of-band changes"
