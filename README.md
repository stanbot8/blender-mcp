# BlenderMCP Fork — Rigging, Mesh Analysis & Safety Tools

Fork of [ahujasid/blender-mcp](https://github.com/ahujasid/blender-mcp) with added rigging intelligence, mesh analysis, file inspection, and safety features.

> For installation, setup, and base features, see the [original README](https://github.com/ahujasid/blender-mcp#readme).

---

## What This Fork Adds

### Rigging & Bone Tools
- **Mesh-guided bone placement** — `get_mesh_analysis()` and `get_mesh_landmarks()` detect extremities, spine line, joint candidates (narrowing points), and width maxima so bones are placed at anatomically meaningful positions instead of hardcoded coordinates
- **Humanoid rig generator** — `create_humanoid_rig(height)` creates a standard skeleton (Hips, Spine, Chest, Neck, Head, Arms, Legs with .L/.R naming) scaled to your mesh
- **Full bone toolset** — `create_armature`, `add_bone`, `add_bone_chain`, `edit_bone`, `remove_bone`, `get_armature_info`
- **Skinning** — `parent_mesh_to_armature` with automatic weight painting, `manage_vertex_groups` for manual control
- **Constraints** — `setup_ik`, `add_bone_constraint`, `remove_bone_constraint`, `set_bone_pose`, `reset_pose`
- **Rigging strategy prompt** — Teaches Claude bone positioning rules (elbow/knee bends for IK, spine centering, bone roll, weight painting troubleshooting)

### Blender → Unreal Engine
Built into the rigging prompt so Claude knows the differences:
- Coordinate systems (right-hand Y-forward vs left-hand X-forward)
- Scale (meters vs centimeters, 100x factor)
- Bone naming mapping (`.L/.R` → `_l/_r`, full UE5 mannequin skeleton)
- FBX export settings (disable leaf bones, only deform bones, smoothing, axis)
- Common problems and fixes

### Edge Loop Tools
- `get_edge_loops(mesh_name)` — detect all edge loops, sorted by size
- `select_edge_loop(mesh_name, edge_index=N)` — select a loop by edge index or nearest position
- `select_edge_ring(mesh_name, edge_index=N)` — select perpendicular rings (cross-sections)

### File Inspection (non-destructive)
Read external files without importing them into your scene:
- `inspect_blend_file(filepath)` — lists all data blocks (objects, meshes, armatures, materials)
- `inspect_blend_object(filepath, object_name)` — reads full details via temp link (bone hierarchy, vertex counts, materials), then removes
- `inspect_external_file(filepath)` — handles `.fbx`/`.obj`/`.glb`/`.gltf` by temp-importing, reading, then deleting everything

### Safety
- **Auto-backup** — every modifying MCP command backs up your `.blend` to `.mcp_backup` first (one file, overwritten each time — never piles up)
- **Save blocked** — `execute_code` rejects `bpy.ops.wm.save_mainfile` so the MCP can't save over your work
- **Restore** — `restore_blend()` reverts to the last backup
- **Manual backup** — `backup_blend()` to force a backup anytime

### Mesh Analysis
- Bounding box, center of mass, Z-axis cross-sections
- Symmetry detection
- Mesh island detection via union-find (disconnected components like eyes, teeth, accessories)
- Geometric landmarks: extremities, spine line, joint candidates, width maxima, labeled islands

---

## Running Tests

Tests run without Blender installed using a mock `bpy` infrastructure:

```bash
pip install -e ".[test]"
pytest tests/ -v
```

97 tests covering rigging, mesh analysis, constraints, vertex groups, landmarks, and MCP tool forwarding.

---

## Install Addon to Blender

```bash
bash install.sh
```

Copies `addon.py` to Blender 5.0, keeping one `.bak` rollback of the previous version.
