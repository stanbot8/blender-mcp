"""Shared fixtures — installs mock bpy before anything else."""

import sys
import os

# Install mocks before any addon imports
from tests.mock_bpy import install
install()

# Add project root so `import addon` works
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import addon  # noqa: E402
from tests.mock_bpy import bpy_module  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def clean_bpy_state():
    """Reset mock bpy state before each test."""
    bpy_module.reset()
    yield
    bpy_module.reset()


@pytest.fixture
def server():
    """Fresh BlenderMCPServer instance."""
    return addon.BlenderMCPServer()


@pytest.fixture
def server_with_armature(server):
    """Server + a pre-created armature named 'TestArm'."""
    result = server.create_armature(name="TestArm", location=[0, 0, 0])
    return server, result


@pytest.fixture
def server_with_humanoid(server):
    """Server + a full humanoid rig."""
    result = server.create_humanoid_rig(name="Human", height=1.8)
    return server, result
