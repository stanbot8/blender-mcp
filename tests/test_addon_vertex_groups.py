"""Tests for vertex group management."""

import pytest
from tests.mock_bpy import bpy_module as bpy


@pytest.fixture
def mesh(server):
    bpy.create_test_mesh("TestMesh", vertices=[
        (0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1),
    ])
    return server


class TestManageVertexGroups:
    def test_create(self, mesh):
        result = mesh.manage_vertex_groups("TestMesh", "create", "Group1")
        assert result["action"] == "created"
        assert result["vertex_group"] == "Group1"

    def test_remove(self, mesh):
        mesh.manage_vertex_groups("TestMesh", "create", "Group1")
        result = mesh.manage_vertex_groups("TestMesh", "remove", "Group1")
        assert result["action"] == "removed"

    def test_remove_not_found(self, mesh):
        with pytest.raises(Exception, match="Vertex group not found"):
            mesh.manage_vertex_groups("TestMesh", "remove", "Missing")

    def test_assign(self, mesh):
        result = mesh.manage_vertex_groups("TestMesh", "assign", "Weights",
                                           vertex_indices=[0, 1, 2], weight=0.75)
        assert result["action"] == "assigned"
        assert result["vertex_count"] == 3
        assert result["weight"] == 0.75

    def test_assign_creates_if_missing(self, mesh):
        result = mesh.manage_vertex_groups("TestMesh", "assign", "New",
                                           vertex_indices=[0], weight=1.0)
        assert result["action"] == "assigned"

    def test_list(self, mesh):
        mesh.manage_vertex_groups("TestMesh", "create", "A")
        mesh.manage_vertex_groups("TestMesh", "create", "B")
        result = mesh.manage_vertex_groups("TestMesh", "list", "")
        assert result["action"] == "list"
        assert result["count"] == 2
        names = [g["name"] for g in result["vertex_groups"]]
        assert "A" in names
        assert "B" in names

    def test_invalid_action(self, mesh):
        with pytest.raises(Exception, match="Unknown action"):
            mesh.manage_vertex_groups("TestMesh", "invalid", "X")

    def test_mesh_not_found(self, server):
        with pytest.raises(Exception, match="Mesh not found"):
            server.manage_vertex_groups("Missing", "list", "")
