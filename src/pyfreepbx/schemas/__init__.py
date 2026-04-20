"""Input/update payload schemas for pyfreepbx.

These are separated from domain models because:
- API responses (models) may include computed/read-only fields
- Mutation inputs (schemas) only include writable fields
- Keeping them apart avoids accidentally sending read-only fields in mutations
"""

from pyfreepbx.schemas.extension_create import ExtensionCreate
from pyfreepbx.schemas.extension_update import ExtensionUpdate
from pyfreepbx.schemas.firewall_create import FirewallNetworkCreate
from pyfreepbx.schemas.firewall_update import FirewallNetworkUpdate
from pyfreepbx.schemas.queue_member import QueueMemberAdd, QueueMemberRemove

__all__ = [
    "ExtensionCreate",
    "ExtensionUpdate",
    "FirewallNetworkCreate",
    "FirewallNetworkUpdate",
    "QueueMemberAdd",
    "QueueMemberRemove",
]
