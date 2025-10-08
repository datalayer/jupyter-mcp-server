# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""List all available kernels tool."""

from typing import Any, Optional, List, Dict
from jupyter_server_api import JupyterServerClient

from ._base import BaseTool, ServerMode


class ListKernelsTool(BaseTool):
    """List all available kernels in the Jupyter server.
    
    This tool shows all running and available kernel sessions on the Jupyter server,
    including their IDs, names, states, connection information, and kernel specifications.
    Useful for monitoring kernel resources and identifying specific kernels for connection.
    """
    
    @property
    def name(self) -> str:
        return "list_kernels"
    
    @property
    def description(self) -> str:
        return "List all available kernels in the Jupyter server"
    
    def _list_kernels_http(self, server_client: JupyterServerClient) -> List[Dict[str, str]]:
        """List kernels using HTTP API (MCP_SERVER mode)."""
        try:
            # Get all kernels from the Jupyter server
            kernels = server_client.kernels.list_kernels()
            
            if not kernels:
                return []
            
            # Get kernel specifications for additional details
            kernels_specs = server_client.kernelspecs.list_kernelspecs()
            
            # Create enhanced kernel information list
            output = []
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
                
                output.append(kernel_info)
            
            # Enhance kernel info with specifications
            for kernel in output:
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
            
            return output
            
        except Exception as e:
            raise RuntimeError(f"Error listing kernels via HTTP: {str(e)}")
    
    async def _list_kernels_local(
        self, 
        kernel_manager: Any, 
        kernel_spec_manager: Any
    ) -> List[Dict[str, str]]:
        """List kernels using local kernel_manager API (JUPYTER_SERVER mode)."""
        try:
            # Get all running kernels - list_kernels() returns dicts with kernel info
            kernel_infos = list(kernel_manager.list_kernels())
            
            if not kernel_infos:
                return []
            
            # Get kernel specifications
            kernel_specs = kernel_spec_manager.get_all_specs() if kernel_spec_manager else {}
            
            # Create enhanced kernel information list
            output = []
            for kernel_info_dict in kernel_infos:
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
                
                output.append(kernel_info)
            
            # Enhance kernel info with specifications
            for kernel in output:
                kernel_name = kernel["name"]
                if kernel_name in kernel_specs:
                    spec = kernel_specs[kernel_name].get('spec', {})
                    if 'display_name' in spec:
                        kernel["display_name"] = spec['display_name']
                    if 'language' in spec:
                        kernel["language"] = spec['language']
                    if 'env' in spec and spec['env']:
                        env_dict = spec['env']
                        env_str = "; ".join([f"{k}={v}" for k, v in env_dict.items()])
                        kernel["env"] = env_str[:100] + "..." if len(env_str) > 100 else env_str
            
            return output
            
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
            kernel_list = await self._list_kernels_local(kernel_manager, kernel_spec_manager)
        elif mode == ServerMode.MCP_SERVER and server_client is not None:
            kernel_list = self._list_kernels_http(server_client)
        else:
            raise ValueError(f"Invalid mode or missing required managers/clients: mode={mode}")
        
        if not kernel_list:
            return "No kernels found on the Jupyter server."
        
        try:
            # Create TSV formatted output
            lines = ["ID\tName\tDisplay_Name\tLanguage\tState\tConnections\tLast_Activity\tEnvironment"]
            
            for kernel in kernel_list:
                lines.append(f"{kernel['id']}\t{kernel['name']}\t{kernel['display_name']}\t{kernel['language']}\t{kernel['state']}\t{kernel['connections']}\t{kernel['last_activity']}\t{kernel['env']}")
            
            return "\n".join(lines)
            
        except Exception as e:
            return f"Error formatting kernel list: {str(e)}"

