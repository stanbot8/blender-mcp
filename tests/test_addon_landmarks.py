"""Tests for get_mesh_landmarks landmark detection."""

import pytest
from tests.mock_bpy import bpy_module as bpy


class TestLandmarkExtremities:
    def test_extremities_cube(self, server):
        bpy.create_test_mesh("Cube", vertices=[
            (-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0),
            (-1, -1, 2), (1, -1, 2), (1, 1, 2), (-1, 1, 2),
        ], edges=[
            (0, 1), (1, 2), (2, 3), (3, 0),
            (4, 5), (5, 6), (6, 7), (7, 4),
            (0, 4), (1, 5), (2, 6), (3, 7),
        ])
        result = server.get_mesh_landmarks("Cube")
        ext = result["extremities"]
        assert ext["top"][2] == 2.0
        assert ext["bottom"][2] == 0.0
        assert ext["left"][0] == -1.0
        assert ext["right"][0] == 1.0
        assert ext["front"][1] == -1.0
        assert ext["back"][1] == 1.0

    def test_mesh_not_found(self, server):
        with pytest.raises(Exception, match="Mesh not found"):
            server.get_mesh_landmarks("Ghost")


class TestLandmarkSpineLine:
    def test_spine_samples(self, server):
        # Vertical column of vertices
        verts = [(0, 0, i * 0.2) for i in range(11)]  # z from 0 to 2
        edges = [(i, i + 1) for i in range(10)]
        bpy.create_test_mesh("Column", vertices=verts, edges=edges)

        result = server.get_mesh_landmarks("Column", num_height_samples=5)
        assert len(result["spine_line"]) > 0
        assert len(result["spine_line"]) <= 5
        # Each point should have position, width, depth
        for pt in result["spine_line"]:
            assert "position" in pt
            assert "width" in pt
            assert "depth" in pt
            assert "height_pct" in pt

    def test_zero_samples(self, server):
        bpy.create_test_mesh("Dot", vertices=[(0, 0, 0), (1, 0, 1)], edges=[(0, 1)])
        result = server.get_mesh_landmarks("Dot", num_height_samples=0)
        assert result["spine_line"] == []


class TestLandmarkJointCandidates:
    def test_narrowing_detected(self, server):
        # Create an hourglass shape: wide at top and bottom, narrow in middle
        verts = []
        edges = []
        vi = 0
        for z_idx in range(5):
            z = z_idx * 0.5  # z = 0, 0.5, 1.0, 1.5, 2.0
            # Width pattern: wide, medium, narrow, medium, wide
            widths = [1.0, 0.6, 0.3, 0.6, 1.0]
            w = widths[z_idx]
            verts.append((-w, 0, z))
            verts.append((w, 0, z))
            if vi > 0:
                edges.append((vi - 2, vi))
                edges.append((vi - 1, vi + 1))
            vi += 2

        bpy.create_test_mesh("Hourglass", vertices=verts, edges=edges)
        result = server.get_mesh_landmarks("Hourglass", num_height_samples=5)

        # Should detect at least one narrowing point
        assert len(result["joint_candidates"]) >= 1
        for jc in result["joint_candidates"]:
            assert jc["type"] == "narrowing"


class TestLandmarkWidthMaxima:
    def test_widening_detected(self, server):
        # Create a diamond shape: narrow at top and bottom, wide in middle
        verts = []
        edges = []
        vi = 0
        for z_idx in range(5):
            z = z_idx * 0.5
            widths = [0.2, 0.6, 1.0, 0.6, 0.2]
            w = widths[z_idx]
            verts.append((-w, 0, z))
            verts.append((w, 0, z))
            if vi > 0:
                edges.append((vi - 2, vi))
                edges.append((vi - 1, vi + 1))
            vi += 2

        bpy.create_test_mesh("Diamond", vertices=verts, edges=edges)
        result = server.get_mesh_landmarks("Diamond", num_height_samples=5)

        assert len(result["width_maxima"]) >= 1
        for wm in result["width_maxima"]:
            assert wm["type"] == "widening"


class TestLandmarkIslandLabels:
    def test_main_body_labeled(self, server):
        # Single island should be labeled main_body
        bpy.create_test_mesh("Body", vertices=[
            (0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
        ], edges=[(0, 1), (1, 2), (2, 3), (3, 0)])

        result = server.get_mesh_landmarks("Body")
        assert len(result["labeled_islands"]) == 1
        assert "main_body" in result["labeled_islands"][0]["labels"]

    def test_top_region_labeled(self, server):
        # Main body at bottom, small island at top
        bpy.create_test_mesh("WithHead", vertices=[
            # Main body (4 verts, bottom)
            (-1, 0, 0), (1, 0, 0), (1, 0, 1), (-1, 0, 1),
            # Top island (2 verts)
            (0, 0, 9), (0.1, 0, 9.5),
        ], edges=[
            (0, 1), (1, 2), (2, 3), (3, 0),
            (4, 5),
        ])

        result = server.get_mesh_landmarks("WithHead")
        assert len(result["labeled_islands"]) == 2
        labels_flat = []
        for isl in result["labeled_islands"]:
            labels_flat.extend(isl["labels"])
        assert "main_body" in labels_flat
        assert "top_region" in labels_flat

    def test_side_islands_labeled(self, server):
        # Main body in center, small island on the right (+X)
        bpy.create_test_mesh("WithArm", vertices=[
            # Main body (4 verts)
            (-0.5, 0, 0), (0.5, 0, 0), (0.5, 0, 2), (-0.5, 0, 2),
            # Right island (2 verts, far +X)
            (3, 0, 1), (3.5, 0, 1),
        ], edges=[
            (0, 1), (1, 2), (2, 3), (3, 0),
            (4, 5),
        ])

        result = server.get_mesh_landmarks("WithArm")
        labels_flat = []
        for isl in result["labeled_islands"]:
            labels_flat.extend(isl["labels"])
        assert "right_side" in labels_flat


class TestLandmarkHeight:
    def test_height_value(self, server):
        bpy.create_test_mesh("Tall", vertices=[
            (0, 0, 0), (0, 0, 5),
        ], edges=[(0, 1)])

        result = server.get_mesh_landmarks("Tall")
        assert result["height"] == 5.0
