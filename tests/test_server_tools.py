"""Tests for MCP server tool functions — mocks BlenderConnection.send_command."""

import json
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def mock_blender():
    """Patch get_blender_connection to return a mock."""
    mock_conn = MagicMock()
    with patch('blender_mcp.server.get_blender_connection', return_value=mock_conn):
        yield mock_conn


@pytest.fixture
def ctx():
    return MagicMock()


# We import the tool functions after the mock_bpy is installed (via conftest)
from blender_mcp.server import (  # noqa: E402
    create_armature as tool_create_armature,
    add_bone as tool_add_bone,
    add_bone_chain as tool_add_bone_chain,
    edit_bone as tool_edit_bone,
    remove_bone as tool_remove_bone,
    get_armature_info as tool_get_armature_info,
    parent_mesh_to_armature as tool_parent_mesh,
    add_bone_constraint as tool_add_constraint,
    remove_bone_constraint as tool_remove_constraint,
    set_bone_pose as tool_set_pose,
    reset_pose as tool_reset_pose,
    manage_vertex_groups as tool_manage_vg,
    setup_ik as tool_setup_ik,
    create_humanoid_rig as tool_create_humanoid,
    get_mesh_analysis as tool_mesh_analysis,
    get_mesh_landmarks as tool_mesh_landmarks,
)


class TestCreateArmatureTool:
    def test_sends_correct_command(self, mock_blender, ctx):
        mock_blender.send_command.return_value = {
            "armature_name": "Arm", "bone_count": 1, "root_bone": "Root"
        }
        result = tool_create_armature(ctx, name="Arm")
        mock_blender.send_command.assert_called_once_with(
            "create_armature", {"name": "Arm"}
        )
        data = json.loads(result)
        assert data["armature_name"] == "Arm"

    def test_with_location(self, mock_blender, ctx):
        mock_blender.send_command.return_value = {"armature_name": "A", "bone_count": 1, "root_bone": "Root"}
        tool_create_armature(ctx, name="A", location=[1, 2, 3])
        args = mock_blender.send_command.call_args
        assert args[0][1]["location"] == [1, 2, 3]

    def test_error_handling(self, mock_blender, ctx):
        mock_blender.send_command.side_effect = Exception("Connection lost")
        result = tool_create_armature(ctx, name="Arm")
        assert "Error" in result


class TestAddBoneTool:
    def test_sends_command(self, mock_blender, ctx):
        mock_blender.send_command.return_value = {"bone_name": "B1", "armature_name": "A"}
        result = tool_add_bone(ctx, armature_name="A", bone_name="B1",
                               head=[0, 0, 0], tail=[0, 0, 1])
        assert mock_blender.send_command.called
        assert json.loads(result)["bone_name"] == "B1"

    def test_with_parent(self, mock_blender, ctx):
        mock_blender.send_command.return_value = {"bone_name": "B", "armature_name": "A"}
        tool_add_bone(ctx, armature_name="A", bone_name="B",
                      head=[0, 0, 0], tail=[0, 0, 1], parent_bone="Root")
        args = mock_blender.send_command.call_args[0][1]
        assert args["parent_bone"] == "Root"


class TestGetArmatureInfoTool:
    def test_returns_json(self, mock_blender, ctx):
        mock_blender.send_command.return_value = {
            "name": "Arm", "bone_count": 3, "bones": [], "constraints": []
        }
        result = tool_get_armature_info(ctx, armature_name="Arm")
        data = json.loads(result)
        assert data["bone_count"] == 3


class TestSetupIKTool:
    def test_sends_ik_command(self, mock_blender, ctx):
        mock_blender.send_command.return_value = {
            "constraint_type": "IK", "bone": "Hand", "armature": "Arm"
        }
        result = tool_setup_ik(ctx, armature_name="Arm", bone_name="Hand",
                               chain_count=2)
        assert mock_blender.send_command.called
        data = json.loads(result)
        assert data["constraint_type"] == "IK"


class TestMeshAnalysisTool:
    def test_sends_command(self, mock_blender, ctx):
        mock_blender.send_command.return_value = {
            "mesh_name": "Body", "island_count": 3, "islands": []
        }
        result = tool_mesh_analysis(ctx, mesh_name="Body", num_slices=10)
        args = mock_blender.send_command.call_args[0][1]
        assert args["mesh_name"] == "Body"
        assert args["num_slices"] == 10
        data = json.loads(result)
        assert data["island_count"] == 3


class TestMeshLandmarksTool:
    def test_sends_command(self, mock_blender, ctx):
        mock_blender.send_command.return_value = {
            "mesh_name": "Body", "height": 1.8, "extremities": {},
            "spine_line": [], "joint_candidates": [], "width_maxima": [],
            "labeled_islands": []
        }
        result = tool_mesh_landmarks(ctx, mesh_name="Body", num_height_samples=15)
        args = mock_blender.send_command.call_args[0][1]
        assert args["mesh_name"] == "Body"
        assert args["num_height_samples"] == 15
        data = json.loads(result)
        assert data["height"] == 1.8


class TestHumanoidRigTool:
    def test_sends_command(self, mock_blender, ctx):
        mock_blender.send_command.return_value = {
            "armature_name": "Human", "bone_count": 21, "bones": [], "height": 1.8
        }
        result = tool_create_humanoid(ctx, name="Human", height=1.8)
        data = json.loads(result)
        assert data["bone_count"] == 21


class TestParentMeshTool:
    def test_sends_command(self, mock_blender, ctx):
        mock_blender.send_command.return_value = {
            "mesh": "Body", "armature": "Arm", "parent_type": "ARMATURE_AUTO",
            "has_armature_modifier": True, "vertex_groups_count": 5, "vertex_groups": []
        }
        result = tool_parent_mesh(ctx, mesh_name="Body", armature_name="Arm")
        data = json.loads(result)
        assert data["has_armature_modifier"] is True
