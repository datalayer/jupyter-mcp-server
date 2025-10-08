# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""
Environment Configuration Management Module

This module manages environment variables for multimodal output support.
Following the same pattern as other environment variables in the project.
"""

import os


def _get_env_bool(env_name: str, default_value: bool = True) -> bool:
    """
    Get boolean value from environment variable, supporting multiple formats.
    
    Args:
        env_name: Environment variable name
        default_value: Default value
        
    Returns:
        bool: Boolean value
    """
    env_value = os.getenv(env_name)
    if env_value is None:
        return default_value
    
    # Supported true value formats
    true_values = {'true', '1', 'yes', 'on', 'enable', 'enabled'}
    # Supported false value formats  
    false_values = {'false', '0', 'no', 'off', 'disable', 'disabled'}
    
    env_value_lower = env_value.lower().strip()
    
    if env_value_lower in true_values:
        return True
    elif env_value_lower in false_values:
        return False
    else:
        return default_value


# Multimodal Output Configuration
# Environment variable controls whether to return actual image content or text placeholder
ALLOW_IMG_OUTPUT: bool = _get_env_bool("ALLOW_IMG_OUTPUT", True)
