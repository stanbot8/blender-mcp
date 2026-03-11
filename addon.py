# Code created by Siddharth Ahuja: www.github.com/ahujasid © 2025

import re
import bpy
import mathutils
import json
import threading
import socket
import time
import requests
import tempfile
import traceback
import os
import shutil
import zipfile
from bpy.props import IntProperty, BoolProperty
import io
from datetime import datetime
import hashlib, hmac, base64
import os.path as osp
from contextlib import redirect_stdout, suppress

bl_info = {
    "name": "Blender MCP",
    "author": "BlenderMCP",
    "version": (1, 2),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > BlenderMCP",
    "description": "Connect Blender to Claude via MCP",
    "category": "Interface",
}

RODIN_FREE_TRIAL_KEY = "k9TcfFoEhNd9cCPP2guHAHHHkctZHIRhZDywZ1euGUXwihbYLpOjQhofby80NJez"

# Add User-Agent as required by Poly Haven API
REQ_HEADERS = requests.utils.default_headers()
REQ_HEADERS.update({"User-Agent": "blender-mcp"})

class BlenderMCPServer:
    def __init__(self, host='localhost', port=9876):
        self.host = host
        self.port = port
        self.running = False
        self.socket = None
        self.server_thread = None

    def start(self):
        if self.running:
            print("Server is already running")
            return

        self.running = True

        try:
            # Create socket
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind((self.host, self.port))
            self.socket.listen(1)

            # Start server thread
            self.server_thread = threading.Thread(target=self._server_loop)
            self.server_thread.daemon = True
            self.server_thread.start()

            print(f"BlenderMCP server started on {self.host}:{self.port}")
        except Exception as e:
            print(f"Failed to start server: {str(e)}")
            self.stop()

    def stop(self):
        self.running = False

        # Close socket
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None

        # Wait for thread to finish
        if self.server_thread:
            try:
                if self.server_thread.is_alive():
                    self.server_thread.join(timeout=1.0)
            except:
                pass
            self.server_thread = None

        print("BlenderMCP server stopped")

    def _server_loop(self):
        """Main server loop in a separate thread"""
        print("Server thread started")
        self.socket.settimeout(1.0)  # Timeout to allow for stopping

        while self.running:
            try:
                # Accept new connection
                try:
                    client, address = self.socket.accept()
                    print(f"Connected to client: {address}")

                    # Handle client in a separate thread
                    client_thread = threading.Thread(
                        target=self._handle_client,
                        args=(client,)
                    )
                    client_thread.daemon = True
                    client_thread.start()
                except socket.timeout:
                    # Just check running condition
                    continue
                except Exception as e:
                    print(f"Error accepting connection: {str(e)}")
                    time.sleep(0.5)
            except Exception as e:
                print(f"Error in server loop: {str(e)}")
                if not self.running:
                    break
                time.sleep(0.5)

        print("Server thread stopped")

    def _handle_client(self, client):
        """Handle connected client"""
        print("Client handler started")
        client.settimeout(None)  # No timeout
        buffer = b''

        try:
            while self.running:
                # Receive data
                try:
                    data = client.recv(8192)
                    if not data:
                        print("Client disconnected")
                        break

                    buffer += data
                    try:
                        # Try to parse command
                        command = json.loads(buffer.decode('utf-8'))
                        buffer = b''

                        # Execute command in Blender's main thread
                        def execute_wrapper():
                            try:
                                response = self.execute_command(command)
                                response_json = json.dumps(response)
                                try:
                                    client.sendall(response_json.encode('utf-8'))
                                except:
                                    print("Failed to send response - client disconnected")
                            except Exception as e:
                                print(f"Error executing command: {str(e)}")
                                traceback.print_exc()
                                try:
                                    error_response = {
                                        "status": "error",
                                        "message": str(e)
                                    }
                                    client.sendall(json.dumps(error_response).encode('utf-8'))
                                except:
                                    pass
                            return None

                        # Schedule execution in main thread
                        bpy.app.timers.register(execute_wrapper, first_interval=0.0)
                    except json.JSONDecodeError:
                        # Incomplete data, wait for more
                        pass
                except Exception as e:
                    print(f"Error receiving data: {str(e)}")
                    break
        except Exception as e:
            print(f"Error in client handler: {str(e)}")
        finally:
            try:
                client.close()
            except:
                pass
            print("Client handler stopped")

    def execute_command(self, command):
        """Execute a command in the main Blender thread"""
        try:
            return self._execute_command_internal(command)

        except Exception as e:
            print(f"Error executing command: {str(e)}")
            traceback.print_exc()
            return {"status": "error", "message": str(e)}

    # Commands that only read data and never modify the scene
    _READONLY_COMMANDS = frozenset({
        "get_scene_info", "get_object_info", "get_viewport_screenshot",
        "get_telemetry_consent", "get_polyhaven_status", "get_hyper3d_status",
        "get_sketchfab_status", "get_hunyuan3d_status",
        "get_mesh_analysis", "get_mesh_landmarks", "get_edge_loops",
        "get_armature_info", "get_polyhaven_categories",
        "search_polyhaven_assets", "search_sketchfab_models",
        "backup_blend",
    })

    def _auto_backup(self):
        """Save a single rolling backup of the current .blend file.
        Overwrites the previous backup each time — never piles up."""
        filepath = bpy.data.filepath
        if not filepath:
            return  # File hasn't been saved yet, nothing to back up
        backup_path = filepath + ".mcp_backup"
        try:
            import shutil
            shutil.copy2(filepath, backup_path)
            print(f"MCP auto-backup saved: {backup_path}")
        except Exception as e:
            print(f"MCP auto-backup failed: {e}")

    def _execute_command_internal(self, command):
        """Internal command execution with proper context"""
        cmd_type = command.get("type")
        params = command.get("params", {})

        # Auto-backup before any command that modifies the scene
        if cmd_type not in self._READONLY_COMMANDS:
            self._auto_backup()

        # Add a handler for checking PolyHaven status
        if cmd_type == "get_polyhaven_status":
            return {"status": "success", "result": self.get_polyhaven_status()}

        # Base handlers that are always available
        handlers = {
            "get_scene_info": self.get_scene_info,
            "get_object_info": self.get_object_info,
            "get_viewport_screenshot": self.get_viewport_screenshot,
            "execute_code": self.execute_code,
            "get_telemetry_consent": self.get_telemetry_consent,
            "get_polyhaven_status": self.get_polyhaven_status,
            "get_hyper3d_status": self.get_hyper3d_status,
            "get_sketchfab_status": self.get_sketchfab_status,
            "get_hunyuan3d_status": self.get_hunyuan3d_status,
            # Mesh analysis & rigging handlers
            "get_mesh_analysis": self.get_mesh_analysis,
            "get_mesh_landmarks": self.get_mesh_landmarks,
            "backup_blend": self.backup_blend,
            "restore_blend": self.restore_blend,
            "get_edge_loops": self.get_edge_loops,
            "select_edge_loop": self.select_edge_loop,
            "select_edge_ring": self.select_edge_ring,
            "create_armature": self.create_armature,
            "add_bone": self.add_bone,
            "add_bone_chain": self.add_bone_chain,
            "edit_bone": self.edit_bone,
            "remove_bone": self.remove_bone,
            "get_armature_info": self.get_armature_info,
            "parent_mesh_to_armature": self.parent_mesh_to_armature,
            "add_bone_constraint": self.add_bone_constraint,
            "remove_bone_constraint": self.remove_bone_constraint,
            "set_bone_pose": self.set_bone_pose,
            "reset_pose": self.reset_pose,
            "manage_vertex_groups": self.manage_vertex_groups,
            "setup_ik": self.setup_ik,
            "create_humanoid_rig": self.create_humanoid_rig,
        }

        # Add Polyhaven handlers only if enabled
        if bpy.context.scene.blendermcp_use_polyhaven:
            polyhaven_handlers = {
                "get_polyhaven_categories": self.get_polyhaven_categories,
                "search_polyhaven_assets": self.search_polyhaven_assets,
                "download_polyhaven_asset": self.download_polyhaven_asset,
                "set_texture": self.set_texture,
            }
            handlers.update(polyhaven_handlers)

        # Add Hyper3d handlers only if enabled
        if bpy.context.scene.blendermcp_use_hyper3d:
            polyhaven_handlers = {
                "create_rodin_job": self.create_rodin_job,
                "poll_rodin_job_status": self.poll_rodin_job_status,
                "import_generated_asset": self.import_generated_asset,
            }
            handlers.update(polyhaven_handlers)

        # Add Sketchfab handlers only if enabled
        if bpy.context.scene.blendermcp_use_sketchfab:
            sketchfab_handlers = {
                "search_sketchfab_models": self.search_sketchfab_models,
                "get_sketchfab_model_preview": self.get_sketchfab_model_preview,
                "download_sketchfab_model": self.download_sketchfab_model,
            }
            handlers.update(sketchfab_handlers)
        
        # Add Hunyuan3d handlers only if enabled
        if bpy.context.scene.blendermcp_use_hunyuan3d:
            hunyuan_handlers = {
                "create_hunyuan_job": self.create_hunyuan_job,
                "poll_hunyuan_job_status": self.poll_hunyuan_job_status,
                "import_generated_asset_hunyuan": self.import_generated_asset_hunyuan
            }
            handlers.update(hunyuan_handlers)

        handler = handlers.get(cmd_type)
        if handler:
            try:
                print(f"Executing handler for {cmd_type}")
                result = handler(**params)
                print(f"Handler execution complete")
                return {"status": "success", "result": result}
            except Exception as e:
                print(f"Error in handler: {str(e)}")
                traceback.print_exc()
                return {"status": "error", "message": str(e)}
        else:
            return {"status": "error", "message": f"Unknown command type: {cmd_type}"}



    def get_scene_info(self):
        """Get information about the current Blender scene"""
        try:
            print("Getting scene info...")
            # Simplify the scene info to reduce data size
            scene_info = {
                "name": bpy.context.scene.name,
                "object_count": len(bpy.context.scene.objects),
                "objects": [],
                "materials_count": len(bpy.data.materials),
            }

            # Collect minimal object information (limit to first 10 objects)
            for i, obj in enumerate(bpy.context.scene.objects):
                if i >= 10:  # Reduced from 20 to 10
                    break

                obj_info = {
                    "name": obj.name,
                    "type": obj.type,
                    # Only include basic location data
                    "location": [round(float(obj.location.x), 2),
                                round(float(obj.location.y), 2),
                                round(float(obj.location.z), 2)],
                }
                scene_info["objects"].append(obj_info)

            print(f"Scene info collected: {len(scene_info['objects'])} objects")
            return scene_info
        except Exception as e:
            print(f"Error in get_scene_info: {str(e)}")
            traceback.print_exc()
            return {"error": str(e)}

    @staticmethod
    def _get_aabb(obj):
        """ Returns the world-space axis-aligned bounding box (AABB) of an object. """
        if obj.type != 'MESH':
            raise TypeError("Object must be a mesh")

        # Get the bounding box corners in local space
        local_bbox_corners = [mathutils.Vector(corner) for corner in obj.bound_box]

        # Convert to world coordinates
        world_bbox_corners = [obj.matrix_world @ corner for corner in local_bbox_corners]

        # Compute axis-aligned min/max coordinates
        min_corner = mathutils.Vector(map(min, zip(*world_bbox_corners)))
        max_corner = mathutils.Vector(map(max, zip(*world_bbox_corners)))

        return [
            [*min_corner], [*max_corner]
        ]



    def get_object_info(self, name):
        """Get detailed information about a specific object"""
        obj = bpy.data.objects.get(name)
        if not obj:
            raise ValueError(f"Object not found: {name}")

        # Basic object info
        obj_info = {
            "name": obj.name,
            "type": obj.type,
            "location": [obj.location.x, obj.location.y, obj.location.z],
            "rotation": [obj.rotation_euler.x, obj.rotation_euler.y, obj.rotation_euler.z],
            "scale": [obj.scale.x, obj.scale.y, obj.scale.z],
            "visible": obj.visible_get(),
            "materials": [],
        }

        if obj.type == "MESH":
            bounding_box = self._get_aabb(obj)
            obj_info["world_bounding_box"] = bounding_box

        # Add material slots
        for slot in obj.material_slots:
            if slot.material:
                obj_info["materials"].append(slot.material.name)

        # Add mesh data if applicable
        if obj.type == 'MESH' and obj.data:
            mesh = obj.data
            obj_info["mesh"] = {
                "vertices": len(mesh.vertices),
                "edges": len(mesh.edges),
                "polygons": len(mesh.polygons),
            }

        # Add armature data if applicable
        if obj.type == 'ARMATURE' and obj.data:
            armature = obj.data
            bone_list = []
            for bone in armature.bones:
                bone_list.append({
                    "name": bone.name,
                    "head": [round(bone.head_local[i], 4) for i in range(3)],
                    "tail": [round(bone.tail_local[i], 4) for i in range(3)],
                    "parent": bone.parent.name if bone.parent else None,
                    "children": [c.name for c in bone.children],
                    "connected": bone.use_connect,
                })
            obj_info["armature"] = {
                "bone_count": len(armature.bones),
                "bones": bone_list,
            }

        return obj_info

    def get_viewport_screenshot(self, max_size=800, filepath=None, format="png"):
        """
        Capture a screenshot of the current 3D viewport and save it to the specified path.

        Parameters:
        - max_size: Maximum size in pixels for the largest dimension of the image
        - filepath: Path where to save the screenshot file
        - format: Image format (png, jpg, etc.)

        Returns success/error status
        """
        try:
            if not filepath:
                return {"error": "No filepath provided"}

            # Find the active 3D viewport
            area = None
            for a in bpy.context.screen.areas:
                if a.type == 'VIEW_3D':
                    area = a
                    break

            if not area:
                return {"error": "No 3D viewport found"}

            # Take screenshot with proper context override
            with bpy.context.temp_override(area=area):
                bpy.ops.screen.screenshot_area(filepath=filepath)

            # Load and resize if needed
            img = bpy.data.images.load(filepath)
            width, height = img.size

            if max(width, height) > max_size:
                scale = max_size / max(width, height)
                new_width = int(width * scale)
                new_height = int(height * scale)
                img.scale(new_width, new_height)

                # Set format and save
                img.file_format = format.upper()
                img.save()
                width, height = new_width, new_height

            # Cleanup Blender image data
            bpy.data.images.remove(img)

            return {
                "success": True,
                "width": width,
                "height": height,
                "filepath": filepath
            }

        except Exception as e:
            return {"error": str(e)}

    def backup_blend(self):
        """Manually trigger a backup of the current .blend file."""
        filepath = bpy.data.filepath
        if not filepath:
            raise Exception("File has not been saved yet — nothing to back up. Save the .blend first.")
        backup_path = filepath + ".mcp_backup"
        import shutil
        shutil.copy2(filepath, backup_path)
        return {"backed_up": True, "backup_path": backup_path, "source": filepath}

    def restore_blend(self):
        """Restore the .blend file from the last MCP backup."""
        filepath = bpy.data.filepath
        if not filepath:
            raise Exception("No file path — cannot restore.")
        backup_path = filepath + ".mcp_backup"
        import os
        if not os.path.exists(backup_path):
            raise Exception(f"No backup found at {backup_path}")
        bpy.ops.wm.open_mainfile(filepath=backup_path)
        return {"restored": True, "from": backup_path}

    def execute_code(self, code):
        """Execute arbitrary Blender Python code"""
        # This is powerful but potentially dangerous - use with caution
        try:
            # Block save operations to prevent accidental overwrites
            import re as _re
            save_patterns = [
                r'bpy\.ops\.wm\.save_mainfile',
                r'bpy\.ops\.wm\.save_as_mainfile',
                r'\.save_mainfile\(',
                r'\.save_as_mainfile\(',
            ]
            for pat in save_patterns:
                if _re.search(pat, code):
                    return {
                        "executed": False,
                        "error": "Saving .blend files via MCP is blocked for safety. "
                                 "Save manually in Blender (Ctrl+S) or use File > Save."
                    }

            # Create a local namespace for execution
            namespace = {"bpy": bpy}

            # Capture stdout during execution, and return it as result
            capture_buffer = io.StringIO()
            with redirect_stdout(capture_buffer):
                exec(code, namespace)

            captured_output = capture_buffer.getvalue()
            return {"executed": True, "result": captured_output}
        except Exception as e:
            raise Exception(f"Code execution error: {str(e)}")

    def get_mesh_analysis(self, mesh_name, num_slices=5):
        """Analyze mesh geometry to help determine bone placement.
        Returns bounding box, center of mass, cross-section info, and mesh islands."""
        try:
            obj = bpy.data.objects.get(mesh_name)
            if not obj or obj.type != 'MESH':
                raise ValueError(f"Mesh not found: {mesh_name}")

            mesh = obj.data
            world_matrix = obj.matrix_world

            # Get all vertex positions in world space
            verts_world = [world_matrix @ v.co for v in mesh.vertices]
            if not verts_world:
                raise ValueError("Mesh has no vertices")

            xs = [v.x for v in verts_world]
            ys = [v.y for v in verts_world]
            zs = [v.z for v in verts_world]

            bbox_min = [min(xs), min(ys), min(zs)]
            bbox_max = [max(xs), max(ys), max(zs)]
            dimensions = [bbox_max[i] - bbox_min[i] for i in range(3)]

            # Center of mass (average vertex position)
            n = len(verts_world)
            center = [sum(xs) / n, sum(ys) / n, sum(zs) / n]

            # Cross-section analysis along Z axis (height slices)
            # This helps determine where to place spine/limb bones
            z_slices = []
            z_range = bbox_max[2] - bbox_min[2]
            if z_range > 0 and num_slices > 0:
                for i in range(num_slices):
                    t = (i + 0.5) / num_slices
                    z_level = bbox_min[2] + t * z_range
                    z_tolerance = z_range / num_slices / 2

                    # Find vertices near this Z level
                    slice_verts = [v for v in verts_world
                                   if abs(v.z - z_level) < z_tolerance]
                    if slice_verts:
                        sx = [v.x for v in slice_verts]
                        sy = [v.y for v in slice_verts]
                        slice_center = [sum(sx) / len(sx), sum(sy) / len(sx), z_level]
                        slice_width = max(sx) - min(sx)
                        slice_depth = max(sy) - min(sy)
                        z_slices.append({
                            "z": round(z_level, 4),
                            "center_x": round(slice_center[0], 4),
                            "center_y": round(slice_center[1], 4),
                            "width": round(slice_width, 4),
                            "depth": round(slice_depth, 4),
                            "vertex_count": len(slice_verts),
                        })

            # Detect likely symmetry
            x_center_offset = abs(center[0] - (bbox_min[0] + bbox_max[0]) / 2)
            is_likely_symmetric = x_center_offset < dimensions[0] * 0.05 if dimensions[0] > 0 else True

            # ---- Mesh island detection via union-find ----
            vert_count = len(mesh.vertices)
            parent = list(range(vert_count))

            def find(x):
                while parent[x] != x:
                    parent[x] = parent[parent[x]]
                    x = parent[x]
                return x

            def union(a, b):
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[ra] = rb

            for edge in mesh.edges:
                union(edge.vertices[0], edge.vertices[1])

            # Group vertices by their root
            from collections import defaultdict
            island_verts = defaultdict(list)
            for vi in range(vert_count):
                island_verts[find(vi)].append(vi)

            # Build island info sorted by vertex count (largest first)
            islands = []
            for root, vert_indices in sorted(island_verts.items(),
                                              key=lambda item: len(item[1]),
                                              reverse=True):
                island_ws = [verts_world[vi] for vi in vert_indices]
                ixs = [v.x for v in island_ws]
                iys = [v.y for v in island_ws]
                izs = [v.z for v in island_ws]
                ic = [sum(ixs) / len(ixs), sum(iys) / len(iys), sum(izs) / len(izs)]
                i_bbox_min = [min(ixs), min(iys), min(izs)]
                i_bbox_max = [max(ixs), max(iys), max(izs)]
                i_dims = [i_bbox_max[j] - i_bbox_min[j] for j in range(3)]

                islands.append({
                    "vertex_count": len(vert_indices),
                    "center": [round(v, 4) for v in ic],
                    "bbox_min": [round(v, 4) for v in i_bbox_min],
                    "bbox_max": [round(v, 4) for v in i_bbox_max],
                    "dimensions": [round(v, 4) for v in i_dims],
                })

            return {
                "mesh_name": obj.name,
                "vertex_count": len(mesh.vertices),
                "bbox_min": [round(v, 4) for v in bbox_min],
                "bbox_max": [round(v, 4) for v in bbox_max],
                "dimensions": [round(v, 4) for v in dimensions],
                "center": [round(v, 4) for v in center],
                "z_slices": z_slices,
                "likely_symmetric": is_likely_symmetric,
                "island_count": len(islands),
                "islands": islands[:30],  # Limit output for large meshes
            }
        except Exception as e:
            raise Exception(f"Error analyzing mesh: {str(e)}")

    def get_mesh_landmarks(self, mesh_name, num_height_samples=10):
        """Detect key geometric landmarks on a mesh for bone placement.
        Returns named pivot points: extremities, spine line, joint candidates,
        and labeled island centers."""
        try:
            obj = bpy.data.objects.get(mesh_name)
            if not obj or obj.type != 'MESH':
                raise ValueError(f"Mesh not found: {mesh_name}")

            mesh = obj.data
            world_matrix = obj.matrix_world
            verts_world = [world_matrix @ v.co for v in mesh.vertices]
            if not verts_world:
                raise ValueError("Mesh has no vertices")

            xs = [v.x for v in verts_world]
            ys = [v.y for v in verts_world]
            zs = [v.z for v in verts_world]

            def r3(v):
                return [round(v[0], 4), round(v[1], 4), round(v[2], 4)]

            # --- Extremities ---
            extremities = {
                "top":    r3(verts_world[zs.index(max(zs))]),
                "bottom": r3(verts_world[zs.index(min(zs))]),
                "left":   r3(verts_world[xs.index(min(xs))]),  # -X
                "right":  r3(verts_world[xs.index(max(xs))]),   # +X
                "front":  r3(verts_world[ys.index(min(ys))]),  # -Y
                "back":   r3(verts_world[ys.index(max(ys))]),   # +Y
            }

            bbox_min = [min(xs), min(ys), min(zs)]
            bbox_max = [max(xs), max(ys), max(zs)]
            height = bbox_max[2] - bbox_min[2]

            # --- Spine line: center of mass at each height level ---
            spine_points = []
            if height > 0 and num_height_samples > 0:
                tolerance = height / num_height_samples / 2
                for i in range(num_height_samples):
                    t = (i + 0.5) / num_height_samples
                    z_level = bbox_min[2] + t * height
                    nearby = [v for v in verts_world if abs(v.z - z_level) < tolerance]
                    if nearby:
                        cx = sum(v.x for v in nearby) / len(nearby)
                        cy = sum(v.y for v in nearby) / len(nearby)
                        width = max(v.x for v in nearby) - min(v.x for v in nearby)
                        depth = max(v.y for v in nearby) - min(v.y for v in nearby)
                        spine_points.append({
                            "height_pct": round(t * 100, 1),
                            "position": r3((cx, cy, z_level)),
                            "width": round(width, 4),
                            "depth": round(depth, 4),
                        })

            # --- Joint candidates: local minima in cross-section width ---
            # These are natural narrowing points (neck, waist, wrists, ankles)
            joint_candidates = []
            if len(spine_points) >= 3:
                for i in range(1, len(spine_points) - 1):
                    prev_w = spine_points[i-1]["width"]
                    curr_w = spine_points[i]["width"]
                    next_w = spine_points[i+1]["width"]
                    if curr_w < prev_w and curr_w < next_w:
                        joint_candidates.append({
                            "position": spine_points[i]["position"],
                            "height_pct": spine_points[i]["height_pct"],
                            "width": curr_w,
                            "type": "narrowing",
                        })

            # --- Width maxima: shoulders, hips ---
            width_maxima = []
            if len(spine_points) >= 3:
                for i in range(1, len(spine_points) - 1):
                    prev_w = spine_points[i-1]["width"]
                    curr_w = spine_points[i]["width"]
                    next_w = spine_points[i+1]["width"]
                    if curr_w > prev_w and curr_w > next_w:
                        width_maxima.append({
                            "position": spine_points[i]["position"],
                            "height_pct": spine_points[i]["height_pct"],
                            "width": curr_w,
                            "type": "widening",
                        })

            # --- Island centers with spatial labels ---
            from collections import defaultdict
            vert_count = len(mesh.vertices)
            parent = list(range(vert_count))

            def find(x):
                while parent[x] != x:
                    parent[x] = parent[parent[x]]
                    x = parent[x]
                return x

            def union(a, b):
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[ra] = rb

            for edge in mesh.edges:
                union(edge.vertices[0], edge.vertices[1])

            island_verts = defaultdict(list)
            for vi in range(vert_count):
                island_verts[find(vi)].append(vi)

            # Build labeled islands
            center_x = (bbox_min[0] + bbox_max[0]) / 2
            center_z = (bbox_min[2] + bbox_max[2]) / 2
            labeled_islands = []
            for root, vert_indices in sorted(island_verts.items(),
                                              key=lambda item: len(item[1]),
                                              reverse=True):
                island_ws = [verts_world[vi] for vi in vert_indices]
                ic = [sum(v.x for v in island_ws) / len(island_ws),
                      sum(v.y for v in island_ws) / len(island_ws),
                      sum(v.z for v in island_ws) / len(island_ws)]

                # Label based on position relative to mesh center
                labels = []
                if len(vert_indices) == max(len(v) for v in island_verts.values()):
                    labels.append("main_body")
                else:
                    # Height-based
                    rel_z = (ic[2] - bbox_min[2]) / height if height > 0 else 0.5
                    if rel_z > 0.85:
                        labels.append("top_region")
                    elif rel_z < 0.15:
                        labels.append("bottom_region")

                    # Side-based
                    x_offset = ic[0] - center_x
                    width = bbox_max[0] - bbox_min[0]
                    if width > 0:
                        if x_offset > width * 0.15:
                            labels.append("right_side")
                        elif x_offset < -width * 0.15:
                            labels.append("left_side")
                        else:
                            labels.append("center")

                    if not labels:
                        labels.append("detail")

                labeled_islands.append({
                    "center": r3(ic),
                    "vertex_count": len(vert_indices),
                    "labels": labels,
                })

            return {
                "mesh_name": obj.name,
                "height": round(height, 4),
                "extremities": extremities,
                "spine_line": spine_points,
                "joint_candidates": joint_candidates,
                "width_maxima": width_maxima,
                "labeled_islands": labeled_islands[:20],
            }
        except Exception as e:
            raise Exception(f"Error getting mesh landmarks: {str(e)}")

    # ==================== Edge Loop Tools ====================

    def _walk_edge_loop(self, bm, start_edge):
        """Walk an edge loop from a starting edge using bmesh topology.
        Returns list of edge indices forming the loop."""
        import bmesh as bm_mod

        def bm_edge_other_loop(edge, loop):
            l_other = loop if loop.edge == edge else loop.link_loop_prev
            l_other = l_other.link_loop_radial_next
            if l_other.vert == loop.vert:
                return l_other.link_loop_prev
            elif l_other.link_loop_next.vert == loop.vert:
                return l_other.link_loop_next
            return None

        def bm_vert_step_fan(loop, e_step):
            if loop.edge == e_step:
                e_next = loop.link_loop_prev.edge
            elif loop.link_loop_prev.edge == e_step:
                e_next = loop.edge
            else:
                return None
            if e_next.is_manifold:
                return bm_edge_other_loop(e_next, loop)
            return None

        if not start_edge.link_loops:
            return [start_edge.index]

        result_indices = [start_edge.index]
        visited = {start_edge.index}

        # Walk in both directions from start edge
        for direction in range(2):
            e_step = start_edge
            loop = e_step.link_loops[0]
            if direction == 1:
                loop = loop.link_loop_next

            pcv = loop.vert
            pov = loop.edge.other_vert(loop.vert)

            for _ in range(10000):
                new_loop = bm_vert_step_fan(loop, e_step)
                if new_loop is None:
                    break

                e_step = new_loop.edge
                if e_step.index in visited:
                    break
                visited.add(e_step.index)
                if direction == 0:
                    result_indices.append(e_step.index)
                else:
                    result_indices.insert(0, e_step.index)

                cur_v = new_loop.vert
                oth_v = new_loop.edge.other_vert(new_loop.vert)
                rad_v = new_loop.link_loop_radial_next.vert

                if cur_v == rad_v and oth_v != pcv:
                    loop = new_loop.link_loop_next
                    pcv, pov = oth_v, cur_v
                elif oth_v == pcv:
                    loop = new_loop
                    pcv, pov = cur_v, oth_v
                elif cur_v == pcv:
                    loop = new_loop.link_loop_radial_next
                    pcv, pov = oth_v, cur_v
                else:
                    break

        return result_indices

    def get_edge_loops(self, mesh_name, max_loops=50):
        """Detect edge loops in a mesh. Returns loops as lists of vertex positions.
        Useful for understanding mesh topology and placing bones along loops."""
        import bmesh
        try:
            obj = bpy.data.objects.get(mesh_name)
            if not obj or obj.type != 'MESH':
                raise ValueError(f"Mesh not found: {mesh_name}")

            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode='EDIT')
            bm = bmesh.from_edit_mesh(obj.data)
            bm.edges.ensure_lookup_table()
            bm.verts.ensure_lookup_table()

            world = obj.matrix_world
            visited_edges = set()
            loops = []

            for edge in bm.edges:
                if edge.index in visited_edges:
                    continue
                # Only start from manifold edges (shared by exactly 2 faces)
                if not edge.is_manifold:
                    continue

                loop_indices = self._walk_edge_loop(bm, edge)
                if len(loop_indices) < 3:
                    continue

                visited_edges.update(loop_indices)

                # Get vertex positions for this loop
                loop_verts = []
                for ei in loop_indices:
                    e = bm.edges[ei]
                    for v in e.verts:
                        if not loop_verts or v.index != loop_verts[-1]["index"]:
                            co = world @ v.co
                            loop_verts.append({
                                "index": v.index,
                                "position": [round(co.x, 4), round(co.y, 4), round(co.z, 4)]
                            })

                # Compute loop center and orientation
                positions = [v["position"] for v in loop_verts]
                n = len(positions)
                center = [
                    round(sum(p[0] for p in positions) / n, 4),
                    round(sum(p[1] for p in positions) / n, 4),
                    round(sum(p[2] for p in positions) / n, 4),
                ]

                loops.append({
                    "edge_count": len(loop_indices),
                    "vertex_count": len(loop_verts),
                    "center": center,
                    "edge_indices": loop_indices,
                    "vertices": loop_verts[:100],  # Limit for large loops
                })

                if len(loops) >= max_loops:
                    break

            bpy.ops.object.mode_set(mode='OBJECT')

            # Sort by edge count (largest loops first — usually most useful)
            loops.sort(key=lambda l: l["edge_count"], reverse=True)

            return {
                "mesh_name": obj.name,
                "loop_count": len(loops),
                "loops": loops,
            }
        except Exception as e:
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except:
                pass
            raise Exception(f"Error getting edge loops: {str(e)}")

    def select_edge_loop(self, mesh_name, edge_index=None, position=None, extend=False):
        """Select an edge loop in the viewport. Specify by edge index or nearest position.
        Returns the selected loop's vertex positions."""
        import bmesh
        try:
            obj = bpy.data.objects.get(mesh_name)
            if not obj or obj.type != 'MESH':
                raise ValueError(f"Mesh not found: {mesh_name}")

            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode='EDIT')
            bm = bmesh.from_edit_mesh(obj.data)
            bm.edges.ensure_lookup_table()
            bm.verts.ensure_lookup_table()

            world = obj.matrix_world
            world_inv = world.inverted()

            # Find the target edge
            if edge_index is not None:
                if edge_index < 0 or edge_index >= len(bm.edges):
                    bpy.ops.object.mode_set(mode='OBJECT')
                    raise ValueError(f"Edge index {edge_index} out of range (0-{len(bm.edges)-1})")
                target_edge = bm.edges[edge_index]
            elif position is not None:
                # Find nearest edge to world position
                pos = mathutils.Vector(position)
                local_pos = world_inv @ pos
                best_dist = float('inf')
                target_edge = bm.edges[0]
                for edge in bm.edges:
                    mid = (edge.verts[0].co + edge.verts[1].co) / 2
                    dist = (mid - local_pos).length
                    if dist < best_dist:
                        best_dist = dist
                        target_edge = edge
            else:
                bpy.ops.object.mode_set(mode='OBJECT')
                raise ValueError("Provide edge_index or position")

            # Clear selection unless extending
            if not extend:
                for e in bm.edges:
                    e.select = False
                for v in bm.verts:
                    v.select = False

            # Walk and select the loop
            loop_indices = self._walk_edge_loop(bm, target_edge)
            loop_verts = []
            for ei in loop_indices:
                e = bm.edges[ei]
                e.select = True
                for v in e.verts:
                    v.select = True
                    co = world @ v.co
                    loop_verts.append({
                        "index": v.index,
                        "position": [round(co.x, 4), round(co.y, 4), round(co.z, 4)]
                    })

            bm.select_flush_mode()
            bmesh.update_edit_mesh(obj.data)
            # Stay in edit mode so selection is visible

            positions = [v["position"] for v in loop_verts]
            n = len(positions) if positions else 1
            center = [
                round(sum(p[0] for p in positions) / n, 4),
                round(sum(p[1] for p in positions) / n, 4),
                round(sum(p[2] for p in positions) / n, 4),
            ]

            return {
                "mesh_name": obj.name,
                "edge_count": len(loop_indices),
                "vertex_count": len(loop_verts),
                "center": center,
                "edge_indices": loop_indices,
                "vertices": loop_verts[:100],
            }
        except Exception as e:
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except:
                pass
            raise Exception(f"Error selecting edge loop: {str(e)}")

    def select_edge_ring(self, mesh_name, edge_index=None, position=None, extend=False):
        """Select an edge ring (perpendicular to edge loops). Useful for selecting
        cross-sections of limbs/tubes."""
        import bmesh
        try:
            obj = bpy.data.objects.get(mesh_name)
            if not obj or obj.type != 'MESH':
                raise ValueError(f"Mesh not found: {mesh_name}")

            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode='EDIT')
            bm = bmesh.from_edit_mesh(obj.data)
            bm.edges.ensure_lookup_table()
            bm.verts.ensure_lookup_table()

            world = obj.matrix_world
            world_inv = world.inverted()

            # Find the target edge
            if edge_index is not None:
                if edge_index < 0 or edge_index >= len(bm.edges):
                    bpy.ops.object.mode_set(mode='OBJECT')
                    raise ValueError(f"Edge index {edge_index} out of range")
                target_edge = bm.edges[edge_index]
            elif position is not None:
                pos = mathutils.Vector(position)
                local_pos = world_inv @ pos
                best_dist = float('inf')
                target_edge = bm.edges[0]
                for edge in bm.edges:
                    mid = (edge.verts[0].co + edge.verts[1].co) / 2
                    dist = (mid - local_pos).length
                    if dist < best_dist:
                        best_dist = dist
                        target_edge = edge
            else:
                bpy.ops.object.mode_set(mode='OBJECT')
                raise ValueError("Provide edge_index or position")

            if not extend:
                for e in bm.edges:
                    e.select = False
                for v in bm.verts:
                    v.select = False

            # Edge ring: walk across quads via opposite edges
            ring_indices = [target_edge.index]
            visited = {target_edge.index}

            def get_opposite_edge(edge, face):
                """In a quad face, get the edge opposite to the given edge."""
                if len(face.edges) != 4:
                    return None
                for e in face.edges:
                    if e == edge:
                        continue
                    if not any(v in edge.verts for v in e.verts):
                        return e
                return None

            # Walk in both directions
            for start_face_idx in range(2):
                current = target_edge
                faces = list(current.link_faces)
                if start_face_idx >= len(faces):
                    continue
                current_face = faces[start_face_idx]

                for _ in range(10000):
                    opp = get_opposite_edge(current, current_face)
                    if opp is None or opp.index in visited:
                        break
                    visited.add(opp.index)
                    ring_indices.append(opp.index)

                    # Move to next face
                    next_faces = [f for f in opp.link_faces if f != current_face]
                    if not next_faces:
                        break
                    current = opp
                    current_face = next_faces[0]

            # Select and gather data
            loop_verts = []
            for ei in ring_indices:
                e = bm.edges[ei]
                e.select = True
                for v in e.verts:
                    v.select = True
                    co = world @ v.co
                    loop_verts.append({
                        "index": v.index,
                        "position": [round(co.x, 4), round(co.y, 4), round(co.z, 4)]
                    })

            bm.select_flush_mode()
            bmesh.update_edit_mesh(obj.data)

            positions = [v["position"] for v in loop_verts]
            n = len(positions) if positions else 1
            center = [
                round(sum(p[0] for p in positions) / n, 4),
                round(sum(p[1] for p in positions) / n, 4),
                round(sum(p[2] for p in positions) / n, 4),
            ]

            return {
                "mesh_name": obj.name,
                "edge_count": len(ring_indices),
                "vertex_count": len(loop_verts),
                "center": center,
                "edge_indices": ring_indices,
                "vertices": loop_verts[:100],
            }
        except Exception as e:
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except:
                pass
            raise Exception(f"Error selecting edge ring: {str(e)}")

    # ==================== Rigging Tools ====================

    def create_armature(self, name="Armature", location=None):
        """Create a new armature object with a single root bone"""
        try:
            loc = location or [0, 0, 0]
            armature_data = bpy.data.armatures.new(name)
            armature_obj = bpy.data.objects.new(name, armature_data)
            bpy.context.collection.objects.link(armature_obj)
            armature_obj.location = mathutils.Vector(loc)

            # Enter edit mode to add root bone
            bpy.context.view_layer.objects.active = armature_obj
            bpy.ops.object.mode_set(mode='EDIT')

            root_bone = armature_data.edit_bones.new("Root")
            root_bone.head = (0, 0, 0)
            root_bone.tail = (0, 0, 0.5)

            bpy.ops.object.mode_set(mode='OBJECT')

            return {
                "armature_name": armature_obj.name,
                "bone_count": len(armature_data.bones),
                "root_bone": "Root"
            }
        except Exception as e:
            # Make sure we return to object mode on error
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except:
                pass
            raise Exception(f"Error creating armature: {str(e)}")

    def add_bone(self, armature_name, bone_name, head, tail, parent_bone=None, connected=False, roll=0.0):
        """Add a bone to an existing armature"""
        try:
            armature_obj = bpy.data.objects.get(armature_name)
            if not armature_obj or armature_obj.type != 'ARMATURE':
                raise ValueError(f"Armature not found: {armature_name}")

            bpy.context.view_layer.objects.active = armature_obj
            bpy.ops.object.mode_set(mode='EDIT')

            armature_data = armature_obj.data
            new_bone = armature_data.edit_bones.new(bone_name)
            new_bone.head = mathutils.Vector(head)
            new_bone.tail = mathutils.Vector(tail)
            new_bone.roll = roll

            if parent_bone:
                parent = armature_data.edit_bones.get(parent_bone)
                if parent:
                    new_bone.parent = parent
                    new_bone.use_connect = connected
                else:
                    bpy.ops.object.mode_set(mode='OBJECT')
                    raise ValueError(f"Parent bone not found: {parent_bone}")

            actual_name = new_bone.name  # Blender may rename if duplicate
            bpy.ops.object.mode_set(mode='OBJECT')

            return {
                "bone_name": actual_name,
                "armature_name": armature_obj.name,
                "head": list(head),
                "tail": list(tail),
                "parent": parent_bone
            }
        except Exception as e:
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except:
                pass
            raise Exception(f"Error adding bone: {str(e)}")

    def add_bone_chain(self, armature_name, chain_name, start, direction, count, bone_length, parent_bone=None):
        """Add a chain of connected bones (useful for spines, limbs, tails, etc.)"""
        try:
            armature_obj = bpy.data.objects.get(armature_name)
            if not armature_obj or armature_obj.type != 'ARMATURE':
                raise ValueError(f"Armature not found: {armature_name}")

            bpy.context.view_layer.objects.active = armature_obj
            bpy.ops.object.mode_set(mode='EDIT')

            armature_data = armature_obj.data
            dir_vec = mathutils.Vector(direction).normalized() * bone_length
            current_head = mathutils.Vector(start)
            bone_names = []
            prev_bone = None

            if parent_bone:
                prev_bone = armature_data.edit_bones.get(parent_bone)
                if not prev_bone:
                    bpy.ops.object.mode_set(mode='OBJECT')
                    raise ValueError(f"Parent bone not found: {parent_bone}")

            for i in range(count):
                bone_name = f"{chain_name}_{i+1:02d}"
                bone = armature_data.edit_bones.new(bone_name)
                bone.head = current_head.copy()
                bone.tail = current_head + dir_vec

                if prev_bone:
                    bone.parent = prev_bone
                    if i > 0 or (parent_bone and prev_bone.tail == bone.head):
                        bone.use_connect = True

                bone_names.append(bone.name)
                current_head = bone.tail.copy()
                prev_bone = bone

            bpy.ops.object.mode_set(mode='OBJECT')

            return {
                "armature_name": armature_obj.name,
                "chain_bones": bone_names,
                "count": len(bone_names)
            }
        except Exception as e:
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except:
                pass
            raise Exception(f"Error creating bone chain: {str(e)}")

    def edit_bone(self, armature_name, bone_name, head=None, tail=None, roll=None,
                  parent_bone=None, use_connect=None, envelope_distance=None,
                  use_deform=None):
        """Edit properties of an existing bone"""
        try:
            armature_obj = bpy.data.objects.get(armature_name)
            if not armature_obj or armature_obj.type != 'ARMATURE':
                raise ValueError(f"Armature not found: {armature_name}")

            bpy.context.view_layer.objects.active = armature_obj
            bpy.ops.object.mode_set(mode='EDIT')

            bone = armature_obj.data.edit_bones.get(bone_name)
            if not bone:
                bpy.ops.object.mode_set(mode='OBJECT')
                raise ValueError(f"Bone not found: {bone_name}")

            if head is not None:
                bone.head = mathutils.Vector(head)
            if tail is not None:
                bone.tail = mathutils.Vector(tail)
            if roll is not None:
                bone.roll = roll
            if parent_bone is not None:
                if parent_bone == "":
                    bone.parent = None
                else:
                    parent = armature_obj.data.edit_bones.get(parent_bone)
                    if parent:
                        bone.parent = parent
                    else:
                        bpy.ops.object.mode_set(mode='OBJECT')
                        raise ValueError(f"Parent bone not found: {parent_bone}")
            if use_connect is not None:
                bone.use_connect = use_connect
            if envelope_distance is not None:
                bone.envelope_distance = envelope_distance
            if use_deform is not None:
                bone.use_deform = use_deform

            bpy.ops.object.mode_set(mode='OBJECT')

            return {
                "bone_name": bone_name,
                "armature_name": armature_name,
                "updated": True
            }
        except Exception as e:
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except:
                pass
            raise Exception(f"Error editing bone: {str(e)}")

    def remove_bone(self, armature_name, bone_name):
        """Remove a bone from an armature"""
        try:
            armature_obj = bpy.data.objects.get(armature_name)
            if not armature_obj or armature_obj.type != 'ARMATURE':
                raise ValueError(f"Armature not found: {armature_name}")

            bpy.context.view_layer.objects.active = armature_obj
            bpy.ops.object.mode_set(mode='EDIT')

            bone = armature_obj.data.edit_bones.get(bone_name)
            if not bone:
                bpy.ops.object.mode_set(mode='OBJECT')
                raise ValueError(f"Bone not found: {bone_name}")

            armature_obj.data.edit_bones.remove(bone)
            bpy.ops.object.mode_set(mode='OBJECT')

            return {
                "removed": bone_name,
                "armature_name": armature_name,
                "remaining_bones": len(armature_obj.data.bones)
            }
        except Exception as e:
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except:
                pass
            raise Exception(f"Error removing bone: {str(e)}")

    def get_armature_info(self, armature_name):
        """Get detailed information about an armature and all its bones"""
        try:
            armature_obj = bpy.data.objects.get(armature_name)
            if not armature_obj or armature_obj.type != 'ARMATURE':
                raise ValueError(f"Armature not found: {armature_name}")

            armature_data = armature_obj.data
            bones_info = []

            for bone in armature_data.bones:
                bone_info = {
                    "name": bone.name,
                    "head": [round(bone.head_local[i], 4) for i in range(3)],
                    "tail": [round(bone.tail_local[i], 4) for i in range(3)],
                    "length": round(bone.length, 4),
                    "parent": bone.parent.name if bone.parent else None,
                    "children": [c.name for c in bone.children],
                    "connected": bone.use_connect,
                    "use_deform": bone.use_deform,
                }
                bones_info.append(bone_info)

            # Get constraints info from pose bones
            constraints_info = []
            if armature_obj.pose:
                for pbone in armature_obj.pose.bones:
                    for c in pbone.constraints:
                        constraints_info.append({
                            "bone": pbone.name,
                            "type": c.type,
                            "name": c.name,
                            "enabled": not c.mute,
                        })

            # Get parented meshes
            parented_meshes = [
                child.name for child in armature_obj.children
                if child.type == 'MESH'
            ]

            return {
                "name": armature_obj.name,
                "location": [round(armature_obj.location[i], 4) for i in range(3)],
                "bone_count": len(armature_data.bones),
                "bones": bones_info,
                "constraints": constraints_info,
                "parented_meshes": parented_meshes,
            }
        except Exception as e:
            raise Exception(f"Error getting armature info: {str(e)}")

    def parent_mesh_to_armature(self, mesh_name, armature_name, parent_type="ARMATURE_AUTO"):
        """Parent a mesh to an armature with automatic weights or other methods"""
        try:
            mesh_obj = bpy.data.objects.get(mesh_name)
            if not mesh_obj or mesh_obj.type != 'MESH':
                raise ValueError(f"Mesh not found: {mesh_name}")

            armature_obj = bpy.data.objects.get(armature_name)
            if not armature_obj or armature_obj.type != 'ARMATURE':
                raise ValueError(f"Armature not found: {armature_name}")

            # Deselect all, then select mesh and armature
            bpy.ops.object.select_all(action='DESELECT')
            mesh_obj.select_set(True)
            armature_obj.select_set(True)
            bpy.context.view_layer.objects.active = armature_obj

            # Parent with automatic weights or other type
            valid_types = ["ARMATURE_AUTO", "ARMATURE_NAME", "ARMATURE_ENVELOPE", "OBJECT"]
            if parent_type not in valid_types:
                raise ValueError(f"Invalid parent type: {parent_type}. Must be one of: {valid_types}")

            if parent_type == "OBJECT":
                bpy.ops.object.parent_set(type='OBJECT')
            else:
                bpy.ops.object.parent_set(type=parent_type)

            # Check if armature modifier was added
            has_modifier = any(
                mod.type == 'ARMATURE' for mod in mesh_obj.modifiers
            )

            # Get vertex groups created
            vertex_groups = [vg.name for vg in mesh_obj.vertex_groups]

            return {
                "mesh": mesh_obj.name,
                "armature": armature_obj.name,
                "parent_type": parent_type,
                "has_armature_modifier": has_modifier,
                "vertex_groups_count": len(vertex_groups),
                "vertex_groups": vertex_groups[:20],  # Limit output
            }
        except Exception as e:
            raise Exception(f"Error parenting mesh to armature: {str(e)}")

    def add_bone_constraint(self, armature_name, bone_name, constraint_type, properties=None):
        """Add a constraint to a pose bone"""
        try:
            armature_obj = bpy.data.objects.get(armature_name)
            if not armature_obj or armature_obj.type != 'ARMATURE':
                raise ValueError(f"Armature not found: {armature_name}")

            bpy.context.view_layer.objects.active = armature_obj
            bpy.ops.object.mode_set(mode='POSE')

            pose_bone = armature_obj.pose.bones.get(bone_name)
            if not pose_bone:
                bpy.ops.object.mode_set(mode='OBJECT')
                raise ValueError(f"Bone not found: {bone_name}")

            # Map friendly names to Blender constraint types
            constraint_map = {
                "IK": "IK",
                "INVERSE_KINEMATICS": "IK",
                "COPY_LOCATION": "COPY_LOCATION",
                "COPY_ROTATION": "COPY_ROTATION",
                "COPY_SCALE": "COPY_SCALE",
                "COPY_TRANSFORMS": "COPY_TRANSFORMS",
                "LIMIT_LOCATION": "LIMIT_LOCATION",
                "LIMIT_ROTATION": "LIMIT_ROTATION",
                "LIMIT_SCALE": "LIMIT_SCALE",
                "TRACK_TO": "TRACK_TO",
                "DAMPED_TRACK": "DAMPED_TRACK",
                "LOCKED_TRACK": "LOCKED_TRACK",
                "STRETCH_TO": "STRETCH_TO",
                "FLOOR": "FLOOR",
                "CLAMP_TO": "CLAMP_TO",
                "TRANSFORMATION": "TRANSFORMATION",
            }

            ctype = constraint_map.get(constraint_type.upper(), constraint_type.upper())
            constraint = pose_bone.constraints.new(type=ctype)

            # Apply properties
            props = properties or {}
            for key, value in props.items():
                if key == "target":
                    target_obj = bpy.data.objects.get(value)
                    if target_obj:
                        constraint.target = target_obj
                elif key == "subtarget":
                    constraint.subtarget = value
                elif key == "pole_target":
                    pole_obj = bpy.data.objects.get(value)
                    if pole_obj:
                        constraint.pole_target = pole_obj
                elif key == "pole_subtarget":
                    constraint.pole_subtarget = value
                elif key == "pole_angle":
                    constraint.pole_angle = value
                elif key == "chain_count":
                    constraint.chain_count = value
                elif key == "use_tail" and hasattr(constraint, 'use_tail'):
                    constraint.use_tail = value
                elif key == "use_stretch" and hasattr(constraint, 'use_stretch'):
                    constraint.use_stretch = value
                elif key == "influence":
                    constraint.influence = value
                elif key == "name":
                    constraint.name = value
                elif hasattr(constraint, key):
                    setattr(constraint, key, value)

            bpy.ops.object.mode_set(mode='OBJECT')

            return {
                "constraint_name": constraint.name,
                "constraint_type": ctype,
                "bone": bone_name,
                "armature": armature_name,
            }
        except Exception as e:
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except:
                pass
            raise Exception(f"Error adding constraint: {str(e)}")

    def remove_bone_constraint(self, armature_name, bone_name, constraint_name):
        """Remove a constraint from a pose bone"""
        try:
            armature_obj = bpy.data.objects.get(armature_name)
            if not armature_obj or armature_obj.type != 'ARMATURE':
                raise ValueError(f"Armature not found: {armature_name}")

            bpy.context.view_layer.objects.active = armature_obj
            bpy.ops.object.mode_set(mode='POSE')

            pose_bone = armature_obj.pose.bones.get(bone_name)
            if not pose_bone:
                bpy.ops.object.mode_set(mode='OBJECT')
                raise ValueError(f"Bone not found: {bone_name}")

            constraint = pose_bone.constraints.get(constraint_name)
            if not constraint:
                bpy.ops.object.mode_set(mode='OBJECT')
                raise ValueError(f"Constraint not found: {constraint_name}")

            pose_bone.constraints.remove(constraint)
            bpy.ops.object.mode_set(mode='OBJECT')

            return {
                "removed": constraint_name,
                "bone": bone_name,
                "armature": armature_name,
            }
        except Exception as e:
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except:
                pass
            raise Exception(f"Error removing constraint: {str(e)}")

    def set_bone_pose(self, armature_name, bone_name, location=None, rotation_euler=None,
                      rotation_quaternion=None, scale=None):
        """Set the pose transform of a bone"""
        try:
            armature_obj = bpy.data.objects.get(armature_name)
            if not armature_obj or armature_obj.type != 'ARMATURE':
                raise ValueError(f"Armature not found: {armature_name}")

            bpy.context.view_layer.objects.active = armature_obj
            bpy.ops.object.mode_set(mode='POSE')

            pose_bone = armature_obj.pose.bones.get(bone_name)
            if not pose_bone:
                bpy.ops.object.mode_set(mode='OBJECT')
                raise ValueError(f"Bone not found: {bone_name}")

            if location is not None:
                pose_bone.location = mathutils.Vector(location)
            if rotation_euler is not None:
                pose_bone.rotation_mode = 'XYZ'
                pose_bone.rotation_euler = mathutils.Euler(rotation_euler)
            if rotation_quaternion is not None:
                pose_bone.rotation_mode = 'QUATERNION'
                pose_bone.rotation_quaternion = mathutils.Quaternion(rotation_quaternion)
            if scale is not None:
                pose_bone.scale = mathutils.Vector(scale)

            bpy.ops.object.mode_set(mode='OBJECT')

            return {
                "bone": bone_name,
                "armature": armature_name,
                "posed": True
            }
        except Exception as e:
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except:
                pass
            raise Exception(f"Error setting bone pose: {str(e)}")

    def reset_pose(self, armature_name, bone_names=None):
        """Reset pose of all or specific bones to rest position"""
        try:
            armature_obj = bpy.data.objects.get(armature_name)
            if not armature_obj or armature_obj.type != 'ARMATURE':
                raise ValueError(f"Armature not found: {armature_name}")

            bpy.context.view_layer.objects.active = armature_obj
            bpy.ops.object.mode_set(mode='POSE')

            reset_bones = []
            bones_to_reset = bone_names or [b.name for b in armature_obj.pose.bones]

            for bname in bones_to_reset:
                pose_bone = armature_obj.pose.bones.get(bname)
                if pose_bone:
                    pose_bone.location = (0, 0, 0)
                    pose_bone.rotation_quaternion = (1, 0, 0, 0)
                    pose_bone.rotation_euler = (0, 0, 0)
                    pose_bone.scale = (1, 1, 1)
                    reset_bones.append(bname)

            bpy.ops.object.mode_set(mode='OBJECT')

            return {
                "armature": armature_name,
                "reset_bones": reset_bones,
                "count": len(reset_bones)
            }
        except Exception as e:
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except:
                pass
            raise Exception(f"Error resetting pose: {str(e)}")

    def manage_vertex_groups(self, mesh_name, action, vertex_group_name, vertex_indices=None, weight=1.0):
        """Create, remove, or assign weights to vertex groups"""
        try:
            mesh_obj = bpy.data.objects.get(mesh_name)
            if not mesh_obj or mesh_obj.type != 'MESH':
                raise ValueError(f"Mesh not found: {mesh_name}")

            if action == "create":
                vg = mesh_obj.vertex_groups.new(name=vertex_group_name)
                return {
                    "action": "created",
                    "vertex_group": vg.name,
                    "mesh": mesh_name
                }

            elif action == "remove":
                vg = mesh_obj.vertex_groups.get(vertex_group_name)
                if not vg:
                    raise ValueError(f"Vertex group not found: {vertex_group_name}")
                mesh_obj.vertex_groups.remove(vg)
                return {
                    "action": "removed",
                    "vertex_group": vertex_group_name,
                    "mesh": mesh_name
                }

            elif action == "assign":
                vg = mesh_obj.vertex_groups.get(vertex_group_name)
                if not vg:
                    vg = mesh_obj.vertex_groups.new(name=vertex_group_name)
                if vertex_indices:
                    vg.add(vertex_indices, weight, 'REPLACE')
                return {
                    "action": "assigned",
                    "vertex_group": vg.name,
                    "mesh": mesh_name,
                    "vertex_count": len(vertex_indices) if vertex_indices else 0,
                    "weight": weight
                }

            elif action == "list":
                groups = [{"name": vg.name, "index": vg.index} for vg in mesh_obj.vertex_groups]
                return {
                    "action": "list",
                    "mesh": mesh_name,
                    "vertex_groups": groups,
                    "count": len(groups)
                }

            else:
                raise ValueError(f"Unknown action: {action}. Must be create, remove, assign, or list")

        except Exception as e:
            raise Exception(f"Error managing vertex groups: {str(e)}")

    def setup_ik(self, armature_name, bone_name, chain_count=0, target_bone=None,
                 pole_bone=None, pole_angle=0.0, use_stretch=False):
        """Convenience method to set up IK on a bone with common settings"""
        try:
            props = {
                "target": armature_name,
                "chain_count": chain_count,
                "use_stretch": use_stretch,
            }

            if target_bone:
                props["subtarget"] = target_bone
            if pole_bone:
                props["pole_target"] = armature_name
                props["pole_subtarget"] = pole_bone
                props["pole_angle"] = pole_angle

            return self.add_bone_constraint(
                armature_name=armature_name,
                bone_name=bone_name,
                constraint_type="IK",
                properties=props
            )
        except Exception as e:
            raise Exception(f"Error setting up IK: {str(e)}")

    def create_humanoid_rig(self, name="Humanoid", location=None, height=1.8):
        """Create a basic humanoid armature with standard bone hierarchy"""
        try:
            loc = location or [0, 0, 0]
            scale = height / 1.8  # Scale relative to default 1.8m height

            armature_data = bpy.data.armatures.new(name)
            armature_obj = bpy.data.objects.new(name, armature_data)
            bpy.context.collection.objects.link(armature_obj)
            armature_obj.location = mathutils.Vector(loc)

            bpy.context.view_layer.objects.active = armature_obj
            bpy.ops.object.mode_set(mode='EDIT')

            s = scale  # shorthand
            bones = armature_data.edit_bones

            # Spine
            hips = bones.new("Hips")
            hips.head = (0, 0, 0.95 * s)
            hips.tail = (0, 0, 1.05 * s)

            spine = bones.new("Spine")
            spine.head = hips.tail.copy()
            spine.tail = (0, 0, 1.2 * s)
            spine.parent = hips
            spine.use_connect = True

            chest = bones.new("Chest")
            chest.head = spine.tail.copy()
            chest.tail = (0, 0, 1.4 * s)
            chest.parent = spine
            chest.use_connect = True

            neck = bones.new("Neck")
            neck.head = chest.tail.copy()
            neck.tail = (0, 0, 1.55 * s)
            neck.parent = chest
            neck.use_connect = True

            head = bones.new("Head")
            head.head = neck.tail.copy()
            head.tail = (0, 0, 1.75 * s)
            head.parent = neck
            head.use_connect = True

            # Left arm
            shoulder_l = bones.new("Shoulder.L")
            shoulder_l.head = (0.05 * s, 0, 1.38 * s)
            shoulder_l.tail = (0.18 * s, 0, 1.38 * s)
            shoulder_l.parent = chest

            upper_arm_l = bones.new("UpperArm.L")
            upper_arm_l.head = shoulder_l.tail.copy()
            upper_arm_l.tail = (0.45 * s, 0, 1.38 * s)
            upper_arm_l.parent = shoulder_l
            upper_arm_l.use_connect = True

            forearm_l = bones.new("Forearm.L")
            forearm_l.head = upper_arm_l.tail.copy()
            forearm_l.tail = (0.68 * s, 0, 1.38 * s)
            forearm_l.parent = upper_arm_l
            forearm_l.use_connect = True

            hand_l = bones.new("Hand.L")
            hand_l.head = forearm_l.tail.copy()
            hand_l.tail = (0.78 * s, 0, 1.38 * s)
            hand_l.parent = forearm_l
            hand_l.use_connect = True

            # Right arm
            shoulder_r = bones.new("Shoulder.R")
            shoulder_r.head = (-0.05 * s, 0, 1.38 * s)
            shoulder_r.tail = (-0.18 * s, 0, 1.38 * s)
            shoulder_r.parent = chest

            upper_arm_r = bones.new("UpperArm.R")
            upper_arm_r.head = shoulder_r.tail.copy()
            upper_arm_r.tail = (-0.45 * s, 0, 1.38 * s)
            upper_arm_r.parent = shoulder_r
            upper_arm_r.use_connect = True

            forearm_r = bones.new("Forearm.R")
            forearm_r.head = upper_arm_r.tail.copy()
            forearm_r.tail = (-0.68 * s, 0, 1.38 * s)
            forearm_r.parent = upper_arm_r
            forearm_r.use_connect = True

            hand_r = bones.new("Hand.R")
            hand_r.head = forearm_r.tail.copy()
            hand_r.tail = (-0.78 * s, 0, 1.38 * s)
            hand_r.parent = forearm_r
            hand_r.use_connect = True

            # Left leg
            upper_leg_l = bones.new("UpperLeg.L")
            upper_leg_l.head = (0.1 * s, 0, 0.93 * s)
            upper_leg_l.tail = (0.1 * s, 0, 0.5 * s)
            upper_leg_l.parent = hips

            lower_leg_l = bones.new("LowerLeg.L")
            lower_leg_l.head = upper_leg_l.tail.copy()
            lower_leg_l.tail = (0.1 * s, 0, 0.08 * s)
            lower_leg_l.parent = upper_leg_l
            lower_leg_l.use_connect = True

            foot_l = bones.new("Foot.L")
            foot_l.head = lower_leg_l.tail.copy()
            foot_l.tail = (0.1 * s, -0.12 * s, 0.0)
            foot_l.parent = lower_leg_l
            foot_l.use_connect = True

            toe_l = bones.new("Toe.L")
            toe_l.head = foot_l.tail.copy()
            toe_l.tail = (0.1 * s, -0.2 * s, 0.0)
            toe_l.parent = foot_l
            toe_l.use_connect = True

            # Right leg
            upper_leg_r = bones.new("UpperLeg.R")
            upper_leg_r.head = (-0.1 * s, 0, 0.93 * s)
            upper_leg_r.tail = (-0.1 * s, 0, 0.5 * s)
            upper_leg_r.parent = hips

            lower_leg_r = bones.new("LowerLeg.R")
            lower_leg_r.head = upper_leg_r.tail.copy()
            lower_leg_r.tail = (-0.1 * s, 0, 0.08 * s)
            lower_leg_r.parent = upper_leg_r
            lower_leg_r.use_connect = True

            foot_r = bones.new("Foot.R")
            foot_r.head = lower_leg_r.tail.copy()
            foot_r.tail = (-0.1 * s, -0.12 * s, 0.0)
            foot_r.parent = lower_leg_r
            foot_r.use_connect = True

            toe_r = bones.new("Toe.R")
            toe_r.head = foot_r.tail.copy()
            toe_r.tail = (-0.1 * s, -0.2 * s, 0.0)
            toe_r.parent = foot_r
            toe_r.use_connect = True

            bone_names = [b.name for b in bones]
            bpy.ops.object.mode_set(mode='OBJECT')

            return {
                "armature_name": armature_obj.name,
                "bone_count": len(bone_names),
                "bones": bone_names,
                "height": height,
            }
        except Exception as e:
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except:
                pass
            raise Exception(f"Error creating humanoid rig: {str(e)}")

    # ==================== End Rigging Tools ====================

    def get_polyhaven_categories(self, asset_type):
        """Get categories for a specific asset type from Polyhaven"""
        try:
            if asset_type not in ["hdris", "textures", "models", "all"]:
                return {"error": f"Invalid asset type: {asset_type}. Must be one of: hdris, textures, models, all"}

            response = requests.get(f"https://api.polyhaven.com/categories/{asset_type}", headers=REQ_HEADERS)
            if response.status_code == 200:
                return {"categories": response.json()}
            else:
                return {"error": f"API request failed with status code {response.status_code}"}
        except Exception as e:
            return {"error": str(e)}

    def search_polyhaven_assets(self, asset_type=None, categories=None):
        """Search for assets from Polyhaven with optional filtering"""
        try:
            url = "https://api.polyhaven.com/assets"
            params = {}

            if asset_type and asset_type != "all":
                if asset_type not in ["hdris", "textures", "models"]:
                    return {"error": f"Invalid asset type: {asset_type}. Must be one of: hdris, textures, models, all"}
                params["type"] = asset_type

            if categories:
                params["categories"] = categories

            response = requests.get(url, params=params, headers=REQ_HEADERS)
            if response.status_code == 200:
                # Limit the response size to avoid overwhelming Blender
                assets = response.json()
                # Return only the first 20 assets to keep response size manageable
                limited_assets = {}
                for i, (key, value) in enumerate(assets.items()):
                    if i >= 20:  # Limit to 20 assets
                        break
                    limited_assets[key] = value

                return {"assets": limited_assets, "total_count": len(assets), "returned_count": len(limited_assets)}
            else:
                return {"error": f"API request failed with status code {response.status_code}"}
        except Exception as e:
            return {"error": str(e)}

    def download_polyhaven_asset(self, asset_id, asset_type, resolution="1k", file_format=None):
        try:
            # First get the files information
            files_response = requests.get(f"https://api.polyhaven.com/files/{asset_id}", headers=REQ_HEADERS)
            if files_response.status_code != 200:
                return {"error": f"Failed to get asset files: {files_response.status_code}"}

            files_data = files_response.json()

            # Handle different asset types
            if asset_type == "hdris":
                # For HDRIs, download the .hdr or .exr file
                if not file_format:
                    file_format = "hdr"  # Default format for HDRIs

                if "hdri" in files_data and resolution in files_data["hdri"] and file_format in files_data["hdri"][resolution]:
                    file_info = files_data["hdri"][resolution][file_format]
                    file_url = file_info["url"]

                    # For HDRIs, we need to save to a temporary file first
                    # since Blender can't properly load HDR data directly from memory
                    with tempfile.NamedTemporaryFile(suffix=f".{file_format}", delete=False) as tmp_file:
                        # Download the file
                        response = requests.get(file_url, headers=REQ_HEADERS)
                        if response.status_code != 200:
                            return {"error": f"Failed to download HDRI: {response.status_code}"}

                        tmp_file.write(response.content)
                        tmp_path = tmp_file.name

                    try:
                        # Create a new world if none exists
                        if not bpy.data.worlds:
                            bpy.data.worlds.new("World")

                        world = bpy.data.worlds[0]
                        world.use_nodes = True
                        node_tree = world.node_tree

                        # Clear existing nodes
                        for node in node_tree.nodes:
                            node_tree.nodes.remove(node)

                        # Create nodes
                        tex_coord = node_tree.nodes.new(type='ShaderNodeTexCoord')
                        tex_coord.location = (-800, 0)

                        mapping = node_tree.nodes.new(type='ShaderNodeMapping')
                        mapping.location = (-600, 0)

                        # Load the image from the temporary file
                        env_tex = node_tree.nodes.new(type='ShaderNodeTexEnvironment')
                        env_tex.location = (-400, 0)
                        env_tex.image = bpy.data.images.load(tmp_path)

                        # Use a color space that exists in all Blender versions
                        if file_format.lower() == 'exr':
                            # Try to use Linear color space for EXR files
                            try:
                                env_tex.image.colorspace_settings.name = 'Linear'
                            except:
                                # Fallback to Non-Color if Linear isn't available
                                env_tex.image.colorspace_settings.name = 'Non-Color'
                        else:  # hdr
                            # For HDR files, try these options in order
                            for color_space in ['Linear', 'Linear Rec.709', 'Non-Color']:
                                try:
                                    env_tex.image.colorspace_settings.name = color_space
                                    break  # Stop if we successfully set a color space
                                except:
                                    continue

                        background = node_tree.nodes.new(type='ShaderNodeBackground')
                        background.location = (-200, 0)

                        output = node_tree.nodes.new(type='ShaderNodeOutputWorld')
                        output.location = (0, 0)

                        # Connect nodes
                        node_tree.links.new(tex_coord.outputs['Generated'], mapping.inputs['Vector'])
                        node_tree.links.new(mapping.outputs['Vector'], env_tex.inputs['Vector'])
                        node_tree.links.new(env_tex.outputs['Color'], background.inputs['Color'])
                        node_tree.links.new(background.outputs['Background'], output.inputs['Surface'])

                        # Set as active world
                        bpy.context.scene.world = world

                        # Clean up temporary file
                        try:
                            tempfile._cleanup()  # This will clean up all temporary files
                        except:
                            pass

                        return {
                            "success": True,
                            "message": f"HDRI {asset_id} imported successfully",
                            "image_name": env_tex.image.name
                        }
                    except Exception as e:
                        return {"error": f"Failed to set up HDRI in Blender: {str(e)}"}
                else:
                    return {"error": f"Requested resolution or format not available for this HDRI"}

            elif asset_type == "textures":
                if not file_format:
                    file_format = "jpg"  # Default format for textures

                downloaded_maps = {}

                try:
                    for map_type in files_data:
                        if map_type not in ["blend", "gltf"]:  # Skip non-texture files
                            if resolution in files_data[map_type] and file_format in files_data[map_type][resolution]:
                                file_info = files_data[map_type][resolution][file_format]
                                file_url = file_info["url"]

                                # Use NamedTemporaryFile like we do for HDRIs
                                with tempfile.NamedTemporaryFile(suffix=f".{file_format}", delete=False) as tmp_file:
                                    # Download the file
                                    response = requests.get(file_url, headers=REQ_HEADERS)
                                    if response.status_code == 200:
                                        tmp_file.write(response.content)
                                        tmp_path = tmp_file.name

                                        # Load image from temporary file
                                        image = bpy.data.images.load(tmp_path)
                                        image.name = f"{asset_id}_{map_type}.{file_format}"

                                        # Pack the image into .blend file
                                        image.pack()

                                        # Set color space based on map type
                                        if map_type in ['color', 'diffuse', 'albedo']:
                                            try:
                                                image.colorspace_settings.name = 'sRGB'
                                            except:
                                                pass
                                        else:
                                            try:
                                                image.colorspace_settings.name = 'Non-Color'
                                            except:
                                                pass

                                        downloaded_maps[map_type] = image

                                        # Clean up temporary file
                                        try:
                                            os.unlink(tmp_path)
                                        except:
                                            pass

                    if not downloaded_maps:
                        return {"error": f"No texture maps found for the requested resolution and format"}

                    # Create a new material with the downloaded textures
                    mat = bpy.data.materials.new(name=asset_id)
                    mat.use_nodes = True
                    nodes = mat.node_tree.nodes
                    links = mat.node_tree.links

                    # Clear default nodes
                    for node in nodes:
                        nodes.remove(node)

                    # Create output node
                    output = nodes.new(type='ShaderNodeOutputMaterial')
                    output.location = (300, 0)

                    # Create principled BSDF node
                    principled = nodes.new(type='ShaderNodeBsdfPrincipled')
                    principled.location = (0, 0)
                    links.new(principled.outputs[0], output.inputs[0])

                    # Add texture nodes based on available maps
                    tex_coord = nodes.new(type='ShaderNodeTexCoord')
                    tex_coord.location = (-800, 0)

                    mapping = nodes.new(type='ShaderNodeMapping')
                    mapping.location = (-600, 0)
                    mapping.vector_type = 'TEXTURE'  # Changed from default 'POINT' to 'TEXTURE'
                    links.new(tex_coord.outputs['UV'], mapping.inputs['Vector'])

                    # Position offset for texture nodes
                    x_pos = -400
                    y_pos = 300

                    # Connect different texture maps
                    for map_type, image in downloaded_maps.items():
                        tex_node = nodes.new(type='ShaderNodeTexImage')
                        tex_node.location = (x_pos, y_pos)
                        tex_node.image = image

                        # Set color space based on map type
                        if map_type.lower() in ['color', 'diffuse', 'albedo']:
                            try:
                                tex_node.image.colorspace_settings.name = 'sRGB'
                            except:
                                pass  # Use default if sRGB not available
                        else:
                            try:
                                tex_node.image.colorspace_settings.name = 'Non-Color'
                            except:
                                pass  # Use default if Non-Color not available

                        links.new(mapping.outputs['Vector'], tex_node.inputs['Vector'])

                        # Connect to appropriate input on Principled BSDF
                        if map_type.lower() in ['color', 'diffuse', 'albedo']:
                            links.new(tex_node.outputs['Color'], principled.inputs['Base Color'])
                        elif map_type.lower() in ['roughness', 'rough']:
                            links.new(tex_node.outputs['Color'], principled.inputs['Roughness'])
                        elif map_type.lower() in ['metallic', 'metalness', 'metal']:
                            links.new(tex_node.outputs['Color'], principled.inputs['Metallic'])
                        elif map_type.lower() in ['normal', 'nor']:
                            # Add normal map node
                            normal_map = nodes.new(type='ShaderNodeNormalMap')
                            normal_map.location = (x_pos + 200, y_pos)
                            links.new(tex_node.outputs['Color'], normal_map.inputs['Color'])
                            links.new(normal_map.outputs['Normal'], principled.inputs['Normal'])
                        elif map_type in ['displacement', 'disp', 'height']:
                            # Add displacement node
                            disp_node = nodes.new(type='ShaderNodeDisplacement')
                            disp_node.location = (x_pos + 200, y_pos - 200)
                            links.new(tex_node.outputs['Color'], disp_node.inputs['Height'])
                            links.new(disp_node.outputs['Displacement'], output.inputs['Displacement'])

                        y_pos -= 250

                    return {
                        "success": True,
                        "message": f"Texture {asset_id} imported as material",
                        "material": mat.name,
                        "maps": list(downloaded_maps.keys())
                    }

                except Exception as e:
                    return {"error": f"Failed to process textures: {str(e)}"}

            elif asset_type == "models":
                # For models, prefer glTF format if available
                if not file_format:
                    file_format = "gltf"  # Default format for models

                if file_format in files_data and resolution in files_data[file_format]:
                    file_info = files_data[file_format][resolution][file_format]
                    file_url = file_info["url"]

                    # Create a temporary directory to store the model and its dependencies
                    temp_dir = tempfile.mkdtemp()
                    main_file_path = ""

                    try:
                        # Download the main model file
                        main_file_name = file_url.split("/")[-1]
                        main_file_path = os.path.join(temp_dir, main_file_name)

                        response = requests.get(file_url, headers=REQ_HEADERS)
                        if response.status_code != 200:
                            return {"error": f"Failed to download model: {response.status_code}"}

                        with open(main_file_path, "wb") as f:
                            f.write(response.content)

                        # Check for included files and download them
                        if "include" in file_info and file_info["include"]:
                            for include_path, include_info in file_info["include"].items():
                                # Get the URL for the included file - this is the fix
                                include_url = include_info["url"]

                                # Create the directory structure for the included file
                                include_file_path = os.path.join(temp_dir, include_path)
                                os.makedirs(os.path.dirname(include_file_path), exist_ok=True)

                                # Download the included file
                                include_response = requests.get(include_url, headers=REQ_HEADERS)
                                if include_response.status_code == 200:
                                    with open(include_file_path, "wb") as f:
                                        f.write(include_response.content)
                                else:
                                    print(f"Failed to download included file: {include_path}")

                        # Import the model into Blender
                        if file_format == "gltf" or file_format == "glb":
                            bpy.ops.import_scene.gltf(filepath=main_file_path)
                        elif file_format == "fbx":
                            bpy.ops.import_scene.fbx(filepath=main_file_path)
                        elif file_format == "obj":
                            bpy.ops.import_scene.obj(filepath=main_file_path)
                        elif file_format == "blend":
                            # For blend files, we need to append or link
                            with bpy.data.libraries.load(main_file_path, link=False) as (data_from, data_to):
                                data_to.objects = data_from.objects

                            # Link the objects to the scene
                            for obj in data_to.objects:
                                if obj is not None:
                                    bpy.context.collection.objects.link(obj)
                        else:
                            return {"error": f"Unsupported model format: {file_format}"}

                        # Get the names of imported objects
                        imported_objects = [obj.name for obj in bpy.context.selected_objects]

                        return {
                            "success": True,
                            "message": f"Model {asset_id} imported successfully",
                            "imported_objects": imported_objects
                        }
                    except Exception as e:
                        return {"error": f"Failed to import model: {str(e)}"}
                    finally:
                        # Clean up temporary directory
                        with suppress(Exception):
                            shutil.rmtree(temp_dir)
                else:
                    return {"error": f"Requested format or resolution not available for this model"}

            else:
                return {"error": f"Unsupported asset type: {asset_type}"}

        except Exception as e:
            return {"error": f"Failed to download asset: {str(e)}"}

    def set_texture(self, object_name, texture_id):
        """Apply a previously downloaded Polyhaven texture to an object by creating a new material"""
        try:
            # Get the object
            obj = bpy.data.objects.get(object_name)
            if not obj:
                return {"error": f"Object not found: {object_name}"}

            # Make sure object can accept materials
            if not hasattr(obj, 'data') or not hasattr(obj.data, 'materials'):
                return {"error": f"Object {object_name} cannot accept materials"}

            # Find all images related to this texture and ensure they're properly loaded
            texture_images = {}
            for img in bpy.data.images:
                if img.name.startswith(texture_id + "_"):
                    # Extract the map type from the image name
                    map_type = img.name.split('_')[-1].split('.')[0]

                    # Force a reload of the image
                    img.reload()

                    # Ensure proper color space
                    if map_type.lower() in ['color', 'diffuse', 'albedo']:
                        try:
                            img.colorspace_settings.name = 'sRGB'
                        except:
                            pass
                    else:
                        try:
                            img.colorspace_settings.name = 'Non-Color'
                        except:
                            pass

                    # Ensure the image is packed
                    if not img.packed_file:
                        img.pack()

                    texture_images[map_type] = img
                    print(f"Loaded texture map: {map_type} - {img.name}")

                    # Debug info
                    print(f"Image size: {img.size[0]}x{img.size[1]}")
                    print(f"Color space: {img.colorspace_settings.name}")
                    print(f"File format: {img.file_format}")
                    print(f"Is packed: {bool(img.packed_file)}")

            if not texture_images:
                return {"error": f"No texture images found for: {texture_id}. Please download the texture first."}

            # Create a new material
            new_mat_name = f"{texture_id}_material_{object_name}"

            # Remove any existing material with this name to avoid conflicts
            existing_mat = bpy.data.materials.get(new_mat_name)
            if existing_mat:
                bpy.data.materials.remove(existing_mat)

            new_mat = bpy.data.materials.new(name=new_mat_name)
            new_mat.use_nodes = True

            # Set up the material nodes
            nodes = new_mat.node_tree.nodes
            links = new_mat.node_tree.links

            # Clear default nodes
            nodes.clear()

            # Create output node
            output = nodes.new(type='ShaderNodeOutputMaterial')
            output.location = (600, 0)

            # Create principled BSDF node
            principled = nodes.new(type='ShaderNodeBsdfPrincipled')
            principled.location = (300, 0)
            links.new(principled.outputs[0], output.inputs[0])

            # Add texture nodes based on available maps
            tex_coord = nodes.new(type='ShaderNodeTexCoord')
            tex_coord.location = (-800, 0)

            mapping = nodes.new(type='ShaderNodeMapping')
            mapping.location = (-600, 0)
            mapping.vector_type = 'TEXTURE'  # Changed from default 'POINT' to 'TEXTURE'
            links.new(tex_coord.outputs['UV'], mapping.inputs['Vector'])

            # Position offset for texture nodes
            x_pos = -400
            y_pos = 300

            # Connect different texture maps
            for map_type, image in texture_images.items():
                tex_node = nodes.new(type='ShaderNodeTexImage')
                tex_node.location = (x_pos, y_pos)
                tex_node.image = image

                # Set color space based on map type
                if map_type.lower() in ['color', 'diffuse', 'albedo']:
                    try:
                        tex_node.image.colorspace_settings.name = 'sRGB'
                    except:
                        pass  # Use default if sRGB not available
                else:
                    try:
                        tex_node.image.colorspace_settings.name = 'Non-Color'
                    except:
                        pass  # Use default if Non-Color not available

                links.new(mapping.outputs['Vector'], tex_node.inputs['Vector'])

                # Connect to appropriate input on Principled BSDF
                if map_type.lower() in ['color', 'diffuse', 'albedo']:
                    links.new(tex_node.outputs['Color'], principled.inputs['Base Color'])
                elif map_type.lower() in ['roughness', 'rough']:
                    links.new(tex_node.outputs['Color'], principled.inputs['Roughness'])
                elif map_type.lower() in ['metallic', 'metalness', 'metal']:
                    links.new(tex_node.outputs['Color'], principled.inputs['Metallic'])
                elif map_type.lower() in ['normal', 'nor', 'dx', 'gl']:
                    # Add normal map node
                    normal_map = nodes.new(type='ShaderNodeNormalMap')
                    normal_map.location = (x_pos + 200, y_pos)
                    links.new(tex_node.outputs['Color'], normal_map.inputs['Color'])
                    links.new(normal_map.outputs['Normal'], principled.inputs['Normal'])
                elif map_type.lower() in ['displacement', 'disp', 'height']:
                    # Add displacement node
                    disp_node = nodes.new(type='ShaderNodeDisplacement')
                    disp_node.location = (x_pos + 200, y_pos - 200)
                    disp_node.inputs['Scale'].default_value = 0.1  # Reduce displacement strength
                    links.new(tex_node.outputs['Color'], disp_node.inputs['Height'])
                    links.new(disp_node.outputs['Displacement'], output.inputs['Displacement'])

                y_pos -= 250

            # Second pass: Connect nodes with proper handling for special cases
            texture_nodes = {}

            # First find all texture nodes and store them by map type
            for node in nodes:
                if node.type == 'TEX_IMAGE' and node.image:
                    for map_type, image in texture_images.items():
                        if node.image == image:
                            texture_nodes[map_type] = node
                            break

            # Now connect everything using the nodes instead of images
            # Handle base color (diffuse)
            for map_name in ['color', 'diffuse', 'albedo']:
                if map_name in texture_nodes:
                    links.new(texture_nodes[map_name].outputs['Color'], principled.inputs['Base Color'])
                    print(f"Connected {map_name} to Base Color")
                    break

            # Handle roughness
            for map_name in ['roughness', 'rough']:
                if map_name in texture_nodes:
                    links.new(texture_nodes[map_name].outputs['Color'], principled.inputs['Roughness'])
                    print(f"Connected {map_name} to Roughness")
                    break

            # Handle metallic
            for map_name in ['metallic', 'metalness', 'metal']:
                if map_name in texture_nodes:
                    links.new(texture_nodes[map_name].outputs['Color'], principled.inputs['Metallic'])
                    print(f"Connected {map_name} to Metallic")
                    break

            # Handle normal maps
            for map_name in ['gl', 'dx', 'nor']:
                if map_name in texture_nodes:
                    normal_map_node = nodes.new(type='ShaderNodeNormalMap')
                    normal_map_node.location = (100, 100)
                    links.new(texture_nodes[map_name].outputs['Color'], normal_map_node.inputs['Color'])
                    links.new(normal_map_node.outputs['Normal'], principled.inputs['Normal'])
                    print(f"Connected {map_name} to Normal")
                    break

            # Handle displacement
            for map_name in ['displacement', 'disp', 'height']:
                if map_name in texture_nodes:
                    disp_node = nodes.new(type='ShaderNodeDisplacement')
                    disp_node.location = (300, -200)
                    disp_node.inputs['Scale'].default_value = 0.1  # Reduce displacement strength
                    links.new(texture_nodes[map_name].outputs['Color'], disp_node.inputs['Height'])
                    links.new(disp_node.outputs['Displacement'], output.inputs['Displacement'])
                    print(f"Connected {map_name} to Displacement")
                    break

            # Handle ARM texture (Ambient Occlusion, Roughness, Metallic)
            if 'arm' in texture_nodes:
                separate_rgb = nodes.new(type='ShaderNodeSeparateRGB')
                separate_rgb.location = (-200, -100)
                links.new(texture_nodes['arm'].outputs['Color'], separate_rgb.inputs['Image'])

                # Connect Roughness (G) if no dedicated roughness map
                if not any(map_name in texture_nodes for map_name in ['roughness', 'rough']):
                    links.new(separate_rgb.outputs['G'], principled.inputs['Roughness'])
                    print("Connected ARM.G to Roughness")

                # Connect Metallic (B) if no dedicated metallic map
                if not any(map_name in texture_nodes for map_name in ['metallic', 'metalness', 'metal']):
                    links.new(separate_rgb.outputs['B'], principled.inputs['Metallic'])
                    print("Connected ARM.B to Metallic")

                # For AO (R channel), multiply with base color if we have one
                base_color_node = None
                for map_name in ['color', 'diffuse', 'albedo']:
                    if map_name in texture_nodes:
                        base_color_node = texture_nodes[map_name]
                        break

                if base_color_node:
                    mix_node = nodes.new(type='ShaderNodeMixRGB')
                    mix_node.location = (100, 200)
                    mix_node.blend_type = 'MULTIPLY'
                    mix_node.inputs['Fac'].default_value = 0.8  # 80% influence

                    # Disconnect direct connection to base color
                    for link in base_color_node.outputs['Color'].links:
                        if link.to_socket == principled.inputs['Base Color']:
                            links.remove(link)

                    # Connect through the mix node
                    links.new(base_color_node.outputs['Color'], mix_node.inputs[1])
                    links.new(separate_rgb.outputs['R'], mix_node.inputs[2])
                    links.new(mix_node.outputs['Color'], principled.inputs['Base Color'])
                    print("Connected ARM.R to AO mix with Base Color")

            # Handle AO (Ambient Occlusion) if separate
            if 'ao' in texture_nodes:
                base_color_node = None
                for map_name in ['color', 'diffuse', 'albedo']:
                    if map_name in texture_nodes:
                        base_color_node = texture_nodes[map_name]
                        break

                if base_color_node:
                    mix_node = nodes.new(type='ShaderNodeMixRGB')
                    mix_node.location = (100, 200)
                    mix_node.blend_type = 'MULTIPLY'
                    mix_node.inputs['Fac'].default_value = 0.8  # 80% influence

                    # Disconnect direct connection to base color
                    for link in base_color_node.outputs['Color'].links:
                        if link.to_socket == principled.inputs['Base Color']:
                            links.remove(link)

                    # Connect through the mix node
                    links.new(base_color_node.outputs['Color'], mix_node.inputs[1])
                    links.new(texture_nodes['ao'].outputs['Color'], mix_node.inputs[2])
                    links.new(mix_node.outputs['Color'], principled.inputs['Base Color'])
                    print("Connected AO to mix with Base Color")

            # CRITICAL: Make sure to clear all existing materials from the object
            while len(obj.data.materials) > 0:
                obj.data.materials.pop(index=0)

            # Assign the new material to the object
            obj.data.materials.append(new_mat)

            # CRITICAL: Make the object active and select it
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)

            # CRITICAL: Force Blender to update the material
            bpy.context.view_layer.update()

            # Get the list of texture maps
            texture_maps = list(texture_images.keys())

            # Get info about texture nodes for debugging
            material_info = {
                "name": new_mat.name,
                "has_nodes": new_mat.use_nodes,
                "node_count": len(new_mat.node_tree.nodes),
                "texture_nodes": []
            }

            for node in new_mat.node_tree.nodes:
                if node.type == 'TEX_IMAGE' and node.image:
                    connections = []
                    for output in node.outputs:
                        for link in output.links:
                            connections.append(f"{output.name} → {link.to_node.name}.{link.to_socket.name}")

                    material_info["texture_nodes"].append({
                        "name": node.name,
                        "image": node.image.name,
                        "colorspace": node.image.colorspace_settings.name,
                        "connections": connections
                    })

            return {
                "success": True,
                "message": f"Created new material and applied texture {texture_id} to {object_name}",
                "material": new_mat.name,
                "maps": texture_maps,
                "material_info": material_info
            }

        except Exception as e:
            print(f"Error in set_texture: {str(e)}")
            traceback.print_exc()
            return {"error": f"Failed to apply texture: {str(e)}"}

    def get_telemetry_consent(self):
        """Get the current telemetry consent status"""
        try:
            # Get addon preferences - use the module name
            addon_prefs = bpy.context.preferences.addons.get(__name__)
            if addon_prefs:
                consent = addon_prefs.preferences.telemetry_consent
            else:
                # Fallback to default if preferences not available
                consent = True
        except (AttributeError, KeyError):
            # Fallback to default if preferences not available
            consent = True
        return {"consent": consent}

    def get_polyhaven_status(self):
        """Get the current status of PolyHaven integration"""
        enabled = bpy.context.scene.blendermcp_use_polyhaven
        if enabled:
            return {"enabled": True, "message": "PolyHaven integration is enabled and ready to use."}
        else:
            return {
                "enabled": False,
                "message": """PolyHaven integration is currently disabled. To enable it:
                            1. In the 3D Viewport, find the BlenderMCP panel in the sidebar (press N if hidden)
                            2. Check the 'Use assets from Poly Haven' checkbox
                            3. Restart the connection to Claude"""
        }

    #region Hyper3D
    def get_hyper3d_status(self):
        """Get the current status of Hyper3D Rodin integration"""
        enabled = bpy.context.scene.blendermcp_use_hyper3d
        if enabled:
            if not bpy.context.scene.blendermcp_hyper3d_api_key:
                return {
                    "enabled": False,
                    "message": """Hyper3D Rodin integration is currently enabled, but API key is not given. To enable it:
                                1. In the 3D Viewport, find the BlenderMCP panel in the sidebar (press N if hidden)
                                2. Keep the 'Use Hyper3D Rodin 3D model generation' checkbox checked
                                3. Choose the right plaform and fill in the API Key
                                4. Restart the connection to Claude"""
                }
            mode = bpy.context.scene.blendermcp_hyper3d_mode
            message = f"Hyper3D Rodin integration is enabled and ready to use. Mode: {mode}. " + \
                f"Key type: {'private' if bpy.context.scene.blendermcp_hyper3d_api_key != RODIN_FREE_TRIAL_KEY else 'free_trial'}"
            return {
                "enabled": True,
                "message": message
            }
        else:
            return {
                "enabled": False,
                "message": """Hyper3D Rodin integration is currently disabled. To enable it:
                            1. In the 3D Viewport, find the BlenderMCP panel in the sidebar (press N if hidden)
                            2. Check the 'Use Hyper3D Rodin 3D model generation' checkbox
                            3. Restart the connection to Claude"""
            }

    def create_rodin_job(self, *args, **kwargs):
        match bpy.context.scene.blendermcp_hyper3d_mode:
            case "MAIN_SITE":
                return self.create_rodin_job_main_site(*args, **kwargs)
            case "FAL_AI":
                return self.create_rodin_job_fal_ai(*args, **kwargs)
            case _:
                return f"Error: Unknown Hyper3D Rodin mode!"

    def create_rodin_job_main_site(
            self,
            text_prompt: str=None,
            images: list[tuple[str, str]]=None,
            bbox_condition=None
        ):
        try:
            if images is None:
                images = []
            """Call Rodin API, get the job uuid and subscription key"""
            files = [
                *[("images", (f"{i:04d}{img_suffix}", img)) for i, (img_suffix, img) in enumerate(images)],
                ("tier", (None, "Sketch")),
                ("mesh_mode", (None, "Raw")),
            ]
            if text_prompt:
                files.append(("prompt", (None, text_prompt)))
            if bbox_condition:
                files.append(("bbox_condition", (None, json.dumps(bbox_condition))))
            response = requests.post(
                "https://hyperhuman.deemos.com/api/v2/rodin",
                headers={
                    "Authorization": f"Bearer {bpy.context.scene.blendermcp_hyper3d_api_key}",
                },
                files=files
            )
            data = response.json()
            return data
        except Exception as e:
            return {"error": str(e)}

    def create_rodin_job_fal_ai(
            self,
            text_prompt: str=None,
            images: list[tuple[str, str]]=None,
            bbox_condition=None
        ):
        try:
            req_data = {
                "tier": "Sketch",
            }
            if images:
                req_data["input_image_urls"] = images
            if text_prompt:
                req_data["prompt"] = text_prompt
            if bbox_condition:
                req_data["bbox_condition"] = bbox_condition
            response = requests.post(
                "https://queue.fal.run/fal-ai/hyper3d/rodin",
                headers={
                    "Authorization": f"Key {bpy.context.scene.blendermcp_hyper3d_api_key}",
                    "Content-Type": "application/json",
                },
                json=req_data
            )
            data = response.json()
            return data
        except Exception as e:
            return {"error": str(e)}

    def poll_rodin_job_status(self, *args, **kwargs):
        match bpy.context.scene.blendermcp_hyper3d_mode:
            case "MAIN_SITE":
                return self.poll_rodin_job_status_main_site(*args, **kwargs)
            case "FAL_AI":
                return self.poll_rodin_job_status_fal_ai(*args, **kwargs)
            case _:
                return f"Error: Unknown Hyper3D Rodin mode!"

    def poll_rodin_job_status_main_site(self, subscription_key: str):
        """Call the job status API to get the job status"""
        response = requests.post(
            "https://hyperhuman.deemos.com/api/v2/status",
            headers={
                "Authorization": f"Bearer {bpy.context.scene.blendermcp_hyper3d_api_key}",
            },
            json={
                "subscription_key": subscription_key,
            },
        )
        data = response.json()
        return {
            "status_list": [i["status"] for i in data["jobs"]]
        }

    def poll_rodin_job_status_fal_ai(self, request_id: str):
        """Call the job status API to get the job status"""
        response = requests.get(
            f"https://queue.fal.run/fal-ai/hyper3d/requests/{request_id}/status",
            headers={
                "Authorization": f"KEY {bpy.context.scene.blendermcp_hyper3d_api_key}",
            },
        )
        data = response.json()
        return data

    @staticmethod
    def _clean_imported_glb(filepath, mesh_name=None):
        # Get the set of existing objects before import
        existing_objects = set(bpy.data.objects)

        # Import the GLB file
        bpy.ops.import_scene.gltf(filepath=filepath)

        # Ensure the context is updated
        bpy.context.view_layer.update()

        # Get all imported objects
        imported_objects = list(set(bpy.data.objects) - existing_objects)
        # imported_objects = [obj for obj in bpy.context.view_layer.objects if obj.select_get()]

        if not imported_objects:
            print("Error: No objects were imported.")
            return

        # Identify the mesh object
        mesh_obj = None

        if len(imported_objects) == 1 and imported_objects[0].type == 'MESH':
            mesh_obj = imported_objects[0]
            print("Single mesh imported, no cleanup needed.")
        else:
            if len(imported_objects) == 2:
                empty_objs = [i for i in imported_objects if i.type == "EMPTY"]
                if len(empty_objs) != 1:
                    print("Error: Expected an empty node with one mesh child or a single mesh object.")
                    return
                parent_obj = empty_objs.pop()
                if len(parent_obj.children) == 1:
                    potential_mesh = parent_obj.children[0]
                    if potential_mesh.type == 'MESH':
                        print("GLB structure confirmed: Empty node with one mesh child.")

                        # Unparent the mesh from the empty node
                        potential_mesh.parent = None

                        # Remove the empty node
                        bpy.data.objects.remove(parent_obj)
                        print("Removed empty node, keeping only the mesh.")

                        mesh_obj = potential_mesh
                    else:
                        print("Error: Child is not a mesh object.")
                        return
                else:
                    print("Error: Expected an empty node with one mesh child or a single mesh object.")
                    return
            else:
                print("Error: Expected an empty node with one mesh child or a single mesh object.")
                return

        # Rename the mesh if needed
        try:
            if mesh_obj and mesh_obj.name is not None and mesh_name:
                mesh_obj.name = mesh_name
                if mesh_obj.data.name is not None:
                    mesh_obj.data.name = mesh_name
                print(f"Mesh renamed to: {mesh_name}")
        except Exception as e:
            print("Having issue with renaming, give up renaming.")

        return mesh_obj

    def import_generated_asset(self, *args, **kwargs):
        match bpy.context.scene.blendermcp_hyper3d_mode:
            case "MAIN_SITE":
                return self.import_generated_asset_main_site(*args, **kwargs)
            case "FAL_AI":
                return self.import_generated_asset_fal_ai(*args, **kwargs)
            case _:
                return f"Error: Unknown Hyper3D Rodin mode!"

    def import_generated_asset_main_site(self, task_uuid: str, name: str):
        """Fetch the generated asset, import into blender"""
        response = requests.post(
            "https://hyperhuman.deemos.com/api/v2/download",
            headers={
                "Authorization": f"Bearer {bpy.context.scene.blendermcp_hyper3d_api_key}",
            },
            json={
                'task_uuid': task_uuid
            }
        )
        data_ = response.json()
        temp_file = None
        for i in data_["list"]:
            if i["name"].endswith(".glb"):
                temp_file = tempfile.NamedTemporaryFile(
                    delete=False,
                    prefix=task_uuid,
                    suffix=".glb",
                )

                try:
                    # Download the content
                    response = requests.get(i["url"], stream=True)
                    response.raise_for_status()  # Raise an exception for HTTP errors

                    # Write the content to the temporary file
                    for chunk in response.iter_content(chunk_size=8192):
                        temp_file.write(chunk)

                    # Close the file
                    temp_file.close()

                except Exception as e:
                    # Clean up the file if there's an error
                    temp_file.close()
                    os.unlink(temp_file.name)
                    return {"succeed": False, "error": str(e)}

                break
        else:
            return {"succeed": False, "error": "Generation failed. Please first make sure that all jobs of the task are done and then try again later."}

        try:
            obj = self._clean_imported_glb(
                filepath=temp_file.name,
                mesh_name=name
            )
            result = {
                "name": obj.name,
                "type": obj.type,
                "location": [obj.location.x, obj.location.y, obj.location.z],
                "rotation": [obj.rotation_euler.x, obj.rotation_euler.y, obj.rotation_euler.z],
                "scale": [obj.scale.x, obj.scale.y, obj.scale.z],
            }

            if obj.type == "MESH":
                bounding_box = self._get_aabb(obj)
                result["world_bounding_box"] = bounding_box

            return {
                "succeed": True, **result
            }
        except Exception as e:
            return {"succeed": False, "error": str(e)}

    def import_generated_asset_fal_ai(self, request_id: str, name: str):
        """Fetch the generated asset, import into blender"""
        response = requests.get(
            f"https://queue.fal.run/fal-ai/hyper3d/requests/{request_id}",
            headers={
                "Authorization": f"Key {bpy.context.scene.blendermcp_hyper3d_api_key}",
            }
        )
        data_ = response.json()
        temp_file = None

        temp_file = tempfile.NamedTemporaryFile(
            delete=False,
            prefix=request_id,
            suffix=".glb",
        )

        try:
            # Download the content
            response = requests.get(data_["model_mesh"]["url"], stream=True)
            response.raise_for_status()  # Raise an exception for HTTP errors

            # Write the content to the temporary file
            for chunk in response.iter_content(chunk_size=8192):
                temp_file.write(chunk)

            # Close the file
            temp_file.close()

        except Exception as e:
            # Clean up the file if there's an error
            temp_file.close()
            os.unlink(temp_file.name)
            return {"succeed": False, "error": str(e)}

        try:
            obj = self._clean_imported_glb(
                filepath=temp_file.name,
                mesh_name=name
            )
            result = {
                "name": obj.name,
                "type": obj.type,
                "location": [obj.location.x, obj.location.y, obj.location.z],
                "rotation": [obj.rotation_euler.x, obj.rotation_euler.y, obj.rotation_euler.z],
                "scale": [obj.scale.x, obj.scale.y, obj.scale.z],
            }

            if obj.type == "MESH":
                bounding_box = self._get_aabb(obj)
                result["world_bounding_box"] = bounding_box

            return {
                "succeed": True, **result
            }
        except Exception as e:
            return {"succeed": False, "error": str(e)}
    #endregion
 
    #region Sketchfab API
    def get_sketchfab_status(self):
        """Get the current status of Sketchfab integration"""
        enabled = bpy.context.scene.blendermcp_use_sketchfab
        api_key = bpy.context.scene.blendermcp_sketchfab_api_key

        # Test the API key if present
        if api_key:
            try:
                headers = {
                    "Authorization": f"Token {api_key}"
                }

                response = requests.get(
                    "https://api.sketchfab.com/v3/me",
                    headers=headers,
                    timeout=30  # Add timeout of 30 seconds
                )

                if response.status_code == 200:
                    user_data = response.json()
                    username = user_data.get("username", "Unknown user")
                    return {
                        "enabled": True,
                        "message": f"Sketchfab integration is enabled and ready to use. Logged in as: {username}"
                    }
                else:
                    return {
                        "enabled": False,
                        "message": f"Sketchfab API key seems invalid. Status code: {response.status_code}"
                    }
            except requests.exceptions.Timeout:
                return {
                    "enabled": False,
                    "message": "Timeout connecting to Sketchfab API. Check your internet connection."
                }
            except Exception as e:
                return {
                    "enabled": False,
                    "message": f"Error testing Sketchfab API key: {str(e)}"
                }

        if enabled and api_key:
            return {"enabled": True, "message": "Sketchfab integration is enabled and ready to use."}
        elif enabled and not api_key:
            return {
                "enabled": False,
                "message": """Sketchfab integration is currently enabled, but API key is not given. To enable it:
                            1. In the 3D Viewport, find the BlenderMCP panel in the sidebar (press N if hidden)
                            2. Keep the 'Use Sketchfab' checkbox checked
                            3. Enter your Sketchfab API Key
                            4. Restart the connection to Claude"""
            }
        else:
            return {
                "enabled": False,
                "message": """Sketchfab integration is currently disabled. To enable it:
                            1. In the 3D Viewport, find the BlenderMCP panel in the sidebar (press N if hidden)
                            2. Check the 'Use assets from Sketchfab' checkbox
                            3. Enter your Sketchfab API Key
                            4. Restart the connection to Claude"""
            }

    def search_sketchfab_models(self, query, categories=None, count=20, downloadable=True):
        """Search for models on Sketchfab based on query and optional filters"""
        try:
            api_key = bpy.context.scene.blendermcp_sketchfab_api_key
            if not api_key:
                return {"error": "Sketchfab API key is not configured"}

            # Build search parameters with exact fields from Sketchfab API docs
            params = {
                "type": "models",
                "q": query,
                "count": count,
                "downloadable": downloadable,
                "archives_flavours": False
            }

            if categories:
                params["categories"] = categories

            # Make API request to Sketchfab search endpoint
            # The proper format according to Sketchfab API docs for API key auth
            headers = {
                "Authorization": f"Token {api_key}"
            }


            # Use the search endpoint as specified in the API documentation
            response = requests.get(
                "https://api.sketchfab.com/v3/search",
                headers=headers,
                params=params,
                timeout=30  # Add timeout of 30 seconds
            )

            if response.status_code == 401:
                return {"error": "Authentication failed (401). Check your API key."}

            if response.status_code != 200:
                return {"error": f"API request failed with status code {response.status_code}"}

            response_data = response.json()

            # Safety check on the response structure
            if response_data is None:
                return {"error": "Received empty response from Sketchfab API"}

            # Handle 'results' potentially missing from response
            results = response_data.get("results", [])
            if not isinstance(results, list):
                return {"error": f"Unexpected response format from Sketchfab API: {response_data}"}

            return response_data

        except requests.exceptions.Timeout:
            return {"error": "Request timed out. Check your internet connection."}
        except json.JSONDecodeError as e:
            return {"error": f"Invalid JSON response from Sketchfab API: {str(e)}"}
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"error": str(e)}

    def get_sketchfab_model_preview(self, uid):
        """Get thumbnail preview image of a Sketchfab model by its UID"""
        try:
            import base64
            
            api_key = bpy.context.scene.blendermcp_sketchfab_api_key
            if not api_key:
                return {"error": "Sketchfab API key is not configured"}

            headers = {"Authorization": f"Token {api_key}"}
            
            # Get model info which includes thumbnails
            response = requests.get(
                f"https://api.sketchfab.com/v3/models/{uid}",
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 401:
                return {"error": "Authentication failed (401). Check your API key."}
            
            if response.status_code == 404:
                return {"error": f"Model not found: {uid}"}
            
            if response.status_code != 200:
                return {"error": f"Failed to get model info: {response.status_code}"}
            
            data = response.json()
            thumbnails = data.get("thumbnails", {}).get("images", [])
            
            if not thumbnails:
                return {"error": "No thumbnail available for this model"}
            
            # Find a suitable thumbnail (prefer medium size ~640px)
            selected_thumbnail = None
            for thumb in thumbnails:
                width = thumb.get("width", 0)
                if 400 <= width <= 800:
                    selected_thumbnail = thumb
                    break
            
            # Fallback to the first available thumbnail
            if not selected_thumbnail:
                selected_thumbnail = thumbnails[0]
            
            thumbnail_url = selected_thumbnail.get("url")
            if not thumbnail_url:
                return {"error": "Thumbnail URL not found"}
            
            # Download the thumbnail image
            img_response = requests.get(thumbnail_url, timeout=30)
            if img_response.status_code != 200:
                return {"error": f"Failed to download thumbnail: {img_response.status_code}"}
            
            # Encode image as base64
            image_data = base64.b64encode(img_response.content).decode('ascii')
            
            # Determine format from content type or URL
            content_type = img_response.headers.get("Content-Type", "")
            if "png" in content_type or thumbnail_url.endswith(".png"):
                img_format = "png"
            else:
                img_format = "jpeg"
            
            # Get additional model info for context
            model_name = data.get("name", "Unknown")
            author = data.get("user", {}).get("username", "Unknown")
            
            return {
                "success": True,
                "image_data": image_data,
                "format": img_format,
                "model_name": model_name,
                "author": author,
                "uid": uid,
                "thumbnail_width": selected_thumbnail.get("width"),
                "thumbnail_height": selected_thumbnail.get("height")
            }
            
        except requests.exceptions.Timeout:
            return {"error": "Request timed out. Check your internet connection."}
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"error": f"Failed to get model preview: {str(e)}"}

    def download_sketchfab_model(self, uid, normalize_size=False, target_size=1.0):
        """Download a model from Sketchfab by its UID
        
        Parameters:
        - uid: The unique identifier of the Sketchfab model
        - normalize_size: If True, scale the model so its largest dimension equals target_size
        - target_size: The target size in Blender units (meters) for the largest dimension
        """
        try:
            api_key = bpy.context.scene.blendermcp_sketchfab_api_key
            if not api_key:
                return {"error": "Sketchfab API key is not configured"}

            # Use proper authorization header for API key auth
            headers = {
                "Authorization": f"Token {api_key}"
            }

            # Request download URL using the exact endpoint from the documentation
            download_endpoint = f"https://api.sketchfab.com/v3/models/{uid}/download"

            response = requests.get(
                download_endpoint,
                headers=headers,
                timeout=30  # Add timeout of 30 seconds
            )

            if response.status_code == 401:
                return {"error": "Authentication failed (401). Check your API key."}

            if response.status_code != 200:
                return {"error": f"Download request failed with status code {response.status_code}"}

            data = response.json()

            # Safety check for None data
            if data is None:
                return {"error": "Received empty response from Sketchfab API for download request"}

            # Extract download URL with safety checks
            gltf_data = data.get("gltf")
            if not gltf_data:
                return {"error": "No gltf download URL available for this model. Response: " + str(data)}

            download_url = gltf_data.get("url")
            if not download_url:
                return {"error": "No download URL available for this model. Make sure the model is downloadable and you have access."}

            # Download the model (already has timeout)
            model_response = requests.get(download_url, timeout=60)  # 60 second timeout

            if model_response.status_code != 200:
                return {"error": f"Model download failed with status code {model_response.status_code}"}

            # Save to temporary file
            temp_dir = tempfile.mkdtemp()
            zip_file_path = os.path.join(temp_dir, f"{uid}.zip")

            with open(zip_file_path, "wb") as f:
                f.write(model_response.content)

            # Extract the zip file with enhanced security
            with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
                # More secure zip slip prevention
                for file_info in zip_ref.infolist():
                    # Get the path of the file
                    file_path = file_info.filename

                    # Convert directory separators to the current OS style
                    # This handles both / and \ in zip entries
                    target_path = os.path.join(temp_dir, os.path.normpath(file_path))

                    # Get absolute paths for comparison
                    abs_temp_dir = os.path.abspath(temp_dir)
                    abs_target_path = os.path.abspath(target_path)

                    # Ensure the normalized path doesn't escape the target directory
                    if not abs_target_path.startswith(abs_temp_dir):
                        with suppress(Exception):
                            shutil.rmtree(temp_dir)
                        return {"error": "Security issue: Zip contains files with path traversal attempt"}

                    # Additional explicit check for directory traversal
                    if ".." in file_path:
                        with suppress(Exception):
                            shutil.rmtree(temp_dir)
                        return {"error": "Security issue: Zip contains files with directory traversal sequence"}

                # If all files passed security checks, extract them
                zip_ref.extractall(temp_dir)

            # Find the main glTF file
            gltf_files = [f for f in os.listdir(temp_dir) if f.endswith('.gltf') or f.endswith('.glb')]

            if not gltf_files:
                with suppress(Exception):
                    shutil.rmtree(temp_dir)
                return {"error": "No glTF file found in the downloaded model"}

            main_file = os.path.join(temp_dir, gltf_files[0])

            # Import the model
            bpy.ops.import_scene.gltf(filepath=main_file)

            # Get the imported objects
            imported_objects = list(bpy.context.selected_objects)
            imported_object_names = [obj.name for obj in imported_objects]

            # Clean up temporary files
            with suppress(Exception):
                shutil.rmtree(temp_dir)

            # Find root objects (objects without parents in the imported set)
            root_objects = [obj for obj in imported_objects if obj.parent is None]

            # Helper function to recursively get all mesh children
            def get_all_mesh_children(obj):
                """Recursively collect all mesh objects in the hierarchy"""
                meshes = []
                if obj.type == 'MESH':
                    meshes.append(obj)
                for child in obj.children:
                    meshes.extend(get_all_mesh_children(child))
                return meshes

            # Collect ALL meshes from the entire hierarchy (starting from roots)
            all_meshes = []
            for obj in root_objects:
                all_meshes.extend(get_all_mesh_children(obj))
            
            if all_meshes:
                # Calculate combined world bounding box for all meshes
                all_min = mathutils.Vector((float('inf'), float('inf'), float('inf')))
                all_max = mathutils.Vector((float('-inf'), float('-inf'), float('-inf')))
                
                for mesh_obj in all_meshes:
                    # Get world-space bounding box corners
                    for corner in mesh_obj.bound_box:
                        world_corner = mesh_obj.matrix_world @ mathutils.Vector(corner)
                        all_min.x = min(all_min.x, world_corner.x)
                        all_min.y = min(all_min.y, world_corner.y)
                        all_min.z = min(all_min.z, world_corner.z)
                        all_max.x = max(all_max.x, world_corner.x)
                        all_max.y = max(all_max.y, world_corner.y)
                        all_max.z = max(all_max.z, world_corner.z)
                
                # Calculate dimensions
                dimensions = [
                    all_max.x - all_min.x,
                    all_max.y - all_min.y,
                    all_max.z - all_min.z
                ]
                max_dimension = max(dimensions)
                
                # Apply normalization if requested
                scale_applied = 1.0
                if normalize_size and max_dimension > 0:
                    scale_factor = target_size / max_dimension
                    scale_applied = scale_factor
                    
                    # ✅ Only apply scale to ROOT objects (not children!)
                    # Child objects inherit parent's scale through matrix_world
                    for root in root_objects:
                        root.scale = (
                            root.scale.x * scale_factor,
                            root.scale.y * scale_factor,
                            root.scale.z * scale_factor
                        )
                    
                    # Update the scene to recalculate matrix_world for all objects
                    bpy.context.view_layer.update()
                    
                    # Recalculate bounding box after scaling
                    all_min = mathutils.Vector((float('inf'), float('inf'), float('inf')))
                    all_max = mathutils.Vector((float('-inf'), float('-inf'), float('-inf')))
                    
                    for mesh_obj in all_meshes:
                        for corner in mesh_obj.bound_box:
                            world_corner = mesh_obj.matrix_world @ mathutils.Vector(corner)
                            all_min.x = min(all_min.x, world_corner.x)
                            all_min.y = min(all_min.y, world_corner.y)
                            all_min.z = min(all_min.z, world_corner.z)
                            all_max.x = max(all_max.x, world_corner.x)
                            all_max.y = max(all_max.y, world_corner.y)
                            all_max.z = max(all_max.z, world_corner.z)
                    
                    dimensions = [
                        all_max.x - all_min.x,
                        all_max.y - all_min.y,
                        all_max.z - all_min.z
                    ]
                
                world_bounding_box = [[all_min.x, all_min.y, all_min.z], [all_max.x, all_max.y, all_max.z]]
            else:
                world_bounding_box = None
                dimensions = None
                scale_applied = 1.0

            result = {
                "success": True,
                "message": "Model imported successfully",
                "imported_objects": imported_object_names
            }
            
            if world_bounding_box:
                result["world_bounding_box"] = world_bounding_box
            if dimensions:
                result["dimensions"] = [round(d, 4) for d in dimensions]
            if normalize_size:
                result["scale_applied"] = round(scale_applied, 6)
                result["normalized"] = True
            
            return result

        except requests.exceptions.Timeout:
            return {"error": "Request timed out. Check your internet connection and try again with a simpler model."}
        except json.JSONDecodeError as e:
            return {"error": f"Invalid JSON response from Sketchfab API: {str(e)}"}
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"error": f"Failed to download model: {str(e)}"}
    #endregion

    #region Hunyuan3D
    def get_hunyuan3d_status(self):
        """Get the current status of Hunyuan3D integration"""
        enabled = bpy.context.scene.blendermcp_use_hunyuan3d
        hunyuan3d_mode = bpy.context.scene.blendermcp_hunyuan3d_mode
        if enabled:
            match hunyuan3d_mode:
                case "OFFICIAL_API":
                    if not bpy.context.scene.blendermcp_hunyuan3d_secret_id or not bpy.context.scene.blendermcp_hunyuan3d_secret_key:
                        return {
                            "enabled": False, 
                            "mode": hunyuan3d_mode, 
                            "message": """Hunyuan3D integration is currently enabled, but SecretId or SecretKey is not given. To enable it:
                                1. In the 3D Viewport, find the BlenderMCP panel in the sidebar (press N if hidden)
                                2. Keep the 'Use Tencent Hunyuan 3D model generation' checkbox checked
                                3. Choose the right platform and fill in the SecretId and SecretKey
                                4. Restart the connection to Claude"""
                        }
                case "LOCAL_API":
                    if not bpy.context.scene.blendermcp_hunyuan3d_api_url:
                        return {
                            "enabled": False, 
                            "mode": hunyuan3d_mode, 
                            "message": """Hunyuan3D integration is currently enabled, but API URL  is not given. To enable it:
                                1. In the 3D Viewport, find the BlenderMCP panel in the sidebar (press N if hidden)
                                2. Keep the 'Use Tencent Hunyuan 3D model generation' checkbox checked
                                3. Choose the right platform and fill in the API URL
                                4. Restart the connection to Claude"""
                        }
                case _:
                    return {
                        "enabled": False, 
                        "message": "Hunyuan3D integration is enabled and mode is not supported."
                    }
            return {
                "enabled": True, 
                "mode": hunyuan3d_mode,
                "message": "Hunyuan3D integration is enabled and ready to use."
            }
        return {
            "enabled": False, 
            "message": """Hunyuan3D integration is currently disabled. To enable it:
                        1. In the 3D Viewport, find the BlenderMCP panel in the sidebar (press N if hidden)
                        2. Check the 'Use Tencent Hunyuan 3D model generation' checkbox
                        3. Restart the connection to Claude"""
        }
    
    @staticmethod
    def get_tencent_cloud_sign_headers(
        method: str,
        path: str,
        headParams: dict,
        data: dict,
        service: str,
        region: str,
        secret_id: str,
        secret_key: str,
        host: str = None
    ):
        """Generate the signature header required for Tencent Cloud API requests headers"""
        # Generate timestamp
        timestamp = int(time.time())
        date = datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d")
        
        # If host is not provided, it is generated based on service and region.
        if not host:
            host = f"{service}.tencentcloudapi.com"
        
        endpoint = f"https://{host}"
        
        # Constructing the request body
        payload_str = json.dumps(data)
        
        # ************* Step 1: Concatenate the canonical request string *************
        canonical_uri = path
        canonical_querystring = ""
        ct = "application/json; charset=utf-8"
        canonical_headers = f"content-type:{ct}\nhost:{host}\nx-tc-action:{headParams.get('Action', '').lower()}\n"
        signed_headers = "content-type;host;x-tc-action"
        hashed_request_payload = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()
        
        canonical_request = (method + "\n" +
                            canonical_uri + "\n" +
                            canonical_querystring + "\n" +
                            canonical_headers + "\n" +
                            signed_headers + "\n" +
                            hashed_request_payload)

        # ************* Step 2: Construct the reception signature string *************
        credential_scope = f"{date}/{service}/tc3_request"
        hashed_canonical_request = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
        string_to_sign = ("TC3-HMAC-SHA256" + "\n" +
                        str(timestamp) + "\n" +
                        credential_scope + "\n" +
                        hashed_canonical_request)

        # ************* Step 3: Calculate the signature *************
        def sign(key, msg):
            return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

        secret_date = sign(("TC3" + secret_key).encode("utf-8"), date)
        secret_service = sign(secret_date, service)
        secret_signing = sign(secret_service, "tc3_request")
        signature = hmac.new(
            secret_signing, 
            string_to_sign.encode("utf-8"), 
            hashlib.sha256
        ).hexdigest()

        # ************* Step 4: Connect Authorization *************
        authorization = ("TC3-HMAC-SHA256" + " " +
                        "Credential=" + secret_id + "/" + credential_scope + ", " +
                        "SignedHeaders=" + signed_headers + ", " +
                        "Signature=" + signature)

        # Constructing request headers
        headers = {
            "Authorization": authorization,
            "Content-Type": "application/json; charset=utf-8",
            "Host": host,
            "X-TC-Action": headParams.get("Action", ""),
            "X-TC-Timestamp": str(timestamp),
            "X-TC-Version": headParams.get("Version", ""),
            "X-TC-Region": region
        }

        return headers, endpoint

    def create_hunyuan_job(self, *args, **kwargs):
        match bpy.context.scene.blendermcp_hunyuan3d_mode:
            case "OFFICIAL_API":
                return self.create_hunyuan_job_main_site(*args, **kwargs)
            case "LOCAL_API":
                return self.create_hunyuan_job_local_site(*args, **kwargs)
            case _:
                return f"Error: Unknown Hunyuan3D mode!"

    def create_hunyuan_job_main_site(
        self,
        text_prompt: str = None,
        image: str = None
    ):
        try:
            secret_id = bpy.context.scene.blendermcp_hunyuan3d_secret_id
            secret_key = bpy.context.scene.blendermcp_hunyuan3d_secret_key

            if not secret_id or not secret_key:
                return {"error": "SecretId or SecretKey is not given"}

            # Parameter verification
            if not text_prompt and not image:
                return {"error": "Prompt or Image is required"}
            if text_prompt and image:
                return {"error": "Prompt and Image cannot be provided simultaneously"}
            # Fixed parameter configuration
            service = "hunyuan"
            action = "SubmitHunyuanTo3DJob"
            version = "2023-09-01"
            region = "ap-guangzhou"

            headParams={
                "Action": action,
                "Version": version,
                "Region": region,
            }

            # Constructing request parameters
            data = {
                "Num": 1  # The current API limit is only 1
            }

            # Handling text prompts
            if text_prompt:
                if len(text_prompt) > 200:
                    return {"error": "Prompt exceeds 200 characters limit"}
                data["Prompt"] = text_prompt

            # Handling image
            if image:
                if re.match(r'^https?://', image, re.IGNORECASE) is not None:
                    data["ImageUrl"] = image
                else:
                    try:
                        # Convert to Base64 format
                        with open(image, "rb") as f:
                            image_base64 = base64.b64encode(f.read()).decode("ascii")
                        data["ImageBase64"] = image_base64
                    except Exception as e:
                        return {"error": f"Image encoding failed: {str(e)}"}
            
            # Get signed headers
            headers, endpoint = self.get_tencent_cloud_sign_headers("POST", "/", headParams, data, service, region, secret_id, secret_key)

            response = requests.post(
                endpoint,
                headers = headers,
                data = json.dumps(data)
            )

            if response.status_code == 200:
                return response.json()
            return {
                "error": f"API request failed with status {response.status_code}: {response}"
            }
        except Exception as e:
            return {"error": str(e)}

    def create_hunyuan_job_local_site(
        self,
        text_prompt: str = None,
        image: str = None):
        try:
            base_url = bpy.context.scene.blendermcp_hunyuan3d_api_url.rstrip('/')
            octree_resolution = bpy.context.scene.blendermcp_hunyuan3d_octree_resolution
            num_inference_steps = bpy.context.scene.blendermcp_hunyuan3d_num_inference_steps
            guidance_scale = bpy.context.scene.blendermcp_hunyuan3d_guidance_scale
            texture = bpy.context.scene.blendermcp_hunyuan3d_texture

            if not base_url:
                return {"error": "API URL is not given"}
            # Parameter verification
            if not text_prompt and not image:
                return {"error": "Prompt or Image is required"}

            # Constructing request parameters
            data = {
                "octree_resolution": octree_resolution,
                "num_inference_steps": num_inference_steps,
                "guidance_scale": guidance_scale,
                "texture": texture,
            }

            # Handling text prompts
            if text_prompt:
                data["text"] = text_prompt

            # Handling image
            if image:
                if re.match(r'^https?://', image, re.IGNORECASE) is not None:
                    try:
                        resImg = requests.get(image)
                        resImg.raise_for_status()
                        image_base64 = base64.b64encode(resImg.content).decode("ascii")
                        data["image"] = image_base64
                    except Exception as e:
                        return {"error": f"Failed to download or encode image: {str(e)}"} 
                else:
                    try:
                        # Convert to Base64 format
                        with open(image, "rb") as f:
                            image_base64 = base64.b64encode(f.read()).decode("ascii")
                        data["image"] = image_base64
                    except Exception as e:
                        return {"error": f"Image encoding failed: {str(e)}"}

            response = requests.post(
                f"{base_url}/generate",
                json = data,
            )

            if response.status_code != 200:
                return {
                    "error": f"Generation failed: {response.text}"
                }
        
            # Decode base64 and save to temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix=".glb") as temp_file:
                temp_file.write(response.content)
                temp_file_name = temp_file.name

            # Import the GLB file in the main thread
            def import_handler():
                bpy.ops.import_scene.gltf(filepath=temp_file_name)
                os.unlink(temp_file.name)
                return None
            
            bpy.app.timers.register(import_handler)

            return {
                "status": "DONE",
                "message": "Generation and Import glb succeeded"
            }
        except Exception as e:
            print(f"An error occurred: {e}")
            return {"error": str(e)}
        
    
    def poll_hunyuan_job_status(self, *args, **kwargs):
        return self.poll_hunyuan_job_status_ai(*args, **kwargs)
    
    def poll_hunyuan_job_status_ai(self, job_id: str):
        """Call the job status API to get the job status"""
        print(job_id)
        try:
            secret_id = bpy.context.scene.blendermcp_hunyuan3d_secret_id
            secret_key = bpy.context.scene.blendermcp_hunyuan3d_secret_key

            if not secret_id or not secret_key:
                return {"error": "SecretId or SecretKey is not given"}
            if not job_id:
                return {"error": "JobId is required"}
            
            service = "hunyuan"
            action = "QueryHunyuanTo3DJob"
            version = "2023-09-01"
            region = "ap-guangzhou"

            headParams={
                "Action": action,
                "Version": version,
                "Region": region,
            }

            clean_job_id = job_id.removeprefix("job_")
            data = {
                "JobId": clean_job_id
            }

            headers, endpoint = self.get_tencent_cloud_sign_headers("POST", "/", headParams, data, service, region, secret_id, secret_key)

            response = requests.post(
                endpoint,
                headers=headers,
                data=json.dumps(data)
            )

            if response.status_code == 200:
                return response.json()
            return {
                "error": f"API request failed with status {response.status_code}: {response}"
            }
        except Exception as e:
            return {"error": str(e)}

    def import_generated_asset_hunyuan(self, *args, **kwargs):
        return self.import_generated_asset_hunyuan_ai(*args, **kwargs)
            
    def import_generated_asset_hunyuan_ai(self, name: str , zip_file_url: str):
        if not zip_file_url:
            return {"error": "Zip file not found"}
        
        # Validate URL
        if not re.match(r'^https?://', zip_file_url, re.IGNORECASE):
            return {"error": "Invalid URL format. Must start with http:// or https://"}
        
        # Create a temporary directory
        temp_dir = tempfile.mkdtemp(prefix="tencent_obj_")
        zip_file_path = osp.join(temp_dir, "model.zip")
        obj_file_path = osp.join(temp_dir, "model.obj")
        mtl_file_path = osp.join(temp_dir, "model.mtl")

        try:
            # Download ZIP file
            zip_response = requests.get(zip_file_url, stream=True)
            zip_response.raise_for_status()
            with open(zip_file_path, "wb") as f:
                for chunk in zip_response.iter_content(chunk_size=8192):
                    f.write(chunk)

            # Unzip the ZIP
            with zipfile.ZipFile(zip_file_path, "r") as zip_ref:
                zip_ref.extractall(temp_dir)

            # Find the .obj file (there may be multiple, assuming the main file is model.obj)
            for file in os.listdir(temp_dir):
                if file.endswith(".obj"):
                    obj_file_path = osp.join(temp_dir, file)

            if not osp.exists(obj_file_path):
                return {"succeed": False, "error": "OBJ file not found after extraction"}

            # Import obj file
            if bpy.app.version>=(4, 0, 0):
                bpy.ops.wm.obj_import(filepath=obj_file_path)
            else:
                bpy.ops.import_scene.obj(filepath=obj_file_path)

            imported_objs = [obj for obj in bpy.context.selected_objects if obj.type == 'MESH']
            if not imported_objs:
                return {"succeed": False, "error": "No mesh objects imported"}

            obj = imported_objs[0]
            if name:
                obj.name = name

            result = {
                "name": obj.name,
                "type": obj.type,
                "location": [obj.location.x, obj.location.y, obj.location.z],
                "rotation": [obj.rotation_euler.x, obj.rotation_euler.y, obj.rotation_euler.z],
                "scale": [obj.scale.x, obj.scale.y, obj.scale.z],
            }

            if obj.type == "MESH":
                bounding_box = self._get_aabb(obj)
                result["world_bounding_box"] = bounding_box

            return {"succeed": True, **result}
        except Exception as e:
            return {"succeed": False, "error": str(e)}
        finally:
            #  Clean up temporary zip and obj, save texture and mtl
            try:
                if os.path.exists(zip_file_path):
                    os.remove(zip_file_path) 
                if os.path.exists(obj_file_path):
                    os.remove(obj_file_path)
            except Exception as e:
                print(f"Failed to clean up temporary directory {temp_dir}: {e}")
    #endregion

# Blender Addon Preferences
class BLENDERMCP_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__
    
    telemetry_consent: BoolProperty(
        name="Allow Telemetry",
        description="Allow collection of prompts, code snippets, and screenshots to help improve Blender MCP",
        default=True
    )

    def draw(self, context):
        layout = self.layout
        
        # Telemetry section
        layout.label(text="Telemetry & Privacy:", icon='PREFERENCES')
        
        box = layout.box()
        row = box.row()
        row.prop(self, "telemetry_consent", text="Allow Telemetry")
        
        # Info text
        box.separator()
        if self.telemetry_consent:
            box.label(text="With consent: We collect anonymized prompts, code, and screenshots.", icon='INFO')
        else:
            box.label(text="Without consent: We only collect minimal anonymous usage data", icon='INFO')
            box.label(text="(tool names, success/failure, duration - no prompts or code).", icon='BLANK1')
        box.separator()
        box.label(text="All data is fully anonymized. You can change this anytime.", icon='CHECKMARK')
        
        # Terms and Conditions link
        box.separator()
        row = box.row()
        row.operator("blendermcp.open_terms", text="View Terms and Conditions", icon='TEXT')

# Blender UI Panel
class BLENDERMCP_PT_Panel(bpy.types.Panel):
    bl_label = "Blender MCP"
    bl_idname = "BLENDERMCP_PT_Panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'BlenderMCP'

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        layout.prop(scene, "blendermcp_port")
        layout.prop(scene, "blendermcp_use_polyhaven", text="Use assets from Poly Haven")

        layout.prop(scene, "blendermcp_use_hyper3d", text="Use Hyper3D Rodin 3D model generation")
        if scene.blendermcp_use_hyper3d:
            layout.prop(scene, "blendermcp_hyper3d_mode", text="Rodin Mode")
            layout.prop(scene, "blendermcp_hyper3d_api_key", text="API Key")
            layout.operator("blendermcp.set_hyper3d_free_trial_api_key", text="Set Free Trial API Key")

        layout.prop(scene, "blendermcp_use_sketchfab", text="Use assets from Sketchfab")
        if scene.blendermcp_use_sketchfab:
            layout.prop(scene, "blendermcp_sketchfab_api_key", text="API Key")

        layout.prop(scene, "blendermcp_use_hunyuan3d", text="Use Tencent Hunyuan 3D model generation")
        if scene.blendermcp_use_hunyuan3d:
            layout.prop(scene, "blendermcp_hunyuan3d_mode", text="Hunyuan3D Mode")
            if scene.blendermcp_hunyuan3d_mode == 'OFFICIAL_API':
                layout.prop(scene, "blendermcp_hunyuan3d_secret_id", text="SecretId")
                layout.prop(scene, "blendermcp_hunyuan3d_secret_key", text="SecretKey")
            if scene.blendermcp_hunyuan3d_mode == 'LOCAL_API':
                layout.prop(scene, "blendermcp_hunyuan3d_api_url", text="API URL")
                layout.prop(scene, "blendermcp_hunyuan3d_octree_resolution", text="Octree Resolution")
                layout.prop(scene, "blendermcp_hunyuan3d_num_inference_steps", text="Number of Inference Steps")
                layout.prop(scene, "blendermcp_hunyuan3d_guidance_scale", text="Guidance Scale")
                layout.prop(scene, "blendermcp_hunyuan3d_texture", text="Generate Texture")
        
        if not scene.blendermcp_server_running:
            layout.operator("blendermcp.start_server", text="Connect to MCP server")
        else:
            layout.operator("blendermcp.stop_server", text="Disconnect from MCP server")
            layout.label(text=f"Running on port {scene.blendermcp_port}")

# Operator to set Hyper3D API Key
class BLENDERMCP_OT_SetFreeTrialHyper3DAPIKey(bpy.types.Operator):
    bl_idname = "blendermcp.set_hyper3d_free_trial_api_key"
    bl_label = "Set Free Trial API Key"

    def execute(self, context):
        context.scene.blendermcp_hyper3d_api_key = RODIN_FREE_TRIAL_KEY
        context.scene.blendermcp_hyper3d_mode = 'MAIN_SITE'
        self.report({'INFO'}, "API Key set successfully!")
        return {'FINISHED'}

# Operator to start the server
class BLENDERMCP_OT_StartServer(bpy.types.Operator):
    bl_idname = "blendermcp.start_server"
    bl_label = "Connect to Claude"
    bl_description = "Start the BlenderMCP server to connect with Claude"

    def execute(self, context):
        scene = context.scene

        # Create a new server instance
        if not hasattr(bpy.types, "blendermcp_server") or not bpy.types.blendermcp_server:
            bpy.types.blendermcp_server = BlenderMCPServer(port=scene.blendermcp_port)

        # Start the server
        bpy.types.blendermcp_server.start()
        scene.blendermcp_server_running = True

        return {'FINISHED'}

# Operator to stop the server
class BLENDERMCP_OT_StopServer(bpy.types.Operator):
    bl_idname = "blendermcp.stop_server"
    bl_label = "Stop the connection to Claude"
    bl_description = "Stop the connection to Claude"

    def execute(self, context):
        scene = context.scene

        # Stop the server if it exists
        if hasattr(bpy.types, "blendermcp_server") and bpy.types.blendermcp_server:
            bpy.types.blendermcp_server.stop()
            del bpy.types.blendermcp_server

        scene.blendermcp_server_running = False

        return {'FINISHED'}

# Operator to open Terms and Conditions
class BLENDERMCP_OT_OpenTerms(bpy.types.Operator):
    bl_idname = "blendermcp.open_terms"
    bl_label = "View Terms and Conditions"
    bl_description = "Open the Terms and Conditions document"

    def execute(self, context):
        # Open the Terms and Conditions on GitHub
        terms_url = "https://github.com/ahujasid/blender-mcp/blob/main/TERMS_AND_CONDITIONS.md"
        try:
            import webbrowser
            webbrowser.open(terms_url)
            self.report({'INFO'}, "Terms and Conditions opened in browser")
        except Exception as e:
            self.report({'ERROR'}, f"Could not open Terms and Conditions: {str(e)}")
        
        return {'FINISHED'}

# Registration functions
def register():
    bpy.types.Scene.blendermcp_port = IntProperty(
        name="Port",
        description="Port for the BlenderMCP server",
        default=9876,
        min=1024,
        max=65535
    )

    bpy.types.Scene.blendermcp_server_running = bpy.props.BoolProperty(
        name="Server Running",
        default=False
    )

    bpy.types.Scene.blendermcp_use_polyhaven = bpy.props.BoolProperty(
        name="Use Poly Haven",
        description="Enable Poly Haven asset integration",
        default=False
    )

    bpy.types.Scene.blendermcp_use_hyper3d = bpy.props.BoolProperty(
        name="Use Hyper3D Rodin",
        description="Enable Hyper3D Rodin generatino integration",
        default=False
    )

    bpy.types.Scene.blendermcp_hyper3d_mode = bpy.props.EnumProperty(
        name="Rodin Mode",
        description="Choose the platform used to call Rodin APIs",
        items=[
            ("MAIN_SITE", "hyper3d.ai", "hyper3d.ai"),
            ("FAL_AI", "fal.ai", "fal.ai"),
        ],
        default="MAIN_SITE"
    )

    bpy.types.Scene.blendermcp_hyper3d_api_key = bpy.props.StringProperty(
        name="Hyper3D API Key",
        subtype="PASSWORD",
        description="API Key provided by Hyper3D",
        default=""
    )

    bpy.types.Scene.blendermcp_use_hunyuan3d = bpy.props.BoolProperty(
        name="Use Hunyuan 3D",
        description="Enable Hunyuan asset integration",
        default=False
    )

    bpy.types.Scene.blendermcp_hunyuan3d_mode = bpy.props.EnumProperty(
        name="Hunyuan3D Mode",
        description="Choose a local or official APIs",
        items=[
            ("LOCAL_API", "local api", "local api"),
            ("OFFICIAL_API", "official api", "official api"),
        ],
        default="LOCAL_API"
    )

    bpy.types.Scene.blendermcp_hunyuan3d_secret_id = bpy.props.StringProperty(
        name="Hunyuan 3D SecretId",
        description="SecretId provided by Hunyuan 3D",
        default=""
    )

    bpy.types.Scene.blendermcp_hunyuan3d_secret_key = bpy.props.StringProperty(
        name="Hunyuan 3D SecretKey",
        subtype="PASSWORD",
        description="SecretKey provided by Hunyuan 3D",
        default=""
    )

    bpy.types.Scene.blendermcp_hunyuan3d_api_url = bpy.props.StringProperty(
        name="API URL",
        description="URL of the Hunyuan 3D API service",
        default="http://localhost:8081"
    )

    bpy.types.Scene.blendermcp_hunyuan3d_octree_resolution = bpy.props.IntProperty(
        name="Octree Resolution",
        description="Octree resolution for the 3D generation",
        default=256,
        min=128,
        max=512,
    )

    bpy.types.Scene.blendermcp_hunyuan3d_num_inference_steps = bpy.props.IntProperty(
        name="Number of Inference Steps",
        description="Number of inference steps for the 3D generation",
        default=20,
        min=20,
        max=50,
    )

    bpy.types.Scene.blendermcp_hunyuan3d_guidance_scale = bpy.props.FloatProperty(
        name="Guidance Scale",
        description="Guidance scale for the 3D generation",
        default=5.5,
        min=1.0,
        max=10.0,
    )

    bpy.types.Scene.blendermcp_hunyuan3d_texture = bpy.props.BoolProperty(
        name="Generate Texture",
        description="Whether to generate texture for the 3D model",
        default=False,
    )
    
    bpy.types.Scene.blendermcp_use_sketchfab = bpy.props.BoolProperty(
        name="Use Sketchfab",
        description="Enable Sketchfab asset integration",
        default=False
    )

    bpy.types.Scene.blendermcp_sketchfab_api_key = bpy.props.StringProperty(
        name="Sketchfab API Key",
        subtype="PASSWORD",
        description="API Key provided by Sketchfab",
        default=""
    )

    # Register preferences class
    bpy.utils.register_class(BLENDERMCP_AddonPreferences)

    bpy.utils.register_class(BLENDERMCP_PT_Panel)
    bpy.utils.register_class(BLENDERMCP_OT_SetFreeTrialHyper3DAPIKey)
    bpy.utils.register_class(BLENDERMCP_OT_StartServer)
    bpy.utils.register_class(BLENDERMCP_OT_StopServer)
    bpy.utils.register_class(BLENDERMCP_OT_OpenTerms)

    print("BlenderMCP addon registered")

def unregister():
    # Stop the server if it's running
    if hasattr(bpy.types, "blendermcp_server") and bpy.types.blendermcp_server:
        bpy.types.blendermcp_server.stop()
        del bpy.types.blendermcp_server

    bpy.utils.unregister_class(BLENDERMCP_PT_Panel)
    bpy.utils.unregister_class(BLENDERMCP_OT_SetFreeTrialHyper3DAPIKey)
    bpy.utils.unregister_class(BLENDERMCP_OT_StartServer)
    bpy.utils.unregister_class(BLENDERMCP_OT_StopServer)
    bpy.utils.unregister_class(BLENDERMCP_OT_OpenTerms)
    bpy.utils.unregister_class(BLENDERMCP_AddonPreferences)

    del bpy.types.Scene.blendermcp_port
    del bpy.types.Scene.blendermcp_server_running
    del bpy.types.Scene.blendermcp_use_polyhaven
    del bpy.types.Scene.blendermcp_use_hyper3d
    del bpy.types.Scene.blendermcp_hyper3d_mode
    del bpy.types.Scene.blendermcp_hyper3d_api_key
    del bpy.types.Scene.blendermcp_use_sketchfab
    del bpy.types.Scene.blendermcp_sketchfab_api_key
    del bpy.types.Scene.blendermcp_use_hunyuan3d
    del bpy.types.Scene.blendermcp_hunyuan3d_mode
    del bpy.types.Scene.blendermcp_hunyuan3d_secret_id
    del bpy.types.Scene.blendermcp_hunyuan3d_secret_key
    del bpy.types.Scene.blendermcp_hunyuan3d_api_url
    del bpy.types.Scene.blendermcp_hunyuan3d_octree_resolution
    del bpy.types.Scene.blendermcp_hunyuan3d_num_inference_steps
    del bpy.types.Scene.blendermcp_hunyuan3d_guidance_scale
    del bpy.types.Scene.blendermcp_hunyuan3d_texture

    print("BlenderMCP addon unregistered")

if __name__ == "__main__":
    register()
