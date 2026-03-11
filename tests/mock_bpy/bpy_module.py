"""
Mock bpy module for testing addon.py without Blender.

Provides enough structure for the BlenderMCPServer rigging/mesh methods to run:
  bpy.data.objects, bpy.data.armatures, bpy.context, bpy.ops.object.mode_set,
  mathutils-compatible Vectors on bones, edit_bones <-> bones sync on mode change.
"""

from .collections import MockCollection
from . import mathutils_module as mathutils


# ── Mode state ──────────────────────────────────────────────────────────────

_current_mode = 'OBJECT'


def _get_mode():
    return _current_mode


# ── Mock data classes ───────────────────────────────────────────────────────

class MockEditBone:
    def __init__(self, name):
        self.name = name
        self._head = mathutils.Vector((0, 0, 0))
        self._tail = mathutils.Vector((0, 0, 1))
        self.roll = 0.0
        self.parent = None
        self.use_connect = False
        self.use_deform = True
        self.envelope_distance = 0.25
        self._children = []

    @property
    def head(self):
        return self._head

    @head.setter
    def head(self, value):
        if isinstance(value, mathutils.Vector):
            self._head = value
        else:
            self._head = mathutils.Vector(value)

    @property
    def tail(self):
        return self._tail

    @tail.setter
    def tail(self, value):
        if isinstance(value, mathutils.Vector):
            self._tail = value
        else:
            self._tail = mathutils.Vector(value)

    @property
    def children(self):
        return self._children


class MockBone:
    """Read-only bone (available after leaving edit mode)."""

    def __init__(self, edit_bone):
        self.name = edit_bone.name
        self.head_local = list(edit_bone.head)
        self.tail_local = list(edit_bone.tail)
        self.length = (
            sum((a - b) ** 2 for a, b in zip(self.head_local, self.tail_local)) ** 0.5
        )
        self.use_connect = edit_bone.use_connect
        self.use_deform = edit_bone.use_deform
        self.parent = None      # set after all bones built
        self.children = []      # set after all bones built
        self._parent_name = edit_bone.parent.name if edit_bone.parent else None


class MockConstraint:
    def __init__(self, ctype):
        self.type = ctype
        self.name = ctype
        self.mute = False
        self.influence = 1.0
        self.target = None
        self.subtarget = ""
        self.pole_target = None
        self.pole_subtarget = ""
        self.pole_angle = 0.0
        self.chain_count = 0
        self.use_tail = True
        self.use_stretch = False


class MockConstraintCollection:
    """Constraints on a pose bone."""

    def __init__(self):
        self._items = {}
        self._order = []

    def new(self, type):
        c = MockConstraint(type)
        # Deduplicate name
        name = type
        if name in self._items:
            i = 1
            while f"{name}.{i:03d}" in self._items:
                i += 1
            name = f"{name}.{i:03d}"
            c.name = name
        self._items[c.name] = c
        self._order.append(c)
        return c

    def get(self, name, default=None):
        return self._items.get(name, default)

    def remove(self, constraint):
        if constraint.name in self._items:
            self._items.pop(constraint.name)
            self._order = [c for c in self._order if c.name != constraint.name]

    def __iter__(self):
        return iter(self._order)

    def __len__(self):
        return len(self._order)


class MockPoseBone:
    def __init__(self, name):
        self.name = name
        self.location = mathutils.Vector((0, 0, 0))
        self.rotation_mode = 'QUATERNION'
        self.rotation_euler = mathutils.Euler((0, 0, 0))
        self.rotation_quaternion = mathutils.Quaternion((1, 0, 0, 0))
        self.scale = mathutils.Vector((1, 1, 1))
        self.constraints = MockConstraintCollection()


class MockVertexGroup:
    def __init__(self, name, index=0):
        self.name = name
        self.index = index
        self._weights = {}  # vertex_index -> weight

    def add(self, indices, weight, mode):
        for idx in indices:
            self._weights[idx] = weight


class MockVertexGroupCollection:
    def __init__(self):
        self._items = {}
        self._order = []
        self._next_index = 0

    def new(self, name):
        vg = MockVertexGroup(name, self._next_index)
        self._next_index += 1
        self._items[name] = vg
        self._order.append(vg)
        return vg

    def get(self, name, default=None):
        return self._items.get(name, default)

    def remove(self, vg):
        if vg.name in self._items:
            self._items.pop(vg.name)
            self._order = [v for v in self._order if v.name != vg.name]

    def __iter__(self):
        return iter(self._order)

    def __len__(self):
        return len(self._order)


class MockModifier:
    def __init__(self, name, mtype):
        self.name = name
        self.type = mtype


class MockVertex:
    def __init__(self, index, co):
        self.index = index
        self.co = mathutils.Vector(co)


class MockEdge:
    def __init__(self, v1, v2):
        self.vertices = (v1, v2)


class MockMeshData:
    def __init__(self, name):
        self.name = name
        self.vertices = []
        self.edges = []
        self.polygons = []


class MockEditBoneCollection:
    """edit_bones collection with .new() that creates MockEditBone."""

    def __init__(self):
        self._items = {}
        self._order = []

    def new(self, name):
        bone = MockEditBone(name)
        # Deduplicate
        if name in self._items:
            i = 1
            while f"{name}.{i:03d}" in self._items:
                i += 1
            bone.name = f"{name}.{i:03d}"
        self._items[bone.name] = bone
        self._order.append(bone)
        return bone

    def get(self, name, default=None):
        return self._items.get(name, default)

    def remove(self, bone):
        if bone.name in self._items:
            self._items.pop(bone.name)
            self._order = [b for b in self._order if b.name != bone.name]

    def __iter__(self):
        return iter(self._order)

    def __len__(self):
        return len(self._order)


class MockArmatureData:
    def __init__(self, name):
        self.name = name
        self.edit_bones = MockEditBoneCollection()
        self.bones = MockCollection()  # populated on mode switch to OBJECT


class MockPose:
    def __init__(self):
        self.bones = _PoseBoneCollection()


class _PoseBoneCollection:
    def __init__(self):
        self._items = {}
        self._order = []

    def get(self, name, default=None):
        return self._items.get(name, default)

    def _add(self, name):
        pb = MockPoseBone(name)
        self._items[name] = pb
        self._order.append(pb)
        return pb

    def __iter__(self):
        return iter(self._order)

    def __len__(self):
        return len(self._order)

    def clear(self):
        self._items.clear()
        self._order.clear()


class MockObject:
    def __init__(self, name, data=None):
        self.name = name
        self.data = data
        self.type = 'EMPTY'
        if isinstance(data, MockArmatureData):
            self.type = 'ARMATURE'
        elif isinstance(data, MockMeshData):
            self.type = 'MESH'

        self.location = mathutils.Vector((0, 0, 0))
        self.rotation_euler = mathutils.Euler((0, 0, 0))
        self.scale = mathutils.Vector((1, 1, 1))
        self.matrix_world = mathutils.Matrix()
        self.parent = None
        self.children = []
        self.material_slots = []
        self.modifiers = []
        self.vertex_groups = MockVertexGroupCollection()
        self.pose = MockPose() if self.type == 'ARMATURE' else None
        self.bound_box = [
            (-0.5, -0.5, -0.5), (0.5, -0.5, -0.5),
            (0.5, 0.5, -0.5), (-0.5, 0.5, -0.5),
            (-0.5, -0.5, 0.5), (0.5, -0.5, 0.5),
            (0.5, 0.5, 0.5), (-0.5, 0.5, 0.5),
        ]
        self._selected = False

    def select_set(self, state):
        self._selected = state

    def visible_get(self):
        return True


# ── Global state ────────────────────────────────────────────────────────────

class _Data:
    """bpy.data"""

    def __init__(self):
        self.objects = MockCollection(factory=lambda name, data=None, **kw: MockObject(name, data))
        self.armatures = MockCollection(factory=lambda name, data=None, **kw: MockArmatureData(name))
        self.materials = MockCollection()
        self.images = MockCollection()

    def reset(self):
        self.objects.clear()
        self.armatures.clear()
        self.materials.clear()
        self.images.clear()


class _Scene:
    def __init__(self):
        self.name = "Scene"
        self.objects = []
        self.blendermcp_use_polyhaven = False
        self.blendermcp_use_hyper3d = False
        self.blendermcp_use_sketchfab = False
        self.blendermcp_use_hunyuan3d = False


class _ViewLayerObjects:
    def __init__(self):
        self.active = None


class _ViewLayer:
    def __init__(self):
        self.objects = _ViewLayerObjects()


class _CollectionObjects(MockCollection):
    def __init__(self):
        super().__init__()


class _Collection:
    def __init__(self):
        self.objects = _CollectionObjects()


class _Context:
    """bpy.context"""

    def __init__(self):
        self.scene = _Scene()
        self.view_layer = _ViewLayer()
        self.collection = _Collection()
        self.screen = _MockScreen()
        self.preferences = _MockPreferences()


class _MockScreen:
    def __init__(self):
        self.areas = []


class _MockPreferences:
    def __init__(self):
        self.addons = {}


# ── Active armature tracking for mode switches ─────────────────────────────

_active_armature_obj = None  # set when view_layer.objects.active is assigned


def _sync_edit_to_bones(armature_obj):
    """Copy edit_bones into the bones collection + pose bones."""
    arm_data = armature_obj.data
    if not isinstance(arm_data, MockArmatureData):
        return

    # Build MockBone list from edit_bones
    bone_map = {}
    bones_list = []
    for eb in arm_data.edit_bones:
        mb = MockBone(eb)
        bone_map[mb.name] = mb
        bones_list.append(mb)

    # Resolve parents and children
    for mb in bones_list:
        if mb._parent_name and mb._parent_name in bone_map:
            mb.parent = bone_map[mb._parent_name]
            bone_map[mb._parent_name].children.append(mb)

    # Replace bones collection
    arm_data.bones = MockCollection()
    for mb in bones_list:
        arm_data.bones._items[mb.name] = mb
        arm_data.bones._order.append(mb)

    # Sync pose bones
    armature_obj.pose.bones.clear()
    for mb in bones_list:
        armature_obj.pose.bones._add(mb.name)


# ── bpy.ops ─────────────────────────────────────────────────────────────────

class _OpsObject:
    @staticmethod
    def mode_set(mode='OBJECT'):
        global _current_mode
        old_mode = _current_mode
        _current_mode = mode

        # On leaving edit mode, sync bones
        if old_mode == 'EDIT' and mode != 'EDIT':
            active = context.view_layer.objects.active
            if active and active.type == 'ARMATURE':
                _sync_edit_to_bones(active)

    @staticmethod
    def select_all(action='DESELECT'):
        for obj in data.objects:
            obj._selected = False

    @staticmethod
    def parent_set(type='OBJECT'):
        # Simulate parenting - find selected mesh and active armature
        active = context.view_layer.objects.active
        if not active:
            return

        for obj in data.objects:
            if obj._selected and obj != active:
                obj.parent = active
                if active not in obj.children:
                    active.children.append(obj)

                # If parenting mesh to armature with weights, add modifier
                if active.type == 'ARMATURE' and obj.type == 'MESH' and type != 'OBJECT':
                    mod = MockModifier("Armature", "ARMATURE")
                    obj.modifiers.append(mod)

                    # Create vertex groups for each bone (simulating auto weights)
                    if type == 'ARMATURE_AUTO' and isinstance(active.data, MockArmatureData):
                        for bone in active.data.bones:
                            if bone.use_deform and not obj.vertex_groups.get(bone.name):
                                obj.vertex_groups.new(name=bone.name)


class _Ops:
    object = _OpsObject()


# ── bpy.app ─────────────────────────────────────────────────────────────────

class _Timers:
    @staticmethod
    def register(func, *args, **kwargs):
        pass


class _App:
    timers = _Timers()


# ── bpy.props (stubs) ──────────────────────────────────────────────────────

class _Props:
    @staticmethod
    def IntProperty(**kwargs):
        return None

    @staticmethod
    def BoolProperty(**kwargs):
        return None

    @staticmethod
    def StringProperty(**kwargs):
        return None

    @staticmethod
    def FloatProperty(**kwargs):
        return None

    @staticmethod
    def EnumProperty(**kwargs):
        return None


# ── bpy.types (stub base classes for addon registration) ───────────────────

class _Types:
    """Mock bpy.types — provides base classes so addon.py class definitions load."""

    class AddonPreferences:
        pass

    class Panel:
        pass

    class Operator:
        bl_idname = ""
        bl_label = ""

        def execute(self, context):
            return {'FINISHED'}

        def report(self, level, message):
            pass

    class Scene:
        pass

    class PropertyGroup:
        pass

    # Allow arbitrary attribute get/set (addon stores blendermcp_server etc.)
    def __getattr__(self, name):
        return None

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)


# ── Module-level singletons ─────────────────────────────────────────────────

data = _Data()
context = _Context()
ops = _Ops()
app = _App()
props = _Props()
types = _Types()


# ── Reset function ──────────────────────────────────────────────────────────

def reset():
    """Reset all mock state for a clean test."""
    global _current_mode
    _current_mode = 'OBJECT'
    data.reset()
    context.scene = _Scene()
    context.view_layer = _ViewLayer()
    context.collection = _Collection()
    context.screen = _MockScreen()


# ── Helper to create test meshes ────────────────────────────────────────────

def create_test_mesh(name, vertices, edges=None, matrix_world=None):
    """
    Create a mock mesh object and register it in bpy.data.

    Args:
        name: object name
        vertices: list of (x, y, z) tuples
        edges: list of (v1_idx, v2_idx) tuples
        matrix_world: optional Matrix (defaults to identity)

    Returns:
        MockObject
    """
    mesh_data = MockMeshData(name)
    mesh_data.vertices = [MockVertex(i, co) for i, co in enumerate(vertices)]
    mesh_data.edges = [MockEdge(e[0], e[1]) for e in (edges or [])]

    obj = MockObject(name, mesh_data)
    if matrix_world:
        obj.matrix_world = matrix_world

    data.objects._items[name] = obj
    data.objects._order.append(obj)
    return obj
