"""Remote GPU job API (GPU Sharing tenant)."""

from app.gpu_sharing.client import GPUSharingClient, GPUSharingError

__all__ = ["GPUSharingClient", "GPUSharingError"]
