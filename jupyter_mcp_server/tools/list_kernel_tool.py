"""List all available kernels tool."""

from jupyter_server_api import JupyterServerClient

from .base import BaseTool, ServerMode
from ..config import get_config


class ListKernelTool(BaseTool):
    """List all available kernels in the Jupyter server.
    
    This tool shows all running and available kernel sessions on the Jupyter server,
    including their IDs, names, states, connection information, and kernel specifications.
    Useful for monitoring kernel resources and identifying specific kernels for connection.
    """
    
    @property
    def name(self) -> str:
        return "list_kernel"
    
    @property
    def description(self) -> str:
        return "List all available kernels in the Jupyter server"
    
    async def execute(
        self,
        mode: ServerMode,
    ) -> str:
        """List all available kernels.
        
        Args:
            mode: Server mode (ignored, always uses HTTP client)
            
        Returns:
            Tab-separated table with columns: ID, Name, Display_Name, Language, State, Connections, Last_Activity, Environment
        """
        config = get_config()
        server_client = JupyterServerClient(base_url=config.runtime_url, token=config.runtime_token)
        
        try:
            # Get all kernels from the Jupyter server
            kernels = server_client.kernels.list_kernels()
            
            if not kernels:
                return "No kernels found on the Jupyter server."
            
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
            
            # Create TSV formatted output
            lines = ["ID\tName\tDisplay_Name\tLanguage\tState\tConnections\tLast_Activity\tEnvironment"]
            
            for kernel in output:
                lines.append(f"{kernel['id']}\t{kernel['name']}\t{kernel['display_name']}\t{kernel['language']}\t{kernel['state']}\t{kernel['connections']}\t{kernel['last_activity']}\t{kernel['env']}")
            
            return "\n".join(lines)
            
        except Exception as e:
            return f"Error listing kernels: {str(e)}"
