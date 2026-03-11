"""Tests for armature/bone creation and editing in addon.py."""

import pytest
from tests.mock_bpy import bpy_module as bpy


class TestCreateArmature:
    def test_basic_creation(self, server):
        result = server.create_armature(name="Arm1")
        assert result["armature_name"] == "Arm1"
        assert result["bone_count"] == 1
        assert result["root_bone"] == "Root"

    def test_registers_in_bpy_data(self, server):
        server.create_armature(name="Arm1")
        obj = bpy.data.objects.get("Arm1")
        assert obj is not None
        assert obj.type == "ARMATURE"

    def test_location(self, server):
        server.create_armature(name="Arm1", location=[3, 4, 5])
        obj = bpy.data.objects.get("Arm1")
        assert list(obj.location) == [3.0, 4.0, 5.0]

    def test_root_bone_positions(self, server):
        server.create_armature(name="Arm1")
        obj = bpy.data.objects.get("Arm1")
        bones = list(obj.data.bones)
        assert len(bones) == 1
        assert bones[0].name == "Root"
        assert bones[0].head_local == [0.0, 0.0, 0.0]
        assert bones[0].tail_local == [0.0, 0.0, 0.5]

    def test_returns_to_object_mode(self, server):
        server.create_armature(name="Arm1")
        assert bpy._get_mode() == 'OBJECT'


class TestAddBone:
    def test_add_basic_bone(self, server_with_armature):
        srv, _ = server_with_armature
        result = srv.add_bone("TestArm", "MyBone", head=[0, 0, 1], tail=[0, 0, 2])
        assert result["bone_name"] == "MyBone"
        assert result["armature_name"] == "TestArm"

    def test_bone_with_parent(self, server_with_armature):
        srv, _ = server_with_armature
        result = srv.add_bone("TestArm", "Child", head=[0, 0, 0.5],
                              tail=[0, 0, 1], parent_bone="Root", connected=True)
        assert result["parent"] == "Root"

    def test_parent_not_found(self, server_with_armature):
        srv, _ = server_with_armature
        with pytest.raises(Exception, match="Parent bone not found"):
            srv.add_bone("TestArm", "Child", head=[0, 0, 0], tail=[0, 0, 1],
                         parent_bone="NonExistent")

    def test_armature_not_found(self, server):
        with pytest.raises(Exception, match="Armature not found"):
            server.add_bone("NoArm", "Bone", head=[0, 0, 0], tail=[0, 0, 1])

    def test_bone_count_increments(self, server_with_armature):
        srv, _ = server_with_armature
        srv.add_bone("TestArm", "B1", head=[0, 0, 1], tail=[0, 0, 2])
        srv.add_bone("TestArm", "B2", head=[0, 0, 2], tail=[0, 0, 3])
        obj = bpy.data.objects.get("TestArm")
        assert len(obj.data.bones) == 3  # Root + B1 + B2


class TestAddBoneChain:
    def test_creates_chain(self, server_with_armature):
        srv, _ = server_with_armature
        result = srv.add_bone_chain("TestArm", "Spine",
                                    start=[0, 0, 1], direction=[0, 0, 1],
                                    count=4, bone_length=0.25)
        assert result["count"] == 4
        assert len(result["chain_bones"]) == 4
        assert result["chain_bones"][0] == "Spine_01"
        assert result["chain_bones"][3] == "Spine_04"

    def test_chain_with_parent(self, server_with_armature):
        srv, _ = server_with_armature
        result = srv.add_bone_chain("TestArm", "Tail",
                                    start=[0, 0, 0.5], direction=[0, -1, 0],
                                    count=3, bone_length=0.2,
                                    parent_bone="Root")
        assert result["count"] == 3

    def test_chain_parent_not_found(self, server_with_armature):
        srv, _ = server_with_armature
        with pytest.raises(Exception, match="Parent bone not found"):
            srv.add_bone_chain("TestArm", "Chain",
                               start=[0, 0, 0], direction=[0, 0, 1],
                               count=2, bone_length=0.3,
                               parent_bone="Missing")


class TestEditBone:
    def test_edit_head_tail(self, server_with_armature):
        srv, _ = server_with_armature
        result = srv.edit_bone("TestArm", "Root",
                               head=[0, 0, 0.1], tail=[0, 0, 0.9])
        assert result["updated"] is True

    def test_edit_roll(self, server_with_armature):
        srv, _ = server_with_armature
        result = srv.edit_bone("TestArm", "Root", roll=1.57)
        assert result["updated"] is True

    def test_edit_unparent(self, server_with_armature):
        srv, _ = server_with_armature
        srv.add_bone("TestArm", "Child", head=[0, 0, 0.5], tail=[0, 0, 1],
                      parent_bone="Root")
        result = srv.edit_bone("TestArm", "Child", parent_bone="")
        assert result["updated"] is True

    def test_bone_not_found(self, server_with_armature):
        srv, _ = server_with_armature
        with pytest.raises(Exception, match="Bone not found"):
            srv.edit_bone("TestArm", "Ghost", head=[0, 0, 0])


class TestRemoveBone:
    def test_remove(self, server_with_armature):
        srv, _ = server_with_armature
        srv.add_bone("TestArm", "Extra", head=[0, 0, 1], tail=[0, 0, 2])
        result = srv.remove_bone("TestArm", "Extra")
        assert result["removed"] == "Extra"
        assert result["remaining_bones"] == 1  # just Root left

    def test_remove_not_found(self, server_with_armature):
        srv, _ = server_with_armature
        with pytest.raises(Exception, match="Bone not found"):
            srv.remove_bone("TestArm", "Missing")


class TestGetArmatureInfo:
    def test_basic_info(self, server_with_armature):
        srv, _ = server_with_armature
        info = srv.get_armature_info("TestArm")
        assert info["name"] == "TestArm"
        assert info["bone_count"] == 1
        assert len(info["bones"]) == 1
        assert info["bones"][0]["name"] == "Root"

    def test_hierarchy(self, server_with_armature):
        srv, _ = server_with_armature
        srv.add_bone("TestArm", "Child", head=[0, 0, 0.5], tail=[0, 0, 1],
                      parent_bone="Root")
        info = srv.get_armature_info("TestArm")
        assert info["bone_count"] == 2

        root_info = next(b for b in info["bones"] if b["name"] == "Root")
        child_info = next(b for b in info["bones"] if b["name"] == "Child")
        assert child_info["parent"] == "Root"
        assert "Child" in root_info["children"]

    def test_not_found(self, server):
        with pytest.raises(Exception, match="Armature not found"):
            server.get_armature_info("Missing")


class TestCreateHumanoidRig:
    def test_bone_count(self, server_with_humanoid):
        srv, result = server_with_humanoid
        assert result["bone_count"] == 21

    def test_expected_bones_present(self, server_with_humanoid):
        srv, result = server_with_humanoid
        bones = result["bones"]
        expected = [
            "Hips", "Spine", "Chest", "Neck", "Head",
            "Shoulder.L", "UpperArm.L", "Forearm.L", "Hand.L",
            "Shoulder.R", "UpperArm.R", "Forearm.R", "Hand.R",
            "UpperLeg.L", "LowerLeg.L", "Foot.L", "Toe.L",
            "UpperLeg.R", "LowerLeg.R", "Foot.R", "Toe.R",
        ]
        for name in expected:
            assert name in bones, f"Missing bone: {name}"

    def test_height_scaling(self, server):
        result = server.create_humanoid_rig(name="Tall", height=2.7)
        assert result["height"] == 2.7
        # Bones should exist and scale is 1.5x default
        assert result["bone_count"] == 21

    def test_returns_to_object_mode(self, server_with_humanoid):
        assert bpy._get_mode() == 'OBJECT'


class TestParentMeshToArmature:
    def test_auto_weights(self, server_with_armature):
        srv, _ = server_with_armature
        # Create a test mesh
        bpy.create_test_mesh("Cube", vertices=[
            (0.5, 0.5, 0), (-0.5, 0.5, 0), (-0.5, -0.5, 0), (0.5, -0.5, 0),
            (0.5, 0.5, 1), (-0.5, 0.5, 1), (-0.5, -0.5, 1), (0.5, -0.5, 1),
        ])

        result = srv.parent_mesh_to_armature("Cube", "TestArm", "ARMATURE_AUTO")
        assert result["mesh"] == "Cube"
        assert result["armature"] == "TestArm"
        assert result["has_armature_modifier"] is True

    def test_mesh_not_found(self, server_with_armature):
        srv, _ = server_with_armature
        with pytest.raises(Exception, match="Mesh not found"):
            srv.parent_mesh_to_armature("NoMesh", "TestArm")

    def test_armature_not_found(self, server):
        bpy.create_test_mesh("Cube", vertices=[(0, 0, 0)])
        with pytest.raises(Exception, match="Armature not found"):
            server.parent_mesh_to_armature("Cube", "NoArm")

    def test_invalid_parent_type(self, server_with_armature):
        srv, _ = server_with_armature
        bpy.create_test_mesh("Cube", vertices=[(0, 0, 0)])
        with pytest.raises(Exception, match="Invalid parent type"):
            srv.parent_mesh_to_armature("Cube", "TestArm", "INVALID")
