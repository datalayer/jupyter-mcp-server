# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""List all available kernels tool."""

from typing import Any, Optional, List, Dict
from jupyter_server_client import JupyterServerClient

from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.utils import format_TSV


class ListKernelsTool(BaseTool):
    """List all available kernel specs and currently active kernels in the Jupyter server."""
    
    def _list_kernels_http(
            self, server_client: JupyterServerClient
    ) -> tuple[List[Dict[str, str]], List[Dict[str, str]]]:
        """List active kernels and available kernel specs using HTTP API (MCP_SERVER mode)."""
        try:
            # 1. Fetch Available Kernel Specs
            available_specs = []
            kernels_specs = server_client.kernelspecs.list_kernelspecs()
            
            specs_dict = getattr(kernels_specs, 'kernelspecs', {}) or {}
            for name, spec_obj in specs_dict.items():
                spec = getattr(spec_obj, 'spec', spec_obj)
                
                display_name = getattr(spec, 'display_name', name) if hasattr(spec, 'display_name') else spec.get('display_name', name)
                language = getattr(spec, 'language', 'unknown') if hasattr(spec, 'language') else spec.get('language', 'unknown')
                
                env_dict = getattr(spec, 'env', {}) if hasattr(spec, 'env') else spec.get('env', {})
                env_str = "; ".join([f"{k}={v}" for k, v in env_dict.items()]) if env_dict else "none"
                if len(env_str) > 100:
                    env_str = env_str[:100] + "..."

                available_specs.append({
                    "name": name,
                    "display_name": display_name,
                    "language": language,
                    "env": env_str,
                })
            

            # 2. Get active kernels from the Jupyter server
            active_kernels = []
            kernels = server_client.kernels.list_kernels() or []
            
            # Create enhanced kernel information list
            for kernel in kernels:
                kernel_info = {
                    "id": kernel.id or "unknown",
                    "name": kernel.name or "unknown",
                    "state": "unknown",
                    "connections": "unknown", 
                    "last_activity": "unknown",
                    "display_name": "unknown",
                    "language": "unknown",
                    "env": "unknown"
                }
                
                # Get kernel state - this might vary depending on the API version
                if hasattr(kernel, 'execution_state'):
                    kernel_info["state"] = kernel.execution_state
                elif hasattr(kernel, 'state'):
                    kernel_info["state"] = kernel.state
                
                # Get connection count
                if hasattr(kernel, 'connections'):
                    kernel_info["connections"] = str(kernel.connections)
                
                # Get last activity
                if hasattr(kernel, 'last_activity') and kernel.last_activity:
                    if hasattr(kernel.last_activity, 'strftime'):
                        kernel_info["last_activity"] = kernel.last_activity.strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        kernel_info["last_activity"] = str(kernel.last_activity)
                
                active_kernels.append(kernel_info)
            
            # Enhance kernel info with specifications
            for kernel in active_kernels:
                kernel_name = kernel["name"]
                if hasattr(kernels_specs, 'kernelspecs') and kernel_name in kernels_specs.kernelspecs:
                    kernel_spec = kernels_specs.kernelspecs[kernel_name]
                    if hasattr(kernel_spec, 'spec'):
                        if hasattr(kernel_spec.spec, 'display_name'):
                            kernel["display_name"] = kernel_spec.spec.display_name
                        if hasattr(kernel_spec.spec, 'language'):
                            kernel["language"] = kernel_spec.spec.language
                        if hasattr(kernel_spec.spec, 'env'):
                            # Convert env dict to a readable string format
                            env_dict = kernel_spec.spec.env
                            if env_dict:
                                env_str = "; ".join([f"{k}={v}" for k, v in env_dict.items()])
                                kernel["env"] = env_str[:100] + "..." if len(env_str) > 100 else env_str
            
            return available_specs, active_kernels
            
        except Exception as e:
            raise RuntimeError(f"Error listing kernels via HTTP: {str(e)}")
    
    async def _list_kernels_local(
        self, 
        kernel_manager: Any, 
        kernel_spec_manager: Any
    ) -> tuple[List[Dict[str, str]], List[Dict[str, str]]]:
        """List active kernels and available kernel specs using local kernel_manager API (JUPYTER_SERVER mode)."""
        try:
            # 1. Fetch Available Kernel Specs
            available_specs = []
            kernels_specs = kernel_spec_manager.get_all_specs() if kernel_spec_manager else {}
            
            for name, spec_info in kernels_specs.items():
                spec = spec_info.get('spec', {})
                display_name = spec.get('display_name', name)
                language = spec.get('language', 'unknown')
                
                env_dict = spec.get('env', {})
                env_str = "; ".join([f"{k}={v}" for k, v in env_dict.items()]) if env_dict else "none"
                if len(env_str) > 100:
                    env_str = env_str[:100] + "..."

                available_specs.append({
                    "name": name,
                    "display_name": display_name,
                    "language": language,
                    "env": env_str,
                })

            # 2. Get all running kernels - list_kernels() returns dicts with kernel info
            running_kernels = list(kernel_manager.list_kernels()) if kernel_manager else []
            
            
            # Create enhanced kernel information list
            active_kernels = []
            for kernel_info_dict in running_kernels:
                # kernel_info_dict is already a dict with kernel information
                kernel_id = kernel_info_dict.get('id', 'unknown')
                kernel_name = kernel_info_dict.get('name', 'unknown')
                
                kernel_info = {
                    "id": kernel_id,
                    "name": kernel_name,
                    "state": kernel_info_dict.get('execution_state', 'unknown'),
                    "connections": str(kernel_info_dict.get('connections', 'unknown')),
                    "last_activity": "unknown",
                    "display_name": "unknown",
                    "language": "unknown",
                    "env": "unknown"
                }
                
                # Format last activity if present
                last_activity = kernel_info_dict.get('last_activity')
                if last_activity:
                    if hasattr(last_activity, 'strftime'):
                        kernel_info["last_activity"] = last_activity.strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        kernel_info["last_activity"] = str(last_activity)
                
                active_kernels.append(kernel_info)
            
            # Enhance kernel info with specifications
            for kernel in active_kernels:
                kernel_name = kernel["name"]
                if kernel_name in kernels_specs:
                    spec = kernels_specs[kernel_name].get('spec', {})
                    if 'display_name' in spec:
                        kernel["display_name"] = spec['display_name']
                    if 'language' in spec:
                        kernel["language"] = spec['language']
                    if 'env' in spec and spec['env']:
                        env_dict = spec['env']
                        env_str = "; ".join([f"{k}={v}" for k, v in env_dict.items()])
                        kernel["env"] = env_str[:100] + "..." if len(env_str) > 100 else env_str
            
            return available_specs, active_kernels
            
        except Exception as e:
            raise RuntimeError(f"Error listing kernels locally: {str(e)}")
    
    async def execute(
        self,
        mode: ServerMode,
        server_client: Optional[JupyterServerClient] = None,
        kernel_client: Optional[Any] = None,
        contents_manager: Optional[Any] = None,
        kernel_manager: Optional[Any] = None,
        kernel_spec_manager: Optional[Any] = None,
        **kwargs
    ) -> str:
        """List all available kernels.
        
        Args:
            mode: Server mode (MCP_SERVER or JUPYTER_SERVER)
            server_client: HTTP client for MCP_SERVER mode
            kernel_manager: Direct kernel manager access for JUPYTER_SERVER mode
            kernel_spec_manager: Kernel spec manager for JUPYTER_SERVER mode
            **kwargs: Additional parameters (unused)
            
        Returns:
            Tab-separated table with columns: ID, Name, Display_Name, Language, State, Connections, Last_Activity, Environment
        """
        # Get kernel info based on mode
        if mode == ServerMode.JUPYTER_SERVER and kernel_manager is not None:
            available_specs, active_kernels = await self._list_kernels_local(kernel_manager, kernel_spec_manager)
        elif mode == ServerMode.MCP_SERVER and server_client is not None:
            available_specs, active_kernels = self._list_kernels_http(server_client)
        else:
            raise ValueError(f"Invalid mode or missing required managers/clients: mode={mode}")
        
        if not available_specs and not active_kernels:
            return "No kernels found on the Jupyter server."
        
        try:
            sections = []

            # Format Section 1: Available Kernel Specs
            sections.append("=== Available Kernel Specs (Can be used to create/start new kernels) ===")
            if available_specs:
                spec_headers = ["Name (kernel_name)", "Display_Name", "Language", "Environment"]
                spec_rows = [
                    [s["name"], s["display_name"], s["language"], s["env"]]
                    for s in available_specs
                ]
                sections.append(format_TSV(spec_headers, spec_rows))
            else:
                sections.append("No kernel specs found.")

            sections.append("\n" + "=" * 100 + "\n")

            # Format Section 2: Active Kernels
            sections.append("=== Active Running Kernels ===")
            if active_kernels:
                active_headers = ["ID (kernel_id)", "Spec_Name", "State", "Connections", "Last_Activity"]
                active_rows = [
                    [k["id"], k["name"], k["state"], k["connections"], k["last_activity"]]
                    for k in active_kernels
                ]
                sections.append(format_TSV(active_headers, active_rows))
            else:
                sections.append("(No active kernels currently running)")

            return "\n".join(sections)
            
        except Exception as e:
            return f"Error formatting kernel list: {str(e)}"

