"""Tests for bone constraints, IK setup, and posing."""

import pytest
from tests.mock_bpy import bpy_module as bpy


class TestAddBoneConstraint:
    def test_add_ik(self, server_with_armature):
        srv, _ = server_with_armature
        result = srv.add_bone_constraint(
            "TestArm", "Root", "IK",
            properties={"chain_count": 2, "target": "TestArm", "subtarget": "Root"}
        )
        assert result["constraint_type"] == "IK"
        assert result["bone"] == "Root"

    def test_add_copy_rotation(self, server_with_armature):
        srv, _ = server_with_armature
        result = srv.add_bone_constraint(
            "TestArm", "Root", "COPY_ROTATION",
            properties={"influence": 0.5}
        )
        assert result["constraint_type"] == "COPY_ROTATION"

    def test_friendly_name_mapping(self, server_with_armature):
        srv, _ = server_with_armature
        result = srv.add_bone_constraint(
            "TestArm", "Root", "INVERSE_KINEMATICS"
        )
        assert result["constraint_type"] == "IK"

    def test_bone_not_found(self, server_with_armature):
        srv, _ = server_with_armature
        with pytest.raises(Exception, match="Bone not found"):
            srv.add_bone_constraint("TestArm", "Missing", "IK")

    def test_armature_not_found(self, server):
        with pytest.raises(Exception, match="Armature not found"):
            server.add_bone_constraint("NoArm", "Root", "IK")


class TestRemoveBoneConstraint:
    def test_remove(self, server_with_armature):
        srv, _ = server_with_armature
        srv.add_bone_constraint("TestArm", "Root", "IK")
        result = srv.remove_bone_constraint("TestArm", "Root", "IK")
        assert result["removed"] == "IK"

    def test_constraint_not_found(self, server_with_armature):
        srv, _ = server_with_armature
        with pytest.raises(Exception, match="Constraint not found"):
            srv.remove_bone_constraint("TestArm", "Root", "Missing")


class TestSetupIK:
    def test_basic_ik(self, server_with_armature):
        srv, _ = server_with_armature
        result = srv.setup_ik("TestArm", "Root", chain_count=2)
        assert result["constraint_type"] == "IK"

    def test_ik_with_target(self, server_with_armature):
        srv, _ = server_with_armature
        srv.add_bone("TestArm", "IKTarget", head=[0, 0, 2], tail=[0, 0, 2.5])
        result = srv.setup_ik("TestArm", "Root", chain_count=2,
                              target_bone="IKTarget")
        assert result["constraint_type"] == "IK"

    def test_ik_with_pole(self, server_with_armature):
        srv, _ = server_with_armature
        srv.add_bone("TestArm", "Pole", head=[0, 1, 1], tail=[0, 1, 1.5])
        result = srv.setup_ik("TestArm", "Root", chain_count=2,
                              pole_bone="Pole", pole_angle=1.57)
        assert result["constraint_type"] == "IK"


class TestSetBonePose:
    def test_pose_location(self, server_with_armature):
        srv, _ = server_with_armature
        result = srv.set_bone_pose("TestArm", "Root", location=[1, 2, 3])
        assert result["posed"] is True

    def test_pose_euler(self, server_with_armature):
        srv, _ = server_with_armature
        result = srv.set_bone_pose("TestArm", "Root",
                                   rotation_euler=[0.5, 0.5, 0.5])
        assert result["posed"] is True

    def test_pose_quaternion(self, server_with_armature):
        srv, _ = server_with_armature
        result = srv.set_bone_pose("TestArm", "Root",
                                   rotation_quaternion=[1, 0, 0, 0])
        assert result["posed"] is True

    def test_pose_scale(self, server_with_armature):
        srv, _ = server_with_armature
        result = srv.set_bone_pose("TestArm", "Root", scale=[2, 2, 2])
        assert result["posed"] is True

    def test_bone_not_found(self, server_with_armature):
        srv, _ = server_with_armature
        with pytest.raises(Exception, match="Bone not found"):
            srv.set_bone_pose("TestArm", "Missing", location=[0, 0, 0])

    def test_returns_to_object_mode(self, server_with_armature):
        srv, _ = server_with_armature
        srv.set_bone_pose("TestArm", "Root", location=[1, 0, 0])
        assert bpy._get_mode() == 'OBJECT'


class TestResetPose:
    def test_reset_all(self, server_with_armature):
        srv, _ = server_with_armature
        srv.set_bone_pose("TestArm", "Root", location=[5, 5, 5])
        result = srv.reset_pose("TestArm")
        assert result["count"] == 1
        assert "Root" in result["reset_bones"]

    def test_reset_specific_bones(self, server_with_armature):
        srv, _ = server_with_armature
        srv.add_bone("TestArm", "B2", head=[0, 0, 1], tail=[0, 0, 2])
        result = srv.reset_pose("TestArm", bone_names=["Root"])
        assert result["count"] == 1
        assert "Root" in result["reset_bones"]

    def test_armature_not_found(self, server):
        with pytest.raises(Exception, match="Armature not found"):
            server.reset_pose("Missing")
