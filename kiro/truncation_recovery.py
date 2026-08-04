# -*- coding: utf-8 -*-

# Kiro Gateway
# https://github.com/jwadow/kiro-gateway
# Copyright (C) 2025 Jwadow
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""
Truncation recovery system for handling upstream Kiro API limitations.

Generates synthetic messages to inform the model about truncation.
ONLY activates when truncation is actually detected.

This module addresses incomplete Kiro responses, including malformed tool
arguments and interrupted response bodies. Recovery messages distinguish a
temporary transport interruption from other incomplete output so the model
does not infer a payload-size limit without evidence.
"""

from typing import Dict, Any

from loguru import logger


TRANSPORT_INTERRUPTION_CAUSE = "transport_interruption"


def should_inject_recovery() -> bool:
    """
    Check if truncation recovery is enabled.
    
    Returns:
        True if recovery should be injected, False otherwise
    """
    from kiro.config import TRUNCATION_RECOVERY
    return TRUNCATION_RECOVERY


def generate_truncation_tool_result(
    tool_name: str,
    tool_use_id: str,
    truncation_info: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Generate synthetic tool_result for truncated tool call.
    
    Message is selected from the recorded failure cause. Transport failures
    explicitly permit one retry and state that no payload-size limit was
    established. Other incomplete output uses conservative wording and does
    not claim a specific upstream size limit.
    
    Args:
        tool_name: Name of the truncated tool
        tool_use_id: ID of the truncated tool call
        truncation_info: Diagnostic information about truncation
    
    Returns:
        Synthetic tool_result in unified format
    
    Example:
        >>> generate_truncation_tool_result("Write", "call_123", {"size_bytes": 5000, "reason": "missing 2 closing braces"})
        {'type': 'tool_result', 'tool_use_id': 'call_123', 'content': '[API Limitation] ...', 'is_error': True}
    """
    if truncation_info.get("cause") == TRANSPORT_INTERRUPTION_CAUSE:
        content = (
            "[Temporary Upstream Transport Error] The response connection closed before this tool call's arguments "
            "were fully transmitted. The tool result below is a consequence of the interrupted transfer, not a "
            "failure reported by the tool itself.\n\n"
            "This event does not establish a tool-call or payload-size limit. Retry the same operation once through "
            "the original tool with the complete arguments. Do not bypass the tool or call its underlying service "
            "directly solely because of this transport interruption. If one retry is interrupted in the same way, "
            "then use a smaller or chunked operation only if the original tool supports it."
        )
    else:
        content = (
            "[Incomplete Upstream Tool Call] The upstream response ended with incomplete tool arguments. The tool "
            "result below is a consequence of those missing arguments, not a failure reported by the tool itself.\n\n"
            "No specific payload-size limit can be inferred from this event. Retry the original tool once. If the "
            "same operation fails deterministically again, adapt using smaller or chunked operations supported by "
            "that tool. Do not bypass the tool's normal interface solely because of this error."
        )
    
    logger.debug(
        f"Generated synthetic tool_result for truncated tool '{tool_name}' "
        f"(id={tool_use_id}, {truncation_info['size_bytes']} bytes, {truncation_info['reason']})"
    )
    
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content,
        "is_error": True
    }


def generate_truncation_user_message() -> str:
    """
    Generate synthetic user message for content truncation.
    
    Message is carefully worded to:
    - Acknowledge it's not model's fault
    - Suggest adaptation without specific instructions
    - NOT tell model to "break into steps" (causes micro-steps)
    
    Returns:
        Synthetic user message text
    
    Example:
        >>> generate_truncation_user_message()
        '[System Notice] Your previous response was truncated...'
    """
    return (
        "[System Notice] Your previous response was truncated by the API due to "
        "output size limitations. This is not an error on your part. "
        "If you need to continue, please adapt your approach rather than repeating the same output."
    )
