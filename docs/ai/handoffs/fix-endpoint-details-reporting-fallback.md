# Endpoint detail reporting fallback

PJSIPShowEndpoint requires system-class AMI privileges, even when a caller only needs registration state. On AMIPermissionError, use the existing DeviceStateList action (call/reporting class). Return only the selected endpoint state, mark the source and unavailable detail fields, and keep unknown/missing states unknown. Propagate a second permission denial. Preserve queue-based registration fallback when the reporting list has no usable state.

Based on merged PR73, which provided the typed DeviceStateList primitive and fleet snapshot fallback. No permission changes are made by this SDK.

Validation: full suite 564 passed, 2 existing xpasses, 11 deprecation warnings. Targeted diagnostics/AMI/health: 100 passed. Changed-file Ruff lint/format pass. Consumer must grant reporting access before using the fallback; no system/config/originate permission is needed.

Risk: device state cannot distinguish unregistered from unreachable. It provides no contact IP/user-agent and does not claim full detail availability. No call action is issued. origin/main fetched before push, unchanged from base 8c389c1.
