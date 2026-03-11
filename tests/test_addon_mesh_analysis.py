"""Tests for get_mesh_analysis including island detection."""

import pytest
from tests.mock_bpy import bpy_module as bpy


class TestMeshAnalysisBounds:
    def test_unit_cube(self, server):
        bpy.create_test_mesh("Cube", vertices=[
            (-0.5, -0.5, -0.5), (0.5, -0.5, -0.5),
            (0.5, 0.5, -0.5), (-0.5, 0.5, -0.5),
            (-0.5, -0.5, 0.5), (0.5, -0.5, 0.5),
            (0.5, 0.5, 0.5), (-0.5, 0.5, 0.5),
        ], edges=[
            (0, 1), (1, 2), (2, 3), (3, 0),
            (4, 5), (5, 6), (6, 7), (7, 4),
            (0, 4), (1, 5), (2, 6), (3, 7),
        ])

        result = server.get_mesh_analysis("Cube")
        assert result["vertex_count"] == 8
        assert result["bbox_min"] == [-0.5, -0.5, -0.5]
        assert result["bbox_max"] == [0.5, 0.5, 0.5]
        assert result["dimensions"] == [1.0, 1.0, 1.0]
        assert result["center"] == [0.0, 0.0, 0.0]

    def test_off_center_mesh(self, server):
        bpy.create_test_mesh("Offset", vertices=[
            (1, 2, 3), (3, 4, 5),
        ], edges=[(0, 1)])

        result = server.get_mesh_analysis("Offset")
        assert result["bbox_min"] == [1.0, 2.0, 3.0]
        assert result["bbox_max"] == [3.0, 4.0, 5.0]
        assert result["center"] == [2.0, 3.0, 4.0]

    def test_mesh_not_found(self, server):
        with pytest.raises(Exception, match="Mesh not found"):
            server.get_mesh_analysis("Ghost")


class TestMeshAnalysisSlices:
    def test_z_slices_count(self, server):
        # Vertical line of verts from z=0 to z=1
        verts = [(0, 0, i * 0.1) for i in range(11)]
        edges = [(i, i + 1) for i in range(10)]
        bpy.create_test_mesh("Line", vertices=verts, edges=edges)

        result = server.get_mesh_analysis("Line", num_slices=5)
        assert len(result["z_slices"]) > 0
        assert len(result["z_slices"]) <= 5

    def test_zero_slices(self, server):
        bpy.create_test_mesh("Dot", vertices=[(0, 0, 0), (1, 0, 1)], edges=[(0, 1)])
        result = server.get_mesh_analysis("Dot", num_slices=0)
        assert result["z_slices"] == []


class TestMeshAnalysisSymmetry:
    def test_symmetric_mesh(self, server):
        bpy.create_test_mesh("Sym", vertices=[
            (-1, 0, 0), (1, 0, 0), (0, 0, 1),
        ], edges=[(0, 1), (1, 2), (2, 0)])

        result = server.get_mesh_analysis("Sym")
        assert result["likely_symmetric"] is True

    def test_asymmetric_mesh(self, server):
        bpy.create_test_mesh("Asym", vertices=[
            (0, 0, 0), (5, 0, 0), (5, 0, 1),
        ], edges=[(0, 1), (1, 2), (2, 0)])

        result = server.get_mesh_analysis("Asym")
        # Center is at ~3.33, bbox center is 2.5, offset is 0.83 vs width 5 → 16.6% > 5%
        assert result["likely_symmetric"] is False


class TestMeshAnalysisIslands:
    def test_single_island(self, server):
        bpy.create_test_mesh("One", vertices=[
            (0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
        ], edges=[(0, 1), (1, 2), (2, 3), (3, 0)])

        result = server.get_mesh_analysis("One")
        assert result["island_count"] == 1

    def test_two_islands(self, server):
        # Two disconnected quads
        bpy.create_test_mesh("Two", vertices=[
            # Island A
            (0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
            # Island B (offset in X)
            (5, 0, 0), (6, 0, 0), (6, 1, 0), (5, 1, 0),
        ], edges=[
            (0, 1), (1, 2), (2, 3), (3, 0),  # Island A
            (4, 5), (5, 6), (6, 7), (7, 4),  # Island B
        ])

        result = server.get_mesh_analysis("Two")
        assert result["island_count"] == 2

    def test_three_islands(self, server):
        bpy.create_test_mesh("Three", vertices=[
            (0, 0, 0), (1, 0, 0),  # Island A
            (5, 0, 0), (6, 0, 0),  # Island B
            (10, 0, 0), (11, 0, 0),  # Island C
        ], edges=[
            (0, 1),  # A
            (2, 3),  # B
            (4, 5),  # C
        ])

        result = server.get_mesh_analysis("Three")
        assert result["island_count"] == 3

    def test_islands_sorted_by_size(self, server):
        bpy.create_test_mesh("Sorted", vertices=[
            # Small island (2 verts)
            (0, 0, 0), (1, 0, 0),
            # Large island (4 verts)
            (5, 0, 0), (6, 0, 0), (6, 1, 0), (5, 1, 0),
        ], edges=[
            (0, 1),
            (2, 3), (3, 4), (4, 5), (5, 2),
        ])

        result = server.get_mesh_analysis("Sorted")
        assert result["island_count"] == 2
        # Largest island first
        assert result["islands"][0]["vertex_count"] == 4
        assert result["islands"][1]["vertex_count"] == 2

    def test_island_centers(self, server):
        bpy.create_test_mesh("Centers", vertices=[
            # Island at origin
            (-1, 0, 0), (1, 0, 0),
            # Island at x=10
            (9, 0, 0), (11, 0, 0),
        ], edges=[(0, 1), (2, 3)])

        result = server.get_mesh_analysis("Centers")
        assert result["island_count"] == 2
        centers = [isl["center"] for isl in result["islands"]]
        center_xs = sorted([c[0] for c in centers])
        assert abs(center_xs[0] - 0.0) < 0.01
        assert abs(center_xs[1] - 10.0) < 0.01

    def test_no_edges_all_isolated(self, server):
        bpy.create_test_mesh("Loose", vertices=[
            (0, 0, 0), (1, 0, 0), (2, 0, 0),
        ], edges=[])  # No edges → each vertex is its own island

        result = server.get_mesh_analysis("Loose")
        assert result["island_count"] == 3

    def test_island_bbox(self, server):
        bpy.create_test_mesh("BBox", vertices=[
            (0, 0, 0), (2, 3, 4),  # Island spanning from origin to (2,3,4)
        ], edges=[(0, 1)])

        result = server.get_mesh_analysis("BBox")
        island = result["islands"][0]
        assert island["bbox_min"] == [0.0, 0.0, 0.0]
        assert island["bbox_max"] == [2.0, 3.0, 4.0]
        assert island["dimensions"] == [2.0, 3.0, 4.0]
