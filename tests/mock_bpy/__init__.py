"""Install mock bpy and mathutils into sys.modules before addon.py is imported."""

import sys
from . import bpy_module
from . import mathutils_module

# A thin wrapper so `from bpy.props import IntProperty` works
_props_module = type(sys)('bpy.props')
_props_module.IntProperty = bpy_module.props.IntProperty
_props_module.BoolProperty = bpy_module.props.BoolProperty
_props_module.StringProperty = bpy_module.props.StringProperty
_props_module.FloatProperty = bpy_module.props.FloatProperty
_props_module.EnumProperty = bpy_module.props.EnumProperty


def install():
    """Inject mock modules into sys.modules."""
    sys.modules['bpy'] = bpy_module
    sys.modules['bpy.props'] = _props_module
    sys.modules['bpy.app'] = bpy_module.app
    sys.modules['mathutils'] = mathutils_module
